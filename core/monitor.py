import json
import time
from datetime import datetime
import os

class TradingMonitor:
    def __init__(self, log_file="trades.json"):
        self.log_file = log_file
        self.trades = self.load_trades()
        
    def load_trades(self):
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r') as f:
                return json.load(f)
        return []
    
    def save_trades(self):
        with open(self.log_file, 'w') as f:
            json.dump(self.trades, f, indent=2)
    
    def log_trade(self, action, symbol, amount, price, profit=0):
        trade = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'symbol': symbol,
            'amount': amount,
            'price': price,
            'profit': profit,
            'value': amount * price
        }
        self.trades.append(trade)
        self.save_trades()
        print(f"[{trade['timestamp']}] {action}: {amount} {symbol} @ ${price}")
    
    def get_stats(self):
        if not self.trades:
            return {'total_trades': 0, 'total_profit': 0, 'avg_profit': 0}
        
        total_profit = sum(t['profit'] for t in self.trades)
        total_trades = len(self.trades)
        
        return {
            'total_trades': total_trades,
            'total_profit': total_profit,
            'avg_profit': total_profit / total_trades if total_trades > 0 else 0
        }
    
    def print_dashboard(self, bot):
        stats = self.get_stats()
        balance = bot.balance_manager.get_balance()
        
        print("\n" + "="*50)
        print("DASHBOARD TRADING")
        print("="*50)
        print(f"Trades totaux: {stats['total_trades']}")
        print(f"Profit total: ${stats['total_profit']:.2f}")
        print(f"Profit moyen: ${stats['avg_profit']:.2f}")
        print(f"USDT: {balance.get('USDT', {}).get('free', 0)}")
        print(f"BTC: {balance.get('BTC', {}).get('free', 0)}")
        print(f"ETH: {balance.get('ETH', {}).get('free', 0)}")
        print(f"BNB: {balance.get('BNB', {}).get('free', 0)}")
        print(f"SOL: {balance.get('SOL', {}).get('free', 0)}")
        print("="*50)

class AlertSystem:
    def __init__(self, profit_threshold=50, loss_threshold=-20):
        self.profit_threshold = profit_threshold
        self.loss_threshold = loss_threshold
    
    def check_alerts(self, current_profit):
        if current_profit >= self.profit_threshold:
            self.send_alert(f"PROFIT ALERT: +${current_profit}")
        elif current_profit <= self.loss_threshold:
            self.send_alert(f"LOSS ALERT: ${current_profit}")
    
    def send_alert(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n*** ALERTE [{timestamp}] ***")
        print(message)
        print("*" * 30)