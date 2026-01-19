import time
import json
import os
import requests
import hmac
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlencode

class BinanceEarnManager:
    def __init__(self, bot):
        self.bot = bot
        self.enabled = os.getenv('ENABLE_EARN', 'True') == 'True'
        
        # Configuration Earn
        self.min_trading_balance = float(os.getenv('MIN_TRADING_BALANCE', '10'))
        self.earn_allocation_percent = float(os.getenv('EARN_ALLOCATION_PERCENT', '80'))
        self.flexible_threshold = float(os.getenv('FLEXIBLE_SAVINGS_THRESHOLD', '5'))
        self.locked_threshold = float(os.getenv('LOCKED_STAKING_THRESHOLD', '50'))
        self.earn_withdraw_threshold = float(os.getenv('EARN_WITHDRAW_THRESHOLD', '5'))
        
        # Configuration API Binance
        self.api_key = bot.api_key
        self.api_secret = bot.api_secret
        self.testnet = bot.testnet
        self.base_url = "https://api.binance.com"
        
        self.earn_positions = self.load_earn_positions()
        self.last_allocation_check = 0
        self.allocation_interval = 3600  # 1 heure
        
        # Cache des produits disponibles
        self.usdt_flexible_product = None
        self.usdt_locked_product = None
        self.last_product_refresh = 0
        
        # Différer l'initialisation pour éviter les erreurs d'attributs
        self.initialized = False
        
        # Sync temps réel toutes les 30 secondes
        self.last_earn_sync = 0
        self.earn_sync_interval = 30
        
        # WebSocket tracking pour profits Earn
        self.last_earn_balance = 0
        self.last_earn_rewards = 0
        
    def _generate_signature(self, params):
        """Génère la signature pour l'API Binance"""
        query_string = urlencode(params)
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, method, endpoint, params=None, signed=True):
        """Effectue une requête à l'API Binance"""
        # Skip Earn API calls if on testnet (not supported)
        if self.testnet or self.bot.paper_trading:
            return None
            
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        headers = {
            'X-MBX-APIKEY': self.api_key
        }
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, data=params, headers=headers, timeout=10)
            
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            # Silencieux pour les erreurs 400 (permissions insuffisantes)
            return None
    
    def get_flexible_products(self):
        """Récupère la liste des produits Flexible (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/flexible/list"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def get_locked_products(self):
        """Récupère la liste des produits Locked (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/locked/list"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def subscribe_flexible_product(self, product_id, amount):
        """Souscrit à un produit Flexible Savings (nouvelle API)"""
        endpoint = "/sapi/v1/simple-earn/flexible/subscribe"
        params = {
            'productId': str(product_id),
            'amount': f"{float(amount):.8f}"
        }
        return self._make_request('POST', endpoint, params)
    
    def redeem_flexible_product(self, product_id, amount, type='FAST'):
        """Rachète un produit Flexible Savings (nouvelle API)"""
        endpoint = "/sapi/v1/simple-earn/flexible/redeem"
        params = {
            'productId': product_id,
            'amount': amount,
            'type': type
        }
        return self._make_request('POST', endpoint, params)
    
    def subscribe_locked_product(self, project_id, amount):
        """Souscrit à un produit Locked Staking (nouvelle API)"""
        endpoint = "/sapi/v1/simple-earn/locked/subscribe"
        params = {
            'projectId': project_id,
            'amount': amount
        }
        return self._make_request('POST', endpoint, params)
    
    def get_flexible_positions(self):
        """Récupère les positions Flexible (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/flexible/position"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def get_locked_positions(self):
        """Récupère les positions Locked (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/locked/position"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def get_lending_account(self):
        """Récupère le compte Lending"""
        endpoint = "/sapi/v1/lending/union/account"
        return self._make_request('GET', endpoint)
    
    def find_usdt_flexible_product(self):
        """Trouve le produit USDT Flexible (API 2025)"""
        result = self.get_flexible_products()
        if result and 'rows' in result:
            for product in result['rows']:
                if product.get('asset') == 'USDT':
                    return {
                        'productId': product['productId'],
                        'asset': product['asset'],
                        'avgAnnualInterestRate': float(product.get('latestAnnualPercentageRate', 0)),
                        'canPurchase': product.get('canPurchase', True),
                        'canRedeem': product.get('canRedeem', True)
                    }
        return None
    
    def find_usdt_locked_product(self, duration_days=30):
        """Trouve un produit USDT Locked (API 2025)"""
        result = self.get_locked_products()
        if result and 'rows' in result:
            for product in result['rows']:
                if (product.get('asset') == 'USDT' and 
                    product.get('duration') == duration_days):
                    return {
                        'projectId': product['projectId'],
                        'asset': product['asset'],
                        'interestRate': float(product.get('interestRate', 0)),
                        'duration': product['duration'],
                        'lotSize': float(product.get('minPurchaseAmount', 1))
                    }
        return None
    
    def load_earn_positions(self):
        """Charge les positions Earn sauvegardées"""
        try:
            with open('data/earn_positions.json', 'r') as f:
                return json.load(f)
        except:
            return {
                'flexible_savings': [],
                'locked_staking': [],
                'total_earned': 0,
                'last_update': None
            }
    
    def save_earn_positions(self, silent=False):
        """Sauvegarde les positions Earn instantanément"""
        try:
            self.earn_positions['last_update'] = datetime.now().isoformat()
            with open('data/earn_positions.json', 'w') as f:
                json.dump(self.earn_positions, f, indent=2)
            if not silent:
                print(f"💾 earn_positions.json mis à jour")
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde Earn: {e}")
    
    def refresh_available_products(self):
        """Actualise la liste des produits disponibles"""
        if self.bot.paper_trading:
            print()
            print("🎯 Flexible USDT: 3.5% APY (simulé)")
            print("🔒 Locked USDT 30j: 8.0% APY (simulé)")
            return
        
        now = time.time()
        if now - self.last_product_refresh < 3600:
            return
        
        try:
            self.usdt_flexible_product = self.find_usdt_flexible_product()
            self.usdt_locked_product = self.find_usdt_locked_product(30)
            self.last_product_refresh = now
            
            if self.usdt_flexible_product:
                min_amt = self.usdt_flexible_product.get('minPurchaseAmount', 0.1)
                print(f"\n🎯 Flexible USDT: {self.usdt_flexible_product.get('avgAnnualInterestRate', 3.5):.2f}% APY (min: {min_amt})")
            else:
                # Utiliser le produit existant depuis earn_positions.json
                existing_positions = [p for p in self.earn_positions['flexible_savings'] if p['status'] == 'active']
                if existing_positions and 'product_id' in existing_positions[0]:
                    product_id = existing_positions[0]['product_id']
                    self.usdt_flexible_product = {
                        'productId': product_id,
                        'avgAnnualInterestRate': existing_positions[0].get('apy', 2.19),
                        'minPurchaseAmount': 0.1
                    }
                    print(f"🎯 Flexible USDT: {self.usdt_flexible_product['avgAnnualInterestRate']:.2f}% APY (produit existant: {product_id})\n")
                else:
                    print("❌ Aucun produit Flexible USDT trouvé")
                
            if self.usdt_locked_product:
                print(f"🔒 Locked USDT 30j: {self.usdt_locked_product.get('interestRate', 8.0):.2f}% APY")
                
        except Exception as e:
            print(f"⚠️ Erreur API Simple Earn: {e}")
            print("📝 Basculement vers mode simulation")
    
    def should_allocate_to_earn(self):
        """Vérifie s'il faut allouer des fonds vers Earn"""
        if not self.enabled:
            return False
        
        now = time.time()
        if now - self.last_allocation_check < self.allocation_interval:
            return False
        
        self.last_allocation_check = now
        
        # Actualiser les produits disponibles
        self.refresh_available_products()
        
        return True
    
    def get_available_balance(self):
        """Récupère le solde USDT disponible"""
        try:
            balance = self.bot.balance_manager.get_balance()
            return balance.get('USDT', {}).get('free', 0)
        except Exception as e:
            print(f"❌ Erreur récupération solde: {e}")
            return 0
    
    def calculate_allocation(self, available_balance):
        """Calcule l'allocation optimale vers Earn"""
        # Garder le minimum pour le trading
        if available_balance <= self.min_trading_balance:
            return 0, 'insufficient_balance'
        
        # Calculer le montant à allouer
        excess_balance = available_balance - self.min_trading_balance
        allocation_amount = excess_balance * (self.earn_allocation_percent / 100)
        
        # Déterminer le type d'Earn
        if allocation_amount >= self.locked_threshold:
            return allocation_amount, 'locked_staking'
        elif allocation_amount >= self.flexible_threshold:
            return allocation_amount, 'flexible_savings'
        else:
            return 0, 'amount_too_small'
    
    def allocate_to_flexible_savings(self, amount):
        """Alloue des fonds vers Flexible Savings"""
        try:
            if self.bot.paper_trading:
                # Mode simulation
                position = {
                    'amount': amount,
                    'product': 'USDT_FLEXIBLE',
                    'apy': 3.5,
                    'start_date': datetime.now().isoformat(),
                    'status': 'active'
                }
                self.earn_positions['flexible_savings'].append(position)
                self.bot.paper_balance -= amount
                return True
            else:
                # Mode live avec nouvelles API
                if not self.usdt_flexible_product:
                    print(f"🐷 Erreur: Aucun produit USDT Flexible trouvé")
                    return False
                
                # Vérifier montant minimum (0.1 USDT pour Binance Earn)
                min_amount = max(float(self.usdt_flexible_product.get('minPurchaseAmount', 0.1)), 0.1)
                if amount < min_amount:
                    print(f"🐷 Montant trop petit: {amount:.2f} < {min_amount:.2f} USDT")
                    return False
                
                print(f"🔄 Souscription: {amount:.2f} USDT (ProductID: {self.usdt_flexible_product['productId']})")
                
                try:
                    result = self.subscribe_flexible_product(
                        self.usdt_flexible_product['productId'], 
                        amount
                    )
                    print(f"📝 Réponse: {result}")
                except Exception as api_error:
                    print(f"🐷 Erreur API subscribe: {api_error}")
                    return False
                
                if result and (result.get('purchaseId') or result.get('success')):
                    position = {
                        'amount': amount,
                        'product_id': self.usdt_flexible_product['productId'],
                        'purchase_id': result.get('purchaseId', 'N/A'),
                        'apy': self.usdt_flexible_product['avgAnnualInterestRate'],
                        'start_date': datetime.now().isoformat(),
                        'status': 'active'
                    }
                    self.earn_positions['flexible_savings'].append(position)
                    return True
                else:
                    print(f"❌ Échec souscription: {result}")
                    return False
                
        except Exception as e:
            print(f"❌ Erreur Flexible Savings: {e}")
            return False
    
    def allocate_to_locked_staking(self, amount, duration_days=30):
        """Alloue des fonds vers Locked Staking (mode simulation)"""
        try:
            # Toujours en mode simulation
            position = {
                'amount': amount,
                'product': f'USDT_LOCKED_{duration_days}D',
                'apy': 8.0,  # 8% APY simulé pour 30 jours
                'start_date': datetime.now().isoformat(),
                'end_date': (datetime.now() + timedelta(days=duration_days)).isoformat(),
                'status': 'locked'
            }
            self.earn_positions['locked_staking'].append(position)
            
            if self.bot.paper_trading:
                self.bot.paper_balance -= amount
            
            print(f"🔒 TIRELIRE - Locked Staking: {amount:.2f} USDT à 8% APY ({duration_days} jours)")
            return True
                
        except Exception as e:
            print(f"❌ Erreur Locked Staking: {e}")
            return False
    
    def silent_sync_earn_positions(self):
        """Synchronisation silencieuse au démarrage"""
        if self.bot.paper_trading:
            return
        
        try:
            result = self.get_flexible_positions()
            if result and 'rows' in result:
                self.earn_positions['flexible_savings'] = []
                
                for pos in result['rows']:
                    if pos.get('asset') == 'USDT' and float(pos.get('totalAmount', 0)) > 0:
                        self.earn_positions['flexible_savings'].append({
                            'amount': float(pos['totalAmount']),
                            'product_id': pos['productId'],
                            'apy': float(pos.get('latestAnnualPercentageRate', 0)),
                            'start_date': datetime.now().isoformat(),
                            'status': 'active'
                        })
                
                self.save_earn_positions(silent=True)
        except:
            pass  # Silencieux
    
    def sync_earn_positions_from_api(self):
        """Synchronise les positions Earn depuis l'API Binance"""
        if self.bot.paper_trading:
            return
        
        # Sync temps réel toutes les 30 secondes
        now = time.time()
        if now - self.last_earn_sync < self.earn_sync_interval:
            return
        
        self.last_earn_sync = now
        
        try:
            result = self.get_flexible_positions()
            if result and 'rows' in result:
                old_total = sum(pos['amount'] for pos in self.earn_positions['flexible_savings'] if pos['status'] == 'active')
                self.earn_positions['flexible_savings'] = []
                
                for pos in result['rows']:
                    if pos.get('asset') == 'USDT' and float(pos.get('totalAmount', 0)) > 0:
                        self.earn_positions['flexible_savings'].append({
                            'amount': float(pos['totalAmount']),
                            'product_id': pos['productId'],
                            'apy': float(pos.get('latestAnnualPercentageRate', 0)),
                            'start_date': datetime.now().isoformat(),
                            'status': 'active'
                        })
                
                new_total = sum(pos['amount'] for pos in self.earn_positions['flexible_savings'] if pos['status'] == 'active')
                if abs(new_total - old_total) > 0.01:  # Changement significatif
                    self.save_earn_positions(silent=True)
                    
        except Exception as e:
            pass  # Silencieux en temps réel
    
    def withdraw_from_flexible(self, amount_needed):
        """Retire des fonds du Flexible Savings pour trading"""
        try:
            # Synchroniser les positions réelles depuis l'API (silencieux)
            if not self.bot.paper_trading:
                self.sync_earn_positions_from_api()
            
            available_flexible = sum(pos['amount'] for pos in self.earn_positions['flexible_savings'] 
                                   if pos['status'] == 'active')
            
            if available_flexible >= amount_needed:
                if self.bot.paper_trading:
                    # Simulation retrait
                    remaining = amount_needed
                    for pos in self.earn_positions['flexible_savings']:
                        if pos['status'] == 'active' and remaining > 0:
                            withdraw = min(pos['amount'], remaining)
                            pos['amount'] -= withdraw
                            remaining -= withdraw
                            self.bot.paper_balance += withdraw
                            
                            if pos['amount'] <= 0:
                                pos['status'] = 'withdrawn'
                    
                    return True
                else:
                    # Mode live avec API réelle
                    remaining = amount_needed
                    for pos in self.earn_positions['flexible_savings']:
                        if pos['status'] == 'active' and remaining > 0:
                            if 'product_id' not in pos:
                                continue
                            
                            withdraw = min(pos['amount'], remaining)
                            result = self.redeem_flexible_product(
                                pos['product_id'],
                                withdraw,
                                'FAST'
                            )
                            
                            if result and result.get('success'):
                                pos['amount'] -= withdraw
                                remaining -= withdraw
                                
                                if pos['amount'] <= 0:
                                    pos['status'] = 'withdrawn'
                            else:
                                return False
                    
                    return remaining == 0
            else:
                return False
                
        except Exception as e:
            return False  # Échec (message affiché par appelant)
    
    def calculate_earn_rewards(self):
        """Calcule les rewards accumulés (simulation)"""
        total_rewards = 0
        
        for pos in self.earn_positions['flexible_savings']:
            if pos['status'] == 'active':
                start_date = datetime.fromisoformat(pos['start_date'])
                days_elapsed = (datetime.now() - start_date).days
                daily_rate = pos['apy'] / 365 / 100
                rewards = pos['amount'] * daily_rate * days_elapsed
                total_rewards += rewards
        
        for pos in self.earn_positions['locked_staking']:
            if pos['status'] == 'locked':
                start_date = datetime.fromisoformat(pos['start_date'])
                days_elapsed = (datetime.now() - start_date).days
                daily_rate = pos['apy'] / 365 / 100
                rewards = pos['amount'] * daily_rate * days_elapsed
                total_rewards += rewards
        
        return total_rewards
    
    def ensure_initialized(self):
        """Initialisation différée pour éviter les erreurs d'attributs"""
        if not self.initialized:
            try:
                # Forcer la recherche de produits
                self.refresh_available_products()
                # Sync silencieuse initiale
                self.silent_sync_earn_positions()
                self.initialized = True
            except:
                pass  # Silencieux si le bot n'est pas prêt
    
    def tirelire_auto_manage(self):
        """Gestion automatique tirelire: < 5 USDT → Earn, Earn >= 5 USDT → Spot"""
        # Vérifier si Earn est activé
        if not self.enabled:
            return
            
        # Initialisation différée
        self.ensure_initialized()
        
        # Sync temps réel des positions Earn
        self.sync_earn_positions_from_api()
        
        available_balance = self.get_available_balance()
        summary = self.get_earn_summary()
        earn_balance = summary['flexible_savings']
        
        # Règle 1: Si Spot < 5 USDT ET > 0.01 USDT → Mettre dans Earn
        if 0.01 < available_balance < self.min_trading_balance:
            print(f"🐷 Tentative: {available_balance:.2f} USDT → Earn...")
            if self.allocate_to_flexible_savings(available_balance):
                self.save_earn_positions()
                print(f"🐷 {available_balance:.2f} USDT → Earn ✅")
                print()  # Ligne vide après succès
            else:
                print(f"🐷 {available_balance:.2f} USDT → Earn ❌ (API Earn désactivée)")
                print()  # Ligne vide après erreur
        
        # Règle 2: Si Earn >= 5 USDT → Retirer vers Spot
        elif earn_balance >= self.earn_withdraw_threshold:
            if self.withdraw_from_flexible(earn_balance):
                self.save_earn_positions()
                print(f"🐷 {earn_balance:.2f} → Spot ✅")
                print()  # Ligne vide après succès
                if hasattr(self.bot, 'notifier'):
                    self.bot.notifier.notify(f"🐷 Tirelire: {earn_balance:.2f} USDT → Spot")
            else:
                print(f"🐷 {earn_balance:.2f} → Spot ❌ Erreur retrait")
                print()  # Ligne vide après erreur
        
        else:
            print(f"🐷 OK (Spot {available_balance:.2f} | Earn {earn_balance:.2f})")
            print()  # Ligne vide après le statut tirelire
    
    def get_earn_summary(self):
        """Résumé des positions Earn"""
        flexible_total = sum(pos['amount'] for pos in self.earn_positions['flexible_savings'] 
                           if pos['status'] == 'active')
        locked_total = sum(pos['amount'] for pos in self.earn_positions['locked_staking'] 
                         if pos['status'] == 'locked')
        total_rewards = self.calculate_earn_rewards()
        
        return {
            'flexible_savings': flexible_total,
            'locked_staking': locked_total,
            'total_invested': flexible_total + locked_total,
            'estimated_rewards': total_rewards,
            'total_value': flexible_total + locked_total + total_rewards
        }
    
    def show_earn_performance(self):
        """Affiche les performances Earn avec détection WebSocket des changements"""
        if not self.enabled:
            return
        
        summary = self.get_earn_summary()
        current_balance = summary['total_invested']
        current_rewards = summary['estimated_rewards']
        
        # Détection WebSocket des changements (seuils ultra-bas)
        balance_changed = abs(current_balance - self.last_earn_balance) > 0.00000001
        rewards_changed = abs(current_rewards - self.last_earn_rewards) > 0.00000001
        
        if current_balance > 0.00000001:
            # Affichage détaillé avec précision maximale
            display_text = f"🏦 EARN: Flex {summary['flexible_savings']:.8f} | Lock {summary['locked_staking']:.8f} | +{current_rewards:.8f} → Total {summary['total_value']:.8f} USDT"
            
            # WebSocket: Détecter profit en temps réel (même minime)
            if rewards_changed and current_rewards > self.last_earn_rewards:
                profit_increase = current_rewards - self.last_earn_rewards
                display_text += f" 📈 +{profit_increase:.8f}"
            
            print(display_text)
        else:
            # Log silencieux si Earn vide (pas d'affichage)
            pass
        
        # Mettre à jour le tracking
        self.last_earn_balance = current_balance
        self.last_earn_rewards = current_rewards
