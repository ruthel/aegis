"""
Capital Manager - Gestion Automatique de Tous Capitaux (8+ USDT)
Adaptation automatique selon le capital disponible + minimums API Binance
"""

import os
from datetime import datetime

class CapitalManager:
    """Gestionnaire automatique pour tous niveaux de capital"""
    
    def __init__(self, bot):
        self.bot = bot
        self.min_amounts_cache = {}
        self.last_update = None
        
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
                'max_daily_loss': max(2, total_balance_usdt * 0.25),
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
                'max_daily_loss': max(5, total_balance_usdt * 0.20),
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