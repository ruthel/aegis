"""
Gestionnaire de seuils adaptatifs - Niveau Quant/Hedge Fund
Optimise les seuils selon performance et conditions de marché
"""
import time
import numpy as np
from datetime import datetime, timedelta

class AdaptiveThresholdsManager:
    def __init__(self, bot):
        self.bot = bot
        self.performance_history = []
        self.market_regimes = {}
        self.adaptive_thresholds = {}
        self.last_optimization = 0
        # Dynamique: s'adapte au rythme du bot
        self.base_multiplier = 1800  # 30min si check_interval=1s
        
    def get_adaptive_confidence_threshold(self, symbol, volatility):
        """Seuil de confiance adaptatif - Méthode Quantitative"""
        # 1. Seuil de base selon volatilité (maintenant centralisé)
        base_threshold = self._get_base_threshold(volatility, symbol)
        
        # 2. Ajustement selon performance récente
        performance_adj = self._calculate_performance_adjustment(symbol)
        
        # 3. Ajustement selon régime de marché
        market_adj = self._calculate_market_regime_adjustment(symbol)
        
        # 4. Ajustement selon corrélation
        correlation_adj = self._calculate_correlation_adjustment(symbol)
        
        # 5. Combinaison sophistiquée (comme Renaissance Technologies)
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
        """Seuil de base selon volatilité - Utilise le gestionnaire centralisé"""
        try:
            from utils.timeframe_manager import TimeframeManager
            return TimeframeManager.get_confidence_threshold(symbol or 'BTC/USDT', volatility)
        except:
            # Fallback seuils fixes
            if volatility >= 4.0:
                return 25  # Très volatil = seuil bas
            elif volatility >= 3.0:
                return 30
            elif volatility >= 2.0:
                return 35
            elif volatility >= 1.5:
                return 40
            else:
                return 45  # Peu volatil = seuil élevé
    
    def _calculate_performance_adjustment(self, symbol):
        """Ajustement selon performance récente - Méthode Adaptative"""
        try:
            # Récupérer trades récents (7 derniers jours)
            recent_trades = self._get_recent_trades(symbol, days=7)
            
            if len(recent_trades) < 3:
                return 0  # Pas assez de données
            
            # Calculer win rate et profit factor
            wins = sum(1 for trade in recent_trades if trade['pnl'] > 0)
            win_rate = wins / len(recent_trades)
            
            total_profit = sum(trade['pnl'] for trade in recent_trades if trade['pnl'] > 0)
            total_loss = abs(sum(trade['pnl'] for trade in recent_trades if trade['pnl'] < 0))
            profit_factor = total_profit / total_loss if total_loss > 0 else 2.0
            
            # Ajustement selon performance (comme les hedge funds)
            if win_rate > 0.7 and profit_factor > 1.5:
                return -10  # Excellente performance = plus agressif
            elif win_rate > 0.6 and profit_factor > 1.2:
                return -5   # Bonne performance = légèrement plus agressif
            elif win_rate < 0.4 or profit_factor < 0.8:
                return +15  # Mauvaise performance = plus conservateur
            elif win_rate < 0.5 or profit_factor < 1.0:
                return +8   # Performance médiocre = plus conservateur
            else:
                return 0    # Performance normale = pas d'ajustement
                
        except Exception as e:
            return 0
    
    def _calculate_market_regime_adjustment(self, symbol):
        """Ajustement selon régime de marché - Analyse Quantitative"""
        try:
            # Détecter régime de marché
            regime = self._detect_market_regime(symbol)
            
            # Ajustements selon régime (calibrés sur backtests)
            regime_adjustments = {
                'BULL_STRONG': -8,    # Marché très haussier = agressif
                'BULL_WEAK': -3,     # Marché haussier faible = légèrement agressif
                'SIDEWAYS': +5,      # Marché latéral = plus conservateur
                'BEAR_WEAK': +10,    # Marché baissier faible = conservateur
                'BEAR_STRONG': +20,  # Marché très baissier = très conservateur
                'VOLATILE': +8,      # Marché très volatil = conservateur
                'UNKNOWN': 0         # Régime indéterminé = neutre
            }
            
            return regime_adjustments.get(regime, 0)
            
        except Exception as e:
            return 0
    
    def _calculate_correlation_adjustment(self, symbol):
        """Ajustement selon corrélation avec BTC - Gestion Risque Institutionnelle"""
        try:
            if symbol == 'BTC/USDT':
                return 0
            
            # Calculer corrélation avec BTC sur 30 jours
            correlation = self._calculate_btc_correlation(symbol, days=30)
            
            # Si forte corrélation avec BTC et BTC en difficulté
            btc_momentum = self._get_btc_momentum()
            
            # Seuils corrélation adaptatifs selon crypto
            correlation_thresholds = self._get_correlation_thresholds(symbol)
            momentum_thresholds = self._get_btc_momentum_thresholds()
            
            if correlation > correlation_thresholds['high'] and btc_momentum < momentum_thresholds['strong_down']:
                return +12  # Très conservateur si corrélé à BTC en baisse
            elif correlation > correlation_thresholds['medium'] and btc_momentum < momentum_thresholds['weak_down']:
                return +6   # Conservateur
            elif correlation < correlation_thresholds['low']:
                return -3   # Légèrement plus agressif
            else:
                return 0    # Corrélation normale
                
        except Exception as e:
            return 0
    
    def _detect_market_regime(self, symbol):
        """Détection de régime de marché - Algorithme Quantitatif"""
        try:
            # Timeframes adaptatifs selon volatilité
            volatility = self._get_symbol_volatility(symbol)
            daily_tf = self.get_optimal_timeframe(symbol, 'regime_detection', volatility)
            hourly_tf = '1h' if volatility >= 3.0 else '4h'
            
            # Récupérer données multi-timeframes
            daily_klines = self.bot.get_klines(symbol, 50, daily_tf)
            hourly_klines = self.bot.get_klines(symbol, 100, hourly_tf)
            
            if len(daily_klines) < 20 or len(hourly_klines) < 50:
                return 'UNKNOWN'
            
            # Calculer indicateurs de régime
            daily_closes = [k['close'] for k in daily_klines]
            hourly_closes = [k['close'] for k in hourly_klines]
            
            # Tendance long terme (EMA 20/50 daily)
            ema_20_daily = self._calculate_ema(daily_closes, 20)
            ema_50_daily = self._calculate_ema(daily_closes, 50)
            
            # Volatilité récente
            recent_volatility = np.std([
                (hourly_closes[i] - hourly_closes[i-1]) / hourly_closes[i-1] 
                for i in range(1, min(50, len(hourly_closes)))
            ]) * 100
            
            # Momentum court terme
            short_momentum = (daily_closes[-1] - daily_closes[-7]) / daily_closes[-7]
            
            # Classification du régime
            current_price = daily_closes[-1]
            
            # Seuils adaptatifs selon crypto au lieu de fixes
            try:
                from utils.timeframe_manager import TimeframeManager
                thresholds = TimeframeManager.get_volatility_thresholds(symbol)
                volatility_threshold = thresholds['extreme'] * 100  # Convertir en %
            except:
                volatility_threshold = 8  # Fallback
            
            # Seuils momentum adaptatifs selon volatilité de la crypto
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
                return 'SIDEWAYS'
                
        except Exception as e:
            return 'UNKNOWN'
    
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
            cutoff_time = datetime.now() - timedelta(days=days)
            recent_trades = []
            
            for position in self.bot.state.get('positions', []):
                if (position['symbol'] == symbol and 
                    position.get('timestamp') and
                    datetime.fromisoformat(position['timestamp']) > cutoff_time):
                    
                    # Calculer P&L si trade fermé
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
            
        except Exception as e:
            return []
    
    def _calculate_btc_correlation(self, symbol, days=30):
        """Calcule corrélation avec BTC"""
        try:
            # Timeframe adaptatif selon volatilité
            volatility = self._get_symbol_volatility(symbol)
            correlation_tf = self.get_optimal_timeframe(symbol, 'correlation', volatility)
            
            # Récupérer données des deux cryptos
            btc_klines = self.bot.get_klines('BTC/USDT', days, correlation_tf)
            symbol_klines = self.bot.get_klines(symbol, days, correlation_tf)
            
            if len(btc_klines) < days or len(symbol_klines) < days:
                return 0.5  # Corrélation moyenne par défaut
            
            # Calculer returns
            btc_returns = [(btc_klines[i]['close'] - btc_klines[i-1]['close']) / btc_klines[i-1]['close'] 
                          for i in range(1, len(btc_klines))]
            symbol_returns = [(symbol_klines[i]['close'] - symbol_klines[i-1]['close']) / symbol_klines[i-1]['close'] 
                             for i in range(1, len(symbol_klines))]
            
            # Calculer corrélation
            correlation = np.corrcoef(btc_returns, symbol_returns)[0, 1]
            return correlation if not np.isnan(correlation) else 0.5
            
        except Exception as e:
            return 0.5
    
    def _get_btc_momentum(self):
        """Récupère momentum BTC récent"""
        try:
            # Timeframe adaptatif selon volatilité BTC
            btc_volatility = self._get_symbol_volatility('BTC/USDT')
            momentum_tf = '1h' if btc_volatility >= 3.0 else '1d'
            period = 24 if momentum_tf == '1h' else 7
            
            btc_klines = self.bot.get_klines('BTC/USDT', period, momentum_tf)
            if len(btc_klines) < period:
                return 0
            
            return (btc_klines[-1]['close'] - btc_klines[-period]['close']) / btc_klines[-period]['close']
            
        except Exception as e:
            return 0
    
    def optimize_thresholds_daily(self):
        """Optimisation adaptative des seuils - Processus Automatisé"""
        now = time.time()
        
        # Calcul dynamique de l'intervalle d'optimisation
        try:
            trading_pairs = self.bot.crypto_scorer.rank_cryptos(self.bot, 
                self.bot.get_trading_pairs(), [])
            current_check_interval = self.bot.get_optimal_check_interval(trading_pairs)
            optimization_interval = current_check_interval * self.base_multiplier
        except:
            optimization_interval = 3600  # Fallback 1h
        
        if now - self.last_optimization < optimization_interval:
            return
        
        # Analyser performance des seuils actuels
        performance_metrics = self._analyze_threshold_performance()
        
        # Ajuster les paramètres si nécessaire
        if performance_metrics['needs_adjustment']:
            self._adjust_threshold_parameters(performance_metrics)
            print(f"✅ Seuils optimisés - Win rate: {performance_metrics['win_rate']:.1%}")
        
        self.last_optimization = now
    
    def _analyze_threshold_performance(self):
        """Analyse performance des seuils actuels"""
        # Implémentation simplifiée - En production, analyse plus sophistiquée
        return {
            'win_rate': 0.65,  # Exemple
            'profit_factor': 1.3,
            'needs_adjustment': False
        }
    
    def _adjust_threshold_parameters(self, metrics):
        """Ajuste paramètres selon performance"""
        # Implémentation des ajustements automatiques
        pass
    
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
    
    def get_trading_pairs(self):
        """Récupère les paires de trading configurées"""
        import os
        return os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT').split(',')
    
    def get_optimal_timeframe(self, symbol, analysis_type, volatility=None):
        """Timeframe adaptatif selon volatilité et type d'analyse"""
        if volatility is None:
            volatility = self._get_symbol_volatility(symbol)
        
        if analysis_type == 'regime_detection':
            if volatility >= 4.0:
                return '4h'    # Très volatil = plus réactif
            elif volatility >= 2.0:
                return '12h'   # Moyen = compromis
            else:
                return '1d'    # Calme = tendance long terme
        
        elif analysis_type == 'correlation':
            if volatility >= 3.0:
                return '1h'    # Volatil = corrélation change vite
            else:
                return '1d'    # Stable = corrélation stable
        
        elif analysis_type == 'main_trading':
            if volatility >= 4.0:
                return '5m'    # Très volatil = ultra réactif
            elif volatility >= 2.5:
                return '15m'   # Moyen (actuel)
            else:
                return '1h'    # Calme = long terme
        
        return '15m'  # Fallback
    
    def _get_symbol_volatility(self, symbol):
        """Récupère volatilité du symbole"""
        try:
            klines = self.bot.get_klines(symbol, 20, '15m')
            if len(klines) >= 10:
                from utils.volatility_calculator import VolatilityCalculator
                return VolatilityCalculator.calculate(klines, symbol)
            return 2.0
        except:
            return 2.0
    
    def _get_momentum_thresholds(self, symbol, volatility):
        """Seuils momentum adaptatifs selon crypto et volatilité"""
        # BTC/ETH = seuils plus bas (moins volatils)
        if symbol in ['BTC/USDT', 'ETH/USDT']:
            return {
                'bull_strong': 0.05,   # 5% au lieu de 10%
                'bull_weak': 0,
                'bear_strong': -0.05,  # -5% au lieu de -10%
                'bear_weak': 0
            }
        # Altcoins = seuils standards
        else:
            return {
                'bull_strong': 0.1,    # 10% standard
                'bull_weak': 0,
                'bear_strong': -0.1,   # -10% standard
                'bear_weak': 0
            }
    
    def _get_correlation_thresholds(self, symbol):
        """Seuils corrélation adaptatifs selon crypto"""
        # Altcoins ont généralement plus de corrélation avec BTC
        if symbol in ['BTC/USDT']:
            return {'high': 0.9, 'medium': 0.7, 'low': 0.5}  # BTC = seuils élevés
        elif symbol in ['ETH/USDT']:
            return {'high': 0.8, 'medium': 0.6, 'low': 0.4}  # ETH = seuils moyens
        else:
            return {'high': 0.7, 'medium': 0.5, 'low': 0.3}  # Altcoins = seuils bas
    
    def _get_btc_momentum_thresholds(self):
        """Seuils momentum BTC adaptatifs"""
        return {
            'strong_down': -0.05,  # -5%
            'weak_down': -0.02     # -2%
        }