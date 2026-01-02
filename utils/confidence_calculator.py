class ConfidenceCalculator:
    """Calculateur centralisé des seuils de confiance adaptatifs"""
    
    @staticmethod
    def get_min_confidence(volatility):
        """
        Calcule le seuil de confiance minimum selon la volatilité - AJUSTÉ 15m
        
        Args:
            volatility: Score volatilité 1-5
        
        Returns:
            int: Seuil de confiance minimum (%)
        """
        # Seuils réduits car 15m = signaux plus fiables
        if volatility >= 3.0:  # Était 4.0
            return 30  # Réduit: 35 → 30
        elif volatility >= 2.0:  # Était 3.0
            return 35  # Réduit: 40 → 35
        elif volatility >= 1.5:  # Était 2.0
            return 38  # Réduit: 42 → 38
        elif volatility >= 1.0:
            return 45  # Réduit: 50 → 45
        else:
            return 50  # Réduit: 55 → 50
