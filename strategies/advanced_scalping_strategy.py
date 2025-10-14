import time
from strategy import ScalpingStrategy
from multi_timeframe_analyzer import MultiTimeframeAnalyzer
from notification_manager import AlertManager

class AdvancedScalpingStrategy(ScalpingStrategy):
    def __init__(self, bot, symbol, amount_usdt=10):
        super().__init__(bot, symbol, amount_usdt)
        self.multi_tf_analyzer = MultiTimeframeAnalyzer()
        self.last_analysis = None
        self.min_confidence = 60  # Confiance minimum pour trader
        
    def should_buy(self, current_price, multi_tf_analysis):
        """Détermine si on doit acheter basé sur l'analyse multi-timeframes"""
        global_signal = multi_tf_analysis['global_signal']
        
        # Conditions d'achat
        buy_actions = ['BUY', 'STRONG_BUY']
        sufficient_confidence = global_signal['confidence'] >= self.min_confidence
        bullish_trend = global_signal['dominant_trend'] in ['bullish', 'neutral']
        
        return (global_signal['action'] in buy_actions and 
                sufficient_confidence and 
                bullish_trend)
    
    def should_sell(self, current_price, multi_tf_analysis):
        """Détermine si on doit vendre basé sur l'analyse multi-timeframes"""
        global_signal = multi_tf_analysis['global_signal']
        
        # Conditions de vente
        sell_actions = ['SELL', 'STRONG_SELL']
        sufficient_confidence = global_signal['confidence'] >= self.min_confidence
        
        # Vendre aussi si tendance devient baissière même sans signal de vente
        bearish_trend = global_signal['dominant_trend'] == 'bearish'
        
        return ((global_signal['action'] in sell_actions and sufficient_confidence) or
                (bearish_trend and global_signal['confidence'] > 70))
    
    def get_position_size(self, multi_tf_analysis):
        """Calcule la taille de position basée sur la confiance"""
        confidence = multi_tf_analysis['global_signal']['confidence']
        strength = abs(multi_tf_analysis['global_signal']['strength'])
        
        # Position sizing dynamique
        base_amount = self.amount_usdt
        
        if confidence >= 80 and strength >= 2:
            # Signal très fort et très confiant → position 1.5x
            return base_amount * 1.5
        elif confidence >= 70 and strength >= 1.5:
            # Signal fort et confiant → position 1.2x
            return base_amount * 1.2
        elif confidence >= 60:
            # Signal modéré → position normale
            return base_amount
        else:
            # Signal faible → position réduite
            return base_amount * 0.7
    
    def print_multi_tf_analysis(self, analysis):
        """Affiche l'analyse multi-timeframes"""
        print("\n" + "="*60)
        print(f"ANALYSE MULTI-TIMEFRAMES - {self.symbol}")
        print("="*60)
        
        # Analyse par timeframe
        for tf, tf_analysis in analysis['timeframes'].items():
            trend_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡", "unknown": "⚪"}
            icon = trend_icon.get(tf_analysis['trend'], "⚪")
            
            print(f"{icon} {tf.upper()}: {tf_analysis['trend'].upper()} (Force: {tf_analysis['strength']:.1f})")
            if tf_analysis['signals']:
                print(f"   Signaux: {', '.join(tf_analysis['signals'][:3])}")
        
        # Signal global
        global_signal = analysis['global_signal']
        action_icon = {
            'STRONG_BUY': '🚀', 'BUY': '📈', 'HOLD': '⏸️', 
            'SELL': '📉', 'STRONG_SELL': '💥'
        }
        icon = action_icon.get(global_signal['action'], '❓')
        
        print(f"\n{icon} SIGNAL GLOBAL: {global_signal['action']}")
        print(f"📊 Force: {global_signal['strength']:.2f}")
        print(f"🎯 Confiance: {global_signal['confidence']:.1f}%")
        print(f"📝 Résumé: {global_signal['summary']}")
        print("="*60)
    
    def run(self):
        """Version améliorée avec analyse multi-timeframes"""
        print(f"🚀 Démarrage Scalping Avancé {self.symbol}")
        print(f"🧠 Analyse multi-timeframes activée (1m, 5m, 15m)")
        print(f"🎯 Confiance minimum: {self.min_confidence}%")
        
        while True:
            try:
                current_price = self.bot.get_price(self.symbol)
                
                # Analyse multi-timeframes
                multi_tf_analysis = self.multi_tf_analyzer.analyze_all_timeframes(
                    self.bot, self.symbol, current_price
                )
                self.last_analysis = multi_tf_analysis
                
                # Logique d'achat améliorée
                if not self.position and self.should_buy(current_price, multi_tf_analysis):
                    if (self.safety_manager.can_trade() and 
                        self.risk_manager.can_trade(self.amount_usdt) and 
                        not self.portfolio_manager.should_diversify(self.bot) and
                        self.correlation_manager.can_open_position(self.symbol, self.bot)):
                        
                        # Position sizing intelligent
                        smart_amount = self.get_position_size(multi_tf_analysis)
                        amount = smart_amount / current_price
                        
                        order = self.bot.buy_market(self.symbol, amount)
                        if order:
                            self.position = 'long'
                            self.buy_price = current_price
                            
                            # Activer le trailing stop
                            self.trailing_stop.add_position(self.symbol, current_price)
                            self.correlation_manager.add_position(self.symbol)
                            
                            self.monitor.log_trade('BUY', self.symbol, amount, current_price)
                            self.safety_manager.record_trade(0)
                            
                            # Notification avec détails multi-timeframes
                            global_signal = multi_tf_analysis['global_signal']
                            print(f"🎯 ACHAT: {global_signal['summary']}")
                            self.alert_manager.notify_trade('BUY', self.symbol, amount, current_price)
                
                # Mise à jour du trailing stop
                if self.position == 'long':
                    self.trailing_stop.update_position(self.symbol, current_price)
                
                # Logique de vente améliorée
                elif (self.position == 'long' and 
                      (self.should_sell(current_price, multi_tf_analysis) or
                       self.trailing_stop.should_stop_loss(self.symbol, current_price))):
                    
                    balance = self.bot.get_balance()
                    base_currency = self.symbol.split('/')[0]
                    amount = balance[base_currency]['free']
                    
                    if amount > 0:
                        order = self.bot.sell_market(self.symbol, amount)
                        if order:
                            profit = (current_price - self.buy_price) * amount
                            self.position = None
                            
                            # Nettoyer les gestionnaires
                            self.trailing_stop.remove_position(self.symbol)
                            self.correlation_manager.remove_position(self.symbol)
                            
                            self.risk_manager.update_daily_loss(profit)
                            self.safety_manager.record_trade(profit)
                            self.monitor.log_trade('SELL', self.symbol, amount, current_price, profit)
                            self.alerts.check_alerts(profit)
                            
                            # Notification avec raison de vente
                            global_signal = multi_tf_analysis['global_signal']
                            if global_signal['action'] in ['SELL', 'STRONG_SELL']:
                                print(f"📉 VENTE: Signal multi-timeframes - {global_signal['summary']}")
                            else:
                                print(f"🛑 VENTE: Trailing stop - Profit: ${profit:.2f}")
                            
                            self.alert_manager.notify_trade('SELL', self.symbol, amount, current_price, profit)
                
                # Afficher dashboard toutes les 20 itérations
                if hasattr(self, 'counter'):
                    self.counter += 1
                else:
                    self.counter = 1
                    
                if self.counter % 20 == 0:
                    self.monitor.print_dashboard(self.bot)
                    self.print_multi_tf_analysis(multi_tf_analysis)
                
                time.sleep(2)  # Analyse plus fréquente pour multi-timeframes
                
            except Exception as e:
                print(f"❌ Erreur stratégie avancée: {e}")
                self.alert_manager.check_bot_status(False, str(e))
                
                if hasattr(self.bot, 'reconnect') and self.bot.reconnect():
                    print("✅ Reconnexion réussie, reprise du trading")
                    self.alert_manager.check_bot_status(True)
                else:
                    print("❌ Reconnexion échouée, attente 30s")
                    time.sleep(30)
    
    def get_current_analysis(self):
        """Retourne la dernière analyse multi-timeframes"""
        return self.last_analysis
    
    def set_confidence_threshold(self, threshold):
        """Modifie le seuil de confiance minimum"""
        self.min_confidence = max(0, min(100, threshold))
        print(f"🎯 Seuil de confiance mis à jour: {self.min_confidence}%")