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
        
    def get_adaptive_config(self, total_balance_usd):
        """Configuration automatique selon le capital avec limites de positions"""
        
        # Récupérer les montants minimums de l'exchange
        min_amounts = self._get_exchange_min_amounts()
        
        # Obtenir les limites de positions
        from utils.market_analyzer import MarketAnalyzer
        limits = MarketAnalyzer.get_position_limits(total_balance_usd)
        
        if total_balance_usd < 20:
            # Mode Micro-Capital (8-20 USD)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 1), total_balance_usd * 0.15),
                'spot_allocation': 1.0,  # 100% spot
                'max_daily_loss': max(10, total_balance_usd * 0.25),
                'max_positions': limits['max_positions_per_crypto'],
                'max_tradeable_cryptos': limits['max_tradeable_cryptos'],
                'total_max_positions': limits['total_max_positions'],
                'aggressive_mode': True,
                'compound_rate': 1.0,  # 100% réinvestissement
                'min_profit_threshold': 0.5,  # 0.5% minimum
                'stop_loss_percent': 3.0,  # Stop serré
                'preferred_cryptos': ['DOGE', 'SHIB', 'PEPE']  # Volatiles
            }
            
        elif total_balance_usd < 50:
            # Mode Croissance (20-50 USD)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 2), total_balance_usd * 0.12),
                'spot_allocation': 1.0,  # 100% spot
                'max_daily_loss': max(10, total_balance_usd * 0.20),
                'max_positions': 2,
                'aggressive_mode': True,
                'compound_rate': 0.9,  # 90% réinvestissement
                'min_profit_threshold': 0.6,
                'stop_loss_percent': 4.0,
                'preferred_cryptos': ['BTC', 'ETH', 'DOGE', 'SHIB']
            }
            
        elif total_balance_usd < 200:
            # Mode Équilibré (50-200 USD)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 5), total_balance_usd * 0.08),
                'spot_allocation': 0.95,  # 95% spot
                'cash_reserve': 0.05,  # 5% cash
                'max_daily_loss': max(10, total_balance_usd * 0.15),
                'max_positions': 3,
                'aggressive_mode': False,
                'compound_rate': 0.8,  # 80% réinvestissement
                'min_profit_threshold': 0.8,
                'stop_loss_percent': 5.0,
                'preferred_cryptos': ['BTC', 'ETH', 'SOL', 'ADA']
            }
            
        else:
            # Mode Professionnel (200+ USD)
            return {
                'trade_amount': max(min_amounts.get('min_trade', 10), total_balance_usd * 0.05),
                'spot_allocation': 0.85,  # 85% spot
                'cash_reserve': 0.15,  # 15% cash
                'max_daily_loss': max(20, total_balance_usd * 0.10),
                'max_positions': 5,
                'aggressive_mode': False,
                'compound_rate': 0.7,  # 70% réinvestissement
                'min_profit_threshold': 1.0,
                'stop_loss_percent': 5.0,
                'preferred_cryptos': ['BTC', 'ETH', 'SOL', 'ADA', 'ADA']
            }
    
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
                markets = self.bot.exchange.load_markets()
                
                min_amounts = {
                    'min_trade': 1.0
                }
                
                # Analyser les minimums pour les principales paires
                for symbol in ['BTC/USD', 'ETH/USD', 'DOGE/USD']:
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
                # En mode live, utiliser balance_manager
                if hasattr(self.bot, 'balance_manager'):
                    try:
                        balance_info = self.bot.balance_manager.get_total_balance_usd()
                        total_balance = balance_info['total']
                    except:
                        # Fallback sur balance simple
                        balance = self.bot.balance_manager.get_balance()
                        total_balance = balance.get('USD', balance.get('USD', {})).get('free', 0)
                else:
                    # Fallback direct
                    try:
                        balance = self.bot.exchange.fetch_balance()
                        total_balance = balance.get('USD', balance.get('USD', {})).get('free', 0)
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
            taker_fee = fees.get('taker', 0.001)
            
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
            base_fee = 0.001
        
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
        
        print(f"\n🧹 DUST DÉTECTÉ (valeurs trop petites pour trader):")
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
                
                print(f"\n🔧 ACTIONS RECOMMANDÉES:")
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
