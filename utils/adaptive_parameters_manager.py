"""
Gestionnaire de Paramètres Adaptatifs - Niveau Professionnel
Ajuste automatiquement tous les paramètres selon les caractéristiques de chaque crypto
"""

import time
from datetime import datetime

class AdaptiveParametersManager:
    """Gestionnaire professionnel de paramètres adaptatifs par crypto"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Profils par crypto (basés sur analyse historique)
        self.crypto_profiles = {
            'BTC/USDT': {
                'base_volatility': 2.0,
                'price_sensitivity': 0.0008,  # 0.08%
                'volume_thresholds': {'high': 1.5, 'low': 0.8},
                'active_sessions': list(range(24)),  # 24/7
                'base_timeframes': {'scalping': '5m', 'trend': '1h', 'pattern': '15m'},
                'cumulative_sensitivity': 0.12
            },
            'ETH/USDT': {
                'base_volatility': 2.5,
                'price_sensitivity': 0.0006,  # 0.06%
                'volume_thresholds': {'high': 2.0, 'low': 0.6},
                'active_sessions': [2,3,4,5,6,7,8, 14,15,16,17,18,19,20,21,22],  # ASIA + US
                'base_timeframes': {'scalping': '5m', 'trend': '15m', 'pattern': '15m'},
                'cumulative_sensitivity': 0.15
            },
            'SOL/USDT': {
                'base_volatility': 3.5,
                'price_sensitivity': 0.0015,  # 0.15%
                'volume_thresholds': {'high': 2.5, 'low': 0.4},
                'active_sessions': list(range(14, 23)),  # US principalement
                'base_timeframes': {'scalping': '1m', 'trend': '5m', 'pattern': '5m'},
                'cumulative_sensitivity': 0.20
            },
            'BNB/USDT': {
                'base_volatility': 2.8,
                'price_sensitivity': 0.0010,  # 0.10%
                'volume_thresholds': {'high': 2.2, 'low': 0.5},
                'active_sessions': [8,9,10,11,12,13,14,15,16,17,18,19,20,21,22],  # EU + US
                'base_timeframes': {'scalping': '5m', 'trend': '15m', 'pattern': '10m'},
                'cumulative_sensitivity': 0.18
            }
        }
    
    def get_active_sessions(self, symbol):
        """Sessions actives adaptées par crypto"""
        hour = datetime.now().hour
        profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
        return hour in profile['active_sessions']
    
    def get_volume_thresholds(self, symbol):
        """Seuils de volume adaptés par crypto"""
        profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
        return profile['volume_thresholds']
    
    def get_price_change_threshold(self, symbol):
        """Seuil de détection prix adapté par crypto et volatilité"""
        try:
            profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
            current_volatility = self.bot.get_pair_volatility(symbol)
            base_threshold = profile['price_sensitivity']
            
            # Ajuster selon volatilité actuelle vs normale
            volatility_ratio = current_volatility / profile['base_volatility']
            return base_threshold * volatility_ratio
        except:
            return 0.0005  # Fallback
    
    def get_optimal_timeframe(self, symbol, analysis_type='trend'):
        """Timeframe optimal selon crypto et type d'analyse"""
        try:
            profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
            current_volatility = self.bot.get_pair_volatility(symbol)
            
            base_timeframe = profile['base_timeframes'].get(analysis_type, '15m')
            
            # Ajuster selon volatilité actuelle
            if current_volatility > profile['base_volatility'] * 1.5:
                # Plus volatil = timeframe plus court
                timeframe_map = {
                    '1h': '15m', '15m': '5m', '5m': '1m', '1m': '1m'
                }
                return timeframe_map.get(base_timeframe, base_timeframe)
            elif current_volatility < profile['base_volatility'] * 0.7:
                # Moins volatil = timeframe plus long
                timeframe_map = {
                    '1m': '5m', '5m': '15m', '15m': '1h', '1h': '4h'
                }
                return timeframe_map.get(base_timeframe, base_timeframe)
            
            return base_timeframe
        except:
            return '15m'  # Fallback
    
    def get_min_analysis_interval(self, symbol):
        """Délai minimum entre analyses adapté par crypto"""
        try:
            profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
            current_volatility = self.bot.get_pair_volatility(symbol)
            
            # Base selon profil crypto
            base_intervals = {
                'BTC/USDT': 0.1,   # 100ms
                'ETH/USDT': 0.08,  # 80ms
                'SOL/USDT': 0.05,  # 50ms
                'BNB/USDT': 0.07   # 70ms
            }
            
            base_interval = base_intervals.get(symbol, 0.08)
            
            # Ajuster selon volatilité actuelle
            volatility_factor = max(0.5, min(2.0, current_volatility / profile['base_volatility']))
            return base_interval / volatility_factor
        except:
            return 0.1  # Fallback 100ms
    
    def get_cumulative_thresholds(self, symbol):
        """Seuils tendance cumulative adaptés par crypto"""
        try:
            profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
            current_volatility = self.bot.get_pair_volatility(symbol)
            
            # Nombre de confirmations selon volatilité
            base_count = 4
            if current_volatility > profile['base_volatility'] * 1.5:
                min_count = 3  # Plus volatil = moins de confirmations
            elif current_volatility < profile['base_volatility'] * 0.7:
                min_count = 5  # Moins volatil = plus de confirmations
            else:
                min_count = base_count
            
            # Seuil de changement selon profil et volatilité
            min_change = profile['cumulative_sensitivity'] * (current_volatility / profile['base_volatility'])
            
            return {
                'min_count': min_count,
                'min_change': min_change
            }
        except:
            return {'min_count': 4, 'min_change': 0.3}  # Fallback
    
    def get_pattern_confidence_threshold(self, symbol, pattern_type):
        """Seuil de confiance pattern adapté par crypto et type"""
        try:
            profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
            current_volatility = self.bot.get_pair_volatility(symbol)
            
            # Seuils de base par type de pattern
            base_thresholds = {
                'bullish': 75,
                'bearish': 70,
                'reversal': 80,
                'continuation': 65
            }
            
            base_threshold = base_thresholds.get(pattern_type, 75)
            
            # Ajuster selon volatilité (plus volatil = seuil plus élevé)
            volatility_adjustment = (current_volatility / profile['base_volatility'] - 1) * 10
            return max(60, min(90, base_threshold + volatility_adjustment))
        except:
            return 75  # Fallback
    
    def get_adaptive_multipliers(self, symbol):
        """Multiplicateurs adaptatifs pour intervalles"""
        try:
            profile = self.crypto_profiles.get(symbol, self.crypto_profiles['ETH/USDT'])
            current_volatility = self.bot.get_pair_volatility(symbol)
            
            # Multiplicateurs de base
            base_multipliers = {
                'position_open': 0.7,
                'session_closed': 2.0,
                'high_volume': 0.7,
                'low_volume': 1.5
            }
            
            # Ajuster selon volatilité
            volatility_factor = current_volatility / profile['base_volatility']
            
            return {
                'position_open': base_multipliers['position_open'] * (0.8 + 0.4 * volatility_factor),
                'session_closed': base_multipliers['session_closed'] * (1.2 - 0.4 * volatility_factor),
                'high_volume': base_multipliers['high_volume'] * (0.9 + 0.2 * volatility_factor),
                'low_volume': base_multipliers['low_volume'] * (1.1 - 0.2 * volatility_factor)
            }
        except:
            return {
                'position_open': 0.7,
                'session_closed': 2.0,
                'high_volume': 0.7,
                'low_volume': 1.5
            }