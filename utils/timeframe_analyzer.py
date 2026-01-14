import numpy as np
from collections import deque
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TimeframeAnalyzer:
    def __init__(self):
        self.cache = {}
        self.data_cache = {}  # Cache des données par timeframe
        self.signal_history = deque(maxlen=10)
    
    def get_main_timeframe(self, symbol, volatility=2.5):
        """Timeframe principal adaptatif pour le trading"""
        if volatility >= 4.0:
            return '5m'
        elif volatility >= 2.5:
            return '15m'
        else:
            return '1h'
    
    def get_ema_periods(self, symbol, timeframe, bot=None, volatility=2.5):
        """Périodes EMA adaptatives selon timeframe et volatilité"""
        
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
    
    def get_confidence_threshold(self, symbol, volatility=2.5, bot=None, balance=None):
        """Seuil de confiance adaptatif - LOGIQUE PROFESSIONNELLE"""
        
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

    # ========== MÉTHODES EXISTANTES ==========
        
    def get_klines_for_timeframe(self, bot, symbol, timeframe, limit=50):
        """Récupère les données kline pour un timeframe spécifique"""
        cache_key = f"{symbol}_{timeframe}"
        
        try:
            # En réalité, on utiliserait bot.exchange.fetch_ohlcv avec le timeframe
            # Pour la simulation, on adapte les données 1m
            base_klines = bot.get_klines(symbol, limit * self.get_timeframe_multiplier(timeframe), timeframe)
            
            if not base_klines:
                return []
            
            # Convertir les données selon le timeframe
            converted_klines = self.convert_to_timeframe(base_klines, timeframe)
            
            self.data_cache[cache_key] = converted_klines
            return converted_klines
            
        except Exception as e:
            print(f"Erreur récupération données {timeframe}: {e}")
            return self.data_cache.get(cache_key, [])
    
    def get_timeframe_multiplier(self, timeframe):
        """Retourne le multiplicateur pour le timeframe"""
        multipliers = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240}
        return multipliers.get(timeframe, 1)
    
    def get_adaptive_timeframes(self, volatility):
        """Sélectionne les timeframes optimaux selon la volatilité - SEUILS AJUSTÉS 15m"""
        if volatility >= 3.0:  # Réduit de 4.0 → 3.0
            # Haute volatilité: timeframes courts pour réactivité
            return ['15m', '5m', '1m'], {'15m': 5, '5m': 3, '1m': 2}
        elif volatility >= 1.8:  # Réduit de 2.5 → 1.8
            # Volatilité moyenne: équilibre standard
            return ['1h', '15m', '5m'], {'1h': 5, '15m': 3, '5m': 2}
        else:
            # Faible volatilité: timeframes longs pour filtrer bruit
            return ['4h', '1h', '15m'], {'4h': 5, '1h': 3, '15m': 2}
    
    def convert_to_timeframe(self, klines_1m, target_timeframe):
        """Convertit les données 1m vers le timeframe cible"""
        if target_timeframe == '1m':
            return klines_1m
        
        multiplier = self.get_timeframe_multiplier(target_timeframe)
        converted = []
        
        for i in range(0, len(klines_1m), multiplier):
            chunk = klines_1m[i:i+multiplier]
            if len(chunk) == multiplier:
                # Créer une bougie agrégée
                aggregated = {
                    'timestamp': chunk[0]['timestamp'],
                    'open': chunk[0]['open'],
                    'high': max(k['high'] for k in chunk),
                    'low': min(k['low'] for k in chunk),
                    'close': chunk[-1]['close'],
                    'volume': sum(k['volume'] for k in chunk)
                }
                converted.append(aggregated)
        
        return converted
    
    def analyze_timeframe(self, klines, current_price):
        """Analyse un timeframe spécifique avec 20 facteurs professionnels"""
        if len(klines) < 50:
            return {'trend': 'unknown', 'strength': 0, 'signals': [], 'confidence': 0}
        
        closes = [k['close'] for k in klines]
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        volumes = [k['volume'] for k in klines]
        
        # ===== CALCUL DES 20 FACTEURS PROFESSIONNELS =====
        
        # 1-5: FACTEURS AMÉLIORÉS (existants)
        rsi_multi = self.calculate_rsi_multi_period(closes)
        macd_advanced = self.calculate_macd_advanced(closes)
        bollinger_advanced = self.calculate_bollinger_advanced(closes, current_price)
        ema_ribbon = self.calculate_ema_ribbon(closes, current_price)
        volume_profile = self.calculate_volume_profile_advanced(klines)
        
        # 6-10: MOMENTUM AVANCÉ
        stochastic = self.calculate_stochastic(highs, lows, closes)
        williams_r = self.calculate_williams_r(highs, lows, closes)
        roc = self.calculate_roc(closes)
        cci = self.calculate_cci(klines)
        elder_ray = self.calculate_elder_ray(klines)
        
        # 11-15: TREND & SUPPORT/RESISTANCE
        ichimoku = self.calculate_ichimoku(klines)
        parabolic_sar = self.calculate_parabolic_sar(klines, current_price)
        fibonacci = self.calculate_fibonacci_levels(klines, current_price)
        pivot_points = self.calculate_pivot_points(klines, current_price)
        aroon = self.calculate_aroon(highs, lows)
        
        # 16-20: VOLUME & FLOW
        mfi = self.calculate_mfi(klines)
        obv = self.calculate_obv(closes, volumes)
        ad_line = self.calculate_ad_line(klines)
        cmf = self.calculate_cmf(klines)
        atr_signals = self.calculate_atr_signals(klines)
        
        # ===== PONDÉRATION PROFESSIONNELLE =====
        weights = {
            # Momentum (35%)
            'rsi_multi': 0.08, 'macd_advanced': 0.08, 'stochastic': 0.06,
            'williams_r': 0.05, 'roc': 0.04, 'elder_ray': 0.04,
            
            # Trend (25%)
            'ema_ribbon': 0.07, 'ichimoku': 0.06, 'parabolic_sar': 0.06,
            'aroon': 0.06,
            
            # Volume (20%)
            'volume_profile': 0.06, 'mfi': 0.05, 'obv': 0.05, 'ad_line': 0.04,
            
            # Support/Resistance (15%)
            'fibonacci': 0.05, 'pivot_points': 0.05, 'bollinger_advanced': 0.05,
            
            # Volatility/Other (5%)
            'atr_signals': 0.03, 'cci': 0.02, 'cmf': 0.02
        }
        
        # ===== CALCUL SCORE PONDÉRÉ =====
        factors = {
            'rsi_multi': rsi_multi, 'macd_advanced': macd_advanced,
            'bollinger_advanced': bollinger_advanced, 'ema_ribbon': ema_ribbon,
            'volume_profile': volume_profile, 'stochastic': stochastic,
            'williams_r': williams_r, 'roc': roc, 'cci': cci,
            'elder_ray': elder_ray, 'ichimoku': ichimoku,
            'parabolic_sar': parabolic_sar, 'fibonacci': fibonacci,
            'pivot_points': pivot_points, 'aroon': aroon, 'mfi': mfi,
            'obv': obv, 'ad_line': ad_line, 'cmf': cmf, 'atr_signals': atr_signals
        }
        
        total_strength = 0
        active_signals = []
        
        for factor_name, factor_data in factors.items():
            if factor_data and 'strength' in factor_data:
                weight = weights.get(factor_name, 0.01)
                strength = factor_data['strength']
                total_strength += strength * weight
                
                if abs(strength) > 0.5:  # Signal significatif
                    signal_type = factor_data.get('signal', 'neutral')
                    if signal_type != 'neutral':
                        active_signals.append(f"{factor_name}: {signal_type}")
        
        # ===== DÉTERMINATION TENDANCE =====
        trend = 'bullish' if total_strength > 0.3 else 'bearish' if total_strength < -0.3 else 'neutral'
        
        # ===== CALCUL CONFIANCE =====
        signal_count = len(active_signals)
        signal_consistency = self._calculate_signal_consistency(factors)
        
        confidence = min(95, max(10, 
            (abs(total_strength) * 40) + 
            (signal_count * 5) + 
            (signal_consistency * 30)
        ))
        
        return {
            'trend': trend,
            'strength': total_strength,
            'signals': active_signals[:8],  # Top 8 signaux
            'confidence': round(confidence, 1),
            'factors': factors,
            'signal_count': signal_count,
            'consistency': signal_consistency
        }
    
    def determine_trend(self, closes, ema_20, ema_50):
        """Détermine la tendance générale"""
        if not ema_20 or not ema_50:
            return 'unknown'
        
        current_price = closes[-1]
        
        # Tendance basée sur les EMAs et le prix
        if ema_20 > ema_50 and current_price > ema_20:
            return 'bullish'
        elif ema_20 < ema_50 and current_price < ema_20:
            return 'bearish'
        else:
            return 'neutral'
    
    def get_bb_position(self, price, upper, middle, lower):
        """Position du prix par rapport aux Bollinger Bands"""
        if not all([upper, middle, lower]):
            return 'unknown'
        
        if price >= upper:
            return 'above_upper'
        elif price <= lower:
            return 'below_lower'
        elif price > middle:
            return 'above_middle'
        else:
            return 'below_middle'
    
    def calculate_volatility(self, bot, symbol):
        """Calcule la volatilité réelle - MÉTHODE CENTRALISÉE avec WebSocket"""
        try:
            # Import local pour éviter circularité
            from utils.market_analyzer import MarketAnalyzer
            
            # Utiliser WebSocket si disponible
            if hasattr(bot, 'websocket') and bot.websocket.is_connected():
                return MarketAnalyzer.calculate_volatility_from_websocket(bot.websocket, symbol)
            
            # Fallback API REST
            klines = bot.get_klines(symbol, 60, os.getenv('MAIN_TIMEFRAME', '15m'))
            return MarketAnalyzer.calculate_volatility(klines, symbol)
        except Exception as e:
            return 2.0
    
    def get_crypto_profile(self, symbol, volatility):
        """Retourne le profil adaptatif selon crypto et volatilité"""
        # Import local pour éviter circularité
        from utils.market_analyzer import MarketAnalyzer
        return MarketAnalyzer.get_crypto_profile(volatility)
    
    def analyze_all_timeframes(self, bot, symbol, current_price):
        """Analyse tous les timeframes et génère un signal global"""
        # Calculer volatilité d'abord pour adapter les timeframes
        volatility = self.calculate_volatility(bot, symbol)
        
        # Sélectionner timeframes adaptatifs selon volatilité (TOUJOURS actif)
        active_timeframes, weights = self.get_adaptive_timeframes(volatility)
        
        timeframe_analysis = {}
        for tf in active_timeframes:
            klines = self.get_klines_for_timeframe(bot, symbol, tf, 50)
            analysis = self.analyze_timeframe(klines, current_price)
            timeframe_analysis[tf] = analysis
        
        global_signal = self.generate_global_signal(timeframe_analysis, current_price, symbol, volatility, weights)
        
        return {
            'timeframes': timeframe_analysis,
            'global_signal': global_signal,
            'volatility': volatility,
            'active_timeframes': active_timeframes,
            'timestamp': bot.exchange.milliseconds() if hasattr(bot, 'exchange') else None
        }
    
    def generate_global_signal(self, timeframe_analysis, current_price, symbol='', volatility=2.0, weights=None):
        """Génère un signal global basé sur tous les timeframes"""
        if weights is None:
            weights = {'15m': 3, '5m': 2, '1m': 1}
        
        total_strength = 0
        max_weight = 0
        trend_votes = {'bullish': 0, 'bearish': 0, 'neutral': 0, 'unknown': 0}
        all_signals = []
        
        for tf, analysis in timeframe_analysis.items():
            weight = weights.get(tf, 1)
            strength = analysis['strength']
            trend = analysis['trend']
            
            total_strength += strength * weight
            max_weight += weight
            trend_votes[trend] += weight
            
            for signal in analysis['signals']:
                all_signals.append(f"{tf}: {signal}")
        
        avg_strength = total_strength / max_weight if max_weight > 0 else 0
        dominant_trend = max(trend_votes, key=trend_votes.get)
        # Convertir 'unknown' en 'neutral'
        if dominant_trend == 'unknown':
            dominant_trend = 'neutral'
        action = self.determine_action(avg_strength, dominant_trend, timeframe_analysis)
        base_confidence = self.calculate_confidence(timeframe_analysis, avg_strength)
        
        profile = self.get_crypto_profile(symbol, volatility)
        adjusted_confidence = base_confidence + profile['confidence_adjustment']
        adjusted_confidence = max(0, min(100, adjusted_confidence))
        
        return {
            'action': action,
            'strength': avg_strength,
            'confidence': round(adjusted_confidence, 1),
            'base_confidence': base_confidence,
            'dominant_trend': dominant_trend,
            'signals': all_signals[:5],
            'volatility': volatility,
            'profile': profile,
            'summary': self.generate_summary(action, avg_strength, dominant_trend, adjusted_confidence, volatility)
        }
    
    def determine_action(self, avg_strength, dominant_trend, timeframe_analysis):
        """Détermine l'action recommandée - SIMPLIFIÉ"""
        strong_buy_threshold = 1.5
        buy_threshold = 0.3
        sell_threshold = -0.3
        strong_sell_threshold = -1.5
        
        trends = [analysis['trend'] for analysis in timeframe_analysis.values()]
        trend_consistency = trends.count(dominant_trend) / len(trends)
        adjusted_strength = avg_strength * trend_consistency
        
        # Logique simplifiée: strength détermine l'action
        if adjusted_strength >= strong_buy_threshold:
            return 'STRONG_BUY'
        elif adjusted_strength >= buy_threshold:
            return 'BUY'
        elif adjusted_strength <= strong_sell_threshold:
            return 'STRONG_SELL'
        elif adjusted_strength <= sell_threshold:
            return 'SELL'
        else:
            return 'HOLD'
    
    def calculate_confidence(self, timeframe_analysis, avg_strength):
        """Calcule le score de confiance (0-100) - VERSION RÉALISTE"""
        strength_factor = min(abs(avg_strength) / 2.0, 1.0)
        
        trends = [analysis['trend'] for analysis in timeframe_analysis.values()]
        dominant_trend = max(set(trends), key=trends.count)
        consistency_factor = trends.count(dominant_trend) / len(trends)
        
        total_signals = sum(len(analysis['signals']) for analysis in timeframe_analysis.values())
        signal_factor = min(total_signals / 6.0, 1.0)
        
        confidence = (
            strength_factor * 0.40 + 
            consistency_factor * 0.30 + 
            signal_factor * 0.30
        ) * 100
        
        if abs(avg_strength) >= 2.5:
            confidence = min(confidence * 1.1, 100)
        
        return round(confidence, 1)
    
    def generate_summary(self, action, strength, trend, confidence, volatility=2.0):
        """Génère un résumé textuel de l'analyse"""
        strength_desc = "forte" if abs(strength) > 2 else "modérée" if abs(strength) > 1 else "faible"
        trend_desc = {"bullish": "haussière", "bearish": "baissière", "neutral": "neutre", "unknown": "indéterminée"}.get(trend, "neutre")
        
        return f"{action} - Tendance {trend_desc}, force {strength_desc} (conf: {confidence}%, vol: {volatility:.1f}/5)"
    
    def check_volume_confirmation(self, volumes):
        """Vérifie si le volume confirme le signal"""
        if len(volumes) < 10:
            return False
        
        current_volume = volumes[-1]
        avg_volume = sum(volumes[-10:]) / 10
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        return volume_ratio >= float(os.getenv('MIN_VOLUME_RATIO', '1.2'))
    
    def calculate_adx(self, klines, period=14):
        """Calcule l'ADX pour détecter les marchés tendanciels"""
        if len(klines) < period + 1:
            return None
        
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        closes = [k['close'] for k in klines]
        
        dm_plus = []
        dm_minus = []
        tr_values = []
        
        for i in range(1, len(klines)):
            high_diff = highs[i] - highs[i-1]
            low_diff = lows[i-1] - lows[i]
            
            dm_plus.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
            dm_minus.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
            
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_values.append(tr)
        
        if len(tr_values) < period:
            return None
        
        avg_dm_plus = sum(dm_plus[-period:]) / period
        avg_dm_minus = sum(dm_minus[-period:]) / period
        avg_tr = sum(tr_values[-period:]) / period
        
        if avg_tr == 0:
            return 0
        
        di_plus = (avg_dm_plus / avg_tr) * 100
        di_minus = (avg_dm_minus / avg_tr) * 100
        
        dx = abs(di_plus - di_minus) / (di_plus + di_minus) * 100 if (di_plus + di_minus) > 0 else 0
        return dx
    
    def is_trending_market(self, klines):
        """Détermine si le marché est tendanciel (ADX > 25)"""
        adx = self.calculate_adx(klines)
        if adx is None:
            return True
        
        threshold = float(os.getenv('ADX_TRENDING_THRESHOLD', '25'))
        return adx > threshold
    
    def get_btc_correlation_filter(self, bot, symbol):
        """Filtre basé sur la corrélation avec BTC"""
        if symbol == 'BTC/USDT' or not os.getenv('BTC_CORRELATION_FILTER', 'False') == 'True':
            return True
        
        try:
            btc_klines = bot.get_klines('BTC/USDT', 20, os.getenv('MAIN_TIMEFRAME', '15m'))
            symbol_klines = bot.get_klines(symbol, 20, os.getenv('MAIN_TIMEFRAME', '15m'))
            
            if len(btc_klines) < 10 or len(symbol_klines) < 10:
                return True
            
            btc_momentum = (btc_klines[-1]['close'] - btc_klines[-5]['close']) / btc_klines[-5]['close']
            
            # Si BTC baisse fortement (-2%+), éviter les achats altcoins
            if btc_momentum < -0.02:
                return False
            
            return True
        except:
            return True
    
    def detect_reversal_signals(self, klines, current_price):
        """Détecte les signaux de retournement imminent"""
        if len(klines) < 20:
            return {'has_reversal_risk': False, 'risk_factors': []}
        
        risk_factors = []
        
        # 1. Divergence RSI/Prix
        if self.check_rsi_divergence(klines):
            risk_factors.append('RSI_DIVERGENCE')
        
        # 2. Volume décroissant sur mouvement
        if self.check_volume_weakness(klines):
            risk_factors.append('WEAK_VOLUME')
        
        # 3. Approche niveau clé
        if self.check_key_levels(current_price, klines):
            risk_factors.append('NEAR_KEY_LEVEL')
        
        # 4. Momentum décroissant
        if self.check_momentum_weakness(klines):
            risk_factors.append('WEAK_MOMENTUM')
        
        has_risk = len(risk_factors) >= 2  # Au moins 2 facteurs de risque
        
        return {
            'has_reversal_risk': has_risk,
            'risk_factors': risk_factors,
            'risk_count': len(risk_factors)
        }
    
    def check_rsi_divergence(self, klines):
        """Détecte divergence entre RSI et prix"""
        if len(klines) < 14:
            return False
        
        closes = [k['close'] for k in klines]
        rsi_values = []
        
        # Calculer RSI pour les 10 dernières périodes
        for i in range(14, len(closes)):
            rsi = self.calculate_rsi(closes[:i+1])
            if rsi:
                rsi_values.append(rsi)
        
        if len(rsi_values) < 5:
            return False
        
        # Comparer tendances prix vs RSI sur 5 périodes
        price_trend = closes[-1] > closes[-5]
        rsi_trend = rsi_values[-1] > rsi_values[-5]
        
        # Divergence = tendances opposées
        return price_trend != rsi_trend
    
    def check_volume_weakness(self, klines):
        """Détecte volume décroissant sur mouvement"""
        if len(klines) < 10:
            return False
        
        volumes = [k['volume'] for k in klines]
        closes = [k['close'] for k in klines]
        
        # Volume moyen récent vs historique
        recent_volume = sum(volumes[-3:]) / 3
        avg_volume = sum(volumes[-10:]) / 10
        
        # Prix en mouvement mais volume faible
        price_movement = abs(closes[-1] - closes[-3]) / closes[-3]
        volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1
        
        return price_movement > 0.01 and volume_ratio < 0.8
    
    def check_key_levels(self, current_price, klines):
        """Vérifie proximité niveaux support/résistance"""
        if len(klines) < 20:
            return False
        
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        
        # Résistances récentes (3 plus hauts)
        recent_highs = sorted(highs[-20:], reverse=True)[:3]
        # Supports récents (3 plus bas)
        recent_lows = sorted(lows[-20:])[:3]
        
        # Vérifier proximité (1% de distance)
        threshold = current_price * 0.01
        
        for level in recent_highs + recent_lows:
            if abs(current_price - level) < threshold:
                return True
        
        return False
    
    def check_momentum_weakness(self, klines):
        """Détecte affaiblissement du momentum"""
        if len(klines) < 10:
            return False
        
        closes = [k['close'] for k in klines]
        
        # Momentum récent vs précédent
        recent_momentum = (closes[-1] - closes[-3]) / closes[-3]
        previous_momentum = (closes[-3] - closes[-6]) / closes[-6]
        
        # Momentum s'affaiblit si récent < 50% du précédent
        if abs(previous_momentum) > 0.005:  # Éviter division par zéro
            momentum_ratio = abs(recent_momentum) / abs(previous_momentum)
            return momentum_ratio < 0.5
    
    def calculate_rsi(self, prices, period=14):
        """Calcule le RSI (Relative Strength Index)"""
        if len(prices) < period + 1:
            return None
            
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        """Calcule le MACD"""
        if len(prices) < slow:
            return None, None, None
            
        prices = np.array(prices)
        
        # EMA rapide et lente
        ema_fast = self.calculate_ema(prices, fast)
        ema_slow = self.calculate_ema(prices, slow)
        
        if ema_fast is None or ema_slow is None:
            return None, None, None
            
        # Ligne MACD
        macd_line = ema_fast - ema_slow
        
        # Signal line (EMA du MACD)
        signal_line = self.calculate_ema([macd_line], signal)
        
        # Histogramme
        histogram = macd_line - (signal_line or 0)
        
        return macd_line, signal_line, histogram
    
    def calculate_ema(self, prices, period):
        """Calcule l'EMA (Exponential Moving Average)"""
        if len(prices) < period:
            return None
            
        prices = np.array(prices)
        multiplier = 2 / (period + 1)
        
        # Première valeur = SMA
        ema = np.mean(prices[:period])
        
        # Calcul EMA pour le reste
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
            
        return ema
    
    def calculate_bollinger_bands(self, prices, period=20, std_dev=2):
        """Calcule les Bollinger Bands"""
        if len(prices) < period:
            return None, None, None
            
        prices = np.array(prices)
        
        # Moyenne mobile simple
        sma = np.mean(prices[-period:])
        
        # Écart-type
        std = np.std(prices[-period:])
        
        # Bandes
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return upper_band, sma, lower_band
    
    def calculate_volume_profile(self, klines):
        """Analyse le profil de volume"""
        if len(klines) < 10:
            return {'trend': 'neutral', 'strength': 0}
            
        volumes = [k['volume'] for k in klines[-10:]]
        avg_volume = np.mean(volumes)
        current_volume = volumes[-1]
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        if volume_ratio > 1.5:
            return {'trend': 'strong', 'strength': min(volume_ratio, 3)}
        elif volume_ratio > 1.2:
            return {'trend': 'moderate', 'strength': volume_ratio}
        else:
            return {'trend': 'weak', 'strength': volume_ratio}
    
    def analyze_signals(self, symbol, klines, current_price):
        """Génère des signaux de trading basés sur les indicateurs"""
        if len(klines) < 30:
            return {'action': 'HOLD', 'strength': 0, 'reason': 'Données insuffisantes'}
        
        # Extraire les prix de clôture
        closes = [k['close'] for k in klines]
        
        # Calculer les indicateurs
        rsi = self.calculate_rsi(closes)
        macd, signal, histogram = self.calculate_macd(closes)
        upper_bb, middle_bb, lower_bb = self.calculate_bollinger_bands(closes)
        volume_profile = self.calculate_volume_profile(klines)
        
        signals = []
        strength = 0
        
        # Signal RSI
        if rsi is not None:
            if rsi < 30:  # Survente
                signals.append("RSI survente")
                strength += 2
            elif rsi > 70:  # Surachat
                signals.append("RSI surachat")
                strength -= 2
        
        # Signal MACD
        if macd is not None and signal is not None:
            if macd > signal and histogram > 0:  # Croisement haussier
                signals.append("MACD haussier")
                strength += 1.5
            elif macd < signal and histogram < 0:  # Croisement baissier
                signals.append("MACD baissier")
                strength -= 1.5
        
        # Signal Bollinger Bands
        if lower_bb is not None and upper_bb is not None:
            if current_price <= lower_bb:  # Prix touche bande basse
                signals.append("BB support")
                strength += 1
            elif current_price >= upper_bb:  # Prix touche bande haute
                signals.append("BB résistance")
                strength -= 1
        
        # Signal Volume
        if volume_profile['trend'] == 'strong':
            if strength > 0:  # Renforce signal haussier
                signals.append("Volume fort")
                strength *= 1.3
            elif strength < 0:  # Renforce signal baissier
                signals.append("Volume fort")
                strength *= 1.3
        
        # Déterminer l'action
        if strength >= 2:
            action = 'BUY'
        elif strength <= -2:
            action = 'SELL'
        else:
            action = 'HOLD'
        
        signal_data = {
            'action': action,
            'strength': abs(strength),
            'reason': ' + '.join(signals) if signals else 'Aucun signal fort',
            'indicators': {
                'rsi': rsi,
                'macd': macd,
                'bb_position': self._get_bb_position(current_price, upper_bb, middle_bb, lower_bb),
                'volume': volume_profile
            }
        }
        
        # Ajouter à l'historique
        self.signal_history.append({
            'timestamp': klines[-1]['timestamp'],
            'symbol': symbol,
            'signal': signal_data
        })
        
        return signal_data
    
    def _get_bb_position(self, price, upper, middle, lower):
        """Détermine la position du prix par rapport aux Bollinger Bands"""
        if upper is None or lower is None:
            return 'unknown'
            
        if price >= upper:
            return 'above_upper'
        elif price <= lower:
            return 'below_lower'
        elif price > middle:
            return 'above_middle'
        else:
            return 'below_middle'
    
    def get_signal_summary(self, symbol):
        """Résumé des derniers signaux"""
        recent_signals = [s for s in self.signal_history if s['symbol'] == symbol]
        if not recent_signals:
            return "Aucun signal récent"
            
        last_signal = recent_signals[-1]['signal']
        return f"{last_signal['action']} ({last_signal['strength']:.1f}) - {last_signal['reason']}"
    # ===== 20 FACTEURS PROFESSIONNELS - IMPLÉMENTATION =====
    
    def calculate_rsi_multi_period(self, closes):
        """RSI multi-période avec divergences"""
        try:
            rsi_14 = self.calculate_rsi(closes, 14)
            rsi_21 = self.calculate_rsi(closes, 21)
            
            if rsi_14 is None or rsi_21 is None:
                return {'strength': 0, 'signal': 'neutral'}
            
            # Analyse multi-période
            if rsi_14 < 30 and rsi_21 < 35:
                return {'strength': 2.0, 'signal': 'oversold_strong'}
            elif rsi_14 > 70 and rsi_21 > 65:
                return {'strength': -2.0, 'signal': 'overbought_strong'}
            elif rsi_14 < 40:
                return {'strength': 1.0, 'signal': 'oversold'}
            elif rsi_14 > 60:
                return {'strength': -1.0, 'signal': 'overbought'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_macd_advanced(self, closes):
        """MACD avancé avec histogram et divergences"""
        try:
            macd, signal, histogram = self.calculate_macd(closes)
            
            if macd is None or signal is None:
                return {'strength': 0, 'signal': 'neutral'}
            
            # Analyse avancée
            if macd > signal and histogram > 0:
                strength = min(2.0, abs(histogram) * 10)
                return {'strength': strength, 'signal': 'bullish_crossover'}
            elif macd < signal and histogram < 0:
                strength = min(2.0, abs(histogram) * 10)
                return {'strength': -strength, 'signal': 'bearish_crossover'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_bollinger_advanced(self, closes, current_price):
        """Bollinger Bands avancé avec %B et squeeze"""
        try:
            upper, middle, lower = self.calculate_bollinger_bands(closes)
            
            if upper is None or lower is None:
                return {'strength': 0, 'signal': 'neutral'}
            
            # %B calculation
            bb_width = upper - lower
            percent_b = (current_price - lower) / bb_width if bb_width > 0 else 0.5
            
            # BB Squeeze detection
            bb_squeeze = bb_width < (middle * 0.02)  # 2% squeeze
            
            if percent_b < 0.1:  # Near lower band
                strength = 1.5 if bb_squeeze else 1.0
                return {'strength': strength, 'signal': 'bb_support'}
            elif percent_b > 0.9:  # Near upper band
                strength = 1.5 if bb_squeeze else 1.0
                return {'strength': -strength, 'signal': 'bb_resistance'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_ema_ribbon(self, closes, current_price):
        """EMA Ribbon avec cloud analysis"""
        try:
            ema_7 = self.calculate_ema(closes, 7)
            ema_25 = self.calculate_ema(closes, 25)
            ema_99 = self.calculate_ema(closes, 99)
            
            if not all([ema_7, ema_25, ema_99]):
                return {'strength': 0, 'signal': 'neutral'}
            
            # Cloud analysis
            if ema_7 > ema_25 > ema_99 and current_price > ema_7:
                return {'strength': 2.0, 'signal': 'strong_uptrend'}
            elif ema_7 < ema_25 < ema_99 and current_price < ema_7:
                return {'strength': -2.0, 'signal': 'strong_downtrend'}
            elif ema_7 > ema_25:
                return {'strength': 1.0, 'signal': 'uptrend'}
            elif ema_7 < ema_25:
                return {'strength': -1.0, 'signal': 'downtrend'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_volume_profile_advanced(self, klines):
        """Volume Profile avec VWAP"""
        try:
            if len(klines) < 20:
                return {'strength': 0, 'signal': 'neutral'}
            
            # VWAP calculation
            total_pv = sum(k['close'] * k['volume'] for k in klines[-20:])
            total_volume = sum(k['volume'] for k in klines[-20:])
            vwap = total_pv / total_volume if total_volume > 0 else 0
            
            current_price = klines[-1]['close']
            current_volume = klines[-1]['volume']
            avg_volume = sum(k['volume'] for k in klines[-10:]) / 10
            
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            price_vs_vwap = (current_price - vwap) / vwap if vwap > 0 else 0
            
            if volume_ratio > 1.5 and price_vs_vwap > 0.01:
                return {'strength': 1.5, 'signal': 'volume_breakout_up'}
            elif volume_ratio > 1.5 and price_vs_vwap < -0.01:
                return {'strength': -1.5, 'signal': 'volume_breakout_down'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_stochastic(self, highs, lows, closes, k_period=14, d_period=3):
        """Stochastic Oscillator"""
        try:
            if len(closes) < k_period:
                return {'strength': 0, 'signal': 'neutral'}
            
            # %K calculation
            lowest_low = min(lows[-k_period:])
            highest_high = max(highs[-k_period:])
            current_close = closes[-1]
            
            if highest_high == lowest_low:
                return {'strength': 0, 'signal': 'neutral'}
            
            k_percent = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100
            
            if k_percent < 20:
                return {'strength': 1.5, 'signal': 'stoch_oversold'}
            elif k_percent > 80:
                return {'strength': -1.5, 'signal': 'stoch_overbought'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_williams_r(self, highs, lows, closes, period=14):
        """Williams %R"""
        try:
            if len(closes) < period:
                return {'strength': 0, 'signal': 'neutral'}
            
            highest_high = max(highs[-period:])
            lowest_low = min(lows[-period:])
            current_close = closes[-1]
            
            if highest_high == lowest_low:
                return {'strength': 0, 'signal': 'neutral'}
            
            williams_r = ((highest_high - current_close) / (highest_high - lowest_low)) * -100
            
            if williams_r < -80:
                return {'strength': 1.5, 'signal': 'wr_oversold'}
            elif williams_r > -20:
                return {'strength': -1.5, 'signal': 'wr_overbought'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_roc(self, closes, period=12):
        """Rate of Change"""
        try:
            if len(closes) < period + 1:
                return {'strength': 0, 'signal': 'neutral'}
            
            current_price = closes[-1]
            past_price = closes[-(period + 1)]
            
            if past_price == 0:
                return {'strength': 0, 'signal': 'neutral'}
            
            roc = ((current_price - past_price) / past_price) * 100
            
            if roc > 5:
                return {'strength': min(2.0, roc / 5), 'signal': 'strong_momentum_up'}
            elif roc < -5:
                return {'strength': max(-2.0, roc / 5), 'signal': 'strong_momentum_down'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_cci(self, klines, period=20):
        """Commodity Channel Index"""
        try:
            if len(klines) < period:
                return {'strength': 0, 'signal': 'neutral'}
            
            # Typical Price
            typical_prices = [(k['high'] + k['low'] + k['close']) / 3 for k in klines[-period:]]
            sma_tp = sum(typical_prices) / len(typical_prices)
            
            # Mean Deviation
            mean_deviation = sum(abs(tp - sma_tp) for tp in typical_prices) / len(typical_prices)
            
            if mean_deviation == 0:
                return {'strength': 0, 'signal': 'neutral'}
            
            current_tp = (klines[-1]['high'] + klines[-1]['low'] + klines[-1]['close']) / 3
            cci = (current_tp - sma_tp) / (0.015 * mean_deviation)
            
            if cci > 100:
                return {'strength': min(2.0, cci / 100), 'signal': 'cci_overbought'}
            elif cci < -100:
                return {'strength': max(-2.0, cci / 100), 'signal': 'cci_oversold'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_elder_ray(self, klines):
        """Elder Ray Index (Bull/Bear Power)"""
        try:
            if len(klines) < 13:
                return {'strength': 0, 'signal': 'neutral'}
            
            closes = [k['close'] for k in klines]
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]
            
            ema_13 = self.calculate_ema(closes, 13)
            if ema_13 is None:
                return {'strength': 0, 'signal': 'neutral'}
            
            bull_power = highs[-1] - ema_13
            bear_power = lows[-1] - ema_13
            
            bull_strength = bull_power / ema_13 * 100 if ema_13 > 0 else 0
            bear_strength = bear_power / ema_13 * 100 if ema_13 > 0 else 0
            
            if bull_power > 0 and bear_power > 0:
                return {'strength': 1.5, 'signal': 'bulls_control'}
            elif bull_power < 0 and bear_power < 0:
                return {'strength': -1.5, 'signal': 'bears_control'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_ichimoku(self, klines):
        """Ichimoku Cloud"""
        try:
            if len(klines) < 52:
                return {'strength': 0, 'signal': 'neutral'}
            
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]
            closes = [k['close'] for k in klines]
            
            # Tenkan-sen (9 periods)
            tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
            
            # Kijun-sen (26 periods)
            kijun = (max(highs[-26:]) + min(lows[-26:])) / 2
            
            current_price = closes[-1]
            
            if current_price > tenkan > kijun:
                return {'strength': 2.0, 'signal': 'ichimoku_bullish'}
            elif current_price < tenkan < kijun:
                return {'strength': -2.0, 'signal': 'ichimoku_bearish'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_parabolic_sar(self, klines, current_price):
        """Parabolic SAR"""
        try:
            if len(klines) < 10:
                return {'strength': 0, 'signal': 'neutral'}
            
            # Simplified SAR calculation
            highs = [k['high'] for k in klines[-10:]]
            lows = [k['low'] for k in klines[-10:]]
            
            recent_high = max(highs)
            recent_low = min(lows)
            
            # Determine trend
            if current_price > (recent_high + recent_low) / 2:
                sar_level = recent_low * 0.98  # 2% below recent low
                if current_price > sar_level:
                    return {'strength': 1.0, 'signal': 'sar_uptrend'}
            else:
                sar_level = recent_high * 1.02  # 2% above recent high
                if current_price < sar_level:
                    return {'strength': -1.0, 'signal': 'sar_downtrend'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_fibonacci_levels(self, klines, current_price):
        """Fibonacci Retracements"""
        try:
            if len(klines) < 20:
                return {'strength': 0, 'signal': 'neutral'}
            
            highs = [k['high'] for k in klines[-20:]]
            lows = [k['low'] for k in klines[-20:]]
            
            swing_high = max(highs)
            swing_low = min(lows)
            
            # Fibonacci levels
            fib_236 = swing_high - (swing_high - swing_low) * 0.236
            fib_382 = swing_high - (swing_high - swing_low) * 0.382
            fib_618 = swing_high - (swing_high - swing_low) * 0.618
            
            # Check proximity to Fib levels
            for level, name in [(fib_236, 'fib_236'), (fib_382, 'fib_382'), (fib_618, 'fib_618')]:
                distance = abs(current_price - level) / current_price
                if distance < 0.01:  # Within 1%
                    return {'strength': 1.0, 'signal': f'near_{name}'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_pivot_points(self, klines, current_price):
        """Pivot Points"""
        try:
            if len(klines) < 2:
                return {'strength': 0, 'signal': 'neutral'}
            
            # Previous day data
            prev_high = klines[-2]['high']
            prev_low = klines[-2]['low']
            prev_close = klines[-2]['close']
            
            # Pivot Point
            pivot = (prev_high + prev_low + prev_close) / 3
            
            # Support and Resistance
            r1 = 2 * pivot - prev_low
            s1 = 2 * pivot - prev_high
            
            # Check proximity
            for level, name in [(pivot, 'pivot'), (r1, 'r1'), (s1, 's1')]:
                distance = abs(current_price - level) / current_price
                if distance < 0.005:  # Within 0.5%
                    return {'strength': 1.5, 'signal': f'near_{name}'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_aroon(self, highs, lows, period=25):
        """Aroon Indicator"""
        try:
            if len(highs) < period or len(lows) < period:
                return {'strength': 0, 'signal': 'neutral'}
            
            # Find periods since highest high and lowest low
            high_period = 0
            low_period = 0
            
            recent_highs = highs[-period:]
            recent_lows = lows[-period:]
            
            max_high = max(recent_highs)
            min_low = min(recent_lows)
            
            # Find last occurrence
            for i in range(len(recent_highs) - 1, -1, -1):
                if recent_highs[i] == max_high and high_period == 0:
                    high_period = len(recent_highs) - 1 - i
                if recent_lows[i] == min_low and low_period == 0:
                    low_period = len(recent_lows) - 1 - i
            
            aroon_up = ((period - high_period) / period) * 100
            aroon_down = ((period - low_period) / period) * 100
            
            if aroon_up > 70 and aroon_down < 30:
                return {'strength': 1.5, 'signal': 'aroon_uptrend'}
            elif aroon_down > 70 and aroon_up < 30:
                return {'strength': -1.5, 'signal': 'aroon_downtrend'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_mfi(self, klines, period=14):
        """Money Flow Index"""
        try:
            if len(klines) < period + 1:
                return {'strength': 0, 'signal': 'neutral'}
            
            money_flows = []
            for i in range(1, len(klines)):
                typical_price = (klines[i]['high'] + klines[i]['low'] + klines[i]['close']) / 3
                prev_typical = (klines[i-1]['high'] + klines[i-1]['low'] + klines[i-1]['close']) / 3
                
                raw_money_flow = typical_price * klines[i]['volume']
                
                if typical_price > prev_typical:
                    money_flows.append(('positive', raw_money_flow))
                elif typical_price < prev_typical:
                    money_flows.append(('negative', raw_money_flow))
                else:
                    money_flows.append(('neutral', raw_money_flow))
            
            if len(money_flows) < period:
                return {'strength': 0, 'signal': 'neutral'}
            
            recent_flows = money_flows[-period:]
            positive_flow = sum(flow[1] for flow in recent_flows if flow[0] == 'positive')
            negative_flow = sum(flow[1] for flow in recent_flows if flow[0] == 'negative')
            
            if positive_flow + negative_flow == 0:
                return {'strength': 0, 'signal': 'neutral'}
            
            money_ratio = positive_flow / negative_flow if negative_flow > 0 else float('inf')
            mfi = 100 - (100 / (1 + money_ratio))
            
            if mfi > 80:
                return {'strength': -1.5, 'signal': 'mfi_overbought'}
            elif mfi < 20:
                return {'strength': 1.5, 'signal': 'mfi_oversold'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_obv(self, closes, volumes):
        """On-Balance Volume"""
        try:
            if len(closes) < 10 or len(volumes) < 10:
                return {'strength': 0, 'signal': 'neutral'}
            
            obv_values = [volumes[0]]
            
            for i in range(1, len(closes)):
                if closes[i] > closes[i-1]:
                    obv_values.append(obv_values[-1] + volumes[i])
                elif closes[i] < closes[i-1]:
                    obv_values.append(obv_values[-1] - volumes[i])
                else:
                    obv_values.append(obv_values[-1])
            
            # OBV trend
            recent_obv = obv_values[-5:]
            obv_trend = (recent_obv[-1] - recent_obv[0]) / abs(recent_obv[0]) if recent_obv[0] != 0 else 0
            
            if obv_trend > 0.1:
                return {'strength': 1.0, 'signal': 'obv_accumulation'}
            elif obv_trend < -0.1:
                return {'strength': -1.0, 'signal': 'obv_distribution'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_ad_line(self, klines):
        """Accumulation/Distribution Line"""
        try:
            if len(klines) < 10:
                return {'strength': 0, 'signal': 'neutral'}
            
            ad_values = [0]
            
            for k in klines[1:]:
                if k['high'] == k['low']:
                    clv = 0
                else:
                    clv = ((k['close'] - k['low']) - (k['high'] - k['close'])) / (k['high'] - k['low'])
                
                ad_values.append(ad_values[-1] + clv * k['volume'])
            
            # A/D Line trend
            recent_ad = ad_values[-5:]
            ad_trend = (recent_ad[-1] - recent_ad[0]) / abs(recent_ad[0]) if recent_ad[0] != 0 else 0
            
            if ad_trend > 0.05:
                return {'strength': 1.0, 'signal': 'ad_accumulation'}
            elif ad_trend < -0.05:
                return {'strength': -1.0, 'signal': 'ad_distribution'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_cmf(self, klines, period=21):
        """Chaikin Money Flow"""
        try:
            if len(klines) < period:
                return {'strength': 0, 'signal': 'neutral'}
            
            recent_klines = klines[-period:]
            money_flow_volume = 0
            total_volume = 0
            
            for k in recent_klines:
                if k['high'] == k['low']:
                    clv = 0
                else:
                    clv = ((k['close'] - k['low']) - (k['high'] - k['close'])) / (k['high'] - k['low'])
                
                money_flow_volume += clv * k['volume']
                total_volume += k['volume']
            
            if total_volume == 0:
                return {'strength': 0, 'signal': 'neutral'}
            
            cmf = money_flow_volume / total_volume
            
            if cmf > 0.1:
                return {'strength': 1.0, 'signal': 'cmf_buying_pressure'}
            elif cmf < -0.1:
                return {'strength': -1.0, 'signal': 'cmf_selling_pressure'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def calculate_atr_signals(self, klines, period=14):
        """ATR-based Volatility Signals"""
        try:
            if len(klines) < period + 1:
                return {'strength': 0, 'signal': 'neutral'}
            
            tr_values = []
            for i in range(1, len(klines)):
                high = klines[i]['high']
                low = klines[i]['low']
                prev_close = klines[i-1]['close']
                
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                tr_values.append(tr)
            
            if len(tr_values) < period:
                return {'strength': 0, 'signal': 'neutral'}
            
            current_atr = sum(tr_values[-period:]) / period
            prev_atr = sum(tr_values[-period-5:-5]) / period if len(tr_values) >= period + 5 else current_atr
            
            atr_change = (current_atr - prev_atr) / prev_atr if prev_atr > 0 else 0
            
            if atr_change > 0.2:  # 20% increase in volatility
                return {'strength': 1.0, 'signal': 'volatility_breakout'}
            elif atr_change < -0.2:  # 20% decrease in volatility
                return {'strength': -0.5, 'signal': 'volatility_compression'}
            
            return {'strength': 0, 'signal': 'neutral'}
        except:
            return {'strength': 0, 'signal': 'neutral'}
    
    def _calculate_signal_consistency(self, factors):
        """Calcule la cohérence des signaux"""
        try:
            bullish_signals = 0
            bearish_signals = 0
            total_signals = 0
            
            for factor_data in factors.values():
                if factor_data and 'strength' in factor_data:
                    strength = factor_data['strength']
                    if abs(strength) > 0.5:  # Signal significatif
                        total_signals += 1
                        if strength > 0:
                            bullish_signals += 1
                        else:
                            bearish_signals += 1
            
            if total_signals == 0:
                return 0
            
            # Cohérence = dominance du signal majoritaire
            dominant_signals = max(bullish_signals, bearish_signals)
            consistency = (dominant_signals / total_signals) * 100
            
            return consistency
        except:
            return 0