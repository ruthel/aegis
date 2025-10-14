import time
import json
import os
from datetime import datetime, timedelta
from core.binance_earn_api import BinanceEarnAPI

class BinanceEarnManager:
    def __init__(self, bot):
        self.bot = bot
        self.enabled = os.getenv('ENABLE_EARN', 'True') == 'True'
        self.tirelire_mode = os.getenv('TIRELIRE_MODE', 'False') == 'True'
        self.min_trading_balance = float(os.getenv('MIN_TRADING_BALANCE', '10'))
        self.earn_allocation_percent = float(os.getenv('EARN_ALLOCATION_PERCENT', '80'))
        self.flexible_threshold = float(os.getenv('FLEXIBLE_SAVINGS_THRESHOLD', '5'))
        self.locked_threshold = float(os.getenv('LOCKED_STAKING_THRESHOLD', '50'))
        self.earn_withdraw_threshold = float(os.getenv('EARN_WITHDRAW_THRESHOLD', '5'))
        
        # Tenter les nouvelles API Simple Earn (silencieux)
        if not bot.paper_trading:
            self.earn_api = BinanceEarnAPI(bot.api_key, bot.api_secret, testnet=False)
        else:
            self.earn_api = None
        
        self.earn_positions = self.load_earn_positions()
        self.last_allocation_check = 0
        self.allocation_interval = 3600  # 1 heure
        
        # Cache des produits disponibles
        self.usdt_flexible_product = None
        self.usdt_locked_product = None
        self.last_product_refresh = 0
        
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
        if self.earn_api is None:
            print("🎯 Flexible USDT: 3.5% APY (simulé)")
            print("🔒 Locked USDT 30j: 8.0% APY (simulé)")
            return
        
        now = time.time()
        if now - self.last_product_refresh < 3600:
            return
        
        try:
            self.usdt_flexible_product = self.earn_api.find_usdt_flexible_product()
            self.usdt_locked_product = self.earn_api.find_usdt_locked_product(30)
            self.last_product_refresh = now
            
            if self.usdt_flexible_product:
                print(f"🎯 Flexible USDT: {self.usdt_flexible_product.get('avgAnnualInterestRate', 3.5):.2f}% APY")
            if self.usdt_locked_product:
                print(f"🔒 Locked USDT 30j: {self.usdt_locked_product.get('interestRate', 8.0):.2f}% APY")
                
        except Exception as e:
            print(f"⚠️ Erreur nouvelles API Simple Earn: {e}")
            print("📝 Basculement vers mode simulation")
            self.earn_api = None
    
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
            balance = self.bot.get_balance()
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
            if self.earn_api is None or self.bot.paper_trading:
                # Mode simulation
                position = {
                    'amount': amount,
                    'product': 'USDT_FLEXIBLE',
                    'apy': 3.5,
                    'start_date': datetime.now().isoformat(),
                    'status': 'active'
                }
                self.earn_positions['flexible_savings'].append(position)
                if self.bot.paper_trading:
                    self.bot.paper_balance -= amount
                pass  # Message déjà affiché dans tirelire_auto_manage
                return True
            else:
                # Mode live avec nouvelles API
                if not self.usdt_flexible_product:
                    return False
                
                print(f"🔄 Tentative souscription LIVE: {amount:.2f} USDT")
                result = self.earn_api.subscribe_flexible_product(
                    self.usdt_flexible_product['productId'], 
                    amount
                )
                
                print(f"📝 Réponse API: {result}")
                
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
                    pass  # Message déjà affiché dans tirelire_auto_manage
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
    
    def sync_earn_positions_from_api(self):
        """Synchronise les positions Earn depuis l'API Binance"""
        if self.earn_api is None or self.bot.paper_trading:
            return
        
        try:
            result = self.earn_api.get_flexible_positions()
            if result and 'rows' in result:
                old_count = len([p for p in self.earn_positions['flexible_savings'] if p['status'] == 'active'])
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
                
                new_count = len(self.earn_positions['flexible_savings'])
                if new_count != old_count:
                    self.save_earn_positions()
                    
        except Exception as e:
            print(f"⚠️ Erreur sync Earn: {e}")
    
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
                            result = self.earn_api.redeem_flexible_product(
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
    
    def tirelire_auto_manage(self):
        """Gestion automatique tirelire: < 5 USDT → Earn, Earn >= 5 USDT → Spot"""
        if not self.tirelire_mode:
            return
        
        available_balance = self.get_available_balance()
        summary = self.get_earn_summary()
        earn_balance = summary['flexible_savings']
        
        # Règle 1: Si Spot < 5 USDT ET > 0.01 USDT → Mettre dans Earn
        if 0.01 < available_balance < self.min_trading_balance:
            if self.allocate_to_flexible_savings(available_balance):
                self.save_earn_positions()
                print(f"🐷 {available_balance:.2f} → Earn ✅")
            # Pas d'affichage si échec en paper trading (normal)
        
        # Règle 2: Si Earn >= 5 USDT → Retirer vers Spot
        elif earn_balance >= self.earn_withdraw_threshold:
            if self.withdraw_from_flexible(earn_balance):
                self.save_earn_positions()
                print(f"🐷 {earn_balance:.2f} → Spot ✅")
                if self.bot.notify_trades:
                    self.bot.notifier.notify(f"🐷 Tirelire: {earn_balance:.2f} USDT → Spot")
            else:
                print(f"🐷 {earn_balance:.2f} → Spot ❌ Erreur retrait")
        
        else:
            print(f"🐷 OK (Spot {available_balance:.2f} | Earn {earn_balance:.2f})")
    
    def auto_allocate_idle_funds(self):
        """Allocation automatique des fonds inactifs"""
        # Mode tirelire prioritaire
        if self.tirelire_mode:
            self.tirelire_auto_manage()
            return
        """Allocation automatique des fonds inactifs"""
        if not self.should_allocate_to_earn():
            return
        
        available_balance = self.get_available_balance()
        allocation_amount, allocation_type = self.calculate_allocation(available_balance)
        
        if allocation_amount > 0:
            print(f"\n💼 EARN ALLOCATION")
            print(f"💰 Solde disponible: {available_balance:.2f} USDT")
            print(f"📊 Montant à allouer: {allocation_amount:.2f} USDT")
            print(f"🎯 Type: {allocation_type}")
            
            if allocation_type == 'flexible_savings':
                success = self.allocate_to_flexible_savings(allocation_amount)
            elif allocation_type == 'locked_staking':
                success = self.allocate_to_locked_staking(allocation_amount)
            
            if success:
                self.save_earn_positions()
                if self.bot.notify_trades:
                    self.bot.notifier.notify(f"🏦 Earn: {allocation_amount:.2f} USDT → {allocation_type}")
        else:
            if allocation_type == 'insufficient_balance':
                print(f"💼 Solde insuffisant pour Earn: {available_balance:.2f} < {self.min_trading_balance}")
            elif allocation_type == 'amount_too_small':
                print(f"💼 Montant trop petit pour Earn: {allocation_amount:.2f} < {self.flexible_threshold}")
    
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
        """Affiche les performances Earn (format compact)"""
        if not self.enabled:
            return
        
        summary = self.get_earn_summary()
        
        if summary['total_invested'] > 0:
            # Format détaillé si Earn actif
            print(f"🏦 EARN: Flex {summary['flexible_savings']:.2f} | Lock {summary['locked_staking']:.2f} | +{summary['estimated_rewards']:.2f} → Total {summary['total_value']:.2f} USDT")
        else:
            # Format minimal si Earn vide
            print(f"🏦 EARN: 0.00 USDT (vide)")