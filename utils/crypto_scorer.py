import time
from datetime import datetime
import os
from utils.volatility_calculator import VolatilityCalculator
from utils.market_calculator import MarketCalculator

class CryptoScorer:
    def __init__(self, min_score=40, max_tradeable=2):
        self.base_min_score = min_score
        self.max_tradeable = max_tradeable
        self.blacklist = {}
        self.blacklist_duration = 3600
        self.optimizer = None  # Sera défini par le bot
        self.score_history = {}  # Learning system
        self.performance_weights = self._get_default_weights()
        
    def calculate_volatility_score(self, klines, symbol='', volatility=None, websocket_manager=None):
        """Score basé sur volatilité 1-5 (0-30 points) - ADAPTATIF"""
        if len(klines) < 10:
            return 0
        
        # Calculer volatilité réelle si non fournie
        if volatility is None:
            volatility = VolatilityCalculator.calculate(klines, symbol, websocket_manager)
        
        # Points adaptatifs selon crypto
        base_points = self._get_base_volatility_points(volatility)
        crypto_multiplier = self._get_crypto_multiplier(symbol)
        
        return int(base_points * crypto_multiplier)
    
    def calculate_volume_score(self, klines):
        """Score basé sur volume/liquidité (0-25 points)"""
        return MarketCalculator.calculate_volume_score(klines)
    
    def calculate_momentum_score(self, klines):
        """Score basé sur momentum/tendance (0-25 points)"""
        return MarketCalculator.calculate_momentum_score(klines)
    
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
        """Calcule le score total d'une crypto (0-100)"""
        try:
            # Timeframe adaptatif au lieu de statique
            from utils.timeframe_manager import TimeframeManager
            optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
            
            klines = bot.get_klines(symbol, 20, optimal_timeframe)
            current_price = bot.get_price(symbol)
            
            if not klines or len(klines) < 10:
                return 0
            
            # Scoring avec pondération adaptative
            websocket_manager = getattr(bot, 'websocket', None)
            
            volatility_score = self.calculate_volatility_score(klines, symbol, volatility, websocket_manager)
            volume_score = self.calculate_volume_score(klines)
            momentum_score = self.calculate_momentum_score(klines)
            spread_score = self.calculate_spread_score(symbol, current_price)
            history_score = self.calculate_history_score(symbol, stuck_positions)
            
            # Pondération dynamique selon stratégie et marché
            weights = self._get_dynamic_weights(symbol)
            
            total_score = (
                volatility_score * weights['volatility'] +
                volume_score * weights['volume'] +
                momentum_score * weights['momentum'] +
                spread_score * weights['spread'] +
                history_score * weights['history']
            )
            
            return total_score
            
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
        """Détails du score pour debug"""
        # Timeframe adaptatif au lieu de statique
        from utils.timeframe_manager import TimeframeManager
        optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
        
        klines = bot.get_klines(symbol, 20, optimal_timeframe)
        current_price = bot.get_price(symbol)
        
        if not klines or len(klines) < 10:
            return None
        
        return {
            'volatility': self.calculate_volatility_score(klines, symbol, volatility, websocket_manager),
            'volume': self.calculate_volume_score(klines),
            'momentum': self.calculate_momentum_score(klines),
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
