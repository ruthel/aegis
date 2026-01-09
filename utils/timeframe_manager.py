"""
Gestionnaire Centralisé de Timeframes Adaptatifs
Remplace tous les timeframes statiques par des timeframes intelligents
"""

class TimeframeManager:
    """Gestionnaire centralisé pour tous les timeframes du système"""
    
    @staticmethod
    def get_main_timeframe(symbol, strategy_type='intelligent', bot=None):
        """Timeframe principal adaptatif pour le trading"""
        volatility = TimeframeManager._get_volatility(symbol, bot)
        
        if strategy_type == 'scalping':
            if volatility >= 4.0:
                return '1m'    # Très volatil = ultra réactif
            elif volatility >= 3.0:
                return '5m'    # Volatil = réactif
            else:
                return '15m'   # Normal = standard
        
        elif strategy_type == 'swing':
            if volatility >= 3.0:
                return '15m'   # Volatil = moyen terme
            else:
                return '1h'    # Calme = long terme
        
        else:  # intelligent/adaptive (défaut)
            if volatility >= 4.0:
                return '5m'    # Très volatil
            elif volatility >= 2.5:
                return '15m'   # Moyen (actuel)
            else:
                return '1h'    # Calme
    
    @staticmethod
    def get_analysis_timeframe(symbol, analysis_type, bot=None):
        """Timeframe pour analyses spécifiques"""
        volatility = TimeframeManager._get_volatility(symbol, bot)
        
        if analysis_type == 'ema_analysis':
            if volatility >= 4.0:
                return '5m'    # Très volatil = plus réactif
            elif volatility >= 2.0:
                return '15m'   # Moyen
            else:
                return '1h'    # Calme = tendance stable
        
        elif analysis_type == 'volume_analysis':
            if volatility >= 3.0:
                return '15m'   # Volatil = volume change vite
            else:
                return '1h'    # Stable = volume stable
        
        elif analysis_type == 'momentum_analysis':
            if volatility >= 3.5:
                return '5m'    # Très volatil = momentum rapide
            elif volatility >= 2.0:
                return '15m'   # Moyen
            else:
                return '1h'    # Calme
        
    @staticmethod
    def get_volatility_thresholds(symbol):
        """Seuils de volatilité adaptatifs selon crypto"""
        # Seuils différents selon type de crypto
        if symbol in ['BTC/USDT', 'ETH/USDT']:
            # Cryptos stables = seuils plus bas
            return {'low': 0.10, 'medium': 0.25, 'high': 0.50, 'extreme': 1.00}
        elif 'USDT' in symbol:
            # Altcoins = seuils standards
            return {'low': 0.15, 'medium': 0.30, 'high': 0.60, 'extreme': 1.20}
        else:
            # Autres paires = seuils élevés
            return {'low': 0.20, 'medium': 0.40, 'high': 0.80, 'extreme': 1.50}
    
    @staticmethod
    def get_ema_periods(symbol, timeframe, bot=None):
        """Périodes EMA adaptatives selon timeframe et volatilité"""
        volatility = TimeframeManager._get_volatility(symbol, bot)
        
        if timeframe in ['1m', '5m']:
            if volatility >= 4.0:
                return {'short': 5, 'medium': 15, 'long': 50}  # Plus réactif
            else:
                return {'short': 7, 'medium': 21, 'long': 99}  # Standard
        
        elif timeframe == '15m':
            if volatility >= 3.0:
                return {'short': 3, 'medium': 12, 'long': 45}  # Réactif
            else:
                return {'short': 7, 'medium': 25, 'long': 99}  # Standard
        
        elif timeframe in ['1h', '4h']:
            return {'short': 7, 'medium': 25, 'long': 99}  # Standard long terme
        
        else:
            return {'short': 7, 'medium': 25, 'long': 99}  # Défaut
    
    @staticmethod
    def _get_volatility(symbol, bot=None):
        """Récupère volatilité du symbole"""
        try:
            if bot:
                klines = bot.get_klines(symbol, 20, '15m')
                if len(klines) >= 10:
                    from utils.volatility_calculator import VolatilityCalculator
                    return VolatilityCalculator.calculate(klines, symbol)
            return 2.5  # Volatilité moyenne par défaut
        except:
            return 2.5
    
    @staticmethod
    def get_confidence_threshold(symbol, volatility=None, bot=None, balance=None):
        """Seuil de confiance adaptatif - LOGIQUE PROFESSIONNELLE"""
        if volatility is None:
            volatility = TimeframeManager._get_volatility(symbol, bot)
        
        # STRATÉGIE PROFESSIONNELLE selon taille de compte
        if balance and balance < 50:  # Petit compte
            # Objectif: Croissance rapide (comme les pros débutants)
            base_threshold = 20  # Agressif
            if volatility >= 3.0:
                return max(15, base_threshold - 5)  # Très agressif si volatil
            return base_threshold
            
        elif balance and balance < 200:  # Compte moyen
            # Objectif: Équilibre croissance/préservation
            base_threshold = 30
            if volatility >= 4.0:
                return base_threshold - 5
            elif volatility <= 1.5:
                return base_threshold + 5
            return base_threshold
            
        else:  # Gros compte (> 200 ou non spécifié)
            # Objectif: Préservation capital (comme fonds institutionnels)
            base_threshold = 45  # Conservateur
            if volatility >= 4.0:
                return base_threshold - 10  # Même conservateur, on profite volatilité
            elif volatility <= 1.5:
                return min(60, base_threshold + 10)  # Très sélectif si calme
            return base_threshold