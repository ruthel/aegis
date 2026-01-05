"""
Gestionnaire de Niveaux Dynamiques - Phase 1 Amélioration Bot
Remplace les niveaux fixes par des calculs temps réel professionnels
"""

import numpy as np
from datetime import datetime, timedelta

class DynamicLevelsManager:
    """Gestionnaire de niveaux dynamiques professionnels"""
    
    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.cache_duration = 300  # 5 minutes
    
    def get_dynamic_levels(self, symbol):
        """Calcule les niveaux d'entrée dynamiques"""
        # Vérifier cache
        if self._is_cached(symbol):
            return self.cache[symbol]['levels']
        
        levels = {
            'support': [],
            'resistance': [],
            'pivot_points': {},
            'order_blocks': [],
            'volume_poc': None
        }
        
        try:
            # 1. Pivot Points (Daily)
            levels['pivot_points'] = self._calculate_pivot_points(symbol)
            
            # 2. Support/Résistance (Weekly/Monthly)
            support_resistance = self._calculate_support_resistance(symbol)
            levels['support'] = support_resistance['support']
            levels['resistance'] = support_resistance['resistance']
            
            # 3. Order Blocks (4H)
            levels['order_blocks'] = self._detect_order_blocks(symbol)
            
            # 4. Volume Profile POC
            levels['volume_poc'] = self._calculate_volume_poc(symbol)
            
            # Cache résultats
            self.cache[symbol] = {
                'levels': levels,
                'timestamp': datetime.now()
            }
            
            return levels
            
        except Exception as e:
            print(f"⚠️ Erreur calcul niveaux dynamiques {symbol}: {e}")
            return self._get_fallback_levels(symbol)
    
    def _calculate_pivot_points(self, symbol):
        """Calcule les pivot points Daily"""
        try:
            # Récupérer données Daily
            klines = self.bot.get_klines(symbol, 5, '1d')
            if len(klines) < 2:
                return {}
            
            yesterday = klines[-2]
            high = yesterday['high']
            low = yesterday['low']
            close = yesterday['close']
            
            # Pivot classique
            pivot = (high + low + close) / 3
            
            # Support/Résistance
            r1 = 2 * pivot - low
            r2 = pivot + (high - low)
            r3 = high + 2 * (pivot - low)
            
            s1 = 2 * pivot - high
            s2 = pivot - (high - low)
            s3 = low - 2 * (high - pivot)
            
            return {
                'pivot': pivot,
                'r1': r1, 'r2': r2, 'r3': r3,
                's1': s1, 's2': s2, 's3': s3
            }
            
        except Exception as e:
            print(f"⚠️ Erreur pivot points {symbol}: {e}")
            return {}
    
    def _calculate_support_resistance(self, symbol):
        """Calcule support/résistance dynamiques"""
        try:
            # Données 4H sur 7 jours
            klines = self.bot.get_klines(symbol, 42, '4h')  # 7 jours * 6 bougies/jour
            if len(klines) < 20:
                return {'support': [], 'resistance': []}
            
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]
            
            # Trouver les niveaux significatifs
            resistance_levels = self._find_significant_levels(highs, 'high')
            support_levels = self._find_significant_levels(lows, 'low')
            
            return {
                'support': support_levels[:3],  # Top 3
                'resistance': resistance_levels[:3]  # Top 3
            }
            
        except Exception as e:
            print(f"⚠️ Erreur support/résistance {symbol}: {e}")
            return {'support': [], 'resistance': []}
    
    def _find_significant_levels(self, prices, level_type):
        """Trouve les niveaux significatifs par clustering"""
        if len(prices) < 10:
            return []
        
        # Convertir en numpy pour calculs
        prices_array = np.array(prices)
        
        # Clustering simple par proximité
        levels = []
        tolerance = np.std(prices_array) * 0.5  # 50% de l'écart-type
        
        # Trier selon le type
        sorted_prices = sorted(prices, reverse=(level_type == 'high'))
        
        for price in sorted_prices:
            # Vérifier si proche d'un niveau existant
            is_new_level = True
            for existing_level in levels:
                if abs(price - existing_level) < tolerance:
                    is_new_level = False
                    break
            
            if is_new_level:
                levels.append(price)
                
            # Limiter à 5 niveaux max
            if len(levels) >= 5:
                break
        
        return levels
    
    def _detect_order_blocks(self, symbol):
        """Détecte les order blocks institutionnels"""
        try:
            # Données 1H sur 3 jours
            klines = self.bot.get_klines(symbol, 72, '1h')
            if len(klines) < 20:
                return []
            
            order_blocks = []
            
            # Calculer volume moyen pour comparaison
            volumes = [k['volume'] for k in klines if k['volume'] > 0]
            if len(volumes) < 10:
                return []
            
            avg_volume = sum(volumes) / len(volumes)
            volume_threshold = avg_volume * 1.5
            
            for i in range(2, len(klines) - 2):
                current = klines[i]
                prev = klines[i-1]
                next_candle = klines[i+1]
                
                # Vérifier que les données sont valides
                if current['volume'] == 0 or current['high'] == current['low']:
                    continue
                
                # Bullish Order Block
                if (current['close'] > current['open'] and  # Bougie verte
                    current['volume'] > volume_threshold and  # Volume élevé
                    next_candle['low'] > current['high']):  # Gap up
                    
                    order_blocks.append({
                        'type': 'bullish',
                        'high': current['high'],
                        'low': current['low'],
                        'strength': current['volume']
                    })
                
                # Bearish Order Block
                elif (current['close'] < current['open'] and  # Bougie rouge
                      current['volume'] > volume_threshold and  # Volume élevé
                      next_candle['high'] < current['low']):  # Gap down
                    
                    order_blocks.append({
                        'type': 'bearish',
                        'high': current['high'],
                        'low': current['low'],
                        'strength': current['volume']
                    })
            
            # Trier par force (volume) et garder les 3 meilleurs
            if order_blocks:
                order_blocks.sort(key=lambda x: x['strength'], reverse=True)
                return order_blocks[:3]
            
            return []
            
        except Exception as e:
            print(f"⚠️ Erreur order blocks {symbol}: {e}")
            return []
    
    def _calculate_volume_poc(self, symbol):
        """Calcule le Point of Control du Volume Profile"""
        try:
            # Données 15m sur 24h
            klines = self.bot.get_klines(symbol, 96, '15m')
            if len(klines) < 50:
                return None
            
            # Créer des bins de prix
            all_prices = []
            all_volumes = []
            
            for k in klines:
                # Prix moyen de la bougie
                avg_price = (k['high'] + k['low'] + k['close']) / 3
                volume = k['volume']
                
                # Vérifier que le volume n'est pas zéro
                if volume > 0:
                    all_prices.append(avg_price)
                    all_volumes.append(volume)
            
            # Vérifier qu'on a des données valides
            if len(all_prices) < 10:
                return None
            
            # Trouver le prix avec le plus de volume
            price_volume_pairs = list(zip(all_prices, all_volumes))
            
            # Grouper par tranches de prix
            price_bins = {}
            price_range = max(all_prices) - min(all_prices)
            
            # Éviter division par zéro
            if price_range == 0:
                return all_prices[0]  # Tous les prix sont identiques
            
            bin_size = price_range / 20  # 20 bins
            
            for price, volume in price_volume_pairs:
                bin_key = int((price - min(all_prices)) / bin_size)
                if bin_key not in price_bins:
                    price_bins[bin_key] = {'total_volume': 0, 'avg_price': 0, 'count': 0}
                
                price_bins[bin_key]['total_volume'] += volume
                price_bins[bin_key]['avg_price'] += price
                price_bins[bin_key]['count'] += 1
            
            # Vérifier qu'on a des bins
            if not price_bins:
                return None
            
            # Trouver le bin avec le plus de volume (POC)
            max_volume_bin = max(price_bins.items(), key=lambda x: x[1]['total_volume'])
            
            # Éviter division par zéro
            if max_volume_bin[1]['count'] == 0:
                return None
                
            poc_price = max_volume_bin[1]['avg_price'] / max_volume_bin[1]['count']
            
            return poc_price
            
        except Exception as e:
            print(f"⚠️ Erreur Volume POC {symbol}: {e}")
            return None
    
    def get_entry_levels(self, symbol, current_price):
        """Obtient les niveaux d'entrée recommandés"""
        levels = self.get_dynamic_levels(symbol)
        entry_opportunities = []
        
        # 1. Support levels (achats)
        for support in levels['support']:
            distance_pct = abs(current_price - support) / support * 100
            if distance_pct <= 2.0:  # Dans les 2%
                entry_opportunities.append({
                    'price': support,
                    'type': 'support',
                    'distance': distance_pct,
                    'strength': 'high'
                })
        
        # 2. Pivot points
        pivots = levels['pivot_points']
        for level_name, level_price in pivots.items():
            if level_name.startswith('s') and level_price:  # Support pivots
                distance_pct = abs(current_price - level_price) / level_price * 100
                if distance_pct <= 1.5:
                    entry_opportunities.append({
                        'price': level_price,
                        'type': f'pivot_{level_name}',
                        'distance': distance_pct,
                        'strength': 'medium'
                    })
        
        # 3. Order blocks bullish
        for ob in levels['order_blocks']:
            if ob['type'] == 'bullish':
                # Entrée au milieu de l'order block
                entry_price = (ob['high'] + ob['low']) / 2
                distance_pct = abs(current_price - entry_price) / entry_price * 100
                if distance_pct <= 1.0:
                    entry_opportunities.append({
                        'price': entry_price,
                        'type': 'order_block',
                        'distance': distance_pct,
                        'strength': 'very_high'
                    })
        
        # 4. Volume POC
        if levels['volume_poc']:
            distance_pct = abs(current_price - levels['volume_poc']) / levels['volume_poc'] * 100
            if distance_pct <= 1.0:
                entry_opportunities.append({
                    'price': levels['volume_poc'],
                    'type': 'volume_poc',
                    'distance': distance_pct,
                    'strength': 'high'
                })
        
        # Trier par force et distance
        strength_order = {'very_high': 4, 'high': 3, 'medium': 2, 'low': 1}
        entry_opportunities.sort(key=lambda x: (strength_order[x['strength']], -x['distance']), reverse=True)
        
        return entry_opportunities[:3]  # Top 3
    
    def _is_cached(self, symbol):
        """Vérifie si les données sont en cache et valides"""
        if symbol not in self.cache:
            return False
        
        cache_age = (datetime.now() - self.cache[symbol]['timestamp']).seconds
        return cache_age < self.cache_duration
    
    def _get_fallback_levels(self, symbol):
        """Niveaux de fallback en cas d'erreur"""
        current_price = self.bot.get_price(symbol)
        
        return {
            'support': [current_price * 0.98, current_price * 0.95],
            'resistance': [current_price * 1.02, current_price * 1.05],
            'pivot_points': {'pivot': current_price},
            'order_blocks': [],
            'volume_poc': current_price
        }
    
    def display_levels(self, symbol):
        """Affiche les niveaux pour debug"""
        levels = self.get_dynamic_levels(symbol)
        current_price = self.bot.get_price(symbol)
        crypto = symbol.split('/')[0]
        
        print(f"\n📊 NIVEAUX DYNAMIQUES {crypto} (Prix: {current_price:.2f})")
        
        # Pivot Points
        if levels['pivot_points']:
            pivots = levels['pivot_points']
            print(f"🎯 Pivots: S1={pivots.get('s1', 0):.2f} | Pivot={pivots.get('pivot', 0):.2f} | R1={pivots.get('r1', 0):.2f}")
        
        # Support/Résistance
        if levels['support']:
            supports = [f"{s:.2f}" for s in levels['support'][:2]]
            print(f"🟢 Supports: {' | '.join(supports)}")
        
        # Order Blocks
        if levels['order_blocks']:
            ob_count = len([ob for ob in levels['order_blocks'] if ob['type'] == 'bullish'])
            print(f"📦 Order Blocks: {ob_count} bullish détectés")
        
        # Volume POC
        if levels['volume_poc']:
            print(f"📈 Volume POC: {levels['volume_poc']:.2f}")
        
        # Opportunités d'entrée
        entries = self.get_entry_levels(symbol, current_price)
        if entries:
            best_entry = entries[0]
            print(f"⚡ MEILLEURE ENTRÉE: {best_entry['price']:.2f} ({best_entry['type']}) - Distance: {best_entry['distance']:.1f}%")
    
    def _get_fallback_levels(self, symbol):
        """Niveaux de fallback en cas d'erreur"""
        try:
            current_price = self.bot.get_price(symbol)
            return {
                'pivot_points': {'pivot': current_price},
                'support': [current_price * 0.98, current_price * 0.96],
                'resistance': [current_price * 1.02, current_price * 1.04],
                'order_blocks': [],
                'volume_poc': current_price
            }
        except:
            return {
                'pivot_points': {},
                'support': [],
                'resistance': [],
                'order_blocks': [],
                'volume_poc': None
            }
    
    def get_entry_levels(self, symbol, current_price):
        """Obtient les meilleurs niveaux d'entrée"""
        try:
            levels = self.get_dynamic_levels(symbol)
            entry_opportunities = []
            
            # Pivot points
            pivots = levels.get('pivot_points', {})
            for level_name, price in pivots.items():
                if level_name.startswith('s') and price:  # Support levels
                    distance = abs(current_price - price) / current_price * 100
                    if distance < 2.0:  # Dans les 2%
                        entry_opportunities.append({
                            'price': price,
                            'type': f'Pivot {level_name.upper()}',
                            'distance': distance,
                            'strength': 0.8
                        })
            
            # Support levels
            for support in levels.get('support', []):
                distance = abs(current_price - support) / current_price * 100
                if distance < 1.5:  # Dans les 1.5%
                    entry_opportunities.append({
                        'price': support,
                        'type': 'Support dynamique',
                        'distance': distance,
                        'strength': 0.9
                    })
            
            # Order blocks bullish
            for ob in levels.get('order_blocks', []):
                if ob['type'] == 'bullish':
                    avg_price = (ob['high'] + ob['low']) / 2
                    distance = abs(current_price - avg_price) / current_price * 100
                    if distance < 1.0:  # Dans les 1%
                        entry_opportunities.append({
                            'price': avg_price,
                            'type': 'Order Block',
                            'distance': distance,
                            'strength': 0.95
                        })
            
            # Trier par force puis distance
            entry_opportunities.sort(key=lambda x: (x['strength'], -x['distance']), reverse=True)
            
            return entry_opportunities[:3]  # Top 3
            
        except Exception as e:
            print(f"⚠️ Erreur entry levels {symbol}: {e}")
            return []
    
    def display_levels(self, symbol):
        """Affiche les niveaux pour debug"""
        try:
            levels = self.get_dynamic_levels(symbol)
            current_price = self.bot.get_price(symbol)
            
            print(f"\n📊 NIVEAUX DYNAMIQUES {symbol} (Prix: {current_price:.2f})")
            
            # Pivot points
            pivots = levels.get('pivot_points', {})
            if pivots:
                print("🔸 Pivot Points:")
                for name, price in pivots.items():
                    if price:
                        distance = (price - current_price) / current_price * 100
                        print(f"   {name.upper()}: {price:.2f} ({distance:+.1f}%)")
            
            # Support/Resistance
            supports = levels.get('support', [])
            if supports:
                print("🟢 Supports:")
                for i, support in enumerate(supports[:3]):
                    distance = (support - current_price) / current_price * 100
                    print(f"   S{i+1}: {support:.2f} ({distance:+.1f}%)")
            
            resistances = levels.get('resistance', [])
            if resistances:
                print("🔴 Résistances:")
                for i, resistance in enumerate(resistances[:3]):
                    distance = (resistance - current_price) / current_price * 100
                    print(f"   R{i+1}: {resistance:.2f} ({distance:+.1f}%)")
            
            # Order blocks
            order_blocks = levels.get('order_blocks', [])
            if order_blocks:
                print("📦 Order Blocks:")
                for i, ob in enumerate(order_blocks[:2]):
                    avg_price = (ob['high'] + ob['low']) / 2
                    distance = (avg_price - current_price) / current_price * 100
                    print(f"   OB{i+1} ({ob['type']}): {avg_price:.2f} ({distance:+.1f}%)")
            
            # Volume POC
            poc = levels.get('volume_poc')
            if poc:
                distance = (poc - current_price) / current_price * 100
                print(f"📊 Volume POC: {poc:.2f} ({distance:+.1f}%)")
            
        except Exception as e:
            print(f"⚠️ Erreur affichage niveaux {symbol}: {e}")