"""
Double Investment Manager - Gestion Automatique Double Investment
Intégration avec Capital Manager pour stratégies adaptées au capital
"""

import time
import json
from datetime import datetime, timedelta

class DoubleInvestmentManager:
    """Gestionnaire automatique Double Investment"""
    
    def __init__(self, bot):
        self.bot = bot
        self.positions = []
        self.enabled = True  # Toujours activé pour récupérer les positions
        self.min_amount = 10  # Minimum Binance
        self.cached_positions = []  # Cache des positions
        self.last_api_call = 0  # Timestamp dernier appel
        self.cache_duration = 60  # Cache 60 secondes
        
    def is_creation_enabled(self):
        """Vérifie si la création de nouvelles positions est activée"""
        # En paper trading, pas de création
        if self.bot.paper_trading:
            return False
        
        # Vérifier variable d'environnement
        import os
        return os.getenv('DUAL_INVESTMENT_CREATE', 'False') == 'True'
    
    def is_enabled_for_capital(self, total_balance):
        """Vérifie si Double Investment est activé selon le capital"""
        return total_balance >= 20  # Activé à partir de 20 USDT
    
    def get_allocation_for_capital(self, total_balance):
        """Retourne l'allocation Double Investment selon le capital"""
        if total_balance < 20:
            return 0.0  # 0%
        elif total_balance < 50:
            return 0.05  # 5%
        elif total_balance < 200:
            return 0.20  # 20%
        else:
            return 0.25  # 25%
    
    def auto_manage_positions(self):
        """Gestion automatique des positions Double Investment"""
        try:
            # Toujours récupérer les positions existantes
            real_positions = self.get_dual_investment_positions_from_api()
            
            # Si pas activé pour créer de nouvelles positions, arrêter ici
            if not self.is_creation_enabled():
                return
            
            # Vérifier que le bot a les méthodes nécessaires
            if not hasattr(self.bot, 'balance_manager') or not hasattr(self.bot, 'get_price'):
                print("⚠️ Double Investment: Méthodes bot manquantes")
                return
            
            # Récupérer le capital total
            balance_info = self.bot.balance_manager.get_total_balance_usdt()
            total_balance = balance_info['total']
            
            # Vérifier si activé pour ce capital
            if not self.is_enabled_for_capital(total_balance):
                return
            
            # Calculer allocation disponible
            allocation = self.get_allocation_for_capital(total_balance)
            available_amount = total_balance * allocation
            
            # Stratégie selon capital
            if total_balance < 50:
                # Petit capital : 1 position conservative
                self._manage_small_capital_strategy(available_amount)
            elif total_balance < 200:
                # Capital moyen : 2-3 positions diversifiées
                self._manage_medium_capital_strategy(available_amount)
            else:
                # Gros capital : Stratégie complète
                self._manage_large_capital_strategy(available_amount)
                
        except Exception as e:
            print(f"⚠️ Erreur gestion Double Investment: {e}")
    
    def _manage_small_capital_strategy(self, available_amount):
        """Stratégie petit capital (20-50 USDT)"""
        if available_amount < self.min_amount:
            return
        
        # Une seule position conservative
        # Priorité : Covered Call sur positions en perte
        stuck_positions = self._get_stuck_positions()
        if stuck_positions:
            best_position = max(stuck_positions, key=lambda p: abs(p.get('pnl_percent', 0)))
            self._create_covered_call(best_position, min(available_amount, 10))
        else:
            # Sinon, PUT sur BTC/ETH pour acheter les dips
            self._create_conservative_put('BTC/USDT', available_amount)
    
    def _manage_medium_capital_strategy(self, available_amount):
        """Stratégie capital moyen (50-200 USDT)"""
        # Répartir sur 2-3 positions
        per_position = available_amount / 2
        
        if per_position >= self.min_amount:
            # 50% Covered Calls sur positions existantes
            self._manage_covered_calls(available_amount * 0.5)
            
            # 50% PUT stratégiques sur dips
            self._manage_strategic_puts(available_amount * 0.5)
    
    def _manage_large_capital_strategy(self, available_amount):
        """Stratégie gros capital (200+ USDT)"""
        # Stratégie complète diversifiée
        allocations = {
            'covered_calls': 0.4,  # 40% - Revenus sur positions
            'strategic_puts': 0.35,  # 35% - Achats programmés
            'volatility_plays': 0.25  # 25% - Jeu sur volatilité
        }
        
        for strategy, allocation in allocations.items():
            amount = available_amount * allocation
            if amount >= self.min_amount:
                getattr(self, f'_manage_{strategy}')(amount)
    
    def _get_stuck_positions(self):
        """Récupère les positions en perte (candidates pour Covered Call)"""
        stuck_positions = []
        
        try:
            positions = self.bot.state.get('positions', [])
            for pos in positions:
                if pos['side'] == 'buy':
                    current_price = self.bot.get_price(pos['symbol'])
                    pnl_percent = ((current_price - pos['price']) / pos['price']) * 100
                    
                    if pnl_percent < -3:  # En perte de plus de 3%
                        pos['pnl_percent'] = pnl_percent
                        pos['current_price'] = current_price
                        stuck_positions.append(pos)
                        
        except Exception as e:
            print(f"⚠️ Erreur récupération positions bloquées: {e}")
        
        return stuck_positions
    
    def _create_covered_call(self, position, amount):
        """Crée un Covered Call sur une position existante"""
        try:
            symbol = position['symbol']
            current_price = position['current_price']
            
            # Strike +2% à +5% selon volatilité
            volatility = self._get_symbol_volatility(symbol)
            if volatility > 4:
                strike_percent = 0.05  # +5% haute volatilité
            else:
                strike_percent = 0.02  # +2% faible volatilité
            
            strike_price = current_price * (1 + strike_percent)
            
            # Simuler création Covered Call
            call_position = {
                'type': 'covered_call',
                'symbol': symbol,
                'strike_price': strike_price,
                'amount': amount,
                'expiry': (datetime.now() + timedelta(days=7)).isoformat(),
                'premium_expected': amount * 0.02,  # 2% premium estimé
                'created_at': datetime.now().isoformat()
            }
            
            self.positions.append(call_position)
            
        except Exception as e:
            print(f"⚠️ Erreur création Covered Call: {e}")
    
    def _create_conservative_put(self, symbol, amount):
        """Crée un PUT conservateur pour acheter les dips"""
        try:
            current_price = self.bot.get_price(symbol)
            
            # Strike -5% à -10% selon marché
            market_trend = self._get_market_trend()
            if market_trend == 'bullish':
                strike_percent = -0.05  # -5% marché haussier
            else:
                strike_percent = -0.10  # -10% marché baissier
            
            strike_price = current_price * (1 + strike_percent)
            
            put_position = {
                'type': 'cash_secured_put',
                'symbol': symbol,
                'strike_price': strike_price,
                'amount': amount,
                'expiry': (datetime.now() + timedelta(days=7)).isoformat(),
                'premium_expected': amount * 0.015,  # 1.5% premium estimé
                'created_at': datetime.now().isoformat()
            }
            
            self.positions.append(put_position)
            
        except Exception as e:
            print(f"⚠️ Erreur création PUT: {e}")
    
    def _manage_covered_calls(self, amount):
        """Gère les Covered Calls sur positions existantes"""
        stuck_positions = self._get_stuck_positions()
        
        if not stuck_positions:
            return
        
        per_position = amount / len(stuck_positions)
        
        for position in stuck_positions:
            if per_position >= self.min_amount:
                self._create_covered_call(position, per_position)
    
    def _manage_strategic_puts(self, amount):
        """Gère les PUT stratégiques"""
        # Répartir sur BTC et ETH
        symbols = ['BTC/USDT', 'ETH/USDT']
        per_symbol = amount / len(symbols)
        
        for symbol in symbols:
            if per_symbol >= self.min_amount:
                self._create_conservative_put(symbol, per_symbol)
    
    def _manage_volatility_plays(self, amount):
        """Gère les jeux sur volatilité (stratégie avancée)"""
        # Pour gros capitaux : positions plus sophistiquées
        # Vendre volatilité implicite élevée
        high_vol_symbols = self._get_high_volatility_symbols()
        
        if high_vol_symbols:
            per_symbol = amount / len(high_vol_symbols)
            for symbol in high_vol_symbols:
                if per_symbol >= self.min_amount:
                    self._create_volatility_position(symbol, per_symbol)
    
    def _get_symbol_volatility(self, symbol):
        """Calcule la volatilité d'un symbole"""
        try:
            if hasattr(self.bot, 'volatility_calculator'):
                return self.bot.volatility_calculator.get_volatility(symbol)
            return 2.0  # Défaut
        except:
            return 2.0
    
    def _get_market_trend(self):
        """Détermine la tendance générale du marché"""
        try:
            # Analyser BTC comme proxy du marché
            btc_analysis = self.bot.get_cached_analysis('BTC/USDT', self.bot.get_price('BTC/USDT'))
            trend = btc_analysis.get('global_signal', {}).get('dominant_trend', 'neutral')
            
            if 'bullish' in trend.lower():
                return 'bullish'
            elif 'bearish' in trend.lower():
                return 'bearish'
            else:
                return 'neutral'
        except:
            return 'neutral'
    
    def _get_high_volatility_symbols(self):
        """Retourne les symboles à haute volatilité"""
        high_vol = []
        
        for symbol in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
            vol = self._get_symbol_volatility(symbol)
            if vol > 3.0:  # Volatilité > 3%
                high_vol.append(symbol)
        
        return high_vol
    
    def _create_volatility_position(self, symbol, amount):
        """Crée une position de volatilité"""
        # Stratégie avancée : vendre calls et puts simultanément (strangle)
        current_price = self.bot.get_price(symbol)
        
        vol_position = {
            'type': 'volatility_strangle',
            'symbol': symbol,
            'call_strike': current_price * 1.05,  # +5%
            'put_strike': current_price * 0.95,   # -5%
            'amount': amount,
            'expiry': (datetime.now() + timedelta(days=3)).isoformat(),
            'premium_expected': amount * 0.03,  # 3% premium estimé
            'created_at': datetime.now().isoformat()
        }
        
        self.positions.append(vol_position)
    
    def check_expirations(self):
        """Vérifie et gère les expirations"""
        now = datetime.now()
        expired_positions = []
        
        for i, position in enumerate(self.positions):
            try:
                expiry = datetime.fromisoformat(position['expiry'])
                if now >= expiry:
                    expired_positions.append(i)
            except:
                continue
        
        # Traiter les expirations (du plus récent au plus ancien)
        for i in reversed(expired_positions):
            position = self.positions.pop(i)
            self._process_expiration(position)
    
    def _process_expiration(self, position):
        """Traite l'expiration d'une position"""
        try:
            pos_type = position['type']
            symbol = position['symbol']
            current_price = self.bot.get_price(symbol)
            
            if pos_type == 'covered_call':
                strike = position['strike_price']
                if current_price > strike:
                    # Assigné : vendre la crypto au strike
                    print(f"✅ Call assigné: {symbol} vendu à {strike:.2f}")
                    # Simuler la vente
                else:
                    # Expiré sans valeur : garder la crypto + prime
                    premium = position['premium_expected']
                    print(f"💰 Call expiré: Prime collectée {premium:.2f} USDT")
            
            elif pos_type == 'cash_secured_put':
                strike = position['strike_price']
                if current_price < strike:
                    # Assigné : acheter la crypto au strike
                    print(f"✅ PUT assigné: {symbol} acheté à {strike:.2f}")
                    # Simuler l'achat
                else:
                    # Expiré sans valeur : garder USDT + prime
                    premium = position['premium_expected']
                    print(f"💰 PUT expiré: Prime collectée {premium:.2f} USDT")
            
        except Exception as e:
            print(f"⚠️ Erreur traitement expiration: {e}")
    
    def get_dual_investment_positions_from_api(self):
        """Récupère les positions réelles de Dual Investment via l'API Binance avec cache"""
        try:
            if self.bot.paper_trading:
                return []
            
            # Vérifier cache
            import time
            now = time.time()
            if now - self.last_api_call < self.cache_duration:
                return self.cached_positions
            
            # Endpoint pour récupérer les positions Dual Investment
            endpoint = "/sapi/v1/dci/product/positions"
            
            # Utiliser l'API directement via requests
            import requests
            import hmac
            import hashlib
            from urllib.parse import urlencode
            
            params = {
                'timestamp': int(time.time() * 1000)
            }
            
            # Générer signature
            query_string = urlencode(params)
            signature = hmac.new(
                self.bot.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params['signature'] = signature
            
            headers = {
                'X-MBX-APIKEY': self.bot.api_key
            }
            
            url = f"https://api.binance.com{endpoint}"
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                positions = data.get('list', [])
                
                # Filtrer seulement les positions actives
                active_positions = [pos for pos in positions if pos.get('purchaseStatus') == 'PURCHASE_SUCCESS']
                
                # Mettre à jour cache
                self.cached_positions = active_positions
                self.last_api_call = now
                
                # Afficher seulement si changement
                if len(active_positions) != len(getattr(self, '_last_displayed_count', -1)):
                    if active_positions:
                        print(f"💎 {len(active_positions)} positions Dual Investment actives:")
                        for pos in active_positions:
                            invest_coin = pos.get('investCoin', 'UNKNOWN')
                            exercised_coin = pos.get('exercisedCoin', 'UNKNOWN')
                            option_type = pos.get('optionType', 'UNKNOWN')
                            amount = float(pos.get('subscriptionAmount', 0))
                            strike = float(pos.get('strikePrice', 0))
                            apr = float(pos.get('apr', 0))
                            duration = pos.get('duration', 0)
                            
                            # CORRECTION: APR vient comme 1.05 (pas 105%), donc pas besoin de /100
                            potential_gain_usdt = amount * apr * (duration / 365)
                            
                            # Calculer jours restants
                            settle_date = pos.get('settleDate', 0)
                            if settle_date:
                                settle_datetime = datetime.fromtimestamp(settle_date / 1000)
                                days_left = (settle_datetime - datetime.now()).days
                                if days_left > 0:
                                    time_display = f"[{days_left}j]"
                                else:
                                    time_display = "[Expiré]"
                            else:
                                time_display = f"[{duration}j]"
                            
                            print(f"   {option_type} {exercised_coin}: {amount:.2f} USDT @ {strike:.2f} (+{potential_gain_usdt:.3f} USDT) {time_display}")
                    else:
                        print(f"💎 Aucune position Dual Investment active")
                    self._last_displayed_count = len(active_positions)
                
                return active_positions
            else:
                # Erreur de permissions - utiliser cache si disponible
                if "permissions" in response.text.lower():
                    return self.cached_positions
                return []
                
        except Exception as e:
            # Retourner cache en cas d'erreur
            return self.cached_positions
    
    def get_positions_summary(self):
        """Retourne un résumé des positions Double Investment (réelles + simulées)"""
        # Récupérer positions réelles de l'API
        real_positions = self.get_dual_investment_positions_from_api()
        
        # Combiner positions réelles et simulées
        total_positions = len(real_positions) + len(self.positions)
        
        if total_positions == 0:
            return "Aucune position"
        
        summary_parts = []
        
        # Positions réelles de l'API
        if real_positions:
            for pos in real_positions:
                invest_coin = pos.get('investCoin', 'UNKNOWN')
                exercised_coin = pos.get('exercisedCoin', 'UNKNOWN')
                option_type = pos.get('optionType', 'UNKNOWN')
                amount = float(pos.get('subscriptionAmount', 0))
                apr = float(pos.get('apr', 0))
                duration = pos.get('duration', 0)
                
                # CORRECTION: APR vient comme 1.05 (pas 105%), donc pas besoin de /100
                potential_gain_usdt = amount * apr * (duration / 365)
                
                # Calculer jours restants
                settle_date = pos.get('settleDate', 0)
                if settle_date:
                    settle_datetime = datetime.fromtimestamp(settle_date / 1000)
                    days_left = (settle_datetime - datetime.now()).days
                    if days_left > 0:
                        time_display = f"[{days_left}j]"
                    else:
                        time_display = "[Expiré]"
                else:
                    time_display = f"[{duration}j]"
                
                gain_display = f"+{potential_gain_usdt:.3f} USDT {time_display}"
                
                if option_type == 'CALL':
                    summary_parts.append(f"📞 Call {exercised_coin} {amount:.2f} USDT ({gain_display})")
                elif option_type == 'PUT':
                    summary_parts.append(f"📉 PUT {exercised_coin} {amount:.2f} USDT ({gain_display})")
                else:
                    summary_parts.append(f"💎 {exercised_coin} {amount:.2f} USDT ({gain_display})")
        
        # Positions simulées (pour développement)
        for pos in self.positions:
            pos_type = pos['type']
            symbol = pos['symbol']
            
            if pos_type == 'covered_call':
                summary_parts.append(f"📞 Call {symbol} @ {pos['strike_price']:.2f}")
            elif pos_type == 'cash_secured_put':
                summary_parts.append(f"📉 PUT {symbol} @ {pos['strike_price']:.2f}")
            elif pos_type == 'volatility_strangle':
                summary_parts.append(f"⚡ Strangle {symbol}")
        
        if summary_parts:
            return "\n".join([f"   {part}" for part in summary_parts])
        else:
            return "Aucune position"
    
    def enable(self):
        """Active le Double Investment"""
        self.enabled = True
    
    def disable(self):
        """Désactive le Double Investment"""
        self.enabled = False
        print("❌ Double Investment désactivé")
    
    def test_integration(self):
        """Test d'intégration avec le bot"""
        try:
            # Toujours activé pour récupérer les positions
            self.enabled = True
            
            # Vérifier méthodes bot
            required_methods = ['get_price', 'balance_manager']
            missing_methods = []
            
            for method in required_methods:
                if not hasattr(self.bot, method):
                    missing_methods.append(method)
            
            if missing_methods:
                print(f"❌ Méthodes manquantes: {missing_methods}")
                return False
            
            # Test récupération capital
            balance_info = self.bot.balance_manager.get_total_balance_usdt()
            total_balance = balance_info['total']
            
            # Test configuration
            config = self.get_allocation_for_capital(total_balance)
            
            # Test prix
            btc_price = self.bot.get_price('BTC/USDT')
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur test: {e}")
            return False