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
        self._balance_cache = {}
        self._cache_timestamp = 0
        
    def _get_allowed_assets(self):
        """Récupère la liste des cryptos autorisées depuis TRADING_PAIRS"""
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT').split(',')
        allowed_assets = set(['USDT'])  # USDT toujours autorisé
        
        for pair in trading_pairs:
            if '/' in pair:
                base = pair.split('/')[0]
            else:
                base = pair.replace('USDT', '')
            allowed_assets.add(base)
        
        return allowed_assets

    def _get_paper_balance(self):
        """Reconstruit la balance paper depuis l'USDT simulé et l'état des positions."""
        balance = {
            'USDT': {
                'free': self.bot.paper_balance,
                'used': 0,
                'total': self.bot.paper_balance
            }
        }

        positions = getattr(self.bot, 'state', {}).get('positions', [])
        for position in positions:
            symbol = position.get('symbol', '')
            if not symbol or '/' not in symbol:
                continue

            asset = symbol.split('/')[0]
            amount = float(position.get('amount', 0) or 0)
            if amount <= 0:
                continue

            asset_balance = balance.setdefault(asset, {'free': 0, 'used': 0, 'total': 0})
            if position.get('side') == 'buy':
                asset_balance['free'] += amount
            elif position.get('side') == 'sell':
                asset_balance['free'] -= amount

        for asset, data in balance.items():
            if asset == 'USDT':
                continue
            data['free'] = max(0, data['free'])
            data['total'] = data['free'] + data.get('used', 0)

        return balance
    
    def update_balance_from_websocket(self, balances_data):
        """Met à jour le cache depuis le WebSocket User Data Stream"""
        try:
            allowed_assets = self._get_allowed_assets()
            
            # Format Binance WebSocket: liste de balances
            if isinstance(balances_data, list):
                for balance in balances_data:
                    asset = balance.get('a')  # asset
                    free = float(balance.get('f', 0))  # free
                    locked = float(balance.get('l', 0))  # locked
                    
                    if asset in allowed_assets:
                        self._balance_cache[asset] = {
                            'free': free,
                            'used': locked,
                            'total': free + locked
                        }
            
            self._cache_timestamp = time.time()
        except Exception as e:
            pass  # Silencieux
    
    def get_balance(self, force_refresh=False):
        """Récupère le solde SPOT temps réel via WebSocket (limité aux TRADING_PAIRS)"""
        if self.bot.paper_trading:
            return self._get_paper_balance()
        
        allowed_assets = self._get_allowed_assets()
        
        # Utiliser cache WebSocket si disponible et récent (< 30s)
        if not force_refresh and self._balance_cache and (time.time() - self._cache_timestamp) < 30:
            return self._balance_cache
        
        # Fallback API REST si cache vide ou force_refresh
        if hasattr(self.bot, 'exchange') and self.bot.exchange:
            full_balance = self.bot.safe_request(self.bot.exchange.fetch_balance)
            filtered_balance = {asset: data for asset, data in full_balance.items() if asset in allowed_assets}
            
            # Mettre à jour le cache
            self._balance_cache = filtered_balance
            self._cache_timestamp = time.time()
            
            return filtered_balance
        else:
            return {'USDT': {'free': self.bot.paper_balance, 'used': 0, 'total': self.bot.paper_balance}}
    
    def get_funding_balance(self):
        """Récupère le solde du portefeuille de financement (limité aux TRADING_PAIRS)"""
        if self.bot.paper_trading:
            return {}  # Pas de funding en paper trading
        
        allowed_assets = self._get_allowed_assets()
        dust_threshold = 0.01  # Ignorer valeurs < 0.01 USDT
            
        try:
            # Essayer avec les paramètres de type
            funding_balance = self.bot.exchange.fetch_balance(params={'type': 'funding'})
            # Filtrer seulement les cryptos autorisées ET non-dust
            filtered_balance = {}
            for asset, data in funding_balance.items():
                if (asset in allowed_assets and 
                    isinstance(data, dict) and 
                    data.get('total', 0) > dust_threshold):
                    filtered_balance[asset] = data
            return filtered_balance
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
                        asset = balance['asset']
                        free = float(balance.get('free', 0))
                        locked = float(balance.get('locked', 0))
                        total = free + locked
                        
                        # Filtrer: crypto autorisée ET valeur > seuil dust
                        if (asset in allowed_assets and total > dust_threshold):
                            funding_balance[asset] = {
                                'free': free,
                                'used': locked,
                                'total': total
                            }
                    return funding_balance
                return {}
            except Exception as e:
                # Silencieux si erreur d'accès
                return {}
    
    def get_all_balances(self):
        """Récupère tous les soldes (Spot + Funding + Earn) limités aux TRADING_PAIRS"""
        allowed_assets = self._get_allowed_assets()
        
        balances = {
            'spot': self.get_balance(),
            'funding': self.get_funding_balance(),
            'earn': {}
        }
        
        # Ajouter les balances Earn si disponibles (seulement cryptos autorisées)
        if hasattr(self.bot, 'earn_manager'):
            try:
                earn_positions = self.bot.earn_manager.get_earn_positions()
                for pos in earn_positions:
                    asset = pos.get('asset', 'UNKNOWN')
                    amount = float(pos.get('amount', 0))
                    # Filtrer seulement les cryptos autorisées
                    if amount > 0 and asset in allowed_assets:
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
            # Notification silencieuse pour erreurs de permissions
            if "permissions" in str(e).lower() or "api-key" in str(e).lower():
                if hasattr(self.bot, 'notifier') and self.bot.notifier:
                    self.bot.notifier.notify_silent_error("Transfert Funding→Spot", str(e))
            return False
    
    def auto_transfer_funding_to_spot(self):
        """Transfère automatiquement et silencieusement les fonds du Funding vers Spot (limité aux TRADING_PAIRS)"""
        if self.bot.paper_trading:
            return  # Pas de transfert en paper trading
        
        allowed_assets = self._get_allowed_assets()
        min_transfer_threshold = 1.0  # Minimum 1 USDT pour transférer
            
        try:
            funding_balance = self.get_funding_balance()
            if not funding_balance:
                return  # Pas de fonds en funding
            
            transferred_any = False
            
            for asset in allowed_assets:
                available = funding_balance.get(asset, {}).get('free', 0)
                
                # Seuil plus élevé pour éviter les micro-transferts
                if available >= min_transfer_threshold:
                    try:
                        if self.transfer_from_funding_to_spot(asset, available):
                            transferred_any = True
                    except Exception as transfer_error:
                        # Silencieux - continuer avec les autres assets
                        continue
            
            if transferred_any:
                print(f"✅ Transferts Funding → Spot terminés")
                
        except Exception as e:
            # Silencieux - pas d'affichage d'erreur
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
