"""
Capital Manager - Gestion Automatique de Tous Capitaux (8+ USD)
Adaptation automatique selon le capital disponible + minimums exchange
Intègre Dynamic Fees Manager et Dust Manager
"""

import os
import time
from datetime import datetime, timedelta

class CapitalManager:
    """Gestionnaire automatique pour tous niveaux de capital + frais dynamiques + dust"""
    
    def __init__(self, bot):
        self.bot = bot
        self.min_amounts_cache = {}
        self.last_update = None
        
        # Dynamic Fees integration
        self.fees_cache = {}
        self.last_fees_update = 0
        self.fees_update_interval = 3600  # 1h
        self.vip_level = None
        
        # Dust Manager integration
        self.dust_thresholds_usd = {
            'BTC': 0.50, 'ETH': 0.50, 'SOL': 0.50, 'ADA': 0.50,
            'ADA': 0.10, 'DOT': 0.20, 'MATIC': 0.10, 'AVAX': 0.30,
            'LINK': 0.30, 'UNI': 0.20, 'LTC': 0.50, 'BCH': 0.50
        }
        
        self.safe_minimums = {
            'BTC/USD': {'min_amount': 0.00001, 'min_cost': 1.0},
            'ETH/USD': {'min_amount': 0.0001, 'min_cost': 1.0},
            'SOL/USD': {'min_amount': 0.01, 'min_cost': 1.0},
            'ADA/USD': {'min_amount': 0.001, 'min_cost': 1.0},
            'ADA/USD': {'min_amount': 1.0, 'min_cost': 1.0},
            'DOT/USD': {'min_amount': 0.1, 'min_cost': 1.0},
            'MATIC/USD': {'min_amount': 1.0, 'min_cost': 1.0},
            'AVAX/USD': {'min_amount': 0.01, 'min_cost': 1.0},
            'LINK/USD': {'min_amount': 0.01, 'min_cost': 1.0},
            'UNI/USD': {'min_amount': 0.01, 'min_cost': 1.0},
            'LTC/USD': {'min_amount': 0.001, 'min_cost': 1.0},
            'BCH/USD': {'min_amount': 0.001, 'min_cost': 1.0}
        }

    def _configured_float(self, key, fallback):
        value = os.getenv(key)
        if value is None or str(value).strip() == '':
            return float(fallback)
        try:
            return float(value)
        except Exception:
            return float(fallback)

    def _configured_int(self, key, fallback):
        value = os.getenv(key)
        if value is None or str(value).strip() == '':
            return int(fallback)
        try:
            return int(value)
        except Exception:
            return int(fallback)

    def _active_mode(self):
        return 'paper' if getattr(self.bot, 'paper_trading', True) else 'live'

    def _total_balance_usd(self):
        try:
            if getattr(self.bot, 'paper_trading', True):
                return float(getattr(self.bot, 'paper_balance', 0.0) or 0.0)
            if hasattr(self.bot, 'get_account_balance'):
                return float(self.bot.get_account_balance() or 0.0)
            if hasattr(self.bot, 'balance_manager'):
                balance_info = self.bot.balance_manager.get_total_balance_usd()
                if isinstance(balance_info, dict):
                    return float(balance_info.get('total') or 0.0)
            return 0.0
        except Exception:
            return 0.0

    def get_max_total_exposure_pct(self, total_balance_usd=None):
        """Plafond d'exposition dynamique selon la taille du capital."""
        try:
            total = self._total_balance_usd() if total_balance_usd is None else float(total_balance_usd or 0.0)
        except Exception:
            total = 0.0
        if total < 50:
            return 100.0
        if total < 100:
            return 80.0
        if total < 300:
            return 70.0
        return 60.0

    def get_max_position_exposure_pct(self, total_balance_usd=None):
        """Plafond dynamique par position selon la taille du capital."""
        try:
            total = self._total_balance_usd() if total_balance_usd is None else float(total_balance_usd or 0.0)
        except Exception:
            total = 0.0
        if total < 50:
            return 50.0
        if total < 100:
            return 35.0
        if total < 300:
            return 25.0
        return 15.0

    def get_max_position_size_usd(self, total_balance_usd=None):
        """Montant USD maximum autorisé pour une seule position."""
        try:
            total = self._total_balance_usd() if total_balance_usd is None else float(total_balance_usd or 0.0)
        except Exception:
            total = 0.0
        if total <= 0:
            return 0.0
        return round(total * (self.get_max_position_exposure_pct(total) / 100.0), 2)

    def get_total_capital(self):
        """Retourne le capital total du mode actif en equivalent USD."""
        return round(self._total_balance_usd(), 2)

    def get_available_cash_usd(self):
        """Retourne le cash immédiatement utilisable pour les paires USD."""
        try:
            if getattr(self.bot, 'paper_trading', True):
                return float(getattr(self.bot, 'paper_balance', 0.0) or 0.0)
            if hasattr(self.bot, 'balance_manager'):
                balance = self.bot.balance_manager.get_balance()
                cash = balance.get('USD') or balance.get('USDT') or balance.get('USDC') or {}
                return float(cash.get('free') or 0.0)
        except Exception:
            pass
        return 0.0

    def _open_positions_for_active_mode(self):
        mode = self._active_mode()
        try:
            logger = getattr(self.bot, 'ml_live_logger', None)
            if logger:
                conn = logger._get_conn()
                positions = logger._positions_from_accounting(conn, mode)
                return [
                    p for p in positions
                    if isinstance(p, dict)
                    and p.get('side') == 'buy'
                    and not p.get('closed_at')
                    and str(p.get('status') or '').lower() in {'opened', 'open', 'executed', 'filled', 'closed'}
                ]
        except Exception:
            pass

        if mode == 'paper':
            return [
                p for p in getattr(self.bot, 'state', {}).get('positions', [])
                if isinstance(p, dict) and p.get('side') == 'buy' and not p.get('closed_at')
            ]
        return []

    def get_trade_amount(self, symbol=None):
        """Retourne le montant d'un trade en USD adapté au capital et au mode safe."""
        try:
            total_balance = self._total_balance_usd()
            config = self.get_adaptive_config(total_balance)
            trade_amount = float(config.get('trade_amount', 50.0))
            if getattr(self.bot, 'safe_fallback_mode', False):
                trade_amount *= getattr(self.bot, 'bear_mode_trade_multiplier', 0.35)
            return round(trade_amount, 2)
        except Exception:
            return 1.0
        
    def get_adaptive_config(self, total_balance_usd):
        """Configuration automatique selon le capital avec limites de positions"""
        
        # Récupérer les montants minimums de l'exchange
        min_amounts = self._get_exchange_min_amounts()
        
        # Obtenir les limites de positions
        from utils.market_analyzer import MarketAnalyzer
        limits = MarketAnalyzer.get_position_limits(total_balance_usd)
        
        max_exposure_pct = self.get_max_total_exposure_pct(total_balance_usd)
        max_spot_allocation = max(0.0, min(1.0, max_exposure_pct / 100.0))
        configured_daily_loss = os.getenv('MAX_DAILY_LOSS')
        configured_max_positions = self._configured_int(
            'MAX_POSITIONS_PER_CRYPTO',
            min(int(limits.get('max_positions_per_crypto', 2)), 2)
        )
        configured_total_positions = self._configured_int(
            'MAX_TOTAL_POSITIONS',
            configured_max_positions * int(limits.get('max_tradeable_cryptos', 4))
        )

        if total_balance_usd < 20:
            # Mode Micro-Capital (8-20 USD)
            adaptive_daily_loss = max(10, total_balance_usd * 0.25)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 1), total_balance_usd * 0.15),
                'spot_allocation': max_spot_allocation,
                'cash_reserve': 1.0 - max_spot_allocation,
                'max_daily_loss': self._configured_float('MAX_DAILY_LOSS', adaptive_daily_loss) if configured_daily_loss is not None else adaptive_daily_loss,
                'max_positions': configured_max_positions,
                'max_tradeable_cryptos': limits['max_tradeable_cryptos'],
                'total_max_positions': configured_total_positions,
                'aggressive_mode': True,
                'compound_rate': 1.0,  # 100% réinvestissement
                'min_profit_threshold': 0.5,  # 0.5% minimum
                'stop_loss_percent': 3.0,  # Stop serré
                'preferred_cryptos': ['DOGE', 'SHIB', 'PEPE']  # Volatiles
            }
            
        elif total_balance_usd < 50:
            # Mode Croissance (20-50 USD)
            adaptive_daily_loss = max(10, total_balance_usd * 0.20)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 2), total_balance_usd * 0.12),
                'spot_allocation': max_spot_allocation,
                'cash_reserve': 1.0 - max_spot_allocation,
                'max_daily_loss': self._configured_float('MAX_DAILY_LOSS', adaptive_daily_loss) if configured_daily_loss is not None else adaptive_daily_loss,
                'max_positions': configured_max_positions,
                'max_tradeable_cryptos': limits['max_tradeable_cryptos'],
                'total_max_positions': configured_total_positions,
                'aggressive_mode': True,
                'compound_rate': 0.9,  # 90% réinvestissement
                'min_profit_threshold': 0.6,
                'stop_loss_percent': 4.0,
                'preferred_cryptos': ['BTC', 'ETH', 'DOGE', 'SHIB']
            }
            
        elif total_balance_usd < 200:
            # Mode Équilibré (50-200 USD)
            adaptive_daily_loss = max(10, total_balance_usd * 0.15)
            spot_allocation = min(0.95, max_spot_allocation)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 5), total_balance_usd * 0.08),
                'spot_allocation': spot_allocation,
                'cash_reserve': 1.0 - spot_allocation,
                'max_daily_loss': self._configured_float('MAX_DAILY_LOSS', adaptive_daily_loss) if configured_daily_loss is not None else adaptive_daily_loss,
                'max_positions': configured_max_positions,
                'max_tradeable_cryptos': limits['max_tradeable_cryptos'],
                'total_max_positions': configured_total_positions,
                'aggressive_mode': False,
                'compound_rate': 0.8,  # 80% réinvestissement
                'min_profit_threshold': 0.8,
                'stop_loss_percent': 5.0,
                'preferred_cryptos': ['BTC', 'ETH', 'SOL', 'ADA']
            }
            
        else:
            # Mode Professionnel (200+ USD)
            adaptive_daily_loss = max(20, total_balance_usd * 0.10)
            spot_allocation = min(0.85, max_spot_allocation)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 10), total_balance_usd * 0.05),
                'spot_allocation': spot_allocation,
                'cash_reserve': 1.0 - spot_allocation,
                'max_daily_loss': self._configured_float('MAX_DAILY_LOSS', adaptive_daily_loss) if configured_daily_loss is not None else adaptive_daily_loss,
                'max_positions': configured_max_positions,
                'max_tradeable_cryptos': limits['max_tradeable_cryptos'],
                'total_max_positions': configured_total_positions,
                'aggressive_mode': False,
                'compound_rate': 0.7,  # 70% réinvestissement
                'min_profit_threshold': 1.0,
                'stop_loss_percent': 5.0,
                'preferred_cryptos': ['BTC', 'ETH', 'SOL', 'ADA', 'ADA']
            }

    def can_open_new_position(self, symbol, new_position_usd) -> bool:
        """
        Gouvernance Risque Phase 10 :
        Vérifie que l'exposition globale ne dépasse pas le plafond dynamique du capital total
        et que le nombre de positions sur le même symbole ne dépasse pas max_positions_per_crypto.
        """
        try:
            from utils.market_analyzer import MarketAnalyzer

            total_balance = self._total_balance_usd()
            if total_balance <= 0:
                print("CapitalManager: capital live indisponible ou nul, achat bloqué")
                return False
            max_exposure_pct = self.get_max_total_exposure_pct(total_balance)
            limits = MarketAnalyzer.get_position_limits(total_balance)
            max_pos_per_crypto = self._configured_int(
                'MAX_POSITIONS_PER_CRYPTO',
                min(int(limits.get('max_positions_per_crypto', 2)), 2)
            )
            max_total_positions = self._configured_int(
                'MAX_TOTAL_POSITIONS',
                max_pos_per_crypto * int(limits.get('max_tradeable_cryptos', 4))
            )
            open_positions = self._open_positions_for_active_mode()

            if len(open_positions) >= max_total_positions:
                print(f"CapitalManager: Limite globale atteinte ({len(open_positions)}/{max_total_positions} positions ouvertes)")
                return False

            # 1. Limite par crypto
            symbol_positions = [p for p in open_positions if p.get('symbol') == symbol]
            if len(symbol_positions) >= max_pos_per_crypto:
                print(f"CapitalManager: Limite atteinte de {max_pos_per_crypto} positions max sur {symbol}")
                return False

            # 2. Plafond d'exposition globale (max 60%)
            current_exposure_usd = sum(
                float(p.get('amount', 0) or 0) * float(p.get('price', 0) or 0)
                for p in open_positions
            )
            total_after_trade = current_exposure_usd + float(new_position_usd or 0)
            max_allowed_usd = total_balance * (max_exposure_pct / 100.0)

            if total_after_trade > max_allowed_usd:
                print(f"CapitalManager: Plafond d'exposition globale atteint ({current_exposure_usd:.1f} + {new_position_usd:.1f} = {total_after_trade:.1f} USD > max {max_allowed_usd:.1f} USD [{max_exposure_pct}%])")
                return False

            return True
        except Exception as e:
            print(f"Erreur can_open_new_position: {e}")
            return True

    def get_total_exposure_ratio(self) -> float:
        """Retourne le ratio d'exposition globale du capital (ex: 0.15 pour 15%)."""
        try:
            total_balance = self._total_balance_usd()
            if total_balance <= 0:
                return 0.0
            total_exposure_usd = 0.0
            for position in self._open_positions_for_active_mode():
                symbol = position.get('symbol')
                entry_price = float(position.get('price') or position.get('entry_price') or 0.0)
                price = self.bot.get_price(symbol) if symbol and hasattr(self.bot, 'get_price') else entry_price
                amount = float(position.get('amount') or 0.0)
                total_exposure_usd += amount * (price or entry_price)
            return round(total_exposure_usd / total_balance, 4)
        except Exception as e:
            print(f"⚠️ Erreur get_total_exposure_ratio: {e}")
            return 0.0
    
    def _get_exchange_min_amounts(self):
        """Récupère les montants minimums de l'exchange via CCXT."""
        # En paper trading, utiliser des valeurs par défaut
        if self.bot.paper_trading:
            return {
                'min_trade': 1.0
            }
        
        try:
            # Cache pendant 1 heure
            now = datetime.now()
            if (self.last_update and 
                (now - self.last_update).seconds < 3600 and 
                self.min_amounts_cache):
                return self.min_amounts_cache
            
            # Récupérer les infos d'échange (mode live seulement)
            if hasattr(self.bot, 'exchange') and self.bot.exchange:
                markets = self.bot.exchange.load_markets() or getattr(self.bot.exchange, 'markets', {}) or {}
                
                min_amounts = {
                    'min_trade': 1.0
                }
                
                # Analyser les minimums pour les principales paires
                symbols = []
                for pair in os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD,SOLUSD,ADAUSD').split(','):
                    pair = pair.strip()
                    if not pair:
                        continue
                    if hasattr(self.bot.exchange, 'normalize_symbol'):
                        pair = self.bot.exchange.normalize_symbol(pair)
                    symbols.append(pair)
                for symbol in symbols or ['BTC/USD', 'ETH/USD']:
                    if symbol in markets:
                        market = markets[symbol]
                        min_cost = market.get('limits', {}).get('cost', {}).get('min', 1.0)
                        if min_cost:
                            min_amounts['min_trade'] = max(min_amounts['min_trade'], min_cost)
                
                self.min_amounts_cache = min_amounts
                self.last_update = now
                
                return min_amounts
                
        except Exception as e:
            # En cas d'erreur, ne pas afficher en paper trading
            if not self.bot.paper_trading:
                print(f"⚠️ Erreur récupération minimums exchange: {e}")
        
        # Valeurs par défaut sécurisées
        return {
            'min_trade': 1.0
        }
    
    def apply_config(self, config):
        """Applique automatiquement la configuration au bot"""
        try:
            # Mettre à jour les variables d'environnement temporairement
            os.environ['TRADE_AMOUNT'] = str(config['trade_amount'])
            os.environ['MAX_DAILY_LOSS'] = str(config['max_daily_loss'])
            os.environ['STOP_LOSS_PERCENT'] = str(config['stop_loss_percent'])
            os.environ['MIN_PROFIT_THRESHOLD'] = str(config['min_profit_threshold'])
            
            # Appliquer au bot
            self.bot.trade_amount = config['trade_amount']
            self.bot.max_daily_loss = config['max_daily_loss']
            self.bot.stop_loss_percent = config['stop_loss_percent']
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur application config: {e}")
            return False
    
    def get_capital_status(self, total_balance):
        """Retourne le statut du capital"""
        if total_balance < 8:
            return "INSUFFICIENT"  # Capital insuffisant
        elif total_balance < 20:
            return "MICRO"  # Micro-capital
        elif total_balance < 50:
            return "SMALL"  # Petit capital
        elif total_balance < 200:
            return "MEDIUM"  # Capital moyen
        else:
            return "LARGE"  # Gros capital
    
    def show_capital_analysis(self, total_balance):
        """Affiche l'analyse du capital et les recommandations"""
        status = self.get_capital_status(total_balance)
        config = self.get_adaptive_config(total_balance)
        
        # Affichage compact en une ligne
        aggressive = "AGR" if config['aggressive_mode'] else "CON"
        
        print(f"💰 Capital: {total_balance:.0f} USD ({status}) | Trade: {config['trade_amount']:.0f} | Spot: {config['spot_allocation']*100:.0f}% | Stop: {config['stop_loss_percent']:.1f}% | Mode: {aggressive}")
        
        return config
    
    def auto_adjust_bot(self):
        """Ajuste automatiquement le bot selon le capital actuel"""
        try:
            # Vérifier le mode réel du bot
            is_paper = getattr(self.bot, 'paper_trading', True)
            
            # Récupérer le capital total selon le mode
            if is_paper:
                # En paper trading, utiliser paper_balance
                total_balance = getattr(self.bot, 'paper_balance', 1000)
            else:
                total_balance = self._total_balance_usd()
            
            # Obtenir et appliquer la configuration
            config = self.get_adaptive_config(total_balance)
            self.apply_config(config)
            
            # Afficher l'analyse (seulement si pas en mode test)
            if not os.getenv('TESTING_MODE', 'False') == 'True':
                mode_text = "PAPER" if is_paper else "LIVE"
                self.show_capital_analysis_with_mode(total_balance, mode_text)
            
            return config
            
        except Exception as e:
            # En paper trading, ne pas afficher les erreurs de récupération de balance
            if not getattr(self.bot, 'paper_trading', True):
                print(f"⚠️ Erreur ajustement automatique: {e}")
            return None
    
    def show_capital_analysis_with_mode(self, total_balance, mode_text):
        """Affiche l'analyse du capital avec indication du mode"""
        status = self.get_capital_status(total_balance)
        config = self.get_adaptive_config(total_balance)
        
        # Affichage compact en une ligne avec mode
        aggressive = "AGR" if config['aggressive_mode'] else "CON"
        
        print(f"💰 Capital: {total_balance:.0f} USD ({status}) [{mode_text}] | Trade: {config['trade_amount']:.0f} | Spot: {config['spot_allocation']*100:.0f}% | Stop: {config['stop_loss_percent']:.1f}% | Mode: {aggressive}")
        
        return config
    
    # === DYNAMIC FEES METHODS ===
    
    def get_real_trading_fees(self, symbol):
        """Récupère frais réels depuis l'exchange - Méthode Institutionnelle"""
        cache_key = f"{symbol}_fees"
        now = time.time()
        
        if (cache_key in self.fees_cache and 
            now - self.fees_cache[cache_key]['timestamp'] < self.fees_update_interval):
            return self.fees_cache[cache_key]['fees']
        
        try:
            if not self.bot.paper_trading:
                fees_data = self.bot.safe_request(self.bot.exchange.fetch_trading_fees)
                
                if symbol in fees_data:
                    maker_fee = fees_data[symbol]['maker']
                    taker_fee = fees_data[symbol]['taker']
                    
                    self._detect_vip_level(taker_fee)
                    optimal_fee = self._calculate_optimal_fee(maker_fee, taker_fee)
                    
                    self.fees_cache[cache_key] = {
                        'fees': {
                            'maker': maker_fee,
                            'taker': taker_fee,
                            'optimal': optimal_fee
                        },
                        'timestamp': now
                    }
                    
                    return self.fees_cache[cache_key]['fees']
        except Exception as e:
            if not self.bot.paper_trading:
                print(f"⚠️ Erreur récupération frais {symbol}: {e}")
        
        return self._get_fallback_fees()
        
    def sync_fees_to_bot(self):
        """Récupère et synchronise les frais réels sur le bot"""
        try:
            # Récupérer la première paire configurée
            trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSD,ETHUSD').split(',')
            if not trading_pairs:
                return False
            
            first_pair = trading_pairs[0].strip()
            # Normaliser
            if '/' not in first_pair:
                if first_pair.endswith('USD'):
                    symbol = f"{first_pair[:-3]}/USD"
                else:
                    symbol = f"{first_pair}/USD"
            else:
                symbol = first_pair
            
            fees = self.get_real_trading_fees(symbol)
            taker_fee = fees.get('taker', float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0)
            
            # Mettre à jour les variables sur le bot
            self.bot.trading_fee = taker_fee
            # Formule: (taker_fee * 2) + 0.002 (aller-retour frais + marge 0.2%)
            optimal_min_profit = (taker_fee * 2) + 0.002
            
            # Utiliser la valeur configurée par l'utilisateur (ex: 3%) si elle est supérieure au minimum optimal de couverture des frais
            configured_min_profit = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.8')) / 100
            self.bot.min_profit_threshold = max(configured_min_profit, optimal_min_profit)
            
            print(f"🔄 FRAIS SYNCHRONISÉS: Taker: {taker_fee*100:.3f}% | Profit Min Optimal (frais couverts): {optimal_min_profit*100:.3f}% | Profit Target Effectif: {self.bot.min_profit_threshold*100:.3f}%")
            return True
        except Exception as e:
            print(f"⚠️ Erreur synchronisation frais au bot: {e}")
            return False
    
    def _detect_vip_level(self, taker_fee):
        """Détecte niveau VIP selon frais taker"""
        if taker_fee <= 0.0002:
            self.vip_level = "VIP 9"
        elif taker_fee <= 0.0004:
            self.vip_level = "VIP 5-8"
        elif taker_fee <= 0.0007:
            self.vip_level = "VIP 1-4"
        else:
            self.vip_level = "Standard"
    
    def _calculate_optimal_fee(self, maker_fee, taker_fee):
        """Calcule frais optimal - Stratégie Institutionnelle"""
        return maker_fee if maker_fee < taker_fee else taker_fee
    
    def _get_fallback_fees(self):
        """Frais fallback intelligents selon niveau VIP détecté"""
        if self.vip_level == "VIP 9":
            base_fee = 0.0002
        elif "VIP" in str(self.vip_level):
            base_fee = 0.0005
        else:
            base_fee = float(os.getenv('TRADING_FEE_PERCENT', '0.4')) / 100.0
        
        return {
            'maker': base_fee * 0.9,
            'taker': base_fee,
            'optimal': base_fee
        }
    
    def get_fee_for_trade(self, symbol, order_type='market'):
        """Récupère frais pour un trade spécifique"""
        fees = self.get_real_trading_fees(symbol)
        return fees['maker'] if order_type == 'limit' else fees['taker']
    
    def calculate_trade_cost(self, symbol, amount_usd, order_type='market'):
        """Calcule coût total réel d'un trade"""
        fee_rate = self.get_fee_for_trade(symbol, order_type)
        fee_cost = amount_usd * fee_rate
        
        return {
            'amount': amount_usd,
            'fee_rate': fee_rate,
            'fee_cost': fee_cost,
            'total_cost': amount_usd + fee_cost,
            'vip_level': self.vip_level
        }
    
    def optimize_order_type(self, symbol, urgency='normal'):
        """Recommande type d'ordre optimal - Logique Institutionnelle"""
        fees = self.get_real_trading_fees(symbol)
        maker_advantage = fees['taker'] - fees['maker']
        
        if urgency == 'high':
            return 'market'
        elif maker_advantage > 0.0002:
            return 'limit'
        else:
            return 'market'
    
    def get_fees_summary(self):
        """Résumé des frais pour monitoring"""
        if not self.fees_cache:
            return "Frais non initialisés"
        
        sample_fees = next(iter(self.fees_cache.values()))['fees']
        
        return {
            'vip_level': self.vip_level or "Détection en cours",
            'maker_fee': f"{sample_fees['maker']*100:.3f}%",
            'taker_fee': f"{sample_fees['taker']*100:.3f}%",
            'optimal_fee': f"{sample_fees['optimal']*100:.3f}%"
        }
    
    # === DUST MANAGER METHODS ===
    
    def is_dust(self, asset, amount):
        """Vérifie si une quantité de crypto est considérée comme dust"""
        try:
            if asset == 'USD':
                return amount < 1.0
            
            symbol = f"{asset}/USD"
            price = self.bot.get_price(symbol)
            usd_value = amount * price
            dust_threshold = self.dust_thresholds_usd.get(asset, 0.50)
            
            return usd_value < dust_threshold
        except Exception as e:
            print(f"⚠️ Erreur vérification dust {asset}: {e}")
            return True
    
    def is_tradeable_amount(self, symbol, amount):
        """Vérifie si une quantité peut être tradée (respecte les minimums exchange)"""
        try:
            minimums = self.safe_minimums.get(symbol, {'min_amount': 0.001, 'min_cost': 1.0})
            
            if amount < minimums['min_amount']:
                return False
            
            price = self.bot.get_price(symbol)
            cost = amount * price
            
            return cost >= minimums['min_cost']
        except Exception as e:
            print(f"⚠️ Erreur vérification tradeable {symbol}: {e}")
            return False
    
    def filter_dust_balances(self, balances):
        """Filtre les balances pour exclure le dust"""
        filtered_balances = {}
        dust_detected = {}
        
        for asset, balance_data in balances.items():
            total_amount = balance_data.get('total', 0)
            
            if asset == 'USD':
                filtered_balances[asset] = balance_data
            elif not self.is_dust(asset, total_amount):
                filtered_balances[asset] = balance_data
            else:
                dust_detected[asset] = {
                    'amount': total_amount,
                    'usd_value': self._get_usd_value(asset, total_amount)
                }
        
        return filtered_balances, dust_detected
    
    def _get_usd_value(self, asset, amount):
        """Calcule la valeur USD d'un asset"""
        try:
            if asset == 'USD':
                return amount
            
            symbol = f"{asset}/USD"
            price = self.bot.get_price(symbol)
            return amount * price
        except:
            return 0
    
    def show_dust_summary(self, dust_detected):
        """Affiche un résumé du dust détecté"""
        if not dust_detected:
            return
        
        print(f"🧹 DUST DÉTECTÉ (valeurs trop petites pour trader):")
        total_dust_usd = 0
        
        for asset, data in dust_detected.items():
            amount = data['amount']
            usd_value = data['usd_value']
            total_dust_usd += usd_value
            
            print(f"   • {asset}: {amount:.8f} (~{usd_value:.4f} USD)")
        
        print(f"   Total dust: {total_dust_usd:.4f} USD")
        
        if total_dust_usd > 0.10:
            print(f"   💡 Conseil: ignorer ou consolider ces petits montants manuellement sur l'exchange")
    
    def get_tradeable_balance(self, symbol):
        """Retourne la balance tradeable (sans dust) pour un symbole"""
        try:
            balance = self.bot.balance_manager.get_balance()
            base_currency = symbol.split('/')[0]
            
            if base_currency not in balance:
                return 0
            
            total_amount = balance[base_currency].get('free', 0)
            
            return total_amount if self.is_tradeable_amount(symbol, total_amount) else 0
        except Exception as e:
            print(f"⚠️ Erreur balance tradeable {symbol}: {e}")
            return 0
    
    def suggest_dust_cleanup(self):
        """Suggère des actions pour nettoyer le dust"""
        try:
            balance = self.bot.balance_manager.get_balance()
            filtered_balance, dust_detected = self.filter_dust_balances(balance)
            
            if dust_detected:
                self.show_dust_summary(dust_detected)
                
                print(f"🔧 ACTIONS RECOMMANDÉES:")
                print(f"   1. Consolider manuellement les petits montants sur l'exchange")
                print(f"   2. Ou ignorer (le bot ne tentera pas de trader ces montants)")
                
                return dust_detected
            
            return {}
        except Exception as e:
            print(f"⚠️ Erreur suggestion cleanup: {e}")
            return {}
    
    def validate_trade_amount(self, symbol, amount):
        """Valide qu'un montant peut être tradé sans erreur"""
        try:
            if not self.is_tradeable_amount(symbol, amount):
                base_currency = symbol.split('/')[0]
                minimums = self.safe_minimums.get(symbol, {'min_amount': 0.001, 'min_cost': 1.0})
                
                print(f"❌ {base_currency}: Montant trop petit pour trader")
                print(f"   Minimum: {minimums['min_amount']} {base_currency}")
                print(f"   Coût minimum: {minimums['min_cost']} USD")
                
                return False
            
            return True
        except Exception as e:
            print(f"⚠️ Erreur validation trade: {e}")
            return False
    
    def get_minimum_trade_amount(self, symbol):
        """Retourne le montant minimum pour trader un symbole"""
        minimums = self.safe_minimums.get(symbol, {'min_amount': 0.001, 'min_cost': 1.0})
        
        try:
            price = self.bot.get_price(symbol)
            min_amount_by_cost = minimums['min_cost'] / price
            return max(minimums['min_amount'], min_amount_by_cost)
        except:
            return minimums['min_amount']
