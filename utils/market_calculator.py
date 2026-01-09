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

class MarketCalculator:
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
        """Calcule la volatilité temps réel - Score 1-5 pour scalping"""
        if websocket_manager and websocket_manager.is_connected():
            ws_klines = websocket_manager.get_klines(symbol, 60)
            if len(ws_klines) >= 10:
                klines = ws_klines
        
        try:
            if len(klines) < 10:
                return 2.0
            
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
                avg_change = sum(price_changes) / len(price_changes)
                volatility_hourly = avg_change * 100
            else:
                atr = sum(true_ranges) / len(true_ranges)
                current_price = closes[-1]
                
                if current_price <= 0:
                    avg_change = sum(price_changes) / len(price_changes)
                    volatility_hourly = avg_change * 100
                else:
                    volatility_hourly = (atr / current_price) * 100
            
            # Mapper vers score 1-5
            if volatility_hourly < 0.15:
                return 1.0
            elif volatility_hourly < 0.30:
                return 2.0
            elif volatility_hourly < 0.60:
                return 3.0
            elif volatility_hourly < 1.20:
                return 4.0
            else:
                return 5.0
                
        except Exception:
            return 2.0
    
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
    
    # ===== MÉTHODES EXISTANTES (inchangées) =====
    
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
                return MarketCalculator._calculate_7d_metrics(klines_7d)
            
            klines_24h = bot.get_klines(symbol, 96, '15m')
            if len(klines_24h) >= 50:
                return MarketCalculator._calculate_24h_metrics(klines_24h)
            
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
            'volume_trend': MarketCalculator._get_volume_trend_7d(sma_96, sma_336, sma_672)
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
        
        momentum = MarketCalculator.calculate_momentum(klines)
        
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
            from utils.timeframe_manager import TimeframeManager
            optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
            
            klines_7d = bot.get_klines(symbol, 672, '15m')
            klines_short = bot.get_klines(symbol, 20, optimal_timeframe)
            current_price = bot.get_price(symbol)
            
            if not klines_short or len(klines_short) < 10:
                return 0
            
            websocket_manager = getattr(bot, 'websocket', None)
            volatility_score = self.calculate_volatility_score(klines_short, symbol, volatility, websocket_manager)
            
            if klines_7d and len(klines_7d) >= 672:
                volume_score = self.calculate_volume_score(klines_7d)
                data_quality = 'HIGH_7D'
            elif len(klines_short) >= 96:
                klines_24h = bot.get_klines(symbol, 96, '15m')
                volume_score = self.calculate_volume_score(klines_24h) if klines_24h else self.calculate_volume_score(klines_short)
                data_quality = 'MEDIUM_24H'
            else:
                volume_score = self.calculate_volume_score(klines_short)
                data_quality = 'LIMITED'
            
            momentum_score = self.calculate_momentum_score(klines_short)
            spread_score = self.calculate_spread_score(symbol, current_price)
            history_score = self.calculate_history_score(symbol, stuck_positions)
            
            weights = self._get_dynamic_weights(symbol)
            if data_quality == 'HIGH_7D':
                weights['volume'] *= 1.2
            
            total_score = (
                volatility_score * weights['volatility'] +
                volume_score * weights['volume'] +
                momentum_score * weights['momentum'] +
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
            
            from utils.timeframe_manager import TimeframeManager
            optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
            
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
                breakdown = self.get_score_breakdown(bot, symbol, stuck_positions, websocket_manager=websocket_manager)
                if breakdown:
                    scores.append({
                        'symbol': symbol,
                        'score': score,
                        'volatility': breakdown['volatility'],
                        'volume': breakdown['volume'],
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
    
    def get_score_breakdown(self, bot, symbol, stuck_positions, volatility=None, websocket_manager=None):
        """Détails du score pour debug - Version professionnelle"""
        from utils.timeframe_manager import TimeframeManager
        optimal_timeframe = TimeframeManager.get_main_timeframe(symbol, 'intelligent', bot)
        
        klines_short = bot.get_klines(symbol, 20, optimal_timeframe)
        klines_long = bot.get_klines(symbol, 96, '15m')
        current_price = bot.get_price(symbol)
        
        if not klines_short or len(klines_short) < 10:
            return None
        
        if klines_long and len(klines_long) >= 50:
            volume_score = self.calculate_volume_score(klines_long)
        else:
            volume_score = self.calculate_volume_score(klines_short)
        
        return {
            'volatility': self.calculate_volatility_score(klines_short, symbol, volatility, websocket_manager),
            'volume': volume_score,
            'momentum': self.calculate_momentum_score(klines_short),
            'spread': self.calculate_spread_score(symbol, current_price),
            'history': self.calculate_history_score(symbol, stuck_positions)
        }
    
    def _get_default_weights(self):
        """Pondération par défaut"""
        return {'volatility': 0.25, 'volume': 0.25, 'momentum': 0.25, 'spread': 0.15, 'history': 0.10}
    
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
    
    def _get_dynamic_weights(self, symbol):
        """Pondération adaptative selon crypto"""
        if symbol in ['BTC/USDT', 'ETH/USDT']:
            return {'volatility': 0.20, 'volume': 0.30, 'momentum': 0.25, 'spread': 0.15, 'history': 0.10}
        else:
            return {'volatility': 0.35, 'volume': 0.20, 'momentum': 0.30, 'spread': 0.10, 'history': 0.05}
    
    def _get_dynamic_min_score(self, available_count, capital=None, market_conditions=None):
        """Seuil minimum adaptatif professionnel - VALEURS PAR DÉFAUT"""
        base_min = self.base_min_score
        
        if capital and capital < 20:
            base_min -= 15
        elif capital and capital < 50:
            base_min -= 10
        
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