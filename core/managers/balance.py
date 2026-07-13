"""Gestionnaire centralisé des balances spot."""
import time
import os

class BalanceManager:
    """Gestionnaire centralisé pour les soldes spot et paper."""
    
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
            
            # Format WebSocket de balance: liste de soldes
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
    
    def get_all_balances(self):
        """Récupère les soldes spot limités aux TRADING_PAIRS."""
        return {'spot': self.get_balance()}
    
    def ensure_trading_balance(self, trade_amount):
        """S'assure qu'il y a assez de fonds pour trader"""
        if self.bot.paper_trading:
            return True
            
        try:
            balance = self.get_balance()
            available = balance.get('USDT', {}).get('free', 0)
            needed_balance = trade_amount * 1.2
            
            if available < needed_balance:
                return False
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur vérification balance: {e}")
            return False
    
    def get_total_balance_usdt(self):
        """Calcule le solde spot total en USDT."""
        try:
            spot_balance = self.get_balance()
            spot_usdt = spot_balance.get('USDT', {}).get('free', 0)
            
            return {
                'total': spot_usdt,
                'spot': spot_usdt
            }
            
        except Exception as e:
            print(f"⚠️ Erreur calcul balance totale: {e}")
            return {'total': 0, 'spot': 0}
    
    def show_balance_summary(self):
        """Affiche un résumé complet des balances"""
        try:
            balances = self.get_total_balance_usdt()
            
            print(f"\n💰 RÉSUMÉ BALANCES USDT:")
            print(f"   Spot: {balances['spot']:.2f}")
            print(f"   ─────────────────")
            print(f"   Total: {balances['total']:.2f}")
            
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
        """Test et affiche la balance spot."""
        try:
            print("🔍 Test balance spot...")
            
            # Test Spot
            spot_balance = self.get_balance()
            usdt_spot = spot_balance.get('USDT', {}).get('free', 0)
            print(f"💰 Balance SPOT USDT: {usdt_spot:.2f}")
            
            # Résumé
            self.show_balance_summary()
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur test balances: {e}")
            return False
