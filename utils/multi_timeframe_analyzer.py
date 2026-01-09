import numpy as np
from collections import deque
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.market_calculator import MarketCalculator

class MultiTimeframeAnalyzer:
    def __init__(self):
        self.cache = {}
        self.data_cache = {}  # Cache des données par timeframe
        self.signal_history = deque(maxlen=10)
        
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
        """Analyse un timeframe spécifique avec filtres avancés"""
        if len(klines) < 30:
            return {'trend': 'unknown', 'strength': 0, 'signals': []}
        
        closes = [k['close'] for k in klines]
        volumes = [k['volume'] for k in klines]
        
        # Calculer les indicateurs
        rsi = self.calculate_rsi(closes)
        macd, signal, histogram = self.calculate_macd(closes)
        upper_bb, middle_bb, lower_bb = self.calculate_bollinger_bands(closes)
        ema_20 = self.calculate_ema(closes, 20)
        ema_50 = self.calculate_ema(closes, 50)
        
        # NOUVEAUX FILTRES PHASE 1
        volume_confirmation = self.check_volume_confirmation(volumes)
        is_trending = self.is_trending_market(klines)
        
        # Analyser la tendance
        trend = self.determine_trend(closes, ema_20, ema_50)
        
        # Analyser les signaux avec filtres
        signals = []
        strength = 0
        
        # Signal RSI avec confirmation volume
        if rsi is not None:
            if rsi < 35:
                signals.append("RSI survente")
                strength += 1.5 if volume_confirmation else 0.5
            elif rsi > 65:
                signals.append("RSI surachat")
                strength -= 1.5 if volume_confirmation else 0.5
        
        # Signal MACD avec confirmation volume
        if macd is not None and signal is not None:
            if macd > signal and histogram > 0:
                signals.append("MACD haussier")
                strength += 1.5 if volume_confirmation else 1
            elif macd < signal and histogram < 0:
                signals.append("MACD baissier")
                strength -= 1.5 if volume_confirmation else 1
        
        # Signal Bollinger Bands
        if lower_bb is not None and upper_bb is not None:
            if current_price <= lower_bb:
                signals.append("BB support")
                strength += 1.5 if volume_confirmation else 1
            elif current_price >= upper_bb:
                signals.append("BB résistance")
                strength -= 1.5 if volume_confirmation else 1
        
        # Signal EMA
        if ema_20 is not None and ema_50 is not None:
            if ema_20 > ema_50:
                signals.append("EMA haussier")
                strength += 0.5
            else:
                signals.append("EMA baissier")
                strength -= 0.5
        
        # Réduire force si marché non-tendanciel
        if not is_trending:
            strength *= 0.7
            signals.append("Marché latéral")
        
        return {
            'trend': trend,
            'strength': strength,
            'signals': signals,
            'volume_confirmation': volume_confirmation,
            'is_trending': is_trending,
            'indicators': {
                'rsi': rsi,
                'macd': macd,
                'bb_position': self.get_bb_position(current_price, upper_bb, middle_bb, lower_bb),
                'ema_trend': 'bullish' if ema_20 and ema_50 and ema_20 > ema_50 else 'bearish'
            }
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
            # Utiliser WebSocket si disponible
            if hasattr(bot, 'websocket') and bot.websocket.is_connected():
                return MarketCalculator.calculate_volatility_from_websocket(bot.websocket, symbol)
            
            # Fallback API REST
            klines = bot.get_klines(symbol, 60, os.getenv('MAIN_TIMEFRAME', '15m'))
            return MarketCalculator.calculate_volatility(klines, symbol)
        except Exception as e:
            return 2.0
    
    def get_crypto_profile(self, symbol, volatility):
        """Retourne le profil adaptatif selon crypto et volatilité"""
        return MarketCalculator.get_crypto_profile(volatility)
    
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