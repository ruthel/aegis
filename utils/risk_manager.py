import time
import os
from datetime import datetime, timedelta
from config import TRADING_PAIRS
import statistics
import numpy as np
from core.ml_live_logger import MLLiveLogger

class RiskManager:
    def __init__(self, max_daily_trades=50, max_daily_loss=100, emergency_stop_loss=500):
        self.correlation_data = {}
        self.active_positions = {}
        # Safety Manager integration
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss = max_daily_loss
        self.emergency_stop_loss = emergency_stop_loss
        self.db_logger = MLLiveLogger(
            data_dir='data',
            sqlite_file=os.getenv('ML_LIVE_SQLITE_FILE', 'data/aegis_db.sqlite3')
        )
        self.daily_stats = self.load_daily_stats()
        # Adaptive Thresholds integration
        self.performance_history = []
        self.trading_pairs = TRADING_PAIRS
        self.market_regimes = {}
        self.adaptive_thresholds = {}
        self.last_optimization = 0
        self.base_multiplier = 1800  # 30min si check_interval=1s
        
    def calculate_volatility(self, bot, symbol, periods=20):
        """Calcule la volatilité réelle sur les dernières périodes"""
        try:
            klines = bot.get_klines(symbol, periods, os.getenv('MAIN_TIMEFRAME', '15m'))
            return bot.market_analyzer.calculate_volatility(klines, symbol) / 100  # Convertir en décimal
        except Exception as e:
            print(f"Erreur calcul volatilité {symbol}: {e}")
            return 0.02  # Volatilité par défaut (2%)

    def calculate_position_size(self, bot, symbol, base_amount=10, max_risk_percent=2):
        """Calcule la taille de position basée sur la volatilité et configuration"""
        from config import USE_FULL_BALANCE, MAX_BALANCE_PER_TRADE
        
        if USE_FULL_BALANCE:
            # Mode: Utiliser tout le solde disponible (comportement actuel)
            balance = bot.balance_manager.get_balance()
            usd_available = balance.get('USD', balance.get('USD', {})).get('free', 0)
            
            # Limiter selon MAX_BALANCE_PER_TRADE (% du solde)
            max_allowed = usd_available * (MAX_BALANCE_PER_TRADE / 100)
            position_size = min(usd_available, max_allowed)
            
            print(f"💰 {symbol}: Mode FULL_BALANCE → {position_size:.1f} USD ({MAX_BALANCE_PER_TRADE}% max)")
            return max(base_amount, position_size)
        else:
            # Mode: Montant fixe basé sur volatilité (nouveau comportement)
            volatility = self.calculate_volatility(bot, symbol)
            
            # Plus la volatilité est élevée, plus on réduit la position
            risk_factor = max_risk_percent / (volatility * 100)
            adjusted_amount = base_amount * min(risk_factor, 2.0)  # Max 2x le montant de base
            
            # Minimums spécifiques par paire
            min_notionals = {
                'BTC/USD': 5,
                'ETH/USD': 10,
                'SOL/USD': 8,
                'ADA/USD': 12
            }
            min_required = min_notionals.get(symbol, 10)
            
            # Minimum selon la paire, maximum selon TRADE_AMOUNT
            max_amount = getattr(bot, 'trade_amount', base_amount) * 2
            position_size = max(min_required, min(max_amount, adjusted_amount))
            
            print(f"📊 {symbol}: Mode Fixed Amount → {position_size:.1f} USD (vol: {volatility:.1%})")
            return position_size
    
    def load_daily_stats(self):
        """Charge les statistiques du jour"""
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            stats = self.db_logger.load_daily_stats(today)
            if stats and stats.get('date') == today:
                return stats
        except Exception:
            pass
        stats = self.reset_daily_stats()
        self.db_logger.save_daily_stats(stats)
        return stats
    
    def reset_daily_stats(self):
        """Remet à zéro les stats du jour"""
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'trades_count': 0,
            'total_loss': 0,
            'total_profit': 0,
            'emergency_stop': False
        }
    
    def save_daily_stats(self):
        """Sauvegarde les stats"""
        self.db_logger.save_daily_stats(self.daily_stats)
    
    def can_trade(self):
        """Vérifie si le trading est autorisé"""
        # Vérifier arrêt d'urgence
        if self.daily_stats.get('emergency_stop', False):
            print("🚨 ARRÊT D'URGENCE ACTIVÉ")
            return False
        
        # Vérifier limite de trades
        if self.daily_stats['trades_count'] >= self.max_daily_trades:
            print(f"⛔ Limite de trades atteinte: {self.daily_stats['trades_count']}")
            return False
        
        # Vérifier perte journalière
        if abs(self.daily_stats['total_loss']) >= self.max_daily_loss:
            print(f"⛔ Limite de perte atteinte: ${abs(self.daily_stats['total_loss'])}")
            return False
        
        return True
    
    def record_trade(self, profit_loss):
        """Enregistre un trade"""
        self.daily_stats['trades_count'] += 1
        
        if profit_loss > 0:
            self.daily_stats['total_profit'] += profit_loss
        else:
            self.daily_stats['total_loss'] += profit_loss
        
        # Vérifier arrêt d'urgence
        if abs(self.daily_stats['total_loss']) >= self.emergency_stop_loss:
            self.daily_stats['emergency_stop'] = True
            print(f"🚨 ARRÊT D'URGENCE: Perte de ${abs(self.daily_stats['total_loss'])}")
        
        self.save_daily_stats()
        
        # Afficher stats
        print(f"📊 Trades: {self.daily_stats['trades_count']}, P&L: ${self.daily_stats['total_profit'] + self.daily_stats['total_loss']:.2f}")
    
    def get_stats(self):
        """Retourne les statistiques actuelles"""
        return self.daily_stats
    
    def get_adaptive_confidence_threshold(self, symbol, volatility):
        """Seuil de confiance adaptatif - Méthode Quantitative"""
        # 1. Seuil de base selon volatilité
        base_threshold = self._get_base_threshold(volatility, symbol)
        
        # 2. Ajustement selon performance récente
        performance_adj = self._calculate_performance_adjustment(symbol)
        
        # 3. Ajustement selon régime de marché
        market_adj = self._calculate_market_regime_adjustment(symbol)
        
        # 4. Ajustement selon corrélation
        correlation_adj = self._calculate_correlation_adjustment(symbol)
        
        # 5. Combinaison sophistiquée
        adaptive_threshold = base_threshold + performance_adj + market_adj + correlation_adj
        
        # 6. Contraintes de sécurité
        adaptive_threshold = max(15, min(adaptive_threshold, 85))
        
        # Cache pour éviter recalculs
        self.adaptive_thresholds[symbol] = {
            'threshold': adaptive_threshold,
            'components': {
                'base': base_threshold,
                'performance': performance_adj,
                'market': market_adj,
                'correlation': correlation_adj
            },
            'timestamp': time.time()
        }
        
        return adaptive_threshold
    
    def _get_base_threshold(self, volatility, symbol=None):
        """Seuil de base selon volatilité"""
        try:
            from utils.timeframe_analyzer import TimeframeAnalyzer
            analyzer = TimeframeAnalyzer()
            return analyzer.get_confidence_threshold(symbol or 'BTC/USD', volatility, None, None)
        except:
            if volatility >= 4.0:
                return 25
            elif volatility >= 3.0:
                return 30
            elif volatility >= 2.0:
                return 35
            elif volatility >= 1.5:
                return 40
            else:
                return 45
    
    def _calculate_performance_adjustment(self, symbol):
        """Ajustement selon performance récente"""
        try:
            recent_trades = self._get_recent_trades(symbol, days=7)
            
            if len(recent_trades) < 3:
                return 0
            
            wins = sum(1 for trade in recent_trades if trade['pnl'] > 0)
            win_rate = wins / len(recent_trades)
            
            total_profit = sum(trade['pnl'] for trade in recent_trades if trade['pnl'] > 0)
            total_loss = abs(sum(trade['pnl'] for trade in recent_trades if trade['pnl'] < 0))
            profit_factor = total_profit / total_loss if total_loss > 0 else 2.0
            
            if win_rate > 0.7 and profit_factor > 1.5:
                return -10
            elif win_rate > 0.6 and profit_factor > 1.2:
                return -5
            elif win_rate < 0.4 or profit_factor < 0.8:
                return +15
            elif win_rate < 0.5 or profit_factor < 1.0:
                return +8
            else:
                return 0
        except:
            return 0
    
    def _calculate_market_regime_adjustment(self, symbol):
        """Ajustement selon régime de marché"""
        try:
            regime = self._detect_market_regime(symbol)
            
            regime_adjustments = {
                'BULL_STRONG': -8,
                'BULL_WEAK': -3,
                'SIDEWAYS': +5,
                'BEAR_WEAK': +10,
                'BEAR_STRONG': +20,
                'VOLATILE': +8,
                'UNKNOWN': 0
            }
            
            return regime_adjustments.get(regime, 0)
        except:
            return 0
    
    def _calculate_correlation_adjustment(self, symbol):
        """Ajustement selon corrélation avec BTC"""
        try:
            if symbol == 'BTC/USD':
                return 0
            
            correlation = self._calculate_btc_correlation(symbol, days=30)
            btc_momentum = self._get_btc_momentum()
            
            correlation_thresholds = self._get_correlation_thresholds(symbol)
            momentum_thresholds = self._get_btc_momentum_thresholds()
            
            if correlation > correlation_thresholds['high'] and btc_momentum < momentum_thresholds['strong_down']:
                return +12
            elif correlation > correlation_thresholds['medium'] and btc_momentum < momentum_thresholds['weak_down']:
                return +6
            elif correlation < correlation_thresholds['low']:
                return -3
            else:
                return 0
        except:
            return 0
    
    def _detect_market_regime(self, symbol):
        """Détection de régime de marché"""
        try:
            # Utiliser bot depuis le contexte global si disponible
            if hasattr(self, 'bot') and self.bot:
                bot = self.bot
            else:
                # Fallback - essayer de récupérer depuis le contexte
                import inspect
                frame = inspect.currentframe()
                while frame:
                    if 'self' in frame.f_locals and hasattr(frame.f_locals['self'], 'get_klines'):
                        bot = frame.f_locals['self']
                        break
                    frame = frame.f_back
                else:
                    return 'UNKNOWN'
            
            volatility = self._get_symbol_volatility(symbol, bot)
            daily_tf = self.get_optimal_timeframe(symbol, 'regime_detection', volatility)
            hourly_tf = '1h' if volatility >= 3.0 else '4h'
            
            daily_klines = bot.get_klines(symbol, 50, daily_tf)
            hourly_klines = bot.get_klines(symbol, 100, hourly_tf)
            
            if len(daily_klines) < 20 or len(hourly_klines) < 50:
                return 'UNKNOWN'
            
            daily_closes = [k['close'] for k in daily_klines]
            hourly_closes = [k['close'] for k in hourly_klines]
            
            ema_20_daily = self._calculate_ema(daily_closes, 20)
            ema_50_daily = self._calculate_ema(daily_closes, 50)
            
            recent_volatility = self._calculate_std_volatility([
                (hourly_closes[i] - hourly_closes[i-1]) / hourly_closes[i-1] 
                for i in range(1, min(50, len(hourly_closes)))
            ]) * 100
            
            short_momentum = (daily_closes[-1] - daily_closes[-7]) / daily_closes[-7]
            current_price = daily_closes[-1]
            
            try:
                from utils.timeframe_analyzer import TimeframeAnalyzer
                analyzer = TimeframeAnalyzer()
                from utils.market_analyzer import MarketAnalyzer
                thresholds = MarketAnalyzer.get_volatility_thresholds(symbol)
                volatility_threshold = thresholds['extreme'] * 100
            except:
                volatility_threshold = 8
            
            momentum_thresholds = self._get_momentum_thresholds(symbol, volatility)
            
            if recent_volatility > volatility_threshold:
                return 'VOLATILE'
            elif current_price > ema_20_daily > ema_50_daily and short_momentum > momentum_thresholds['bull_strong']:
                return 'BULL_STRONG'
            elif current_price > ema_20_daily > ema_50_daily and short_momentum > momentum_thresholds['bull_weak']:
                return 'BULL_WEAK'
            elif current_price < ema_20_daily < ema_50_daily and short_momentum < momentum_thresholds['bear_strong']:
                return 'BEAR_STRONG'
            elif current_price < ema_20_daily < ema_50_daily and short_momentum < momentum_thresholds['bear_weak']:
                return 'BEAR_WEAK'
            else:
                if bot and hasattr(bot, 'get_klines') and hasattr(bot, 'calculate_ema'):
                    try:
                        h1_klines = bot.get_klines(symbol, 24, '1h')
                        if len(h1_klines) >= 12:
                            h1_closes = [k['close'] for k in h1_klines]
                            h1_ema20 = bot.calculate_ema(h1_closes, 10)
                            h1_prev = bot.calculate_ema(h1_closes[:-3], 10)
                            slope = (h1_ema20 - h1_prev) / h1_prev if h1_prev else 0
                            if slope < -0.0002:
                                return 'SIDEWAYS_DOWN'
                            elif slope > 0.0002:
                                return 'SIDEWAYS_UP'
                    except Exception:
                        pass
                return 'SIDEWAYS'
        except:
            return 'UNKNOWN'
    
    def _calculate_std_volatility(self, returns):
        """Calcule écart-type sans numpy"""
        if not returns:
            return 0
        mean = sum(returns) / len(returns)
        variance = sum((x - mean) ** 2 for x in returns) / len(returns)
        return variance ** 0.5
    
    def _calculate_ema(self, prices, period):
        """Calcule EMA"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _get_recent_trades(self, symbol, days=7):
        """Récupère trades récents pour analyse performance"""
        try:
            # Utiliser bot depuis le contexte si disponible
            if hasattr(self, 'bot') and self.bot:
                bot = self.bot
            else:
                import inspect
                frame = inspect.currentframe()
                while frame:
                    if 'self' in frame.f_locals and hasattr(frame.f_locals['self'], 'state'):
                        bot = frame.f_locals['self']
                        break
                    frame = frame.f_back
                else:
                    return []
            
            cutoff_time = datetime.now() - timedelta(days=days)
            recent_trades = []
            
            for position in bot.state.get('positions', []):
                if (position['symbol'] == symbol and 
                    position.get('timestamp') and
                    datetime.fromisoformat(position['timestamp']) > cutoff_time):
                    
                    if position.get('exit_price'):
                        entry_price = position['price']
                        exit_price = position['exit_price']
                        amount = position['amount']
                        
                        if position['side'] == 'buy':
                            pnl = (exit_price - entry_price) * amount
                        else:
                            pnl = (entry_price - exit_price) * amount
                        
                        recent_trades.append({
                            'pnl': pnl,
                            'timestamp': position['timestamp']
                        })
            
            return recent_trades
        except:
            return []
    
    def _calculate_btc_correlation(self, symbol, days=30):
        """Calcule corrélation avec BTC"""
        try:
            if hasattr(self, 'bot') and self.bot:
                bot = self.bot
            else:
                import inspect
                frame = inspect.currentframe()
                while frame:
                    if 'self' in frame.f_locals and hasattr(frame.f_locals['self'], 'get_klines'):
                        bot = frame.f_locals['self']
                        break
                    frame = frame.f_back
                else:
                    return 0.5
            
            volatility = self._get_symbol_volatility(symbol, bot)
            correlation_tf = self.get_optimal_timeframe(symbol, 'correlation', volatility)
            
            btc_klines = bot.get_klines('BTC/USD', days, correlation_tf)
            symbol_klines = bot.get_klines(symbol, days, correlation_tf)
            
            if len(btc_klines) < days or len(symbol_klines) < days:
                return 0.5
            
            btc_returns = [(btc_klines[i]['close'] - btc_klines[i-1]['close']) / btc_klines[i-1]['close'] 
                          for i in range(1, len(btc_klines))]
            symbol_returns = [(symbol_klines[i]['close'] - symbol_klines[i-1]['close']) / symbol_klines[i-1]['close'] 
                             for i in range(1, len(symbol_klines))]
            
            if np.std(btc_returns) == 0 or np.std(symbol_returns) == 0:
                return 0.5
            correlation = np.corrcoef(btc_returns, symbol_returns)[0, 1]
            return correlation if not np.isnan(correlation) else 0.5
        except:
            return 0.5
    
    def _get_btc_momentum(self):
        """Récupère momentum BTC récent"""
        try:
            if hasattr(self, 'bot') and self.bot:
                bot = self.bot
            else:
                import inspect
                frame = inspect.currentframe()
                while frame:
                    if 'self' in frame.f_locals and hasattr(frame.f_locals['self'], 'get_klines'):
                        bot = frame.f_locals['self']
                        break
                    frame = frame.f_back
                else:
                    return 0
            
            btc_volatility = self._get_symbol_volatility('BTC/USD', bot)
            momentum_tf = '1h' if btc_volatility >= 3.0 else '1d'
            period = 24 if momentum_tf == '1h' else 7
            
            btc_klines = bot.get_klines('BTC/USD', period, momentum_tf)
            if len(btc_klines) < period:
                return 0
            
            return (btc_klines[-1]['close'] - btc_klines[-period]['close']) / btc_klines[-period]['close']
        except:
            return 0
    
    def optimize_thresholds_daily(self):
        """Optimisation adaptative des seuils"""
        now = time.time()
        
        try:
            current_check_interval = self.bot.get_optimal_check_interval(self.trading_pairs)
            optimization_interval = current_check_interval * self.base_multiplier
        except:
            optimization_interval = 3600
        
        if now - self.last_optimization < optimization_interval:
            return
        
        performance_metrics = self._analyze_threshold_performance()
        
        self.last_optimization = now
    
    def _analyze_threshold_performance(self):
        """Analyse performance des seuils actuels"""
        return {
            'win_rate': 0.65,
            'profit_factor': 1.3,
            'needs_adjustment': False
        }
    
    def get_threshold_summary(self, symbol):
        """Résumé des seuils pour monitoring"""
        if symbol not in self.adaptive_thresholds:
            return "Seuils non calculés"
        
        data = self.adaptive_thresholds[symbol]
        components = data['components']
        
        return {
            'threshold_final': f"{data['threshold']:.0f}%",
            'base': f"{components['base']:.0f}%",
            'performance_adj': f"{components['performance']:+.0f}%",
            'market_adj': f"{components['market']:+.0f}%",
            'correlation_adj': f"{components['correlation']:+.0f}%",
            'last_update': datetime.fromtimestamp(data['timestamp']).strftime('%H:%M:%S')
        }
    
    def get_optimal_timeframe(self, symbol, analysis_type, volatility=None):
        """Timeframe adaptatif selon volatilité et type d'analyse"""
        if volatility is None:
            volatility = self._get_symbol_volatility(symbol)
        
        if analysis_type == 'regime_detection':
            if volatility >= 4.0:
                return '4h'
            elif volatility >= 2.0:
                return '12h'
            else:
                return '1d'
        elif analysis_type == 'correlation':
            if volatility >= 3.0:
                return '1h'
            else:
                return '1d'
        elif analysis_type == 'main_trading':
            if volatility >= 4.0:
                return '5m'
            elif volatility >= 2.5:
                return '15m'
            else:
                return '1h'
        
        return '15m'
    
    def _get_symbol_volatility(self, symbol, bot=None):
        """Récupère volatilité du symbole"""
        try:
            if not bot:
                if hasattr(self, 'bot') and self.bot:
                    bot = self.bot
                else:
                    import inspect
                    frame = inspect.currentframe()
                    while frame:
                        if 'self' in frame.f_locals and hasattr(frame.f_locals['self'], 'get_klines'):
                            bot = frame.f_locals['self']
                            break
                        frame = frame.f_back
                    else:
                        return 2.0
            
            klines = bot.get_klines(symbol, 20, '15m')
            if len(klines) >= 10:
                return bot.market_analyzer.calculate_volatility(klines, symbol)
            return 2.0
        except:
            return 2.0
    
    def _get_momentum_thresholds(self, symbol, volatility):
        """Seuils momentum adaptatifs selon crypto et volatilité"""
        if symbol in ['BTC/USD', 'ETH/USD']:
            return {
                'bull_strong': 0.05,
                'bull_weak': 0,
                'bear_strong': -0.05,
                'bear_weak': 0
            }
        else:
            return {
                'bull_strong': 0.1,
                'bull_weak': 0,
                'bear_strong': -0.1,
                'bear_weak': 0
            }
    
    def _get_correlation_thresholds(self, symbol):
        """Seuils corrélation adaptatifs selon crypto"""
        if symbol in ['BTC/USD']:
            return {'high': 0.9, 'medium': 0.7, 'low': 0.5}
        elif symbol in ['ETH/USD']:
            return {'high': 0.8, 'medium': 0.6, 'low': 0.4}
        else:
            return {'high': 0.7, 'medium': 0.5, 'low': 0.3}
    
    def _get_btc_momentum_thresholds(self):
        """Seuils momentum BTC adaptatifs"""
        return {
            'strong_down': -0.05,
            'weak_down': -0.02
        }

class TrailingStopManager:
    def __init__(self, trailing_percent=3.0):
        self.trailing_percent = trailing_percent
        self.positions = {}  # {symbol: {'buy_price': price, 'highest_price': price, 'stop_price': price, 'trailing_percent': percent}}
    
    def add_position(self, symbol, buy_price, trailing_percent=None, support_price=None, resistance_price=None, fee_rate=None):
        """Ajoute une nouvelle position avec trailing stop adaptatif, support technique et résistance"""
        percent = trailing_percent if trailing_percent is not None else self.trailing_percent
        stop_price = buy_price * (1 - percent / 100)
        if fee_rate is None:
            fee_rate = float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100
        
        # Si un support technique est spécifié, caler le stop initial dessous s'il est plus protecteur
        if support_price is not None:
            technical_stop = float(support_price) * 0.99
            if technical_stop > stop_price:
                stop_price = technical_stop
                print(f"🏰 {symbol}: Stop initial calé sous le support technique à {stop_price:.2f}")
                
        self.positions[symbol] = {
            'buy_price': buy_price,
            'highest_price': buy_price,
            'stop_price': stop_price,
            'trailing_percent': percent,
            'initial_trailing_percent': percent,
            'breakeven_active': False,
            'resistance_price': float(resistance_price) if resistance_price else None,
            'fee_rate': float(fee_rate or 0),
            'created_at': datetime.now().isoformat()
        }
        print(f"🎯 Trailing stop activé pour {symbol}: Stop initial à {stop_price:.2f} (écart: {percent:.1f}%)")
    
    def update_position(self, symbol, current_price):
        """Met à jour le trailing stop si le prix monte avec resserrement progressif selon le profit et Breakeven Stop"""
        if symbol not in self.positions:
            return False
            
        position = self.positions[symbol]
        changed = False
        initial_percent = position.get('initial_trailing_percent', self.trailing_percent)
        
        # Calcul du profit latent en pourcentage
        profit_pct = ((current_price - position['buy_price']) / position['buy_price']) * 100
        
        # SYSTEM ZÉRO PERTE (BREAKEVEN STOP)
        be_enabled = os.getenv('BREAKEVEN_STOP_ENABLED', 'True').lower() == 'true'
        be_use_res = os.getenv('BREAKEVEN_USE_RESISTANCE', 'True').lower() == 'true'
        be_trigger_pct = float(os.getenv('BREAKEVEN_TRIGGER_PROFIT_PCT', '1.5'))
        be_lock_pct = float(os.getenv('BREAKEVEN_LOCK_PROFIT_PCT', '1.0'))
        stored_fee_rate = position.get('fee_rate')
        fee_rate = float(stored_fee_rate) if stored_fee_rate is not None else (float(os.getenv('TRADING_FEE_PERCENT', '0.1')) / 100)
        buy_price = float(position['buy_price'])
        breakeven_price = buy_price * (1 + fee_rate) / max(0.000001, (1 - fee_rate))
        trading_fee_pct = ((breakeven_price / buy_price) - 1) * 100
        net_floor_pct = float(os.getenv('BREAKEVEN_MIN_NET_PROFIT_PCT', '0.05'))
        trigger_buffer_pct = float(os.getenv('BREAKEVEN_TRIGGER_BUFFER_PCT', '0.05'))
        min_stop_gap_pct = float(os.getenv('BREAKEVEN_MIN_STOP_GAP_PCT', '0.03'))
        fee_floor_stop_price = buy_price * (1 + (trading_fee_pct + net_floor_pct) / 100)
        min_price_for_fee_floor = fee_floor_stop_price / max(0.000001, (1 - min_stop_gap_pct / 100))
        fee_floor_trigger_pct = max(
            trading_fee_pct + trigger_buffer_pct,
            ((min_price_for_fee_floor / buy_price) - 1) * 100
        )
        res_price = position.get('resistance_price')
        
        # Mode Résistance Dynamique (50% de la distance vers la résistance)
        if be_use_res and res_price and res_price > position['buy_price']:
            res_dist_pct = ((res_price - position['buy_price']) / position['buy_price']) * 100
            effective_trigger_pct = max(fee_floor_trigger_pct, res_dist_pct * 0.5)
            net_res_gain = max(0.0, res_dist_pct - trading_fee_pct)
            lock_profit = net_res_gain * 0.5
            be_target_price = position['buy_price'] * (1 + (trading_fee_pct + lock_profit) / 100)
        else:
            if be_trigger_pct == 0.0:
                effective_trigger_pct = trading_fee_pct
            elif be_trigger_pct < 0:
                effective_trigger_pct = trading_fee_pct + abs(be_trigger_pct)
            else:
                effective_trigger_pct = be_trigger_pct
            be_target_price = position['buy_price'] * (1 + (trading_fee_pct + be_lock_pct) / 100)

        if be_enabled and profit_pct >= fee_floor_trigger_pct:
            protected_stop = max(fee_floor_stop_price, be_target_price if profit_pct >= effective_trigger_pct else fee_floor_stop_price)
            max_safe_stop = current_price * (1 - min_stop_gap_pct / 100)
            if max_safe_stop < fee_floor_stop_price:
                return changed
            protected_stop = min(protected_stop, max_safe_stop)
            if protected_stop > position['stop_price']:
                old_stop = position['stop_price']
                position['stop_price'] = protected_stop
                position['breakeven_active'] = True
                changed = True
                print(f"🛡️ {symbol}: Stop net protégé ! Stop relevé {old_stop:.2f} → {protected_stop:.2f} (Frais A/R: {trading_fee_pct:.3f}%, plancher net: +{net_floor_pct:.2f}%)")

        # Resserrement par paliers du pourcentage de trailing
        if profit_pct >= 8.0:
            percent = initial_percent * 0.4  # Resserrement agressif (ex: 3.5% -> 1.4%)
        elif profit_pct >= 5.0:
            percent = initial_percent * 0.6  # Resserrement modéré (ex: 3.5% -> 2.1%)
        elif profit_pct >= 3.0:
            percent = initial_percent * 0.8  # Resserrement léger (ex: 3.5% -> 2.8%)
        else:
            percent = initial_percent

        # Le pourcentage de trailing ne peut que se resserrer (diminuer), jamais s'élargir
        # Cela évite qu'une baisse de profit_pct entre deux paliers ne produise
        # un stop calculé avec un écart plus grand → stop qui "descend" par rapport au précédent
        current_trailing = position.get('trailing_percent', initial_percent)
        if percent > current_trailing:
            percent = current_trailing

        # Si nouveau plus haut, on met à jour le trailing stop
        if current_price > position['highest_price']:
            position['highest_price'] = current_price
            changed = True
            new_stop = current_price * (1 - percent / 100)
            
            # Le stop ne peut que monter, jamais descendre
            if new_stop > position['stop_price']:
                old_stop = position['stop_price']
                position['stop_price'] = new_stop
                position['trailing_percent'] = percent
                changed = True
                print(f"📈 {symbol}: Trailing stop mis à jour {old_stop:.2f} → {new_stop:.2f} (écart: {percent:.1f}%, profit: {profit_pct:.1f}%)")
            elif percent < position.get('trailing_percent', initial_percent):
                position['trailing_percent'] = percent
                changed = True
        
        return changed
    
    def should_stop_loss(self, symbol, current_price):
        """Vérifie si le trailing stop est déclenché"""
        if symbol not in self.positions:
            return False
            
        position = self.positions[symbol]
        
        if current_price <= position['stop_price']:
            profit_percent = ((current_price - position['buy_price']) / position['buy_price']) * 100
            print(f"🛑 Trailing stop déclenché pour {symbol}!")
            print(f"   Achat: {position['buy_price']:.2f}")
            print(f"   Plus haut: {position['highest_price']:.2f}")
            print(f"   Vente: {current_price:.2f}")
            print(f"   Profit: {profit_percent:.2f}%")
            return True
            
        return False
    
    def remove_position(self, symbol):
        """Supprime une position fermée"""
        if symbol in self.positions:
            del self.positions[symbol]

class CorrelationManager:
    def __init__(self, max_correlated_positions=2):
        self.max_correlated_positions = max_correlated_positions
        self.crypto_groups = {
            'major': ['BTC/USD', 'ETH/USD'],
            'altcoins': ['SOL/USD', 'ADA/USD']
        }
        self.active_positions = set()
        self.market_sentiment = 'neutral'  # 'bullish', 'bearish', 'neutral'
        self.last_sentiment_check = 0
    
    def update_market_sentiment(self, bot):
        """Analyse le sentiment du marché"""
        if time.time() - self.last_sentiment_check < 300:  # Check toutes les 5 minutes
            return
            
        try:
            btc_price = bot.get_price('BTC/USD')
            eth_price = bot.get_price('ETH/USD')
            
            # Logique simplifiée de sentiment (à améliorer avec de vrais indicateurs)
            # Pour l'instant, on reste neutre
            self.market_sentiment = 'neutral'
            self.last_sentiment_check = time.time()
            
        except Exception as e:
            print(f"Erreur analyse sentiment: {e}")
    
    def can_open_position(self, symbol, bot):
        """Vérifie si on peut ouvrir une position selon la corrélation"""
        # Synchroniser avec le solde réel
        balance = bot.balance_manager.get_balance()
        base_currency = symbol.split('/')[0]
        current_holding = balance.get(base_currency, {}).get('free', 0)
        
        # Si position déjà ouverte (solde réel), bloquer
        if current_holding > 0.00001:
            position_value = current_holding * bot.get_price(symbol)
            min_trade_value = bot.get_min_amount(symbol)['min_cost']
            if position_value >= min_trade_value:
                print(f"🔴 {base_currency} bloqué: position ouverte {current_holding:.6f} ({position_value:.2f} USD)")
                return False
            # else:
            #     print(f"🧹 {base_currency} poussière ignorée: {current_holding:.6f} ({position_value:.2f} < {min_trade_value:.2f})")
        
        self.update_market_sentiment(bot)
        
        # Trouver le groupe de la crypto
        symbol_group = None
        for group, symbols in self.crypto_groups.items():
            if symbol in symbols:
                symbol_group = group
                break
        
        if not symbol_group:
            return True
        
        # Compter positions réelles dans le même groupe
        group_positions = 0
        for group_symbol in self.crypto_groups[symbol_group]:
            if group_symbol == symbol:
                continue
            group_base = group_symbol.split('/')[0]
            group_holding = balance.get(group_base, {}).get('free', 0)
            if group_holding > 0.00001:
                group_value = group_holding * bot.get_price(group_symbol)
                if group_value >= bot.get_min_amount(group_symbol)['min_cost']:
                    group_positions += 1
        
        if group_positions >= self.max_correlated_positions:
            return False
        
        if self.market_sentiment == 'bearish':
            return False
            
        return True
    
    def add_position(self, symbol):
        """Ajoute une position active"""
        self.active_positions.add(symbol)
        print(f"📊 Position ajoutée: {symbol} (Total: {len(self.active_positions)})")
    
    def remove_position(self, symbol):
        """Supprime une position fermée"""
        self.active_positions.discard(symbol)
        print(f"📊 Position fermée: {symbol} (Total: {len(self.active_positions)})")
