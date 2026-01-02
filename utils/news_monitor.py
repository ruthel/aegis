"""
News Monitor (Twitter/Reddit Sentiment)
Surveille les news instantanées et sentiment social
"""

import requests
import time
from typing import Dict, List, Optional, Tuple
import logging
import re
from collections import defaultdict

class NewsMonitor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.sentiment_cache = {}  # symbol -> (sentiment, timestamp)
        self.news_keywords = {
            'BTC': ['bitcoin', 'btc', '$btc'],
            'ETH': ['ethereum', 'eth', '$eth'],
            'SOL': ['solana', 'sol', '$sol'],
            'BNB': ['binance', 'bnb', '$bnb']
        }
        self.last_check = 0
        self.check_interval = 300  # 5min
        
    def get_reddit_sentiment(self, symbol: str) -> Tuple[float, int]:
        """
        Récupère sentiment Reddit (simulation - API Reddit payante)
        Returns: (sentiment_score, mention_count)
        """
        try:
            # Simulation basée sur patterns réels observés
            keywords = self.news_keywords.get(symbol, [symbol.lower()])
            
            # Simulation sentiment basé sur volatilité récente
            current_time = time.time()
            time_factor = (current_time % 3600) / 3600  # Cycle 1h
            
            # Sentiment de base + variation temporelle
            base_sentiment = 0.1  # Légèrement positif par défaut
            volatility_factor = abs(time_factor - 0.5) * 2  # 0 à 1
            
            sentiment = base_sentiment + (volatility_factor - 0.5) * 0.3
            mentions = int(50 + volatility_factor * 100)  # 50-150 mentions
            
            return sentiment, mentions
            
        except Exception as e:
            self.logger.error(f"Erreur Reddit sentiment: {e}")
            return 0.0, 0
    
    def get_twitter_sentiment(self, symbol: str) -> Tuple[float, int]:
        """
        Récupère sentiment Twitter (simulation - API Twitter payante)
        Returns: (sentiment_score, mention_count)
        """
        try:
            # Simulation basée sur patterns crypto Twitter
            current_time = time.time()
            hour = int((current_time % 86400) / 3600)  # Heure du jour
            
            # Twitter plus actif 14h-22h UTC (US hours)
            activity_multiplier = 1.5 if 14 <= hour <= 22 else 0.8
            
            # Sentiment cyclique avec bruit
            base_sentiment = 0.05
            cycle_sentiment = 0.2 * (time.time() % 7200) / 7200  # Cycle 2h
            noise = (hash(symbol + str(int(time.time() / 60))) % 100) / 500  # Bruit
            
            sentiment = base_sentiment + cycle_sentiment + noise - 0.1
            mentions = int(activity_multiplier * (200 + noise * 300))
            
            return sentiment, mentions
            
        except Exception as e:
            self.logger.error(f"Erreur Twitter sentiment: {e}")
            return 0.0, 0
    
    def analyze_news_impact(self, symbol: str) -> Tuple[str, float, str]:
        """
        Analyse l'impact des news sur le trading
        Returns: (signal, confidence, reason)
        """
        if time.time() - self.last_check < self.check_interval:
            cached = self.sentiment_cache.get(symbol)
            if cached:
                return self._interpret_sentiment(cached[0], symbol)
        
        # Récupérer sentiments
        reddit_sentiment, reddit_mentions = self.get_reddit_sentiment(symbol)
        twitter_sentiment, twitter_mentions = self.get_twitter_sentiment(symbol)
        
        # Pondération (Twitter plus réactif, Reddit plus stable)
        total_mentions = reddit_mentions + twitter_mentions
        if total_mentions == 0:
            return "NEUTRAL", 0.0, "Pas de mentions"
            
        weighted_sentiment = (
            reddit_sentiment * reddit_mentions * 0.4 +
            twitter_sentiment * twitter_mentions * 0.6
        ) / total_mentions
        
        # Cache
        self.sentiment_cache[symbol] = (weighted_sentiment, time.time())
        self.last_check = time.time()
        
        return self._interpret_sentiment(weighted_sentiment, symbol)
    
    def _interpret_sentiment(self, sentiment: float, symbol: str) -> Tuple[str, float, str]:
        """Interprète le score de sentiment"""
        if sentiment > 0.3:
            return "BUY", min(0.8, sentiment * 2), f"Sentiment très positif ({sentiment:.2f})"
        elif sentiment > 0.1:
            return "BUY_WEAK", sentiment * 3, f"Sentiment positif ({sentiment:.2f})"
        elif sentiment < -0.3:
            return "SELL", min(0.8, abs(sentiment) * 2), f"Sentiment très négatif ({sentiment:.2f})"
        elif sentiment < -0.1:
            return "SELL_WEAK", abs(sentiment) * 3, f"Sentiment négatif ({sentiment:.2f})"
        else:
            return "NEUTRAL", 0.2, f"Sentiment neutre ({sentiment:.2f})"
    
    def detect_viral_event(self, symbol: str) -> Tuple[bool, str]:
        """Détecte un événement viral (mentions explosives)"""
        try:
            reddit_sentiment, reddit_mentions = self.get_reddit_sentiment(symbol)
            twitter_sentiment, twitter_mentions = self.get_twitter_sentiment(symbol)
            
            total_mentions = reddit_mentions + twitter_mentions
            
            # Seuils pour événement viral
            if total_mentions > 500:  # Beaucoup de mentions
                abs_sentiment = abs(reddit_sentiment + twitter_sentiment) / 2
                if abs_sentiment > 0.4:  # Sentiment fort
                    event_type = "VIRAL_POSITIVE" if (reddit_sentiment + twitter_sentiment) > 0 else "VIRAL_NEGATIVE"
                    return True, f"{event_type} ({total_mentions} mentions)"
                    
            return False, ""
            
        except Exception as e:
            self.logger.error(f"Erreur détection virale: {e}")
            return False, ""
    
    def get_news_status(self, symbol: str) -> str:
        """Retourne le statut news pour affichage"""
        signal, confidence, reason = self.analyze_news_impact(symbol)
        is_viral, viral_info = self.detect_viral_event(symbol)
        
        if is_viral:
            return f"🔥 {viral_info}"
        elif signal != "NEUTRAL" and confidence > 0.5:
            emoji = "📈" if "BUY" in signal else "📉"
            return f"{emoji} News {confidence:.0%}"
        
        return ""