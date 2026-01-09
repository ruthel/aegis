"""
Calculateur centralisé pour métriques de marché et scoring crypto
Fusion de crypto_scorer, volatility_calculator et volume_predictor
"""
import time
from datetime import datetime, timedelta
import os
from typing import Dict, List, Optional

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

class MarketAnalyzer:
    """Calculs de marché centralisés - Tout-en-un"""
    
    def __init__(self, min_score=40, max_tradeable=2):
        # Configuration scoring crypto
        self.base_min_score = min_score
        self.max_tradeable = max_tradeable
        self.blacklist = {}
        self.blacklist_duration = 3600
        self.score_history = {}
        self.performance_weights = self._get_default_weights()
        
        # Configuration volume predictor
        self.volume_cycles = {}
        self.last_predictions = {}
    
    # ===== MÉTHODES VOLATILITÉ =====
    
    @classmethod
    def calculate_volatility(cls, klines, symbol='', websocket_manager=None):
        """Calcule la volatilité temps réel - Score 1-5 pour scalping - VERSION AMÉLIORÉE"""
        if websocket_manager and websocket_manager.is_connected():
            ws_klines = websocket_manager.get_klines(symbol, 60)
            if len(ws_klines) >= 10:
                klines = ws_klines
        
        try:
            if len(klines) < 10:
                return 2.0
            
            # AMÉLIORATION 5: Détection régime de volatilité
            regime = cls._detect_volatility_regime(klines)
            
            # Adapter période selon régime
            if regime == 'high_vol':
                recent_klines = klines[-10:]  # Période courte pour réactivité
            elif regime == 'low_vol':
                recent_klines = klines[-30:] if len(klines) >= 30 else klines[-20:]  # Période longue pour stabilité
            else:
                recent_klines = klines[-20:]  # Période normale
            
            closes = [k['close'] for k in recent_klines if 'close' in k]
            
            if len(closes) < 10:
                return 2.0
            
            # AMÉLIORATION 1: Parkinson + ATR combinés
            parkinson_vol = cls._calculate_parkinson_volatility(recent_klines)
            atr_vol = cls._calculate_atr_volatility(recent_klines, closes)
            
            # Moyenne pondérée (Parkinson 60% + ATR 40%)
            if parkinson_vol is not None:
                volatility_hourly = 0.6 * parkinson_vol + 0.4 * atr_vol
            else:
                volatility_hourly = atr_vol
            
            # AMÉLIORATION 3: Seuils adaptatifs selon crypto
            thresholds = cls._get_volatility_thresholds(symbol)
            
            # Mapper vers score 1-5 avec seuils adaptatifs
            if volatility_hourly < thresholds['very_low']:
                return 1.0
            elif volatility_hourly < thresholds['low']:
                return 2.0
            elif volatility_hourly < thresholds['medium']:
                return 3.0
            elif volatility_hourly < thresholds['high']:
                return 4.0
            else:
                return 5.0
                
        except Exception:
            return 2.0
    
    @classmethod
    def _calculate_parkinson_volatility(cls, klines):
        """AMÉLIORATION 1: Parkinson Estimator - Plus précis qu'ATR"""
        try:
            if len(klines) < 10:
                return None
            
            import math
            hl_ratios_squared = []
            
            for k in klines:
                if k['high'] > 0 and k['low'] > 0 and k['high'] >= k['low']:
                    hl_ratio = math.log(k['high'] / k['low'])
                    hl_ratios_squared.append(hl_ratio ** 2)
            
            if not hl_ratios_squared:
                return None
            
            # Parkinson variance
            parkinson_var = sum(hl_ratios_squared) / (len(hl_ratios_squared) * 4 * math.log(2))
            return math.sqrt(parkinson_var) * 100  # En %
            
        except:
            return None
    
    @classmethod
    def _calculate_atr_volatility(cls, klines, closes):
        """AMÉLIORATION 2: ATR avec EWMA au lieu de moyenne simple"""
        true_ranges = []
        for i in range(1, len(klines)):
            kline = klines[i]
            high = kline.get('high', closes[i] if i < len(closes) else 0)
            low = kline.get('low', closes[i] if i < len(closes) else 0)
            prev_close = closes[i-1] if i-1 < len(closes) else 0
            
            if high <= 0 or low <= 0 or prev_close <= 0 or high < low:
                continue
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            if tr > 0:
                true_ranges.append(tr)
        
        # AMÉLIORATION 2: EWMA au lieu de moyenne simple
        if true_ranges:
            ewma_atr = cls._calculate_ewma_atr(true_ranges)
            current_price = closes[-1]
            if current_price > 0:
                return (ewma_atr / current_price) * 100
        
        # Fallback: volatilité simple
        price_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] > 0]
        if price_changes:
            return sum(price_changes) / len(price_changes) * 100
        
        return 2.0
    
    @classmethod
    def _calculate_ewma_atr(cls, true_ranges, alpha=0.1):
        """AMÉLIORATION 2: Exponentially Weighted Moving Average"""
        if not true_ranges:
            return 0
        
        ewma = true_ranges[0]
        for tr in true_ranges[1:]:
            ewma = alpha * tr + (1 - alpha) * ewma
        return ewma
    
    @classmethod
    def _get_volatility_thresholds(cls, symbol):
        """AMÉLIORATION 3: Seuils adaptatifs par crypto"""
        # Seuils basés sur données historiques réelles
        crypto_thresholds = {
            'BTC/USDT': {'very_low': 0.12, 'low': 0.25, 'medium': 0.50, 'high': 1.0},
            'ETH/USDT': {'very_low': 0.15, 'low': 0.30, 'medium': 0.60, 'high': 1.2},
            'SOL/USDT': {'very_low': 0.25, 'low': 0.50, 'medium': 1.0, 'high': 2.0},
            'BNB/USDT': {'very_low': 0.18, 'low': 0.35, 'medium': 0.70, 'high': 1.4},
            'ADA/USDT': {'very_low': 0.20, 'low': 0.40, 'medium': 0.80, 'high': 1.6},
            'DOT/USDT': {'very_low': 0.22, 'low': 0.45, 'medium': 0.90, 'high': 1.8},
            'MATIC/USDT': {'very_low': 0.30, 'low': 0.60, 'medium': 1.2, 'high': 2.4},
            'AVAX/USDT': {'very_low': 0.28, 'low': 0.55, 'medium': 1.1, 'high': 2.2}
        }
        
        return crypto_thresholds.get(symbol, {
            'very_low': 0.15, 'low': 0.30, 'medium': 0.60, 'high': 1.2
        })
    
    @classmethod
    def _detect_volatility_regime(cls, klines):
        """AMÉLIORATION 5: Détecte régime de volatilité (calme/normal/volatil)"""
        if len(klines) < 50:
            return 'normal'
        
        try:
            # Volatilité récente vs historique
            recent_closes = [k['close'] for k in klines[-10:]]
            historical_closes = [k['close'] for k in klines[-50:]]
            
            # Calcul volatilité simple pour comparaison
            recent_changes = [abs(recent_closes[i] - recent_closes[i-1]) / recent_closes[i-1] 
                            for i in range(1, len(recent_closes)) if recent_closes[i-1] > 0]
            historical_changes = [abs(historical_closes[i] - historical_closes[i-1]) / historical_closes[i-1] 
                                for i in range(1, len(historical_closes)) if historical_closes[i-1] > 0]
            
            if not recent_changes or not historical_changes:
                return 'normal'
            
            recent_vol = sum(recent_changes) / len(recent_changes)
            historical_vol = sum(historical_changes) / len(historical_changes)
            
            ratio = recent_vol / historical_vol if historical_vol > 0 else 1
            
            if ratio > 1.5:
                return 'high_vol'  # Régime volatil
            elif ratio < 0.7:
                return 'low_vol'   # Régime calme
            else:
                return 'normal'    # Régime normal
                
        except:
            return 'normal'
    
    # ===== MÉTHODES VOLUME PREDICTOR =====
    
    def predict_volume_recovery(self, symbol: str, klines_1m: List, klines_15m: List, current_price: float) -> Optional[Dict]:
        """Prédit récupération volume - Version professionnelle avec 7 jours de données"""
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
        recent_avg_15m = sum(volumes_15m[-4:]) / 4  # Dernière heure
        
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
    
    def _predict_with_limited_data(self, symbol: str, klines_1m: List, klines_15m: List, current_price: float) -> Optional[Dict]:
        """Mode dégradé avec données limitées (fallback)"""
        # Utiliser ancienne méthode mais avec avertissement
        volume_decline = self._detect_volume_decline(klines_1m, klines_15m)
        if not volume_decline:
            return None
        
        self._update_historical_patterns(symbol, klines_15m)
        prediction = self._calculate_recovery_prediction(
            symbol, volume_decline, klines_1m, current_price
        )
        
        if prediction:
            prediction['data_quality'] = 'LIMITED'  # Marquer qualité limitée
            prediction['confidence'] = max(30, prediction['confidence'] - 20)  # Réduire confiance
        
        return prediction
    
    def _update_historical_patterns(self, symbol: str, klines_15m: List):
        """Met à jour patterns historiques (version limitée)"""
        if symbol not in self.volume_cycles:
            self.volume_cycles[symbol] = []
        
        volumes = [k['volume'] for k in klines_15m]
        cycles = self._find_volume_cycles(volumes)
        
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
    
    def should_notify(self, symbol: str, prediction: Dict) -> bool:
        """Détermine si notification nécessaire (anti-spam)"""
        if symbol not in self.last_predictions:
            return True
        
        last = self.last_predictions[symbol]
        return time.time() - last['timestamp'] > 1800  # 30min
    
    # ===== MÉTHODES CONFIDENCE CALCULATOR =====
    
    @staticmethod
    def get_min_confidence(volatility, symbol=None):
        """
        Calcule le seuil de confiance minimum selon la volatilité - ADAPTATIF
        
        Args:
            volatility: Score volatilité 1-5
            symbol: Symbole pour optimisations futures
        
        Returns:
            int: Seuil de confiance minimum (%)
        """
        # Utiliser le gestionnaire centralisé
        try:
            from utils.timeframe_analyzer import TimeframeAnalyzer
            analyzer = TimeframeAnalyzer()
            return analyzer.get_confidence_threshold(symbol or 'BTC/USDT', volatility)
        except:
            # Fallback seuils réduits car 15m = signaux plus fiables
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
    
    # ===== NOUVEAUX FACTEURS PROFESSIONNELS =====
    
    def calculate_rsi_score(self, klines):
        """Score RSI (0-20 points) - Niveau Professionnel"""
        if len(klines) < 14:
            return 10  # Score neutre
        
        closes = [k['close'] for k in klines]
        rsi = self._calculate_rsi(closes, 14)
        
        if rsi is None:
            return 10
        
        # Scoring professionnel RSI
        if 30 <= rsi <= 70:  # Zone neutre optimale
            return 20
        elif 25 <= rsi < 30 or 70 < rsi <= 75:  # Légèrement oversold/overbought
            return 15
        elif rsi < 25:  # Très oversold (opportunité)
            return 12
        elif rsi > 75:  # Très overbought (risque)
            return 8
        else:
            return 10
    
    def _calculate_rsi(self, closes, period=14):
        """Calcule RSI standard"""
        if len(closes) < period + 1:
            return None
        
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def calculate_correlation_score(self, bot, symbol):
        """Score corrélation avec BTC (0-15 points)"""
        if symbol == 'BTC/USDT':
            return 15  # BTC = référence
        
        try:
            # Klines 7 jours pour corrélation fiable
            symbol_klines = bot.get_klines(symbol, 168, '1h')  # 7j en 1h
            btc_klines = bot.get_klines('BTC/USDT', 168, '1h')
            
            if len(symbol_klines) < 50 or len(btc_klines) < 50:
                return 10  # Score neutre si pas assez de données
            
            # Prendre même longueur
            min_len = min(len(symbol_klines), len(btc_klines))
            symbol_closes = [k['close'] for k in symbol_klines[-min_len:]]
            btc_closes = [k['close'] for k in btc_klines[-min_len:]]
            
            correlation = self._calculate_correlation(symbol_closes, btc_closes)
            
            # Scoring: Faible corrélation = meilleur (diversification)
            if correlation < 0.3:  # Très faible corrélation
                return 15
            elif correlation < 0.5:  # Faible corrélation
                return 12
            elif correlation < 0.7:  # Corrélation modérée
                return 10
            elif correlation < 0.9:  # Forte corrélation
                return 7
            else:  # Très forte corrélation (risque)
                return 5
                
        except:
            return 10  # Score neutre en cas d'erreur
    
    def _calculate_correlation(self, x, y):
        """Calcule corrélation de Pearson"""
        if len(x) != len(y) or len(x) < 2:
            return 0.5
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi * xi for xi in x)
        sum_y2 = sum(yi * yi for yi in y)
        
        numerator = n * sum_xy - sum_x * sum_y
        denominator = ((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y)) ** 0.5
        
        if denominator == 0:
            return 0
        
        return abs(numerator / denominator)  # Valeur absolue
    
    def calculate_liquidity_score(self, bot, symbol):
        """Score liquidité (0-15 points) - Spread + Order book"""
        try:
            # Estimer spread via ticker
            ticker = bot.get_ticker(symbol)
            if not ticker:
                return 10
            
            # Spread estimé (bid-ask)
            current_price = ticker.get('last', 0)
            if current_price <= 0:
                return 10
            
            # Estimation spread selon crypto (données réelles Binance)
            if symbol in ['BTC/USDT', 'ETH/USDT']:
                estimated_spread = 0.01  # 0.01%
            elif symbol in ['BNB/USDT', 'SOL/USDT']:
                estimated_spread = 0.02  # 0.02%
            else:
                estimated_spread = 0.05  # 0.05%
            
            # Volume 24h comme proxy liquidité
            volume_24h = ticker.get('quoteVolume', 0)
            
            # Score combiné spread + volume
            spread_score = 15 if estimated_spread <= 0.01 else 12 if estimated_spread <= 0.02 else 8 if estimated_spread <= 0.05 else 5
            volume_score = 15 if volume_24h > 100000000 else 12 if volume_24h > 50000000 else 8 if volume_24h > 10000000 else 5
            
            return int((spread_score + volume_score) / 2)
            
        except:
            return 10  # Score neutre
    
    def calculate_technical_score(self, klines):
        """Score technique (0-20 points) - MACD + Bollinger + EMA"""
        if len(klines) < 26:  # MACD nécessite 26 périodes
            return 10
        
        closes = [k['close'] for k in klines]
        score = 0
        signals = 0
        
        # 1. MACD Signal (0-7 points)
        try:
            macd_signal = self._calculate_macd_signal(closes)
            if macd_signal == 'BUY':
                score += 7
            elif macd_signal == 'NEUTRAL':
                score += 4
            # SELL = 0 points
            signals += 1
        except:
            pass
        
        # 2. Bollinger Bands (0-7 points)
        try:
            bb_signal = self._calculate_bollinger_signal(closes)
            if bb_signal == 'BUY':  # Prix près bande basse
                score += 7
            elif bb_signal == 'NEUTRAL':
                score += 4
            signals += 1
        except:
            pass
        
        # 3. EMA Crossover (0-6 points)
        try:
            ema_signal = self._calculate_ema_crossover(closes)
            if ema_signal == 'BUY':
                score += 6
            elif ema_signal == 'NEUTRAL':
                score += 3
            signals += 1
        except:
            pass
        
        # Moyenne pondérée
        if signals > 0:
            return min(20, int((score / signals) * (20 / 7)))  # Normaliser sur 20
        return 10
    
    def _calculate_macd_signal(self, closes):
        """Signal MACD simple"""
        if len(closes) < 26:
            return 'NEUTRAL'
        
        ema_12 = self._calculate_ema(closes, 12)
        ema_26 = self._calculate_ema(closes, 26)
        macd = ema_12 - ema_26
        
        # Signal simple: MACD > 0 = haussier
        if macd > 0:
            return 'BUY'
        elif macd < -0.5:
            return 'SELL'
        return 'NEUTRAL'
    
    def _calculate_bollinger_signal(self, closes):
        """Signal Bollinger Bands"""
        if len(closes) < 20:
            return 'NEUTRAL'
        
        sma_20 = sum(closes[-20:]) / 20
        variance = sum((c - sma_20) ** 2 for c in closes[-20:]) / 20
        std_dev = variance ** 0.5
        
        upper_band = sma_20 + (2 * std_dev)
        lower_band = sma_20 - (2 * std_dev)
        current_price = closes[-1]
        
        # Signal: Prix près bande basse = achat
        distance_to_lower = (current_price - lower_band) / (upper_band - lower_band)
        
        if distance_to_lower < 0.2:  # Près bande basse
            return 'BUY'
        elif distance_to_lower > 0.8:  # Près bande haute
            return 'SELL'
        return 'NEUTRAL'
    
    def _calculate_ema_crossover(self, closes):
        """Signal croisement EMA 9/21"""
        if len(closes) < 21:
            return 'NEUTRAL'
        
        ema_9 = self._calculate_ema(closes, 9)
        ema_21 = self._calculate_ema(closes, 21)
        
        if ema_9 > ema_21:
            return 'BUY'
        elif ema_9 < ema_21 * 0.98:  # 2% en dessous
            return 'SELL'
        return 'NEUTRAL'
    
    def _calculate_ema(self, prices, period):
        """Calcule EMA"""
        if len(prices) < period:
            return sum(prices) / len(prices)
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def calculate_support_resistance_score(self, bot, symbol, current_price):
        """Score Support/Resistance (0-15 points) - Utilise PatternAnalyzer existant"""
        try:
            if not hasattr(bot, 'pattern_analyzer'):
                return 8  # Score neutre
            
            klines = bot.get_klines(symbol, 100, '4h')
            if len(klines) < 50:
                return 8
            
            levels_data = bot.pattern_analyzer.find_support_resistance_levels(klines)
            reversal_data = bot.pattern_analyzer.predict_reversal_probability(current_price, levels_data)
            
            # Scoring selon proximité et force des niveaux
            if reversal_data['has_reversal_potential']:
                probability = reversal_data['probability']
                if reversal_data['direction'] == 'UP':  # Près support = bon pour achat
                    return min(15, int(probability / 100 * 15))
                else:  # Près résistance = mauvais pour achat
                    return max(3, int((100 - probability) / 100 * 15))
            
            # Pas de niveau proche = score moyen
            return 8
            
        except Exception as e:
            return 8  # Score neutre en cas d'erreur
    
    def calculate_multi_timeframe_score(self, bot, symbol):
        """Score Multi-Timeframe (0-10 points) - Utilise TimeframeAnalyzer existant"""
        try:
            if not hasattr(bot, 'multi_tf_analyzer'):
                return 5  # Score neutre
            
            current_price = bot.get_price(symbol)
            analysis = bot.multi_tf_analyzer.analyze_all_timeframes(bot, symbol, current_price)
            
            global_signal = analysis['global_signal']
            confidence = global_signal['confidence']
            action = global_signal['action']
            
            # Scoring selon alignement des timeframes
            if action in ['STRONG_BUY', 'BUY']:
                return min(10, int(confidence / 10))  # Confidence 80% = 8 points
            elif action in ['STRONG_SELL', 'SELL']:
                return max(2, int((100 - confidence) / 10))  # Inverse pour vente
            else:  # HOLD
                return 5  # Neutre
                
        except Exception as e:
            return 5  # Score neutre en cas d'erreur
    
    def calculate_market_cap_score(self, symbol):
        """Score Market Cap (0-10 points) - Taille relative"""
        # Ranking approximatif des cryptos par market cap
        market_cap_ranking = {
            'BTC/USDT': 1,   # #1
            'ETH/USDT': 2,   # #2
            'BNB/USDT': 4,   # #4
            'SOL/USDT': 5,   # #5
            'ADA/USDT': 10,  # #10
            'DOT/USDT': 15,  # #15
            'MATIC/USDT': 20, # #20
            'AVAX/USDT': 25   # #25
        }
        
        rank = market_cap_ranking.get(symbol, 100)
        
        if rank <= 3:      # Top 3
            return 10
        elif rank <= 10:   # Top 10
            return 8
        elif rank <= 25:   # Top 25
            return 6
        elif rank <= 50:   # Top 50
            return 4
        else:              # Au-delà Top 50
            return 2
    
    # ===== 8 NOUVEAUX FACTEURS AVANCÉS =====
    
    def calculate_orderbook_imbalance_score(self, bot, symbol):
        """Score déséquilibre carnet d'ordres (0-15 points)"""
        try:
            orderbook = bot.exchange.fetch_order_book(symbol, limit=10)
            bid_volume = sum(bid[1] for bid in orderbook['bids'][:5])
            ask_volume = sum(ask[1] for ask in orderbook['asks'][:5])
            
            if bid_volume + ask_volume == 0:
                return 10
            
            imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
            
            if imbalance > 0.3:  # Plus d'acheteurs
                return 15
            elif imbalance > 0.1:
                return 12
            elif imbalance < -0.3:  # Plus de vendeurs
                return 5
            else:
                return 10
        except:
            return 10
    
    def calculate_price_action_score(self, klines):
        """Score patterns prix (0-12 points) - Doji, Hammer, etc."""
        if len(klines) < 3:
            return 6
        
        last = klines[-1]
        if last['open'] == 0:
            return 6
            
        body_size = abs(last['close'] - last['open']) / last['open']
        wick_ratio = (last['high'] - last['low']) / last['open'] if last['open'] > 0 else 0
        
        # Doji (indécision)
        if body_size < 0.001:
            return 8
        # Hammer (reversal bullish)
        elif last['close'] > last['open'] and wick_ratio > 0.02:
            return 12
        # Strong candle
        elif body_size > 0.01:
            return 10
        else:
            return 6
    
    def calculate_volume_profile_score(self, klines):
        """Score profil volume (0-18 points)"""
        if len(klines) < 20:
            return 9
        
        volumes = [k['volume'] for k in klines[-20:]]
        prices = [k['close'] for k in klines[-20:]]
        
        total_volume = sum(volumes)
        if total_volume == 0:
            return 9
        
        # Volume-weighted average price
        vwap = sum(p * v for p, v in zip(prices, volumes)) / total_volume
        current_price = prices[-1]
        
        if current_price == 0:
            return 9
            
        distance_from_vwap = abs(current_price - vwap) / current_price
        
        if distance_from_vwap < 0.01:  # Près VWAP
            return 18
        elif distance_from_vwap < 0.02:
            return 15
        else:
            return 9
    
    def calculate_momentum_divergence_score(self, klines):
        """Score divergence momentum/prix (0-16 points)"""
        if len(klines) < 20:
            return 8
        
        prices = [k['close'] for k in klines[-10:]]
        volumes = [k['volume'] for k in klines[-10:]]
        
        if prices[0] == 0 or volumes[0] == 0:
            return 8
        
        price_trend = (prices[-1] - prices[0]) / prices[0]
        volume_trend = (volumes[-1] - volumes[0]) / volumes[0]
        
        # Divergence bullish : prix baisse, volume monte
        if price_trend < -0.01 and volume_trend > 0.1:
            return 16
        # Convergence normale
        elif (price_trend > 0 and volume_trend > 0):
            return 12
        else:
            return 8
    
    def calculate_volatility_clustering_score(self, klines):
        """Score clustering volatilité (0-12 points)"""
        if len(klines) < 20:
            return 6
        
        returns = []
        for i in range(1, len(klines)):
            if klines[i-1]['close'] > 0:
                ret = (klines[i]['close'] - klines[i-1]['close']) / klines[i-1]['close']
                returns.append(abs(ret))
        
        if len(returns) < 10:
            return 6
        
        recent_vol = sum(returns[-5:]) / 5
        avg_vol = sum(returns) / len(returns)
        
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1
        
        if 0.8 <= vol_ratio <= 1.2:  # Volatilité stable
            return 12
        elif vol_ratio > 2.0:  # Volatilité excessive
            return 4
        else:
            return 8
    
    def calculate_fibonacci_score(self, klines):
        """Score niveaux Fibonacci (0-10 points)"""
        if len(klines) < 50:
            return 5
        
        prices = [k['close'] for k in klines]
        high = max(prices[-20:])
        low = min(prices[-20:])
        current = prices[-1]
        
        if high == low or current == 0:
            return 5
        
        # Niveaux Fibonacci
        fib_levels = {
            0.236: high - (high - low) * 0.236,
            0.382: high - (high - low) * 0.382,
            0.618: high - (high - low) * 0.618
        }
        
        for level, price in fib_levels.items():
            if abs(current - price) / current < 0.01:  # Près niveau Fib
                return 10
        
        return 5
    
    def calculate_microstructure_score(self, klines):
        """Score microstructure (0-14 points) - Tick size, gaps"""
        if len(klines) < 10:
            return 7
        
        gaps = []
        tick_sizes = []
        
        for i in range(1, len(klines)):
            if klines[i-1]['close'] > 0 and klines[i]['open'] > 0:
                # Gap entre close précédent et open actuel
                gap = abs(klines[i]['open'] - klines[i-1]['close']) / klines[i-1]['close']
                gaps.append(gap)
                
                # Tick size (plus petit mouvement)
                if klines[i]['open'] > 0:
                    tick = abs(klines[i]['close'] - klines[i]['open']) / klines[i]['open']
                    tick_sizes.append(tick)
        
        if not gaps or not tick_sizes:
            return 7
        
        avg_gap = sum(gaps) / len(gaps)
        avg_tick = sum(tick_sizes) / len(tick_sizes)
        
        # Faibles gaps + ticks réguliers = bon
        if avg_gap < 0.001 and 0.001 < avg_tick < 0.01:
            return 14
        else:
            return 7
    
    def calculate_seasonality_score(self, symbol):
        """Score saisonnalité intraday (0-10 points)"""
        from datetime import datetime
        
        hour = datetime.now().hour
        crypto = symbol.split('/')[0]
        
        # Patterns horaires par crypto (basé sur données historiques)
        hourly_patterns = {
            'BTC': {8: 12, 14: 15, 20: 10, 2: 8},  # Meilleurs à 14h UTC
            'ETH': {9: 12, 15: 14, 21: 9, 3: 7},
            'SOL': {10: 11, 16: 13, 22: 8, 4: 6}
        }
        
        pattern = hourly_patterns.get(crypto, {})
        return pattern.get(hour, 5)  # Score par défaut 5
    
    @staticmethod
    def calculate_momentum(klines):
        """Calcul momentum sur 10 dernières périodes"""
        if len(klines) < 10:
            return 0
        
        if NUMPY_AVAILABLE:
            prices = np.array([k['close'] for k in klines[-10:]])
            return (prices[-1] - prices[0]) / prices[0] * 100
        
        prices = [k['close'] for k in klines[-10:]]
        return (prices[-1] - prices[0]) / prices[0] * 100
    
    @staticmethod
    def calculate_volume_avg(klines, periods=5):
        """Calcul volume moyen sur N périodes"""
        if len(klines) < periods:
            return 0
        
        if NUMPY_AVAILABLE:
            volumes = np.array([k['volume'] for k in klines[-periods:]])
            return volumes.mean()
        
        return sum(k['volume'] for k in klines[-periods:]) / periods
    
    @staticmethod
    def calculate_professional_volume_metrics(bot, symbol):
        """Calcul volume professionnel : 7j + moyennes mobiles + VWAP"""
        try:
            klines_7d = bot.get_klines(symbol, 672, '15m')
            if len(klines_7d) >= 672:
                return MarketAnalyzer._calculate_7d_metrics(klines_7d)
            
            klines_24h = bot.get_klines(symbol, 96, '15m')
            if len(klines_24h) >= 50:
                return MarketAnalyzer._calculate_24h_metrics(klines_24h)
            
            return None
        except:
            return None
    
    @staticmethod
    def _calculate_7d_metrics(klines_7d):
        """Métriques volume 7 jours (optimal)"""
        volumes = [k['volume'] for k in klines_7d]
        
        sma_96 = sum(volumes[-96:]) / 96
        sma_336 = sum(volumes[-336:]) / 336
        sma_672 = sum(volumes) / len(volumes)
        
        current_volume = volumes[-1]
        
        total_pv = sum(k['close'] * k['volume'] for k in klines_7d[-96:])
        total_volume = sum(k['volume'] for k in klines_7d[-96:])
        vwap = total_pv / total_volume if total_volume > 0 else 0
        
        return {
            'volume_7d': sum(volumes),
            'volume_24h': sum(volumes[-96:]),
            'sma_24h': sma_96,
            'sma_3d': sma_336,
            'sma_7d': sma_672,
            'current_volume': current_volume,
            'ratio_vs_24h': current_volume / sma_96 if sma_96 > 0 else 1,
            'ratio_vs_7d': current_volume / sma_672 if sma_672 > 0 else 1,
            'vwap_7d': vwap,
            'data_quality': 'HIGH_7D',
            'volume_trend': MarketAnalyzer._get_volume_trend_7d(sma_96, sma_336, sma_672)
        }
    
    @staticmethod
    def _calculate_24h_metrics(klines_24h):
        """Métriques volume 24h (fallback)"""
        volumes = [k['volume'] for k in klines_24h]
        sma_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
        sma_50 = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else 0
        current_volume = volumes[-1]
        
        total_pv = sum(k['close'] * k['volume'] for k in klines_24h[-20:])
        total_volume = sum(k['volume'] for k in klines_24h[-20:])
        vwap = total_pv / total_volume if total_volume > 0 else 0
        
        return {
            'volume_24h': sum(volumes),
            'sma_20': sma_20,
            'sma_50': sma_50,
            'current_volume': current_volume,
            'ratio_vs_sma20': current_volume / sma_20 if sma_20 > 0 else 1,
            'ratio_vs_sma50': current_volume / sma_50 if sma_50 > 0 else 1,
            'vwap': vwap,
            'data_quality': 'LIMITED_24H',
            'volume_trend': 'INCREASING' if current_volume / sma_20 > 1.2 else 'DECREASING' if current_volume / sma_20 < 0.8 else 'STABLE'
        }
    
    @staticmethod
    def _get_volume_trend_7d(sma_24h, sma_3d, sma_7d):
        """Tendance volume basée sur moyennes 7j"""
        if sma_24h > sma_3d * 1.2 and sma_3d > sma_7d * 1.1:
            return 'STRONG_INCREASING'
        elif sma_24h > sma_3d * 1.1:
            return 'INCREASING'
        elif sma_24h < sma_3d * 0.8 and sma_3d < sma_7d * 0.9:
            return 'STRONG_DECREASING'
        elif sma_24h < sma_3d * 0.9:
            return 'DECREASING'
        else:
            return 'STABLE'
    
    @staticmethod
    def get_crypto_profile(volatility):
        """Profil adaptatif selon volatilité (échelle Binance 1-5)"""
        if volatility >= 4.0:
            return {
                'min_confidence': 45,
                'profit_target': 1.5,
                'confidence_adjustment': +5
            }
        elif volatility >= 3.0:
            return {
                'min_confidence': 50,
                'profit_target': 1.0,
                'confidence_adjustment': +3
            }
        elif volatility >= 2.0:
            return {
                'min_confidence': 55,
                'profit_target': 0.7,
                'confidence_adjustment': 0
            }
        else:
            return {
                'min_confidence': 60,
                'profit_target': 0.5,
                'confidence_adjustment': 0
            }
    
    @staticmethod
    def calculate_momentum_score(klines):
        """Score momentum (0-25 points)"""
        if len(klines) < 10:
            return 0
        
        momentum = MarketAnalyzer.calculate_momentum(klines)
        
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
    
    @staticmethod
    def calculate_volume_score(klines):
        """Score volume professionnel (0-25 points) - Standards institutionnels"""
        if len(klines) < 5:
            return 0
        
        avg_volume = sum(k['volume'] for k in klines) / len(klines)
        
        if avg_volume >= 10000000:
            return 25
        elif avg_volume >= 5000000:
            return 22
        elif avg_volume >= 2000000:
            return 18
        elif avg_volume >= 1000000:
            return 15
        elif avg_volume >= 500000:
            return 10
        elif avg_volume >= 100000:
            return 5
        else:
            return 0
    
    @staticmethod
    def calculate_loss_percent(current_price, buy_price):
        """Calcul pourcentage de perte/gain"""
        return ((current_price - buy_price) / buy_price) * 100
    
    @staticmethod
    def calculate_hours_held(buy_time):
        """Calcul heures de détention"""
        import time
        return (time.time() - buy_time) / 3600
    
    # ===== MÉTHODES CRYPTO SCORING =====
    
    def calculate_volatility_score(self, klines, symbol='', volatility=None, websocket_manager=None):
        """Score basé sur volatilité 1-5 (0-30 points) - ADAPTATIF"""
        if len(klines) < 10:
            return 0
        
        if volatility is None:
            volatility = self.calculate_volatility(klines, symbol, websocket_manager)
        
        base_points = self._get_base_volatility_points(volatility)
        crypto_multiplier = self._get_crypto_multiplier(symbol)
        
        return int(base_points * crypto_multiplier)
    
    def calculate_spread_score(self, symbol, current_price):
        """Score basé sur spread estimé (0-10 points)"""
        estimated_spread = 0.01
        
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
        """Calcule le score total d'une crypto (0-100) - Version professionnelle 7j"""
        try:
            from utils.timeframe_analyzer import TimeframeAnalyzer
            analyzer = TimeframeAnalyzer()
            optimal_timeframe = analyzer.get_main_timeframe(symbol, 'intelligent', bot)
            
            klines_7d = bot.get_klines(symbol, 672, '15m')
            klines_short = bot.get_klines(symbol, 20, optimal_timeframe)
            current_price = bot.get_price(symbol)
            
            if not klines_short or len(klines_short) < 10:
                return 0
            
            # Calculer TOUS les scores (10 facteurs)
            volatility_score = self.calculate_volatility_score(klines_short, symbol, volatility, websocket_manager)
            volume_score = self.calculate_volume_score(klines_7d) if klines_7d and len(klines_7d) >= 672 else self.calculate_volume_score(klines_short)
            momentum_score = self.calculate_momentum_score(klines_short)
            spread_score = self.calculate_spread_score(symbol, current_price)
            history_score = self.calculate_history_score(symbol, stuck_positions)
            
            # NOUVEAUX FACTEURS PROFESSIONNELS
            rsi_score = self.calculate_rsi_score(klines_short)
            correlation_score = self.calculate_correlation_score(bot, symbol)
            liquidity_score = self.calculate_liquidity_score(bot, symbol)
            technical_score = self.calculate_technical_score(klines_short)
            market_cap_score = self.calculate_market_cap_score(symbol)
            
            # FACTEURS DÉJÀ IMPLÉMENTÉS (utilise analyseurs existants)
            support_resistance_score = self.calculate_support_resistance_score(bot, symbol, current_price)
            multi_timeframe_score = self.calculate_multi_timeframe_score(bot, symbol)
            
            # 8 NOUVEAUX FACTEURS AVANCÉS
            orderbook_score = self.calculate_orderbook_imbalance_score(bot, symbol)
            price_action_score = self.calculate_price_action_score(klines_short)
            volume_profile_score = self.calculate_volume_profile_score(klines_short)
            momentum_div_score = self.calculate_momentum_divergence_score(klines_short)
            volatility_cluster_score = self.calculate_volatility_clustering_score(klines_short)
            fibonacci_score = self.calculate_fibonacci_score(klines_short)
            microstructure_score = self.calculate_microstructure_score(klines_short)
            seasonality_score = self.calculate_seasonality_score(symbol)
            
            # Déterminer qualité des données
            if klines_7d and len(klines_7d) >= 672:
                data_quality = 'HIGH_7D'
            else:
                data_quality = 'LIMITED'
            
            # Conditions de marché (nécessaire pour ponderation)
            market_conditions = {
                'avg_volatility': 2.0,  # Valeur par défaut
                'avg_volume_ratio': 1.0
            }
            
            weights = self._get_dynamic_weights(symbol, market_conditions)
            if data_quality == 'HIGH_7D':
                weights['volume'] *= 1.1  # Bonus réduit car plus de facteurs
            
            total_score = (
                volatility_score * weights['volatility'] +
                volume_score * weights['volume'] +
                momentum_score * weights['momentum'] +
                rsi_score * weights['rsi'] +
                correlation_score * weights['correlation'] +
                liquidity_score * weights['liquidity'] +
                technical_score * weights['technical'] +
                market_cap_score * weights['market_cap'] +
                support_resistance_score * weights['support_resistance'] +
                multi_timeframe_score * weights['multi_timeframe'] +
                orderbook_score * weights['orderbook'] +
                price_action_score * weights['price_action'] +
                volume_profile_score * weights['volume_profile'] +
                momentum_div_score * weights['momentum_div'] +
                volatility_cluster_score * weights['volatility_cluster'] +
                fibonacci_score * weights['fibonacci'] +
                microstructure_score * weights['microstructure'] +
                seasonality_score * weights['seasonality'] +
                spread_score * weights['spread'] +
                history_score * weights['history']
            )
            
            return min(total_score, 100)
            
        except Exception as e:
            print(f"❌ Erreur scoring {symbol}: {e}")
            return 0
    
    def rank_cryptos(self, bot, trading_pairs, stuck_positions):
        """Classe toutes les cryptos et retourne les meilleures"""
        balance = bot.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        
        if usdt_available <= 0:
            print(f"⚠️ Balance USDT: 0 - Aucune crypto tradable")
            return []
        
        scores = []
        volatilities = []
        volume_ratios = []
        
        for pair in trading_pairs:
            symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
            base_currency = symbol.split('/')[0]
            
            min_cost = bot.get_min_amount(symbol)['min_cost']
            
            if usdt_available < min_cost:
                continue
            
            crypto_balance = balance.get(base_currency, {}).get('free', 0)
            if crypto_balance > 0.00001:
                price = bot.get_price(symbol)
                if (crypto_balance * price) < min_cost:
                    continue
            
            from utils.timeframe_analyzer import TimeframeAnalyzer
            analyzer = TimeframeAnalyzer()
            optimal_timeframe = analyzer.get_main_timeframe(symbol, 'intelligent', bot)
            
            klines = bot.get_klines(symbol, 20, optimal_timeframe)
            
            if not klines or len(klines) < 10:
                continue
            
            volatility = self.calculate_volatility(klines, symbol)
            volatilities.append(volatility)
            
            if len(klines) >= 5:
                current_vol = klines[-1]['volume']
                avg_vol = sum(k['volume'] for k in klines[:-1]) / (len(klines) - 1)
                vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
                volume_ratios.append(vol_ratio)
            
            websocket_manager = getattr(bot, 'websocket', None)
            score = self.score_crypto(bot, symbol, stuck_positions, websocket_manager)
            if score > 0:
                details = self.get_score_details(bot, symbol, stuck_positions, websocket_manager)
                if details:
                    scores.append({
                        'symbol': symbol,
                        'score': score,
                        'volatility': details['volatility'],
                        'volume': details['volume'],
                        'min_cost': min_cost
                    })
        
        scores.sort(key=lambda x: x['score'], reverse=True)
        
        market_conditions = {
            'avg_volatility': sum(volatilities) / len(volatilities) if volatilities else 2.0,
            'avg_volume_ratio': sum(volume_ratios) / len(volume_ratios) if volume_ratios else 1.0
        }
        
        dynamic_min_score = self._get_dynamic_min_score(
            available_count=len(scores),
            capital=usdt_available,
            market_conditions=market_conditions
        )
        
        # STOCKER le seuil calculé pour intelligent_strategy()
        self.last_dynamic_threshold = dynamic_min_score
        
        tradeable = [c['symbol'] for c in scores[:self.max_tradeable] if c['score'] >= dynamic_min_score]
        
        if tradeable:
            top_display = []
            for c in scores[:self.max_tradeable]:
                if c['score'] >= dynamic_min_score:
                    vol_score = c.get('volatility', 0)
                    if vol_score >= 30:
                        vol_display = 4.0
                    elif vol_score >= 25:
                        vol_display = 3.0
                    elif vol_score >= 20:
                        vol_display = 2.0
                    else:
                        vol_display = 1.0
                    top_display.append(f"{c['symbol'].replace('/USDT', '')} {c['score']:.0f} (V{vol_display:.1f} L{c.get('volume', 0)} M{int(c['min_cost'])})")
            
            if top_display:
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
    

    
    def _get_default_weights(self):
        """Pondération par défaut - 20 facteurs"""
        return {
            'rsi': 0.15, 'support_resistance': 0.11, 'orderbook': 0.07,
            'correlation': 0.11, 'volume_profile': 0.08, 'multi_timeframe': 0.07,
            'momentum': 0.07, 'technical': 0.07, 'momentum_div': 0.06,
            'volatility': 0.07, 'liquidity': 0.06, 'microstructure': 0.06,
            'volume': 0.05, 'price_action': 0.05, 'volatility_cluster': 0.05,
            'fibonacci': 0.04, 'seasonality': 0.04, 'market_cap': 0.02,
            'spread': 0.01, 'history': 0.01
        }
    
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
            return 1.2
        else:
            return 1.0
    
    def _get_dynamic_weights(self, symbol, market_conditions=None):
        """Pondération adaptative selon crypto ET conditions de marché - 20 Facteurs Pro"""
        # Nouvelle pondération avec 20 facteurs
        if symbol in ['BTC/USDT', 'ETH/USDT']:
            base_weights = {
                'rsi': 0.15, 'support_resistance': 0.12, 'orderbook': 0.08,
                'correlation': 0.10, 'volume_profile': 0.09, 'multi_timeframe': 0.08,
                'liquidity': 0.08, 'technical': 0.06, 'momentum': 0.05,
                'volatility': 0.06, 'momentum_div': 0.06, 'microstructure': 0.07,
                'volume': 0.04, 'price_action': 0.05, 'volatility_cluster': 0.05,
                'fibonacci': 0.04, 'seasonality': 0.04, 'market_cap': 0.03,
                'spread': 0.01, 'history': 0.01
            }
        else:
            base_weights = {
                'rsi': 0.15, 'support_resistance': 0.10, 'orderbook': 0.06,
                'correlation': 0.12, 'volume_profile': 0.07, 'multi_timeframe': 0.06,
                'momentum': 0.09, 'technical': 0.08, 'momentum_div': 0.07,
                'volatility': 0.08, 'liquidity': 0.05, 'microstructure': 0.05,
                'volume': 0.04, 'price_action': 0.04, 'volatility_cluster': 0.04,
                'fibonacci': 0.03, 'seasonality': 0.03, 'market_cap': 0.02,
                'spread': 0.01, 'history': 0.01
            }
        
        # Ajustements dynamiques selon marché
        if market_conditions:
            avg_volatility = market_conditions.get('avg_volatility', 2.0)
            avg_volume_ratio = market_conditions.get('avg_volume_ratio', 1.0)
            
            # Marché très volatil = privilégier RSI + support/resistance + orderbook
            if avg_volatility > 3.5:
                base_weights['rsi'] += 0.03
                base_weights['support_resistance'] += 0.02
                base_weights['orderbook'] += 0.02
                base_weights['momentum'] -= 0.03
                base_weights['volatility'] -= 0.02
                base_weights['volume_profile'] -= 0.02
            
            # Marché calme = privilégier multi-timeframe + liquidité + microstructure
            elif avg_volatility < 1.5:
                base_weights['multi_timeframe'] += 0.03
                base_weights['liquidity'] += 0.02
                base_weights['microstructure'] += 0.02
                base_weights['momentum'] -= 0.04
                base_weights['volatility_cluster'] -= 0.03
            
            # Volume anormal = ajuster volume_profile + momentum_div
            if avg_volume_ratio > 2.0:
                base_weights['volume_profile'] += 0.02
                base_weights['momentum_div'] += 0.02
                base_weights['spread'] -= 0.01
                base_weights['history'] -= 0.01
                base_weights['seasonality'] -= 0.02
            elif avg_volume_ratio < 0.5:
                base_weights['volume_profile'] -= 0.02
                base_weights['volatility'] += 0.02
        
        return base_weights
    
    def get_score_details(self, bot, symbol, stuck_positions, websocket_manager=None):
        """Détails du score professionnel pour debug - 20 facteurs"""
        try:
            # Calculer le score professionnel pondéré
            final_score = self.score_crypto(bot, symbol, stuck_positions, websocket_manager)
            
            # Calculer les composants bruts pour affichage
            from utils.timeframe_analyzer import TimeframeAnalyzer
            analyzer = TimeframeAnalyzer()
            optimal_timeframe = analyzer.get_main_timeframe(symbol, 'intelligent', bot)
            
            klines_short = bot.get_klines(symbol, 20, optimal_timeframe)
            klines_long = bot.get_klines(symbol, 96, '15m')
            current_price = bot.get_price(symbol)
            
            if not klines_short or len(klines_short) < 10:
                return None
            
            # TOUS les composants (20 facteurs)
            volatility_raw = self.calculate_volatility_score(klines_short, symbol, None, websocket_manager)
            volume_raw = self.calculate_volume_score(klines_long if klines_long and len(klines_long) >= 50 else klines_short)
            momentum_raw = self.calculate_momentum_score(klines_short)
            rsi_raw = self.calculate_rsi_score(klines_short)
            correlation_raw = self.calculate_correlation_score(bot, symbol)
            liquidity_raw = self.calculate_liquidity_score(bot, symbol)
            technical_raw = self.calculate_technical_score(klines_short)
            market_cap_raw = self.calculate_market_cap_score(symbol)
            support_resistance_raw = self.calculate_support_resistance_score(bot, symbol, current_price)
            multi_timeframe_raw = self.calculate_multi_timeframe_score(bot, symbol)
            
            # 8 nouveaux facteurs
            orderbook_raw = self.calculate_orderbook_imbalance_score(bot, symbol)
            price_action_raw = self.calculate_price_action_score(klines_short)
            volume_profile_raw = self.calculate_volume_profile_score(klines_short)
            momentum_div_raw = self.calculate_momentum_divergence_score(klines_short)
            volatility_cluster_raw = self.calculate_volatility_clustering_score(klines_short)
            fibonacci_raw = self.calculate_fibonacci_score(klines_short)
            microstructure_raw = self.calculate_microstructure_score(klines_short)
            seasonality_raw = self.calculate_seasonality_score(symbol)
            
            return {
                'final_score': final_score,
                'volatility': volatility_raw,
                'volume': volume_raw,
                'momentum': momentum_raw,
                'rsi': rsi_raw,
                'correlation': correlation_raw,
                'liquidity': liquidity_raw,
                'technical': technical_raw,
                'market_cap': market_cap_raw,
                'support_resistance': support_resistance_raw,
                'multi_timeframe': multi_timeframe_raw,
                'orderbook': orderbook_raw,
                'price_action': price_action_raw,
                'volume_profile': volume_profile_raw,
                'momentum_div': momentum_div_raw,
                'volatility_cluster': volatility_cluster_raw,
                'fibonacci': fibonacci_raw,
                'microstructure': microstructure_raw,
                'seasonality': seasonality_raw
            }
        except Exception as e:
            return None
    
    def _get_dynamic_min_score(self, available_count, capital=None, market_conditions=None):
        """Seuil minimum adaptatif professionnel - VALEURS PAR DÉFAUT"""
        base_min = self.base_min_score
        
        if capital and capital < 20:
            base_min -= 20
        elif capital and capital < 50:
            base_min -= 15
        
        if market_conditions:
            if market_conditions.get('avg_volatility', 2.0) < 1.5:
                base_min -= 10
            
            if market_conditions.get('avg_volume_ratio', 1.0) < 0.7:
                base_min -= 5
        
        if available_count < 2:
            base_min -= 15
        elif available_count < 4:
            base_min -= 5
        elif available_count > 8:
            base_min += 10
        
        from datetime import datetime
        now = datetime.now()
        if now.weekday() >= 5:
            base_min -= 5
        elif now.hour < 8 or now.hour > 22:
            base_min -= 3
        
        return max(15, min(base_min, 80))
    
    def _detect_volume_decline(self, klines_1m: List, klines_15m: List) -> Optional[Dict]:
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
    
    def _calculate_recovery_prediction(self, symbol: str, volume_decline: Dict, klines_1m: List, current_price: float) -> Dict:
        """Calcule la prédiction de récupération (version fallback)"""
        
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
        from datetime import datetime, timedelta
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