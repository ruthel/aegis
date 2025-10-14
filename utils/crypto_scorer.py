import time
from datetime import datetime

class CryptoScorer:
    def __init__(self, min_score=50, max_tradeable=2):
        self.min_score = min_score
        self.max_tradeable = max_tradeable
        self.blacklist = {}
        self.blacklist_duration = 3600  # 1 heure
        
    def calculate_volatility_score(self, klines):
        """Score basé sur volatilité (0-30 points)"""
        if len(klines) < 10:
            return 0
        
        prices = [k['close'] for k in klines[-20:]]
        volatility = (max(prices) - min(prices)) / min(prices) * 100
        
        if volatility >= 3:
            return 30
        elif volatility >= 2:
            return 25
        elif volatility >= 1:
            return 20
        elif volatility >= 0.5:
            return 15
        elif volatility >= 0.3:
            return 10
        else:
            return 5
    
    def calculate_volume_score(self, klines):
        """Score basé sur volume/liquidité (0-25 points)"""
        if len(klines) < 5:
            return 0
        
        avg_volume = sum(k['volume'] for k in klines[-5:]) / 5
        
        if avg_volume >= 5000000:
            return 25
        elif avg_volume >= 1000000:
            return 20
        elif avg_volume >= 500000:
            return 15
        elif avg_volume >= 100000:
            return 10
        else:
            return 5
    
    def calculate_momentum_score(self, klines):
        """Score basé sur momentum/tendance (0-25 points)"""
        if len(klines) < 10:
            return 0
        
        prices = [k['close'] for k in klines[-10:]]
        momentum = (prices[-1] - prices[0]) / prices[0] * 100
        
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
    
    def score_crypto(self, bot, symbol, stuck_positions):
        """Calcule le score total d'une crypto (0-100)"""
        try:
            klines = bot.get_klines(symbol, 20)
            current_price = bot.get_price(symbol)
            
            if not klines or len(klines) < 10:
                return 0
            
            volatility_score = self.calculate_volatility_score(klines)
            volume_score = self.calculate_volume_score(klines)
            momentum_score = self.calculate_momentum_score(klines)
            spread_score = self.calculate_spread_score(symbol, current_price)
            history_score = self.calculate_history_score(symbol, stuck_positions)
            
            total_score = (
                volatility_score +
                volume_score +
                momentum_score +
                spread_score +
                history_score
            )
            
            return total_score
            
        except Exception as e:
            print(f"❌ Erreur scoring {symbol}: {e}")
            return 0
    
    def rank_cryptos(self, bot, trading_pairs, stuck_positions):
        """Classe toutes les cryptos et retourne les meilleures"""
        scores = []
        
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            score = self.score_crypto(bot, symbol, stuck_positions)
            breakdown = self.get_score_breakdown(bot, symbol, stuck_positions)
            
            if score > 0:
                scores.append({
                    'symbol': symbol,
                    'score': score,
                    'breakdown': breakdown
                })
        
        scores.sort(key=lambda x: x['score'], reverse=True)
        
        # Format compact: afficher uniquement le TOP 2
        tradeable = [
            c['symbol'] for c in scores[:self.max_tradeable]
            if c['score'] >= self.min_score
        ]
        
        if tradeable:
            top_display = []
            for c in scores[:self.max_tradeable]:
                if c['score'] >= self.min_score:
                    b = c['breakdown']
                    crypto_name = c['symbol'].replace('/USDT', '')
                    top_display.append(f"{crypto_name} {c['score']} (V{b['volatility']} L{b['volume']} M{b['momentum']})")
            print(f"🎯 TOP: {' | '.join(top_display)} → TRADING")
        else:
            print(f"⚠️ Aucune crypto ≥{self.min_score}/100")
        
        return tradeable
    
    def add_to_blacklist(self, symbol):
        """Ajoute une crypto à la blacklist temporaire"""
        self.blacklist[symbol] = time.time()
        print(f"🚫 {symbol} ajouté à la blacklist pour {self.blacklist_duration/3600:.1f}h")
    
    def get_score_breakdown(self, bot, symbol, stuck_positions):
        """Détails du score pour debug"""
        klines = bot.get_klines(symbol, 20)
        current_price = bot.get_price(symbol)
        
        if not klines or len(klines) < 10:
            return None
        
        return {
            'volatility': self.calculate_volatility_score(klines),
            'volume': self.calculate_volume_score(klines),
            'momentum': self.calculate_momentum_score(klines),
            'spread': self.calculate_spread_score(symbol, current_price),
            'history': self.calculate_history_score(symbol, stuck_positions)
        }
