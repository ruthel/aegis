class VolatilityCalculator:
    """Calculateur centralisé de volatilité avec WebSocket"""
    
    @classmethod
    def calculate(cls, klines, symbol='', websocket_manager=None):
        """
        Calcule la volatilité temps réel - Score 1-5 pour scalping
        
        Args:
            klines: Liste de klines avec 'close' prices (1m)
            symbol: Symbole pour WebSocket
            websocket_manager: Instance WebSocketManager pour données temps réel
        
        Returns:
            float: Score volatilité 1-5 (1=calme, 5=très volatil)
        """
        # Priorité aux données WebSocket si disponibles
        if websocket_manager and websocket_manager.is_connected():
            ws_klines = websocket_manager.get_klines(symbol, 60)
            if len(ws_klines) >= 10:
                klines = ws_klines
        
        try:
            if len(klines) < 10:
                return 2.0
            
            # Prendre les données récentes
            recent_klines = klines[-60:] if len(klines) >= 60 else klines[-20:]
            closes = [k['close'] for k in recent_klines if 'close' in k]
            
            if len(closes) < 10:
                return 2.0
            
            # Calcul ATR (Average True Range) temps réel
            true_ranges = []
            for i in range(1, len(recent_klines)):
                kline = recent_klines[i]
                high = kline.get('high', closes[i] if i < len(closes) else 0)
                low = kline.get('low', closes[i] if i < len(closes) else 0)
                prev_close = closes[i-1] if i-1 < len(closes) else 0
                
                # Éviter division par zéro ou valeurs invalides
                if high <= 0 or low <= 0 or prev_close <= 0 or high < low:
                    continue
                
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                if tr > 0:
                    true_ranges.append(tr)
            
            # Fallback: calculer volatilité simple sur les closes
            price_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] > 0]
            if not price_changes:
                return 2.0
            
            if not true_ranges or len(true_ranges) < 5:
                # Utiliser changements de prix simples
                avg_change = sum(price_changes) / len(price_changes)
                volatility_hourly = avg_change * 100
            else:
                # Utiliser ATR si disponible
                atr = sum(true_ranges) / len(true_ranges)
                current_price = closes[-1]
                
                if current_price <= 0:
                    avg_change = sum(price_changes) / len(price_changes)
                    volatility_hourly = avg_change * 100
                else:
                    volatility_hourly = (atr / current_price) * 100
            
            # Mapper vers score 1-5 pour scalping temps réel (ajusté marché crypto)
            # 0-0.15% horaire → 1/5 (très calme)
            # 0.15-0.30% horaire → 2/5 (calme)
            # 0.30-0.60% horaire → 3/5 (moyen)
            # 0.60-1.20% horaire → 4/5 (volatil)
            # 1.20%+ horaire → 5/5 (très volatil)
            if volatility_hourly < 0.15:
                volatility_score = 1.0
            elif volatility_hourly < 0.30:
                volatility_score = 2.0
            elif volatility_hourly < 0.60:
                volatility_score = 3.0
            elif volatility_hourly < 1.20:
                volatility_score = 4.0
            else:
                volatility_score = 5.0
            
            return volatility_score
            
        except Exception as e:
            return 2.0
    
    @classmethod
    def clear_cache(cls, symbol=None):
        """Méthode conservée pour compatibilité (ne fait rien)"""
        pass
    
    @classmethod
    def calculate_from_websocket(cls, websocket_manager, symbol):
        """Calcule volatilité directement depuis WebSocket"""
        if not websocket_manager or not websocket_manager.is_connected():
            return 2.0
        
        klines = websocket_manager.get_klines(symbol, 60)
        return cls.calculate(klines, symbol, websocket_manager)

