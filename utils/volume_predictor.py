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
        Prédit récupération volume - Version professionnelle avec 7 jours de données
        
        Args:
            symbol: Paire trading (ex: BTC/USDT)
            klines_1m: Données 1 minute (60+ dernières)
            klines_15m: Données 15 minutes (672+ pour 7 jours)
            current_price: Prix actuel
            
        Returns:
            Dict avec prédiction ou None si pas de baisse détectée
        """
        try:
            # Standards professionnels : 7 jours de données minimum
            if len(klines_1m) < 60 or len(klines_15m) < 672:
                # Fallback si pas assez de données 7j
                if len(klines_1m) < 30 or len(klines_15m) < 96:
                    return None
                # Mode dégradé avec données disponibles
                return self._predict_with_limited_data(symbol, klines_1m, klines_15m, current_price)
            
            # 1. DÉTECTER BAISSE AVEC MOYENNES MOBILES 7J
            volume_decline = self._detect_volume_decline_7d(klines_1m, klines_15m)
            if not volume_decline:
                return None
            
            # 2. ANALYSER PATTERNS SUR 7 JOURS (cycles complets)
            self._update_historical_patterns_7d(symbol, klines_15m)
            
            # 3. PRÉDICTION AVEC FACTEURS PROFESSIONNELS 7J
            prediction = self._calculate_recovery_prediction_7d(
                symbol, volume_decline, klines_1m, klines_15m, current_price
            )
            
            if prediction:
                self.last_predictions[symbol] = {
                    'prediction': prediction,
                    'timestamp': time.time()
                }
            
            return prediction
            
        except Exception:
            return None
    
    def _detect_volume_decline_7d(self, klines_1m: List, klines_15m: List) -> Optional[Dict]:
        """Détecte baisse volume avec analyse 7 jours - Version professionnelle"""
        if len(klines_1m) < 60 or len(klines_15m) < 672:
            return None
        
        # 1. ANALYSE COURT TERME (1 minute)
        volumes_1m = [k['volume'] for k in klines_1m]
        sma_10_1m = sum(volumes_1m[-10:]) / 10
        sma_30_1m = sum(volumes_1m[-30:]) / 30
        
        # 2. ANALYSE MOYEN TERME (15 minutes sur 7 jours)
        volumes_15m = [k['volume'] for k in klines_15m]
        sma_96_15m = sum(volumes_15m[-96:]) / 96    # 24h
        sma_336_15m = sum(volumes_15m[-336:]) / 336  # 3.5 jours
        sma_672_15m = sum(volumes_15m) / len(volumes_15m)  # 7 jours complets
        
        # 3. CALCULS PROFESSIONNELS
        # Baisse court terme vs moyen terme
        decline_1m_vs_24h = ((sma_10_1m - sma_96_15m) / sma_96_15m) * 100 if sma_96_15m > 0 else 0
        decline_24h_vs_7d = ((sma_96_15m - sma_672_15m) / sma_672_15m) * 100 if sma_672_15m > 0 else 0
        
        # Seuil professionnel avec contexte 7 jours
        if decline_1m_vs_24h < -20 or decline_24h_vs_7d < -15:
            # Trouver début précis avec analyse multi-timeframe
            decline_start = self._find_decline_start_7d(volumes_1m, volumes_15m)
            
            # Classification selon intensité et contexte 7j
            if decline_1m_vs_24h < -50 or decline_24h_vs_7d < -30:
                trend = 'EXTREME_DECLINE'
            elif decline_1m_vs_24h < -35 or decline_24h_vs_7d < -20:
                trend = 'STRONG_DECLINE'
            else:
                trend = 'MODERATE_DECLINE'
            
            return {
                'decline_pct': decline_1m_vs_24h,
                'decline_7d_pct': decline_24h_vs_7d,
                'decline_duration_min': decline_start,
                'current_volume': volumes_1m[-1],
                'avg_volume_24h': sma_96_15m,
                'avg_volume_7d': sma_672_15m,
                'sma_10_1m': sma_10_1m,
                'sma_96_15m': sma_96_15m,
                'volume_trend': trend,
                'context_7d': True
            }
        
        return None
    
    def _find_decline_start_7d(self, volumes_1m: List, volumes_15m: List) -> int:
        """Trouve début précis de baisse avec analyse multi-timeframe"""
        # Analyse sur 15m pour éviter le bruit des 1m
        recent_avg_15m = sum([k for k in volumes_15m[-4:]]) / 4  # Dernière heure
        
        for i in range(len(volumes_15m) - 5, max(0, len(volumes_15m) - 96), -1):
            if volumes_15m[i] > recent_avg_15m * 1.5:
                return (len(volumes_15m) - i) * 15  # Convertir en minutes
        
        return 60  # Défaut 1h
    
    def _update_historical_patterns_7d(self, symbol: str, klines_15m: List):
        """Met à jour patterns historiques avec 7 jours de données"""
        if symbol not in self.volume_cycles:
            self.volume_cycles[symbol] = []
        
        # Analyser cycles sur 7 jours complets (plus fiable)
        volumes_7d = [k['volume'] for k in klines_15m]
        
        # Détecter cycles complets avec plus de précision
        cycles = self._find_volume_cycles_7d(volumes_7d)
        
        # Garder les 50 derniers cycles (plus d'historique)
        self.volume_cycles[symbol].extend(cycles)
        self.volume_cycles[symbol] = self.volume_cycles[symbol][-50:]
    
    def _find_volume_cycles_7d(self, volumes: List) -> List[Dict]:
        """Trouve cycles volume sur 7 jours - Plus précis"""
        cycles = []
        
        # Analyser par blocs de 24h pour éviter faux signaux
        for i in range(96, len(volumes) - 96, 24):  # Par blocs de 6h
            # Volume de référence (moyenne 24h précédente)
            ref_volume = sum(volumes[i-96:i]) / 96
            
            # Chercher baisse significative
            current_avg = sum(volumes[i:i+24]) / 24  # Moyenne 6h courante
            
            if current_avg < ref_volume * 0.7:  # Baisse > 30%
                # Chercher récupération dans les 48h suivantes
                for j in range(i+24, min(i+192, len(volumes)), 24):
                    recovery_avg = sum(volumes[j:j+24]) / 24
                    
                    if recovery_avg > ref_volume * 0.85:  # Récupération à 85%
                        cycle_duration = (j - i) * 15  # Minutes
                        decline_strength = (ref_volume - current_avg) / ref_volume
                        
                        cycles.append({
                            'duration_min': cycle_duration,
                            'decline_strength': decline_strength,
                            'recovery_ratio': recovery_avg / ref_volume,
                            'pattern_quality': 'HIGH_7D'  # Marquer qualité supérieure
                        })
                        break
        
        return cycles
    
    def _predict_with_limited_data(self, symbol: str, klines_1m: List, klines_15m: List, current_price: float) -> Optional[Dict]:
        """Mode dégradé avec données limitées (fallback)"""
        # Utiliser ancienne méthode mais avec avertissement
        volume_decline = self._detect_volume_decline(klines_1m)
        if not volume_decline:
            return None
        
        self._update_historical_patterns(symbol, klines_15m)
        prediction = self._calculate_recovery_prediction(
            symbol, volume_decline, klines_1m, klines_15m, current_price
        )
        
        if prediction:
            prediction['data_quality'] = 'LIMITED'  # Marquer qualité limitée
            prediction['confidence'] = max(30, prediction['confidence'] - 20)  # Réduire confiance
        
        return prediction
    
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
    def _calculate_recovery_prediction_7d(self, symbol: str, volume_decline: Dict, 
                                        klines_1m: List, klines_15m: List, current_price: float) -> Dict:
        """Calcule prédiction avec données 7 jours - Version professionnelle"""
        
        # 1. BASE HISTORIQUE 7 JOURS (plus fiable)
        cycles = self.volume_cycles.get(symbol, [])
        high_quality_cycles = [c for c in cycles if c.get('pattern_quality') == 'HIGH_7D']
        
        if high_quality_cycles:
            avg_duration = sum(c['duration_min'] for c in high_quality_cycles) / len(high_quality_cycles)
            avg_recovery = sum(c['recovery_ratio'] for c in high_quality_cycles) / len(high_quality_cycles)
            confidence_boost = 20  # Bonus confiance pour données 7j
        elif cycles:
            avg_duration = sum(c['duration_min'] for c in cycles) / len(cycles)
            avg_recovery = sum(c['recovery_ratio'] for c in cycles) / len(cycles)
            confidence_boost = 10
        else:
            avg_duration = 60  # Défaut plus conservateur avec 7j
            avg_recovery = 1.15
            confidence_boost = 0
        
        # 2. FACTEURS DYNAMIQUES AMÉLIORÉS
        prices_1m = [k['close'] for k in klines_1m[-20:]]  # Plus de données prix
        price_momentum = (prices_1m[-1] - prices_1m[0]) / prices_1m[0] * 100
        
        # Volatilité sur période plus longue
        price_changes = [abs(prices_1m[i] - prices_1m[i-1]) / prices_1m[i-1] 
                        for i in range(1, len(prices_1m))]
        volatility = sum(price_changes) / len(price_changes) * 100
        
        # Session de marché (inchangé)
        hour = datetime.now().hour
        if 14 <= hour <= 21:
            session_factor = 0.8
        elif 8 <= hour <= 16:
            session_factor = 1.0
        else:
            session_factor = 1.3
        
        # Facteurs spécifiques aux données 7j
        volatility_factor = 0.6 if volatility > 3 else 1.1 if volatility < 0.3 else 1.0
        
        # Divergence avec contexte 7j
        if price_momentum > 1.5 and volume_decline['decline_pct'] < -40:
            divergence_factor = 0.5  # Divergence très forte
        elif price_momentum > 0.5 and volume_decline['decline_7d_pct'] < -20:
            divergence_factor = 0.7  # Contexte 7j favorable
        elif price_momentum > 0:
            divergence_factor = 0.8
        else:
            divergence_factor = 1.3
        
        # 3. CALCUL FINAL AVEC DONNÉES 7J
        base_remaining = max(10, avg_duration - volume_decline['decline_duration_min'])
        predicted_time = base_remaining * session_factor * volatility_factor * divergence_factor
        predicted_time = max(5, min(predicted_time, 180))  # 5min à 3h
        
        # 4. CONFIANCE AVEC BONUS 7J
        confidence = 70 + confidence_boost  # Base plus élevée
        if len(high_quality_cycles) > 10:
            confidence += 15
        elif len(cycles) > 20:
            confidence += 10
        if abs(price_momentum) > 1:
            confidence += 10
        if volume_decline['decline_pct'] < -50:
            confidence += 10
        
        confidence = min(confidence, 95)  # Max 95% avec données 7j
        
        # 5. FORMATAGE
        recovery_time = datetime.now() + timedelta(minutes=predicted_time)
        
        if predicted_time < 10:
            time_str = f"{int(predicted_time)}min"
        elif predicted_time < 30:
            margin = max(2, int(predicted_time * 0.2))
            time_str = f"{int(predicted_time-margin)}-{int(predicted_time+margin)}min"
        elif predicted_time < 120:
            margin = max(5, int(predicted_time * 0.3))
            time_str = f"{int(predicted_time-margin)}-{int(predicted_time+margin)}min"
        else:
            hours = predicted_time / 60
            time_str = f"{hours:.1f}h"
        
        return {
            'status': 'VOLUME_DECLINING',
            'decline_duration_min': volume_decline['decline_duration_min'],
            'decline_pct': volume_decline['decline_pct'],
            'decline_7d_pct': volume_decline['decline_7d_pct'],
            'predicted_recovery_min': predicted_time,
            'recovery_time_str': time_str,
            'recovery_timestamp': recovery_time,
            'confidence': confidence,
            'price_momentum': price_momentum,
            'divergence_detected': price_momentum > 0.5 and volume_decline['decline_pct'] < -25,
            'historical_cycles': len(cycles),
            'high_quality_cycles': len(high_quality_cycles),
            'data_quality': 'HIGH_7D',
            'session_factor': session_factor,
            'volatility_factor': volatility_factor
        }

    def _detect_volume_decline(self, klines_1m: List) -> Optional[Dict]:
        """Ancienne méthode pour fallback"""
        if len(klines_1m) < 30:
            return None
        
        volumes = [k['volume'] for k in klines_1m]
        sma_10 = sum(volumes[-10:]) / 10
        sma_20 = sum(volumes[-30:-10]) / 20 if len(volumes) >= 30 else sum(volumes[-20:-10]) / 10
        
        decline_pct = ((sma_10 - sma_20) / sma_20) * 100 if sma_20 > 0 else 0
        
        if decline_pct < -25:
            decline_start = 15
            for i in range(len(volumes) - 5, max(0, len(volumes) - 25), -1):
                if volumes[i] > sma_10 * 1.4:
                    decline_start = len(volumes) - i
                    break
            
            return {
                'decline_pct': decline_pct,
                'decline_duration_min': decline_start,
                'current_volume': volumes[-1],
                'avg_volume': sma_20,
                'volume_trend': 'STRONG_DECLINE' if decline_pct < -40 else 'MODERATE_DECLINE'
            }
        return None