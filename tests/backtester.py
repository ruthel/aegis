import ccxt
import pandas as pd
from datetime import datetime, timedelta

class Backtester:
    def __init__(self, symbol='BTC/USDT', days=30):
        self.symbol = symbol
        self.days = days
        self.exchange = ccxt.binance()
        
    def get_historical_data(self):
        since = self.exchange.milliseconds() - (self.days * 24 * 60 * 60 * 1000)
        ohlcv = self.exchange.fetch_ohlcv(self.symbol, '5m', since)
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    
    def test_scalping_strategy(self, initial_balance=1000):
        data = self.get_historical_data()
        balance = initial_balance
        position = None
        buy_price = 0
        trades = []
        
        for i in range(1, len(data)):
            current_price = data.iloc[i]['close']
            prev_price = data.iloc[i-1]['close']
            change_percent = ((current_price - prev_price) / prev_price) * 100
            
            # Achat si baisse de 0.1%
            if change_percent <= -0.1 and not position and balance >= 10:
                amount = 10 / current_price
                position = amount
                buy_price = current_price
                balance -= 10
                trades.append({'action': 'BUY', 'price': current_price, 'amount': amount})
            
            # Vente si hausse de 0.2%
            elif change_percent >= 0.2 and position:
                sell_value = position * current_price
                profit = sell_value - (position * buy_price)
                balance += sell_value
                trades.append({'action': 'SELL', 'price': current_price, 'profit': profit})
                position = None
        
        total_profit = balance - initial_balance
        win_rate = len([t for t in trades if t.get('profit', 0) > 0]) / max(len([t for t in trades if 'profit' in t]), 1)
        
        return {
            'initial_balance': initial_balance,
            'final_balance': balance,
            'total_profit': total_profit,
            'profit_percent': (total_profit / initial_balance) * 100,
            'total_trades': len(trades),
            'win_rate': win_rate * 100
        }

class PaperTrader:
    def __init__(self, initial_balance=1000):
        self.balance = {'USDT': initial_balance, 'BTC': 0, 'ETH': 0, 'BNB': 0}
        self.trades = []
        
    def buy_market(self, symbol, amount_usdt):
        base_currency = symbol.split('/')[0]
        if self.balance['USDT'] >= amount_usdt:
            # Simuler prix actuel (ici on utilise un prix fixe pour demo)
            price = 50000 if base_currency == 'BTC' else 3000 if base_currency == 'ETH' else 300
            amount = amount_usdt / price
            
            self.balance['USDT'] -= amount_usdt
            self.balance[base_currency] += amount
            
            trade = {
                'timestamp': datetime.now().isoformat(),
                'action': 'BUY',
                'symbol': symbol,
                'amount': amount,
                'price': price,
                'value': amount_usdt
            }
            self.trades.append(trade)
            print(f"PAPER TRADE - BUY: {amount} {symbol} @ ${price}")
            return trade
        return None
    
    def sell_market(self, symbol, amount):
        base_currency = symbol.split('/')[0]
        if self.balance[base_currency] >= amount:
            price = 50000 if base_currency == 'BTC' else 3000 if base_currency == 'ETH' else 300
            value = amount * price
            
            self.balance[base_currency] -= amount
            self.balance['USDT'] += value
            
            trade = {
                'timestamp': datetime.now().isoformat(),
                'action': 'SELL',
                'symbol': symbol,
                'amount': amount,
                'price': price,
                'value': value
            }
            self.trades.append(trade)
            print(f"PAPER TRADE - SELL: {amount} {symbol} @ ${price}")
            return trade
        return None
    
    def get_balance(self):
        return {currency: {'free': amount} for currency, amount in self.balance.items()}
    
    def get_price(self, symbol):
        base_currency = symbol.split('/')[0]
        return 50000 if base_currency == 'BTC' else 3000 if base_currency == 'ETH' else 300