"""Gestionnaire centralisé des balances spot."""
import time
import os

class BalanceManager:
    """Gestionnaire centralisé pour les soldes spot et paper."""
    
    def __init__(self, bot):
        self.bot = bot
        self._balance_cache = {}
        self._cache_timestamp = 0
        self._last_ledger_sync = 0
        self._last_ledger_import_count = 0
        self._ledger_sync_interval = int(os.getenv('KRAKEN_LEDGER_SYNC_INTERVAL_SECONDS', '300'))
        self._ledger_sync_enabled = os.getenv('KRAKEN_LEDGER_SYNC_ENABLED', 'True').lower() == 'true'
        self._ledger_sync_disabled_reason = None
        self._last_ledger_error_log = 0
        
    def _get_allowed_assets(self):
        """Récupère la liste des cryptos autorisées depuis TRADING_PAIRS"""
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD').split(',')
        allowed_assets = set(['USD', 'USDT', 'USDC', 'CAD'])
        extra_assets = os.getenv('EXTRA_BALANCE_ASSETS', '')
        for asset in extra_assets.split(','):
            asset = asset.strip().upper()
            if asset:
                allowed_assets.add(asset)
        
        for pair in trading_pairs:
            if '/' in pair:
                base = pair.split('/')[0]
            else:
                base = pair.replace('USDT', '').replace('USD', '')
            allowed_assets.add(base)
        
        return allowed_assets

    def _normalize_asset(self, asset):
        """Normalise les codes Kraken/CCXT vers les codes affiches par Aegis."""
        value = str(asset or '').upper()
        aliases = {
            'XXBT': 'BTC',
            'XBT': 'BTC',
            'XETH': 'ETH',
            'ZUSD': 'USD',
            'ZCAD': 'CAD',
            'ZUSDT': 'USDT',
        }
        return aliases.get(value, value)

    def _normalize_balance_payload(self, raw_balance):
        allowed_assets = self._get_allowed_assets()
        normalized = {}
        if not isinstance(raw_balance, dict):
            return normalized
        for asset, data in raw_balance.items():
            if asset in ('free', 'used', 'total', 'info') or not isinstance(data, dict):
                continue
            norm_asset = self._normalize_asset(asset)
            if norm_asset not in allowed_assets:
                continue
            free = float(data.get('free') or 0.0)
            used = float(data.get('used') if data.get('used') is not None else data.get('locked') or 0.0)
            total_raw = data.get('total')
            total = float(total_raw) if total_raw is not None else free + used
            normalized[norm_asset] = {
                'free': free,
                'used': used,
                'locked': used,
                'total': total,
            }
        return normalized

    def _persist_live_balance(self, balance):
        if self.bot.paper_trading:
            return
        try:
            logger = getattr(self.bot, 'ml_live_logger', None)
            if logger:
                logger.sync_external_balances(balance, mode='live')
        except Exception:
            pass

    def _sync_exchange_ledger_if_due(self, force=False):
        if self.bot.paper_trading:
            return 0
        if not self._ledger_sync_enabled or self._ledger_sync_disabled_reason:
            return 0
        now = time.time()
        if not force and now - self._last_ledger_sync < self._ledger_sync_interval:
            return 0
        self._last_ledger_sync = now
        self._last_ledger_import_count = 0
        try:
            logger = getattr(self.bot, 'ml_live_logger', None)
            exchange = getattr(self.bot, 'exchange', None)
            if not logger or not exchange or not hasattr(exchange, 'fetch_ledger'):
                return 0
            since = logger.latest_exchange_ledger_since_ms(mode='live', source='kraken_ledger')
            entries = self.bot.safe_request(exchange.fetch_ledger, None, since, 100) if hasattr(self.bot, 'safe_request') else exchange.fetch_ledger(None, since, 100)
            if not entries:
                return 0
            imported = logger.import_exchange_ledger(entries, mode='live', source='kraken_ledger')
            self._last_ledger_import_count = imported
            return imported
        except Exception as exc:
            error_text = str(exc)
            if 'Permission denied' in error_text or 'EGeneral:Permission denied' in error_text:
                self._ledger_sync_disabled_reason = 'permission_denied'
                print(
                    "⚠️ Ledger Kraken non importé: permission API manquante "
                    "(activer le droit Kraken de lecture ledger, ou mettre KRAKEN_LEDGER_SYNC_ENABLED=False)."
                )
                return 0
            if force or now - self._last_ledger_error_log > 300:
                self._last_ledger_error_log = now
                print(f"⚠️ Erreur import ledger Kraken: {exc}")
            return 0

    def _get_paper_balance(self):
        """Lit la balance paper depuis la couche comptable, avec fallback runtime."""
        try:
            logger = getattr(self.bot, 'ml_live_logger', None)
            if logger:
                conn = logger._get_conn()
                account_id = logger._account_id('paper')
                rows = conn.execute(
                    "SELECT asset, free, locked, total FROM balances WHERE account_id=?",
                    (account_id,),
                ).fetchall()
                if rows:
                    balance = {}
                    for asset, free, locked, total in rows:
                        balance[asset] = {
                            'free': float(free or 0.0),
                            'used': float(locked or 0.0),
                            'total': float(total or 0.0),
                        }
                    usd = balance.get('USD') or balance.get('USDT')
                    if usd:
                        self.bot.paper_balance = round(float(usd.get('free') or 0.0), 2)
                    return balance
        except Exception:
            pass

        """Reconstruit la balance paper depuis l'USD simulé et l'état des positions."""
        balance = {
            'USD': {
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
            side = position.get('side')
            status = position.get('status')
            if side == 'buy' and status != 'canceled':
                asset_balance['free'] += amount
            elif side == 'sell':
                if status == 'opened':
                    asset_balance['used'] += amount
                    asset_balance['free'] -= amount
                elif status in ('executed', 'filled'):
                    asset_balance['free'] -= amount

        for asset, data in balance.items():
            if asset in ('USD', 'USDT'):
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
                    asset = self._normalize_asset(balance.get('a'))  # asset
                    free = float(balance.get('f', 0))  # free
                    locked = float(balance.get('l', 0))  # locked
                    
                    if asset in allowed_assets:
                        self._balance_cache[asset] = {
                            'free': free,
                            'used': locked,
                            'locked': locked,
                            'total': free + locked
                        }
            
            self._cache_timestamp = time.time()
            self._persist_live_balance(self._balance_cache)
        except Exception as e:
            pass  # Silencieux
    
    def get_balance(self, force_refresh=False, skip_ledger_sync=False):
        """Récupère le solde SPOT temps réel via WebSocket (limité aux TRADING_PAIRS)
        
        Args:
            force_refresh: Force un appel API même si le cache est récent
            skip_ledger_sync: Skip le sync ledger Kraken (pour les exits urgents)
        """
        if self.bot.paper_trading:
            return self._get_paper_balance()
        
        allowed_assets = self._get_allowed_assets()
        
        # Utiliser cache WebSocket si disponible et récent (< 30s)
        if not force_refresh and self._balance_cache and (time.time() - self._cache_timestamp) < 30:
            return self._balance_cache
        
        # Fallback API REST si cache vide ou force_refresh
        if hasattr(self.bot, 'exchange') and self.bot.exchange:
            full_balance = self.bot.safe_request(self.bot.exchange.fetch_balance)
            filtered_balance = self._normalize_balance_payload(full_balance)
            
            # Mettre à jour le cache
            self._balance_cache = filtered_balance
            self._cache_timestamp = time.time()
            self._persist_live_balance(filtered_balance)
            if not skip_ledger_sync:
                self._sync_exchange_ledger_if_due(force=force_refresh)
            
            return filtered_balance
        else:
            return {'USD': {'free': self.bot.paper_balance, 'used': 0, 'total': self.bot.paper_balance}}
    
    def get_all_balances(self):
        """Récupère les soldes spot limités aux TRADING_PAIRS."""
        return {'spot': self.get_balance()}
    
    def ensure_trading_balance(self, trade_amount):
        """S'assure qu'il y a assez de fonds pour trader"""
        if self.bot.paper_trading:
            return True
            
        try:
            balance = self.get_balance()
            available = (balance.get('USD') or balance.get('USDT') or {}).get('free', 0)
            needed_balance = trade_amount * 1.2
            
            if available < needed_balance:
                return False
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur vérification balance: {e}")
            return False
    
    def get_total_balance_usd(self):
        """Calcule le solde spot total en USD."""
        try:
            spot_balance = self.get_balance()
            spot_usd = (spot_balance.get('USD') or spot_balance.get('USDT') or {}).get('free', 0)
            
            return {
                'total': spot_usd,
                'spot': spot_usd
            }
            
        except Exception as e:
            print(f"⚠️ Erreur calcul balance totale: {e}")
            return {'total': 0, 'spot': 0}
    
    def force_balance_sync(self):
        print(f"🔄 Synchronisation manuelle des balances...")
        balance = self.get_balance(force_refresh=True)
        self._persist_live_balance(balance)
        imported = self._last_ledger_import_count
        
        if hasattr(self.bot, 'sync_positions_from_exchange'):
            self.bot.sync_positions_from_exchange()
        if hasattr(self.bot, 'save_state'):
            self.bot.save_state()
        
        suffix = f" | Ledger Kraken: {imported} entrée(s)" if not self.bot.paper_trading else ""
        print(f"✅ Balances et positions mises à jour{suffix}")
