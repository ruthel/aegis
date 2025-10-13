import time
from binance_spot_bot import BinanceSpotBot
from monitor import TradingMonitor, AlertSystem
from risk_manager import RiskManager, PortfolioManager
from safety_manager import SafetyManager
from advanced_risk_manager import AdvancedRiskManager, TrailingStopManager, CorrelationManager
from technical_indicators import SignalGenerator
from notification_manager import AlertManager

class ScalpingStrategy:
    def __init__(self, bot, symbol, amount_usdt=10):
        self.bot = bot
        self.symbol = symbol
        self.amount_usdt = amount_usdt
        self.last_price = 0
        self.position = None  # 'long' ou None
        self.monitor = TradingMonitor()
        self.alerts = AlertSystem()
        self.buy_price = 0
        self.risk_manager = RiskManager()
        self.portfolio_manager = PortfolioManager()
        self.safety_manager = SafetyManager()
        self.advanced_risk = AdvancedRiskManager()
        self.trailing_stop = TrailingStopManager(trailing_percent=3.0)
        self.correlation_manager = CorrelationManager()
        self.signal_generator = SignalGenerator()
        self.alert_manager = AlertManager()
        
    def run(self):
        while True:
            try:
                current_price = self.bot.get_price(self.symbol)
                if not current_price:
                    print(f"Prix non disponible pour {self.symbol}")
                    time.sleep(5)
                    continue
                
                # Analyser les signaux techniques
                klines = self.bot.get_klines(self.symbol, 50)
                if not klines or len(klines) < 10:
                    print(f"Données klines insuffisantes pour {self.symbol}")
                    time.sleep(5)
                    continue
                    
                technical_signal = self.signal_generator.analyze_signals(self.symbol, klines, current_price)
                if not technical_signal:
                    print("Signal technique non disponible")
                    time.sleep(5)
                    continue
                
                if self.last_price > 0:
                    change_percent = ((current_price - self.last_price) / self.last_price) * 100 if self.last_price != 0 else 0
                    
                    # Achat si signal technique BUY ET baisse de prix
                    if (technical_signal['action'] == 'BUY' and 
                        technical_signal['strength'] >= 2 and 
                        not self.position):
                        if (self.safety_manager.can_trade() and 
                            self.risk_manager.can_trade(self.amount_usdt) and 
                            not self.portfolio_manager.should_diversify(self.bot) and
                            self.correlation_manager.can_open_position(self.symbol, self.bot)):
                            
                            # Position sizing intelligent basé sur la volatilité
                            smart_amount = self.advanced_risk.calculate_position_size(self.bot, self.symbol, self.amount_usdt)
                            amount = smart_amount / current_price
                            
                            order = self.bot.buy_market(self.symbol, amount)
                            if order:
                                self.position = 'long'
                                self.buy_price = current_price
                                
                                # Activer le trailing stop
                                self.trailing_stop.add_position(self.symbol, current_price)
                                self.correlation_manager.add_position(self.symbol)
                                
                                self.monitor.log_trade('BUY', self.symbol, amount, current_price)
                                self.safety_manager.record_trade(0)  # Pas de P&L sur l'achat
                                print(f"🎯 Signal: {technical_signal['reason']} (Force: {technical_signal['strength']:.1f})")
                                
                                # Notification d'achat
                                self.alert_manager.notify_trade('BUY', self.symbol, amount, current_price)
                                self.alert_manager.notify_signal(self.symbol, 'BUY', technical_signal['strength'], technical_signal['reason'])
                    
                    # Mise à jour du trailing stop si en position
                    if self.position == 'long':
                        self.trailing_stop.update_position(self.symbol, current_price)
                    
                    # Vente si signal SELL, profit target ou trailing stop
                    elif ((technical_signal['action'] == 'SELL' and technical_signal['strength'] >= 2) or
                          change_percent >= 0.3 or 
                          self.trailing_stop.should_stop_loss(self.symbol, current_price)) and self.position == 'long':
                        
                        balance = self.bot.get_balance()
                        base_currency = self.symbol.split('/')[0]
                        
                        if not balance or base_currency not in balance:
                            print(f"Pas de solde disponible pour {base_currency}")
                            continue
                            
                        currency_balance = balance[base_currency]
                        if isinstance(currency_balance, dict):
                            amount = currency_balance.get('free', 0)
                        else:
                            amount = currency_balance if currency_balance else 0
                        
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
                                
                                # Notifications de vente
                                self.alert_manager.notify_trade('SELL', self.symbol, amount, current_price, profit)
                                
                                # Vérifier les seuils de profit/perte
                                daily_stats = self.safety_manager.get_stats()
                                daily_pnl = daily_stats['total_profit'] + daily_stats['total_loss']
                                self.alert_manager.check_profit_loss(profit, daily_pnl)
                                
                                # Afficher raison de la vente
                                if technical_signal['action'] == 'SELL':
                                    print(f"📉 Vente signal: {technical_signal['reason']}")
                                elif change_percent >= 0.3:
                                    print(f"💰 Vente profit: +{change_percent:.2f}%")
                                else:
                                    print("🛑 Vente trailing stop")
                
                self.last_price = current_price
                
                # Afficher dashboard toutes les 10 iterations
                if hasattr(self, 'counter'):
                    self.counter += 1
                else:
                    self.counter = 1
                    
                if self.counter % 10 == 0:
                    self.monitor.print_dashboard(self.bot)
                    
                    # Afficher signaux techniques
                    if len(klines) >= 30:
                        signal_summary = self.signal_generator.get_signal_summary(self.symbol)
                        rsi = technical_signal['indicators'].get('rsi')
                        macd = technical_signal['indicators'].get('macd')
                        
                        print(f"📈 Signaux {self.symbol}:")
                        print(f"   {signal_summary}")
                        if rsi: print(f"   RSI: {rsi:.1f}")
                        if macd: print(f"   MACD: {macd:.4f}")
                
                time.sleep(1)  # Réduit à 1 seconde avec WebSocket
                
            except Exception as e:
                print(f"Erreur strategie: {e}")
                print("Tentative de reconnexion...")
                
                # Notification d'erreur
                self.alert_manager.check_bot_status(False, str(e))
                
                if hasattr(self.bot, 'reconnect') and self.bot.reconnect():
                    print("Reconnexion réussie, reprise du trading")
                    self.alert_manager.check_bot_status(True)
                else:
                    print("Reconnexion échouée, attente 30s")
                    time.sleep(30)

class DCAStrategy:
    def __init__(self, bot, symbol, amount_usdt=10, interval_minutes=60):
        self.bot = bot
        self.symbol = symbol
        self.amount_usdt = amount_usdt
        self.interval = interval_minutes * 60
        
    def run(self):
        while True:
            try:
                current_price = self.bot.get_price(self.symbol)
                amount = self.amount_usdt / current_price
                
                order = self.bot.buy_market(self.symbol, amount)
                if order:
                    print(f"DCA ACHAT: {amount} {self.symbol} a {current_price}")
                
                time.sleep(self.interval)
                
            except Exception as e:
                print(f"Erreur DCA: {e}")
                print("Tentative de reconnexion...")
                if hasattr(self.bot, 'reconnect') and self.bot.reconnect():
                    print("Reconnexion réussie, reprise du DCA")
                else:
                    print("Reconnexion échouée, attente 60s")
                    time.sleep(60)