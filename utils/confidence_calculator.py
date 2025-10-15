class ConfidenceCalculator:
    """Calculateur centralisé des seuils de confiance adaptatifs"""
    
    @staticmethod
    def get_min_confidence(volatility):
        """
        Calcule le seuil de confiance minimum selon la volatilité
        
        Args:
            volatility: Score volatilité 1-5
        
        Returns:
            int: Seuil de confiance minimum (%)
        """
        if volatility >= 4.0:
            return 35
        elif volatility >= 3.0:
            return 40
        elif volatility >= 2.0:
            return 42
        elif volatility >= 1.0:
            return 50
        else:
            return 55
