"""Gestionnaire centralisé des balances - Spot, Funding, Earn"""
import time
import os
import requests
import hmac
import hashlib

class BalanceManager:
    """Gestionnaire centralisé pour toutes les opérations de balance"""
    
    def __init__(self, bot):
        self.bot = bot
        
    def get_balance(self, force_refresh=False):
        """Récupère le solde SPOT avec cache intelligent"""
        if self.bot.paper_trading:
            return {'USDT': {'free': self.bot.paper_balance}}
        
        if force_refresh:
            # Appel direct sans cache
            return self.bot.safe_request(self.bot.exchange.fetch_balance)
        else:
            # Utiliser le cache du bot si disponible
            if hasattr(self.bot, 'balance_cache') and 'balance' in self.bot.balance_cache:
                cache_age = time.time() - self.bot.balance_cache['timestamp']
                if cache_age < 3:  # 3 secondes de cache
                    return self.bot.balance_cache['balance']
            
            # Sinon faire un appel API
            balance = self.bot.safe_request(self.bot.exchange.fetch_balance)
            
            # Mettre en cache dans le bot
            if not hasattr(self.bot, 'balance_cache'):
                self.bot.balance_cache = {}
            self.bot.balance_cache = {
                'balance': balance,
                'timestamp': time.time()
            }
            
            return balance
    
    def get_funding_balance(self):
        """Récupère le solde du portefeuille de financement"""
        try:
            # Essayer avec les paramètres de type
            funding_balance = self.bot.exchange.fetch_balance(params={'type': 'funding'})
            return funding_balance
        except:
            try:
                # Essayer sans paramètres spéciaux
                all_balances = self.bot.exchange.fetch_balance()
                # Binance retourne parfois les balances funding dans 'info'
                info = all_balances.get('info', {})
                if 'balances' in info:
                    # Chercher les balances avec type funding
                    funding_balance = {}
                    for balance in info['balances']:
                        if float(balance.get('free', 0)) > 0:
                            asset = balance['asset']
                            funding_balance[asset] = {
                                'free': float(balance['free']),
                                'used': float(balance.get('locked', 0)),
                                'total': float(balance['free']) + float(balance.get('locked', 0))
                            }
                    return funding_balance
                return {}
            except Exception as e:
                print(f"⚠️ Impossible d'accéder au portefeuille de financement: {e}")
                return {}
    
    def get_all_balances(self):
        """Récupère tous les soldes (Spot + Funding + Earn)"""
        balances = {
            'spot': self.get_balance(),
            'funding': self.get_funding_balance(),
            'earn': {}
        }
        
        # Ajouter les balances Earn si disponibles
        if hasattr(self.bot, 'earn_manager'):
            try:
                earn_positions = self.bot.earn_manager.get_earn_positions()
                for pos in earn_positions:
                    asset = pos.get('asset', 'UNKNOWN')
                    amount = float(pos.get('amount', 0))
                    if amount > 0:
                        balances['earn'][asset] = {
                            'free': amount,
                            'used': 0,
                            'total': amount,
                            'type': pos.get('productName', 'Unknown')
                        }
            except:
                pass
        
        return balances
    
    def transfer_from_funding_to_spot(self, asset='USDT', amount=None):
        """Transfère automatiquement des fonds du portefeuille de financement vers le spot"""
        try:
            funding_balance = self.get_funding_balance()
            available = funding_balance.get(asset, {}).get('free', 0)
            
            if available <= 0.01:
                return False
            
            transfer_amount = amount if amount else available
            transfer_amount = min(transfer_amount, available)
            
            print(f"💸 Transfert {transfer_amount:.2f} {asset}: Funding → Spot...")
            
            result = self.bot.exchange.transfer(asset, transfer_amount, 'funding', 'spot')
            
            if result.get('id') or result.get('tranId'):
                print(f"✅ {transfer_amount:.2f} {asset} transféré vers SPOT")
                time.sleep(1)
                self.get_balance(force_refresh=True)
                return True
            return False
                
        except Exception as e:
            return False
    
    def auto_transfer_funding_to_spot(self):
        """Transfère automatiquement et silencieusement les fonds du Funding vers Spot"""
        try:
            funding_balance = self.get_funding_balance()
            for asset in ['USDT', 'BTC', 'ETH', 'BNB', 'SOL']:
                available = funding_balance.get(asset, {}).get('free', 0)
                if available > 0.01:
                    self.transfer_from_funding_to_spot(asset, available)
        except:
            pass
    
    def ensure_trading_balance(self, trade_amount):
        """S'assure qu'il y a assez de fonds pour trader"""
        if self.bot.paper_trading:
            return True
            
        try:
            balance = self.get_balance()
            available = balance.get('USDT', {}).get('free', 0)
            needed_balance = trade_amount * 1.2
            
            if available < needed_balance:
                shortage = needed_balance - available
                
                # Essayer de retirer des fonds Earn
                if hasattr(self.bot, 'earn_manager'):
                    if self.bot.earn_manager.withdraw_from_flexible(shortage):
                        time.sleep(2)
                        return True
                
                # Vérifier le portefeuille de financement
                funding_balance = self.get_funding_balance()
                usdt_funding = funding_balance.get('USDT', {}).get('free', 0)
                
                if usdt_funding >= shortage:
                    print(f"💰 Fonds USDT détectés en financement: {usdt_funding:.2f}")
                    return self.transfer_from_funding_to_spot('USDT', shortage)
                
                return False
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur vérification balance: {e}")
            return False
    
    def get_total_balance_usdt(self):
        """Calcule le solde total en USDT (Spot + Funding + Earn)"""
        try:
            all_balances = self.get_all_balances()
            total_usdt = 0
            
            # Spot USDT
            spot_usdt = all_balances['spot'].get('USDT', {}).get('free', 0)
            total_usdt += spot_usdt
            
            # Funding USDT
            funding_usdt = all_balances['funding'].get('USDT', {}).get('free', 0)
            total_usdt += funding_usdt
            
            # Earn USDT
            earn_usdt = all_balances['earn'].get('USDT', {}).get('free', 0)
            total_usdt += earn_usdt
            
            return {
                'total': total_usdt,
                'spot': spot_usdt,
                'funding': funding_usdt,
                'earn': earn_usdt
            }
            
        except Exception as e:
            print(f"⚠️ Erreur calcul balance totale: {e}")
            return {'total': 0, 'spot': 0, 'funding': 0, 'earn': 0}
    
    def show_balance_summary(self):
        """Affiche un résumé complet des balances"""
        try:
            balances = self.get_total_balance_usdt()
            
            print(f"\n💰 RÉSUMÉ BALANCES USDT:")
            print(f"   Spot: {balances['spot']:.2f}")
            print(f"   Funding: {balances['funding']:.2f}")
            print(f"   Earn: {balances['earn']:.2f}")
            print(f"   ─────────────────")
            print(f"   Total: {balances['total']:.2f}")
            
            # Recommandations
            if balances['funding'] > 0.01:
                print(f"📝 Transférer {balances['funding']:.2f} USDT de Funding vers Spot")
            
            if balances['total'] > 0 and balances['spot'] < balances['total'] * 0.1:
                print(f"⚠️ Seulement {(balances['spot']/balances['total']*100):.1f}% des fonds en Spot")
            
        except Exception as e:
            print(f"⚠️ Erreur affichage résumé: {e}")
    
    def force_balance_sync(self):
        """Force la synchronisation manuelle des balances (pour debug)"""
        print(f"🔄 Synchronisation manuelle des balances...")
        self.get_balance(force_refresh=True)
        
        if hasattr(self.bot, 'sync_positions_from_exchange'):
            self.bot.sync_positions_from_exchange()
        if hasattr(self.bot, 'save_state'):
            self.bot.save_state()
        
        print(f"✅ Balances et positions mises à jour")
    
    def test_all_balances(self):
        """Test et affiche tous les types de balances"""
        try:
            print("🔍 Test de tous les portefeuilles...")
            
            # Test Spot
            spot_balance = self.get_balance()
            usdt_spot = spot_balance.get('USDT', {}).get('free', 0)
            print(f"💰 Balance SPOT USDT: {usdt_spot:.2f}")
            
            # Test Funding
            funding_balance = self.get_funding_balance()
            usdt_funding = funding_balance.get('USDT', {}).get('free', 0)
            print(f"🏦 Balance FUNDING USDT: {usdt_funding:.2f}")
            
            # Test Earn
            if hasattr(self.bot, 'earn_manager'):
                try:
                    earn_positions = self.bot.earn_manager.get_earn_positions()
                    earn_total = sum(float(p.get('amount', 0)) for p in earn_positions if p.get('asset') == 'USDT')
                    print(f"💎 Balance EARN USDT: {earn_total:.2f}")
                except:
                    print(f"💎 Balance EARN USDT: Non disponible")
            
            # Résumé
            self.show_balance_summary()
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur test balances: {e}")
            return False