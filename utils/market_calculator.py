"""
Calculateur centralisé pour métriques de marché et scoring crypto
Fusion de crypto_scorer et market_calculator pour éviter confusion
"""
import time
from datetime import datetime
import os

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

class MarketCalculator:
    """Calculs de marché centralisés et scoring crypto unifié"""
    
    def __init__(self, min_score=40, max_tradeable=2):
        # Configuration scoring crypto
        self.base_min_score = min_score
        self.max_tradeable = max_tradeable
        self.blacklist = {}
        self.blacklist_duration = 3600
        self.score_history = {}
        self.performance_weights = self._get_default_weights()
    
    @staticmethod
    def calculate_momentum(klines):
        """Calcul momentum sur 10 dernières périodes"""
        if len(klines) < 10:
            return 0
        
        if NUMPY_AVAILABLE:
            prices = np.array([k['close'] for k in klines[-10:]])
            return (prices[-1] - prices[0]) / prices[0] * 100
        
        prices = [k['close'] for k in klines[-10:]]
        return (prices[-1] - prices[0]) / prices[0] * 100
    
    @staticmethod
    def calculate_volume_avg(klines, periods=5):
        """Calcul volume moyen sur N périodes"""
        if len(klines) < periods:
            return 0
        
        if NUMPY_AVAILABLE:
            volumes = np.array([k['volume'] for k in klines[-periods:]])
            return volumes.mean()
        
        return sum(k['volume'] for k in klines[-periods:]) / periods
    
    @staticmethod
    def calculate_professional_volume_metrics(bot, symbol):
        """Calcul volume professionnel : 7j + moyennes mobiles + VWAP"""
        try:
            # 1. Essayer d'abord 7 jours (optimal)
            klines_7d = bot.get_klines(symbol, 672, '15m')  # 7j en 15m
            if len(klines_7d) >= 672:
                return MarketCalculator._calculate_7d_metrics(klines_7d)
            
            # 2. Fallback 24h si 7j indisponible
            klines_24h = bot.get_klines(symbol, 96, '15m')  # 24h en 15m
            if len(klines_24h) >= 50:
                return MarketCalculator._calculate_24h_metrics(klines_24h)
            
            return None
        except:
            return None
    
    @staticmethod
    def _calculate_7d_metrics(klines_7d):
        """Métriques volume 7 jours (optimal)"""
        volumes = [k['volume'] for k in klines_7d]
        
        # Moyennes mobiles 7j
        sma_96 = sum(volumes[-96:]) / 96    # 24h
        sma_336 = sum(volumes[-336:]) / 336  # 3.5j
        sma_672 = sum(volumes) / len(volumes)  # 7j complets
        
        current_volume = volumes[-1]
        
        # VWAP 7j (plus précis)
        total_pv = sum(k['close'] * k['volume'] for k in klines_7d[-96:])
        total_volume = sum(k['volume'] for k in klines_7d[-96:])
        vwap = total_pv / total_volume if total_volume > 0 else 0
        
        return {
            'volume_7d': sum(volumes),
            'volume_24h': sum(volumes[-96:]),
            'sma_24h': sma_96,
            'sma_3d': sma_336,
            'sma_7d': sma_672,
            'current_volume': current_volume,
            'ratio_vs_24h': current_volume / sma_96 if sma_96 > 0 else 1,
            'ratio_vs_7d': current_volume / sma_672 if sma_672 > 0 else 1,
            'vwap_7d': vwap,
            'data_quality': 'HIGH_7D',
            'volume_trend': MarketCalculator._get_volume_trend_7d(sma_96, sma_336, sma_672)
        }
    
    @staticmethod
    def _calculate_24h_metrics(klines_24h):
        """Métriques volume 24h (fallback)"""
        volumes = [k['volume'] for k in klines_24h]
        sma_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
        sma_50 = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else 0
        current_volume = volumes[-1]
        
        total_pv = sum(k['close'] * k['volume'] for k in klines_24h[-20:])
        total_volume = sum(k['volume'] for k in klines_24h[-20:])
        vwap = total_pv / total_volume if total_volume > 0 else 0
        
        return {
            'volume_24h': sum(volumes),
            'sma_20': sma_20,
            'sma_50': sma_50,
            'current_volume': current_volume,
            'ratio_vs_sma20': current_volume / sma_20 if sma_20 > 0 else 1,
            'ratio_vs_sma50': current_volume / sma_50 if sma_50 > 0 else 1,
            'vwap': vwap,
            'data_quality': 'LIMITED_24H',
            'volume_trend': 'INCREASING' if current_volume / sma_20 > 1.2 else 'DECREASING' if current_volume / sma_20 < 0.8 else 'STABLE'
        }
    
    @staticmethod
    def _get_volume_trend_7d(sma_24h, sma_3d, sma_7d):
        """Tendance volume basée sur moyennes 7j"""
        if sma_24h > sma_3d * 1.2 and sma_3d > sma_7d * 1.1:
            return 'STRONG_INCREASING'
        elif sma_24h > sma_3d * 1.1:
            return 'INCREASING'
        elif sma_24h < sma_3d * 0.8 and sma_3d < sma_7d * 0.9:
            return 'STRONG_DECREASING'
        elif sma_24h < sma_3d * 0.9:
            return 'DECREASING'
        else:
            return 'STABLE'
    
    @staticmethod
    def get_crypto_profile(volatility):
        """Profil adaptatif selon volatilité (échelle Binance 1-5)"""
        if volatility >= 4.0:
            return {
                'min_confidence': 45,
                'profit_target': 1.5,
                'confidence_adjustment': +5
            }
        elif volatility >= 3.0:
            return {
                'min_confidence': 50,
                'profit_target': 1.0,
                'confidence_adjustment': +3
            }
        elif volatility >= 2.0:
            return {
                'min_confidence': 55,
                'profit_target': 0.7,
                'confidence_adjustment': 0
            }
        else:
            return {
                'min_confidence': 60,
                'profit_target': 0.5,
                'confidence_adjustment': 0
            }
    
    @staticmethod
    def calculate_momentum_score(klines):
        """Score momentum (0-25 points)"""
        if len(klines) < 10:
            return 0
        
        momentum = MarketCalculator.calculate_momentum(klines)
        
        if momentum >= 1:
            return 25
        elif momentum >= 0.5:
            return 20
        elif momentum >= 0.2:
            return 15
        elif momentum >= 0:
            return 10
        elif momentum >= -0.5:
            return 8
        else:
            return 5
    
    @staticmethod
    def calculate_volume_score(klines):
        """Score volume professionnel (0-25 points) - Standards institutionnels"""
        if len(klines) < 5:
            return 0
        
        # Utiliser volume moyen sur période complète (plus stable)
        avg_volume = sum(k['volume'] for k in klines) / len(klines)
        
        # Seuils professionnels basés sur liquidité réelle
        if avg_volume >= 10000000:     # 10M+ = Liquidité institutionnelle
            return 25
        elif avg_volume >= 5000000:    # 5M+ = Très bonne liquidité
            return 22
        elif avg_volume >= 2000000:    # 2M+ = Bonne liquidité
            return 18
        elif avg_volume >= 1000000:    # 1M+ = Liquidité acceptable
            return 15
        elif avg_volume >= 500000:     # 500K+ = Liquidité minimale
            return 10
        elif avg_volume >= 100000:     # 100K+ = Très faible
            return 5
        else:
            return 0  # < 100K = Illiquide
    
    @staticmethod
    def calculate_loss_percent(current_price, buy_price):
        """Calcul pourcentage de perte/gain"""
        return ((current_price - buy_price) / buy_price) * 100
    
    @staticmethod
    def calculate_hours_held(buy_time):
        """Calcul heures de détention"""
        import time
        return (time.time() - buy_time) / 3600
    
    # ===== MÉTHODES CRYPTO SCORING =====
    
    def calculate_volatility_score(self, klines, symbol='', volatility=None, websocket_manager=None):
        """Score basé sur volatilité 1-5 (0-30 points) - ADAPTATIF"""
        if len(klines) < 10:
            return 0
        
        # Calculer volatilité réelle si non fournie
        if volatility is None:
            from utils.volatility_calculator import VolatilityCalculator
            volatility = VolatilityCalculator.calculate(klines, symbol, websocket_manager)
        
        # Points adaptatifs selon crypto
        base_points = self._get_base_volatility_points(volatility)
        crypto_multiplier = self._get_crypto_multiplier(symbol)
        
        return int(base_points * crypto_multiplier)
    
    def calculate_spread_score(self, symbol, current_price):
        """Score basé sur spread estimé (0-10 points)"""
        # Estimation du spread basée sur le prix
        estimated_spread = 0.01  # 0.01% par défaut
        
        if estimated_spread <= 0.005:
            return 10
        elif estimated_spread <= 0.01:
            return 7
        elif estimated_spread <= 0.02:
            return 4
        else:
            return 2
    
    def calculate_history_score(self, symbol, stuck_positions):
        """Score basé sur historique (0-10 points)"""
        if symbol in stuck_positions:
            return 0
        
        if symbol in self.blacklist:
            blacklist_time = self.blacklist[symbol]
            if time.time() - blacklist_time < self.blacklist_duration:
                return 0
            else:
                del self.blacklist[symbol]
        
        return 10
    
    def score_crypto(self, bot, symbol, stuck_positions, websocket_manager=None, volatility=None):
        """Calcule le score total d'une crypto (0-100) - Version professionnelle 7j"""
        try:
            from utils.timeframe_manager import TimeframeManager
            optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
            
            # Essayer d'abord 7 jours pour volume professionnel
            klines_7d = bot.get_klines(symbol, 672, '15m')  # 7 jours
            klines_short = bot.get_klines(symbol, 20, optimal_timeframe)  # Analyse rapide
            current_price = bot.get_price(symbol)
            
            if not klines_short or len(klines_short) < 10:
                return 0
            
            # Scoring avec données optimales
            websocket_manager = getattr(bot, 'websocket', None)
            volatility_score = self.calculate_volatility_score(klines_short, symbol, volatility, websocket_manager)
            
            # Volume score avec priorité 7j
            if klines_7d and len(klines_7d) >= 672:
                volume_score = self.calculate_volume_score(klines_7d)  # 7j optimal
                data_quality = 'HIGH_7D'
            elif len(klines_short) >= 96:  # Fallback 24h
                klines_24h = bot.get_klines(symbol, 96, '15m')
                volume_score = self.calculate_volume_score(klines_24h) if klines_24h else self.calculate_volume_score(klines_short)
                data_quality = 'MEDIUM_24H'
            else:
                volume_score = self.calculate_volume_score(klines_short)  # Fallback minimal
                data_quality = 'LIMITED'
            
            momentum_score = self.calculate_momentum_score(klines_short)
            spread_score = self.calculate_spread_score(symbol, current_price)
            history_score = self.calculate_history_score(symbol, stuck_positions)
            
            # Pondération avec bonus qualité données
            weights = self._get_dynamic_weights(symbol)
            if data_quality == 'HIGH_7D':
                weights['volume'] *= 1.2  # Bonus 20% pour données 7j
            
            total_score = (
                volatility_score * weights['volatility'] +
                volume_score * weights['volume'] +
                momentum_score * weights['momentum'] +
                spread_score * weights['spread'] +
                history_score * weights['history']
            )
            
            return min(total_score, 100)  # Cap à 100
            
        except Exception as e:
            print(f"❌ Erreur scoring {symbol}: {e}")
            return 0
    
    def rank_cryptos(self, bot, trading_pairs, stuck_positions):
        """Classe toutes les cryptos et retourne les meilleures"""
        balance = bot.balance_manager.get_balance()
        prices_cache = {}
        klines_cache = {}
        
        usdt_available = balance.get('USDT', {}).get('free', 0)
        
        # Vérifier si balance USDT disponible
        if usdt_available <= 0:
            print(f"⚠️ Balance USDT: 0 - Aucune crypto tradable")
            return []
        
        scores = []
        volatilities = []
        volume_ratios = []
        
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            
            # Min cost pour cette crypto spécifique
            min_cost = bot.get_min_amount(symbol)['min_cost']
            
            # CONDITION PRINCIPALE: Balance doit être ≥ min_cost de CETTE crypto
            if usdt_available < min_cost:
                continue  # Skip cette crypto, pas assez de fonds
            
            # Vérifier poussière existante
            crypto_balance = balance.get(base_currency, {}).get('free', 0)
            if crypto_balance > 0.00001:
                price = prices_cache.get(symbol) or bot.get_price(symbol)
                if (crypto_balance * price) < min_cost:
                    continue
            
            # Récupérer données avec timeframe adaptatif
            from utils.timeframe_manager import TimeframeManager
            optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
            
            klines = klines_cache.get(symbol) or bot.get_klines(symbol, 20, optimal_timeframe)
            price = prices_cache.get(symbol) or bot.get_price(symbol)
            
            if not klines or len(klines) < 10:
                continue
            
            # Calculer métriques marché pour adaptation
            from utils.volatility_calculator import VolatilityCalculator
            volatility = VolatilityCalculator.calculate(klines, symbol)
            volatilities.append(volatility)
            
            # Volume ratio (actuel vs moyenne)
            if len(klines) >= 5:
                current_vol = klines[-1]['volume']
                avg_vol = sum(k['volume'] for k in klines[:-1]) / (len(klines) - 1)
                vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
                volume_ratios.append(vol_ratio)
            
            # Scoring avec volatilité réelle
            websocket_manager = getattr(bot, 'websocket', None)
            score = self.score_crypto(bot, symbol, stuck_positions, websocket_manager)
            if score > 0:
                breakdown = self.get_score_breakdown(bot, symbol, stuck_positions, websocket_manager=websocket_manager)
                if breakdown:  # Vérifier que breakdown n'est pas None
                    scores.append({
                        'symbol': symbol,
                        'score': score,
                        'volatility': breakdown['volatility'],
                        'volume': breakdown['volume'],
                        'min_cost': min_cost
                    })
        
        scores.sort(key=lambda x: x['score'], reverse=True)
        
        # Calculer conditions marché pour seuil adaptatif
        market_conditions = {
            'avg_volatility': sum(volatilities) / len(volatilities) if volatilities else 2.0,
            'avg_volume_ratio': sum(volume_ratios) / len(volume_ratios) if volume_ratios else 1.0
        }
        
        # Seuil minimum adaptatif PROFESSIONNEL
        dynamic_min_score = self._get_dynamic_min_score(
            available_count=len(scores),
            capital=usdt_available,
            market_conditions=market_conditions
        )
        
        tradeable = [c['symbol'] for c in scores[:self.max_tradeable] if c['score'] >= dynamic_min_score]
        
        if tradeable:
            top_display = []
            for c in scores[:self.max_tradeable]:
                if c['score'] >= dynamic_min_score:  # Utiliser seuil dynamique
                    vol_score = c.get('volatility', 0)  # Protection contre None
                    if vol_score >= 30:
                        vol_display = 4.0
                    elif vol_score >= 25:
                        vol_display = 3.0
                    elif vol_score >= 20:
                        vol_display = 2.0
                    else:
                        vol_display = 1.0
                    top_display.append(f"{c['symbol'].replace('/USDT', '')} {c['score']:.0f} (V{vol_display:.1f} L{c.get('volume', 0)} M{int(c['min_cost'])})")
            
            if top_display:  # Afficher seulement si cryptos tradables
                # Afficher les ajustements appliqués
                adjustments = []
                if usdt_available < 20:
                    adjustments.append("Capital-15")
                if market_conditions['avg_volatility'] < 1.5:
                    adjustments.append("Volatilité-10")
                if len(scores) < 2:
                    adjustments.append("Options-15")
                
                adj_text = f" ({', '.join(adjustments)})" if adjustments else ""
                print(f"🎯 TOP: {' | '.join(top_display)} → TRADING (Seuil adaptatif: {dynamic_min_score}{adj_text})")
            else:
                print(f"⚠️ Aucune crypto ≥{dynamic_min_score}/100 (Balance: {usdt_available:.2f} USDT)")
        else:
            if usdt_available > 0:
                print(f"⚠️ Aucune crypto ≥{dynamic_min_score}/100 (Balance: {usdt_available:.2f} USDT)")
        
        return tradeable
    
    def add_to_blacklist(self, symbol):
        """Ajoute une crypto à la blacklist temporaire"""
        self.blacklist[symbol] = time.time()
        print(f"🚫 {symbol} ajouté à la blacklist pour {self.blacklist_duration/3600:.1f}h")
    
    def get_score_breakdown(self, bot, symbol, stuck_positions, volatility=None, websocket_manager=None):
        """Détails du score pour debug - Version professionnelle"""
        from utils.timeframe_manager import TimeframeManager
        optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
        
        klines_short = bot.get_klines(symbol, 20, optimal_timeframe)
        klines_long = bot.get_klines(symbol, 96, '15m')  # 24h
        current_price = bot.get_price(symbol)
        
        if not klines_short or len(klines_short) < 10:
            return None
        
        # Volume professionnel si données 24h disponibles
        if klines_long and len(klines_long) >= 50:
            volume_score = self.calculate_volume_score(klines_long)
        else:
            volume_score = self.calculate_volume_score(klines_short)
        
        return {
            'volatility': self.calculate_volatility_score(klines_short, symbol, volatility, websocket_manager),
            'volume': volume_score,
            'momentum': self.calculate_momentum_score(klines_short),
            'spread': self.calculate_spread_score(symbol, current_price),
            'history': self.calculate_history_score(symbol, stuck_positions)
        }
    
    def _get_default_weights(self):
        """Pondération par défaut"""
        return {'volatility': 0.25, 'volume': 0.25, 'momentum': 0.25, 'spread': 0.15, 'history': 0.10}
    
    def _get_base_volatility_points(self, volatility):
        """Points de base selon volatilité"""
        if volatility >= 4.0:
            return 30
        elif volatility >= 3.0:
            return 25
        elif volatility >= 2.0:
            return 20
        elif volatility >= 1.5:
            return 10
        else:
            return 5
    
    def _get_crypto_multiplier(self, symbol):
        """Multiplicateur selon type de crypto"""
        if symbol in ['BTC/USDT', 'ETH/USDT']:
            return 1.2  # Boost 20% pour cryptos stables
        else:
            return 1.0
    
    def _get_dynamic_weights(self, symbol):
        """Pondération adaptative selon crypto"""
        if symbol in ['BTC/USDT', 'ETH/USDT']:
            # Cryptos stables = plus de poids sur volume/history
            return {'volatility': 0.20, 'volume': 0.30, 'momentum': 0.25, 'spread': 0.15, 'history': 0.10}
        else:
            # Altcoins = plus de poids sur volatilité/momentum
            return {'volatility': 0.35, 'volume': 0.20, 'momentum': 0.30, 'spread': 0.10, 'history': 0.05}
    
    def _get_dynamic_min_score(self, available_count, capital=None, market_conditions=None):
        """Seuil minimum adaptatif professionnel - VALEURS PAR DÉFAUT"""
        base_min = self.base_min_score
        
        # 1. Ajustement selon capital (micro-capital plus agressif)
        if capital and capital < 20:
            base_min -= 15  # Micro-capital: seuil plus bas
        elif capital and capital < 50:
            base_min -= 10  # Petit capital: légèrement plus agressif
        
        # 2. Ajustement selon conditions marché
        if market_conditions:
            # Marché calme = seuil plus bas
            if market_conditions.get('avg_volatility', 2.0) < 1.5:
                base_min -= 10
            
            # Volume faible = seuil plus bas
            if market_conditions.get('avg_volume_ratio', 1.0) < 0.7:
                base_min -= 5
        
        # 3. Ajustement selon nombre de cryptos disponibles
        if available_count < 2:
            base_min -= 15  # Très peu d'options = plus agressif
        elif available_count < 4:
            base_min -= 5   # Peu d'options = légèrement plus agressif
        elif available_count > 8:
            base_min += 10  # Beaucoup d'options = plus sélectif
        
        # 4. Ajustement temporel (weekend/nuit)
        from datetime import datetime
        now = datetime.now()
        if now.weekday() >= 5:  # Weekend
            base_min -= 5
        elif now.hour < 8 or now.hour > 22:  # Nuit
            base_min -= 3
        
        # Contraintes de sécurité
        return max(15, min(base_min, 80))  # Entre 15 et 80