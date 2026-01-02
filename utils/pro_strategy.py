"""Stratégie Pro avec niveaux fixes et scaling comme les professionnels"""
import os
import time

class ProStrategy:
    def __init__(self, bot):
        self.bot = bot
        self.fixed_levels = FixedLevelsManager()
        self.multi_position = MultiPositionManager()
        
    def should_buy_pro(self, symbol, current_price):
        """Logique d'achat pro : niveaux fixes + scaling"""
        
        # 1. Vérifier si on peut ouvrir une nouvelle position
        if not self.multi_position.can_open_new_position(self.bot, symbol):
            return False, "Max positions atteintes"
        
        # 2. Mode agressif : ignorer la plupart des protections
        if os.getenv('AGGRESSIVE_MODE', 'False') == 'True':
            # Ignorer marché latéral et patterns
            pass
        else:
            # Mode conservateur : vérifications normales
            if not self.bot.safety_manager.can_trade():
                return False, "Safety manager bloque"
        
        # 3. Vérifier niveaux fixes
        should_buy, level = self.fixed_levels.should_buy_at_level(symbol, current_price, tolerance_pct=1.5)
        
        if should_buy:
            return True, f"Niveau fixe atteint: {level}"
        
        # 4. Vérifier scaling (si position existante)
        last_buy_price = self.multi_position.get_last_buy_price(self.bot, symbol)
        if last_buy_price and self.multi_position.should_scale_in(self.bot, symbol, current_price, last_buy_price):
            return True, f"Scaling depuis {last_buy_price:.2f}"
        
        # 5. Signal technique simple (confidence réduite)
        min_confidence = int(os.getenv('MIN_CONFIDENCE', '50'))
        analysis = self.bot.get_cached_analysis(symbol, current_price)
        global_signal = analysis['global_signal']
        
        if (global_signal['action'] in ['BUY', 'STRONG_BUY'] and 
            global_signal['confidence'] >= min_confidence):
            return True, f"Signal technique {global_signal['confidence']:.0f}%"
        
        return False, "Aucune condition remplie"
    
    def calculate_buy_amount_pro(self, symbol, current_price, reason):
        """Calcule le montant d'achat selon la stratégie pro"""
        base_amount = float(os.getenv('TRADE_AMOUNT', '5'))
        
        # 1. Scaling selon le niveau
        if "Niveau fixe" in reason:
            amount = self.fixed_levels.get_position_size_for_level(symbol, current_price, base_amount)
        elif "Scaling" in reason:
            amount = self.multi_position.calculate_scaled_amount(self.bot, symbol, base_amount, current_price)
        else:
            amount = base_amount
        
        # 2. Vérifier fonds disponibles
        balance = self.bot.balance_manager.get_balance()
        usdt_available = balance.get('USDT', {}).get('free', 0)
        
        if self.bot.paper_trading:
            usdt_available = self.bot.paper_balance
        
        # Limiter au disponible
        max_amount = min(amount, usdt_available * 0.8)  # 80% max du disponible
        
        return max(max_amount, self.bot.get_min_amount(symbol)['min_cost'])
    
    def execute_buy_pro(self, symbol, current_price, reason):
        """Exécute un achat selon la stratégie pro"""
        amount_usdt = self.calculate_buy_amount_pro(symbol, current_price, reason)
        trade_amount = amount_usdt / current_price
        
        crypto = symbol.split('/')[0]
        position_count = self.multi_position.get_position_count(self.bot, symbol)
        
        print(f"🚀 ACHAT PRO {crypto}: {amount_usdt:.1f} USDT (Position #{position_count + 1})")
        print(f"   💡 Raison: {reason}")
        print(f"   💰 Prix: {current_price:.2f}")
        print(f"   📊 Quantité: {trade_amount:.6f} {crypto}")
        
        # Exécuter l'achat
        result = self.bot.buy_market(symbol, trade_amount)
        
        if result:
            print(f"✅ Achat exécuté avec succès")
            return True
        else:
            print(f"❌ Échec de l'achat")
            return False
    
    def should_sell_pro(self, symbol, current_price):
        """Logique de vente pro : take profit par tranches"""
        
        # Vérifier s'il y a des positions
        position_summary = self.multi_position.get_position_summary(self.bot, symbol)
        if not position_summary:
            return False, 0, "Aucune position"
        
        # Vérifier take profit
        should_sell, sell_percentage = self.multi_position.should_take_profit(self.bot, symbol, current_price)
        
        if should_sell:
            total_amount = position_summary['total_amount']
            sell_amount = total_amount * sell_percentage
            avg_price = position_summary['average_price']
            profit_pct = (current_price - avg_price) / avg_price * 100
            
            return True, sell_amount, f"Take profit {profit_pct:.1f}% ({sell_percentage*100:.0f}% position)"
        
        return False, 0, "Pas de take profit"
    
    def run_pro_strategy(self, symbol, current_price):
        """Stratégie principale pro"""
        
        # 1. Vérifier vente d'abord
        should_sell, sell_amount, sell_reason = self.should_sell_pro(symbol, current_price)
        
        if should_sell and sell_amount > 0:
            crypto = symbol.split('/')[0]
            print(f"💰 VENTE PRO {crypto}: {sell_amount:.6f} - {sell_reason}")
            
            # Exécuter vente partielle
            result = self.bot.sell_market(symbol, sell_amount)
            if result:
                print(f"✅ Vente partielle exécutée")
            return
        
        # 2. Vérifier achat
        should_buy, buy_reason = self.should_buy_pro(symbol, current_price)
        
        if should_buy:
            success = self.execute_buy_pro(symbol, current_price, buy_reason)
            if success:
                # Ajouter trailing stop si configuré
                if hasattr(self.bot, 'trailing_stop_manager'):
                    self.bot.trailing_stop_manager.add_position(symbol, current_price)
        else:
            # Mode debug : afficher pourquoi pas d'achat
            if os.getenv('DEBUG_PRO', 'False') == 'True':
                crypto = symbol.split('/')[0]
                print(f"⏸️ {crypto}: {buy_reason}")

# Intégrer dans le bot
def add_pro_strategy_to_bot(bot):
    """Ajoute la stratégie pro au bot"""
    bot.pro_strategy = ProStrategy(bot)
    bot.fixed_levels = FixedLevelsManager()
    bot.multi_position = MultiPositionManager()
    
    # Remplacer la méthode intelligent_strategy
    def intelligent_strategy_pro(symbol, amount, current_price):
        """Version pro de intelligent_strategy"""
        if os.getenv('USE_SIMPLE_STRATEGY', 'False') == 'True':
            bot.pro_strategy.run_pro_strategy(symbol, current_price)
        else:
            # Fallback sur ancienne méthode
            bot.intelligent_strategy_original(symbol, amount, current_price)
    
    # Sauvegarder ancienne méthode
    if hasattr(bot, 'intelligent_strategy'):
        bot.intelligent_strategy_original = bot.intelligent_strategy
    
    # Remplacer par version pro
    bot.intelligent_strategy = intelligent_strategy_pro