"""Prédicteur dynamique de récupération de volume"""
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class VolumePredictor:
    """Prédicteur intelligent de récupération de volume avec apprentissage"""
    
    def __init__(self):
        self.volume_cycles = {}  # Historique par crypto
        self.last_predictions = {}  # Cache prédictions
        
    def predict_volume_recovery(self, symbol: str, klines_1m: List, klines_15m: List, current_price: float) -> Optional[Dict]:
        """
        Prédit quand le volume va récupérer
        
        Args:
            symbol: Paire trading (ex: BTC/USDT)
            klines_1m: Données 1 minute (60 dernières)
            klines_15m: Données 15 minutes (100 dernières)
            current_price: Prix actuel
            
        Returns:
            Dict avec prédiction ou None si pas de baisse détectée
        """
        try:
            if len(klines_1m) < 20 or len(klines_15m) < 50:
                return None
            
            # 1. DÉTECTER BAISSE DE VOLUME ACTUELLE
            volume_decline = self._detect_volume_decline(klines_1m)
            if not volume_decline:
                return None
            
            # 2. ANALYSER PATTERNS HISTORIQUES
            self._update_historical_patterns(symbol, klines_15m)
            
            # 3. CALCULER PRÉDICTION DYNAMIQUE
            prediction = self._calculate_recovery_prediction(
                symbol, volume_decline, klines_1m, klines_15m, current_price
            )
            
            if prediction:
                # Cache pour éviter spam
                self.last_predictions[symbol] = {
                    'prediction': prediction,
                    'timestamp': time.time()
                }
            
            return prediction
            
        except Exception:
            return None
    
    def _detect_volume_decline(self, klines_1m: List) -> Optional[Dict]:
        """Détecte si le volume est en baisse significative"""
        if len(klines_1m) < 10:
            return None
        
        volumes = [k['volume'] for k in klines_1m[-20:]]
        
        # Volume moyen des 10 dernières vs 10 précédentes
        recent_avg = sum(volumes[-10:]) / 10
        previous_avg = sum(volumes[-20:-10]) / 10
        
        decline_pct = ((recent_avg - previous_avg) / previous_avg) * 100
        
        # Baisse significative > 20%
        if decline_pct < -20:
            # Trouver début de la baisse
            decline_start = None
            for i in range(len(volumes) - 5, 0, -1):
                if volumes[i] > recent_avg * 1.3:
                    decline_start = len(volumes) - i
                    break
            
            return {
                'decline_pct': decline_pct,
                'decline_duration_min': decline_start or 10,
                'current_volume': volumes[-1],
                'avg_volume': previous_avg
            }
        
        return None
    
    def _update_historical_patterns(self, symbol: str, klines_15m: List):
        """Met à jour les patterns historiques de volume"""
        if symbol not in self.volume_cycles:
            self.volume_cycles[symbol] = []
        
        # Analyser cycles sur 15m (plus stable)
        volumes_15m = [k['volume'] for k in klines_15m[-80:]]
        
        # Détecter cycles complets (baisse + récupération)
        cycles = self._find_volume_cycles(volumes_15m)
        
        # Garder seulement les 20 derniers cycles
        self.volume_cycles[symbol].extend(cycles)
        self.volume_cycles[symbol] = self.volume_cycles[symbol][-20:]
    
    def _find_volume_cycles(self, volumes: List) -> List[Dict]:
        """Trouve les cycles complets de volume dans l'historique"""
        cycles = []
        
        for i in range(10, len(volumes) - 10):
            # Chercher début de baisse
            if volumes[i] > volumes[i+1] * 1.2:
                # Chercher fin de baisse + récupération
                for j in range(i+2, min(i+20, len(volumes))):
                    if volumes[j] > volumes[i] * 0.8:  # Récupération
                        cycle_duration = (j - i) * 15  # Minutes
                        decline_strength = (volumes[i] - min(volumes[i:j])) / volumes[i]
                        
                        cycles.append({
                            'duration_min': cycle_duration,
                            'decline_strength': decline_strength,
                            'recovery_ratio': volumes[j] / volumes[i]
                        })
                        break
        
        return cycles
    
    def _calculate_recovery_prediction(self, symbol: str, volume_decline: Dict, 
                                     klines_1m: List, klines_15m: List, current_price: float) -> Dict:
        """Calcule la prédiction de récupération"""
        
        # 1. BASE HISTORIQUE
        cycles = self.volume_cycles.get(symbol, [])
        if cycles:
            avg_duration = sum(c['duration_min'] for c in cycles) / len(cycles)
            avg_recovery = sum(c['recovery_ratio'] for c in cycles) / len(cycles)
        else:
            avg_duration = 45  # Défaut 45min
            avg_recovery = 1.2
        
        # 2. FACTEURS DYNAMIQUES
        
        # Prix momentum (divergence prix/volume)
        prices_1m = [k['close'] for k in klines_1m[-10:]]
        price_momentum = (prices_1m[-1] - prices_1m[0]) / prices_1m[0] * 100
        
        # Session de marché
        hour = datetime.now().hour
        if 14 <= hour <= 21:  # Session US
            session_factor = 0.8  # Plus rapide
        elif 8 <= hour <= 16:   # Session EU
            session_factor = 1.0  # Normal
        else:  # Session ASIA
            session_factor = 1.3  # Plus lent
        
        # Volatilité actuelle
        price_changes = [abs(prices_1m[i] - prices_1m[i-1]) / prices_1m[i-1] 
                        for i in range(1, len(prices_1m))]
        volatility = sum(price_changes) / len(price_changes) * 100
        
        volatility_factor = 0.7 if volatility > 2 else 1.2 if volatility < 0.5 else 1.0
        
        # Divergence prix/volume (plus forte = récupération plus rapide)
        if price_momentum > 1 and volume_decline['decline_pct'] < -30:
            divergence_factor = 0.6  # Divergence forte = récupération rapide
        elif price_momentum > 0:
            divergence_factor = 0.8
        else:
            divergence_factor = 1.2
        
        # 3. CALCUL FINAL
        base_remaining = max(5, avg_duration - volume_decline['decline_duration_min'])
        
        predicted_time = base_remaining * session_factor * volatility_factor * divergence_factor
        predicted_time = max(2, min(predicted_time, 120))  # 2min à 2h
        
        # 4. CONFIANCE
        confidence = 60
        if len(cycles) > 5:
            confidence += 15  # Plus d'historique
        if abs(price_momentum) > 1:
            confidence += 10  # Divergence claire
        if volume_decline['decline_pct'] < -40:
            confidence += 10  # Baisse très marquée
        
        confidence = min(confidence, 90)
        
        # 5. FORMATAGE
        recovery_time = datetime.now() + timedelta(minutes=predicted_time)
        
        if predicted_time < 5:
            time_str = f"{int(predicted_time)}min"
        elif predicted_time < 15:
            margin = max(1, int(predicted_time * 0.3))
            time_str = f"{int(predicted_time-margin)}-{int(predicted_time+margin)}min"
        elif predicted_time < 60:
            margin = max(2, int(predicted_time * 0.4))
            time_str = f"{int(predicted_time-margin)}-{int(predicted_time+margin)}min"
        else:
            hours = predicted_time / 60
            time_str = f"{hours:.1f}h"
        
        return {
            'status': 'VOLUME_DECLINING',
            'decline_duration_min': volume_decline['decline_duration_min'],
            'decline_pct': volume_decline['decline_pct'],
            'predicted_recovery_min': predicted_time,
            'recovery_time_str': time_str,
            'recovery_timestamp': recovery_time,
            'confidence': confidence,
            'price_momentum': price_momentum,
            'divergence_detected': price_momentum > 0.5 and volume_decline['decline_pct'] < -25,
            'historical_cycles': len(cycles),
            'session_factor': session_factor,
            'volatility_factor': volatility_factor
        }
    
    def should_notify(self, symbol: str, prediction: Dict) -> bool:
        """Détermine si une notification doit être envoyée (anti-spam)"""
        if symbol not in self.last_predictions:
            return True
        
        last = self.last_predictions[symbol]
        
        # Pas de notification si < 30min depuis la dernière
        if time.time() - last['timestamp'] < 1800:
            return False
        
        # Notification si changement significatif de prédiction
        time_diff = abs(prediction['predicted_recovery_min'] - 
                       last['prediction']['predicted_recovery_min'])
        
        return time_diff > 10  # Changement > 10min