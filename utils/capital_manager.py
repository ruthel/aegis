"""
Capital Manager - Gestion Automatique de Tous Capitaux (8+ USDT)
Adaptation automatique selon le capital disponible + minimums API Binance
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
        self.bnb_discount = False
        
        # Dust Manager integration
        self.dust_thresholds_usdt = {
            'BTC': 0.50, 'ETH': 0.50, 'SOL': 0.50, 'BNB': 0.50,
            'ADA': 0.10, 'DOT': 0.20, 'MATIC': 0.10, 'AVAX': 0.30,
            'LINK': 0.30, 'UNI': 0.20, 'LTC': 0.50, 'BCH': 0.50
        }
        
        self.safe_minimums = {
            'BTC/USDT': {'min_amount': 0.00001, 'min_cost': 1.0},
            'ETH/USDT': {'min_amount': 0.0001, 'min_cost': 1.0},
            'SOL/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'BNB/USDT': {'min_amount': 0.001, 'min_cost': 1.0},
            'ADA/USDT': {'min_amount': 1.0, 'min_cost': 1.0},
            'DOT/USDT': {'min_amount': 0.1, 'min_cost': 1.0},
            'MATIC/USDT': {'min_amount': 1.0, 'min_cost': 1.0},
            'AVAX/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'LINK/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'UNI/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'LTC/USDT': {'min_amount': 0.001, 'min_cost': 1.0},
            'BCH/USDT': {'min_amount': 0.001, 'min_cost': 1.0}
        }
        
    def get_adaptive_config(self, total_balance_usdt):
        """Configuration automatique selon le capital"""
        
        # Récupérer les montants minimums de l'API Binance
        min_amounts = self._get_binance_min_amounts()
        
        if total_balance_usdt < 20:
            # Mode Micro-Capital (8-20 USDT)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 1), total_balance_usdt * 0.15),
                'spot_allocation': 1.0,  # 100% spot
                'dual_allocation': 0.0,  # 0% double investment
                'max_daily_loss': max(10, total_balance_usdt * 0.25),
                'max_positions': 1,  # Une position à la fois
                'aggressive_mode': True,
                'compound_rate': 1.0,  # 100% réinvestissement
                'min_profit_threshold': 0.5,  # 0.5% minimum
                'stop_loss_percent': 3.0,  # Stop serré
                'preferred_cryptos': ['DOGE', 'SHIB', 'PEPE'],  # Volatiles
                'enable_earn': False,  # Pas de Earn
                'enable_dual_investment': False
            }
            
        elif total_balance_usdt < 50:
            # Mode Croissance (20-50 USDT)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 2), total_balance_usdt * 0.12),
                'spot_allocation': 0.95,  # 95% spot
                'dual_allocation': 0.05,  # 5% double investment
                'max_daily_loss': max(10, total_balance_usdt * 0.20),
                'max_positions': 2,
                'aggressive_mode': True,
                'compound_rate': 0.9,  # 90% réinvestissement
                'min_profit_threshold': 0.6,
                'stop_loss_percent': 4.0,
                'preferred_cryptos': ['BTC', 'ETH', 'DOGE', 'SHIB'],
                'enable_earn': True,
                'enable_dual_investment': True,
                'dual_min_amount': max(min_amounts.get('dual_min', 10), 5)
            }
            
        elif total_balance_usdt < 200:
            # Mode Équilibré (50-200 USDT)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 5), total_balance_usdt * 0.08),
                'spot_allocation': 0.75,  # 75% spot
                'dual_allocation': 0.20,  # 20% double investment
                'cash_reserve': 0.05,  # 5% cash
                'max_daily_loss': max(10, total_balance_usdt * 0.15),
                'max_positions': 3,
                'aggressive_mode': False,
                'compound_rate': 0.8,  # 80% réinvestissement
                'min_profit_threshold': 0.8,
                'stop_loss_percent': 5.0,
                'preferred_cryptos': ['BTC', 'ETH', 'SOL', 'BNB'],
                'enable_earn': True,
                'enable_dual_investment': True,
                'dual_min_amount': max(min_amounts.get('dual_min', 10), 10)
            }
            
        else:
            # Mode Professionnel (200+ USDT)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 10), total_balance_usdt * 0.05),
                'spot_allocation': 0.60,  # 60% spot
                'dual_allocation': 0.25,  # 25% double investment
                'cash_reserve': 0.15,  # 15% cash
                'max_daily_loss': max(20, total_balance_usdt * 0.10),
                'max_positions': 5,
                'aggressive_mode': False,
                'compound_rate': 0.7,  # 70% réinvestissement
                'min_profit_threshold': 1.0,
                'stop_loss_percent': 5.0,
                'preferred_cryptos': ['BTC', 'ETH', 'SOL', 'BNB', 'ADA'],
                'enable_earn': True,
                'enable_dual_investment': True,
                'dual_min_amount': max(min_amounts.get('dual_min', 10), 20)
            }
    
    def _get_binance_min_amounts(self):
        """Récupère les montants minimums de l'API Binance"""
        # En paper trading, utiliser des valeurs par défaut
        if self.bot.paper_trading:
            return {
                'min_trade': 1.0,
                'dual_min': 10.0
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
                markets = self.bot.exchange.load_markets()
                
                min_amounts = {
                    'min_trade': 1.0,  # Défaut
                    'dual_min': 10.0   # Défaut Double Investment
                }
                
                # Analyser les minimums pour les principales paires
                for symbol in ['BTC/USDT', 'ETH/USDT', 'DOGE/USDT']:
                    if symbol in markets:
                        market = markets[symbol]
                        min_cost = market.get('limits', {}).get('cost', {}).get('min', 1.0)
                        if min_cost:
                            min_amounts['min_trade'] = max(min_amounts['min_trade'], min_cost)
                
                # Double Investment minimum (généralement 10 USDT)
                min_amounts['dual_min'] = 10.0
                
                self.min_amounts_cache = min_amounts
                self.last_update = now
                
                return min_amounts
                
        except Exception as e:
            # En cas d'erreur, ne pas afficher en paper trading
            if not self.bot.paper_trading:
                print(f"⚠️ Erreur récupération minimums Binance: {e}")
        
        # Valeurs par défaut sécurisées
        return {
            'min_trade': 1.0,
            'dual_min': 10.0
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
            
            # Configuration Earn
            if hasattr(self.bot, 'earn_manager'):
                self.bot.earn_manager.enabled = config['enable_earn']
            
            # Configuration Double Investment
            if hasattr(self.bot, 'double_investment_manager'):
                if config.get('enable_dual_investment', False):
                    self.bot.double_investment_manager.enable()
                    self.bot.double_investment_manager.min_amount = config.get('dual_min_amount', 10)
                else:
                    self.bot.double_investment_manager.disable()
            
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
        dual_status = f"{config.get('dual_allocation', 0)*100:.0f}%" if config.get('dual_allocation', 0) > 0 else "OFF"
        aggressive = "AGR" if config['aggressive_mode'] else "CON"
        
        print(f"💰 Capital: {total_balance:.0f} USDT ({status}) | Trade: {config['trade_amount']:.0f} | Spot: {config['spot_allocation']*100:.0f}% | Dual: {dual_status} | Stop: {config['stop_loss_percent']:.1f}% | Mode: {aggressive}")
        
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
                # En mode live, utiliser balance_manager
                if hasattr(self.bot, 'balance_manager'):
                    try:
                        balance_info = self.bot.balance_manager.get_total_balance_usdt()
                        total_balance = balance_info['total']
                    except:
                        # Fallback sur balance simple
                        balance = self.bot.balance_manager.get_balance()
                        total_balance = balance.get('USDT', {}).get('free', 0)
                else:
                    # Fallback direct
                    try:
                        balance = self.bot.exchange.fetch_balance()
                        total_balance = balance.get('USDT', {}).get('free', 0)
                    except:
                        total_balance = 0
            
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
        dual_status = f"{config.get('dual_allocation', 0)*100:.0f}%" if config.get('dual_allocation', 0) > 0 else "OFF"
        aggressive = "AGR" if config['aggressive_mode'] else "CON"
        
        print(f"💰 Capital: {total_balance:.0f} USDT ({status}) [{mode_text}] | Trade: {config['trade_amount']:.0f} | Spot: {config['spot_allocation']*100:.0f}% | Dual: {dual_status} | Stop: {config['stop_loss_percent']:.1f}% | Mode: {aggressive}")
        
        return config
    
    # === DYNAMIC FEES METHODS ===
    
    def get_real_trading_fees(self, symbol):
        """Récupère frais réels depuis Binance - Méthode Institutionnelle"""
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
                    self._check_bnb_discount()
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
    
    def _check_bnb_discount(self):
        """Vérifie si discount BNB actif"""
        try:
            if not self.bot.paper_trading:
                balance = self.bot.balance_manager.get_balance()
                bnb_balance = balance.get('BNB', {}).get('free', 0)
                self.bnb_discount = bnb_balance > 0.1
        except:
            self.bnb_discount = False
    
    def _calculate_optimal_fee(self, maker_fee, taker_fee):
        """Calcule frais optimal - Stratégie Institutionnelle"""
        optimal = maker_fee if maker_fee < taker_fee else taker_fee
        if self.bnb_discount:
            optimal *= 0.75
        return optimal
    
    def _get_fallback_fees(self):
        """Frais fallback intelligents selon niveau VIP détecté"""
        if self.vip_level == "VIP 9":
            base_fee = 0.0002
        elif "VIP" in str(self.vip_level):
            base_fee = 0.0005
        else:
            base_fee = 0.001
        
        if self.bnb_discount:
            base_fee *= 0.75
        
        return {
            'maker': base_fee * 0.9,
            'taker': base_fee,
            'optimal': base_fee * 0.9 if self.bnb_discount else base_fee
        }
    
    def get_fee_for_trade(self, symbol, order_type='market'):
        """Récupère frais pour un trade spécifique"""
        fees = self.get_real_trading_fees(symbol)
        return fees['maker'] if order_type == 'limit' else fees['taker']
    
    def calculate_trade_cost(self, symbol, amount_usdt, order_type='market'):
        """Calcule coût total réel d'un trade"""
        fee_rate = self.get_fee_for_trade(symbol, order_type)
        fee_cost = amount_usdt * fee_rate
        
        return {
            'amount': amount_usdt,
            'fee_rate': fee_rate,
            'fee_cost': fee_cost,
            'total_cost': amount_usdt + fee_cost,
            'vip_level': self.vip_level,
            'bnb_discount': self.bnb_discount
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
            'bnb_discount': "Actif" if self.bnb_discount else "Inactif",
            'maker_fee': f"{sample_fees['maker']*100:.3f}%",
            'taker_fee': f"{sample_fees['taker']*100:.3f}%",
            'optimal_fee': f"{sample_fees['optimal']*100:.3f}%"
        }
    
    # === DUST MANAGER METHODS ===
    
    def is_dust(self, asset, amount):
        """Vérifie si une quantité de crypto est considérée comme dust"""
        try:
            if asset == 'USDT':
                return amount < 1.0
            
            symbol = f"{asset}/USDT"
            price = self.bot.get_price(symbol)
            usdt_value = amount * price
            dust_threshold = self.dust_thresholds_usdt.get(asset, 0.50)
            
            return usdt_value < dust_threshold
        except Exception as e:
            print(f"⚠️ Erreur vérification dust {asset}: {e}")
            return True
    
    def is_tradeable_amount(self, symbol, amount):
        """Vérifie si une quantité peut être tradée (respecte minimums Binance)"""
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
            
            if asset == 'USDT':
                filtered_balances[asset] = balance_data
            elif not self.is_dust(asset, total_amount):
                filtered_balances[asset] = balance_data
            else:
                dust_detected[asset] = {
                    'amount': total_amount,
                    'usdt_value': self._get_usdt_value(asset, total_amount)
                }
        
        return filtered_balances, dust_detected
    
    def _get_usdt_value(self, asset, amount):
        """Calcule la valeur USDT d'un asset"""
        try:
            if asset == 'USDT':
                return amount
            
            symbol = f"{asset}/USDT"
            price = self.bot.get_price(symbol)
            return amount * price
        except:
            return 0
    
    def show_dust_summary(self, dust_detected):
        """Affiche un résumé du dust détecté"""
        if not dust_detected:
            return
        
        print(f"\n🧹 DUST DÉTECTÉ (valeurs trop petites pour trader):")
        total_dust_usdt = 0
        
        for asset, data in dust_detected.items():
            amount = data['amount']
            usdt_value = data['usdt_value']
            total_dust_usdt += usdt_value
            
            print(f"   • {asset}: {amount:.8f} (~{usdt_value:.4f} USDT)")
        
        print(f"   Total dust: {total_dust_usdt:.4f} USDT")
        
        if total_dust_usdt > 0.10:
            print(f"   💡 Conseil: Convertir le dust en BNB via Binance (Convert Small Assets)")
    
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
                
                print(f"\n🔧 ACTIONS RECOMMANDÉES:")
                print(f"   1. Binance Web → Wallet → Convert Small Assets to BNB")
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
                print(f"   Coût minimum: {minimums['min_cost']} USDT")
                
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