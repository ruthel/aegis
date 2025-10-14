from backtester import Backtester

class StrategyOptimizer:
    def __init__(self, symbol='BTC/USDT'):
        self.symbol = symbol
        self.backtester = Backtester(symbol)
        
    def optimize_scalping_params(self):
        best_params = None
        best_profit = -float('inf')
        
        # Tester différents seuils
        buy_thresholds = [-0.05, -0.1, -0.15, -0.2]
        sell_thresholds = [0.1, 0.15, 0.2, 0.25]
        
        print("Optimisation des parametres...")
        
        for buy_thresh in buy_thresholds:
            for sell_thresh in sell_thresholds:
                result = self.test_params(buy_thresh, sell_thresh)
                
                if result['total_profit'] > best_profit:
                    best_profit = result['total_profit']
                    best_params = {
                        'buy_threshold': buy_thresh,
                        'sell_threshold': sell_thresh,
                        'profit': result['total_profit'],
                        'win_rate': result['win_rate']
                    }
                
                print(f"Buy: {buy_thresh}%, Sell: {sell_thresh}% -> Profit: ${result['total_profit']:.2f}")
        
        return best_params
    
    def test_params(self, buy_threshold, sell_threshold):
        # Version simplifiée du backtest avec paramètres personnalisés
        data = self.backtester.get_historical_data()
        balance = 1000
        position = None
        buy_price = 0
        trades = []
        
        for i in range(1, len(data)):
            current_price = data.iloc[i]['close']
            prev_price = data.iloc[i-1]['close']
            change_percent = ((current_price - prev_price) / prev_price) * 100
            
            if change_percent <= buy_threshold and not position and balance >= 10:
                amount = 10 / current_price
                position = amount
                buy_price = current_price
                balance -= 10
                trades.append({'action': 'BUY', 'price': current_price})
            
            elif change_percent >= sell_threshold and position:
                sell_value = position * current_price
                profit = sell_value - (position * buy_price)
                balance += sell_value
                trades.append({'action': 'SELL', 'price': current_price, 'profit': profit})
                position = None
        
        total_profit = balance - 1000
        win_trades = [t for t in trades if t.get('profit', 0) > 0]
        win_rate = len(win_trades) / max(len([t for t in trades if 'profit' in t]), 1) * 100
        
        return {
            'total_profit': total_profit,
            'win_rate': win_rate,
            'total_trades': len(trades)
        }