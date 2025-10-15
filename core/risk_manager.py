from datetime import datetime, timedelta

class RiskManager:
    def __init__(self, max_daily_loss=100, max_position_size=50, stop_loss_percent=5):
        self.max_daily_loss = max_daily_loss
        self.max_position_size = max_position_size
        self.stop_loss_percent = stop_loss_percent
        self.daily_loss = 0
        self.last_reset = datetime.now().date()
        
    def reset_daily_counters(self):
        today = datetime.now().date()
        if today > self.last_reset:
            self.daily_loss = 0
            self.last_reset = today
    
    def can_trade(self, trade_amount):
        self.reset_daily_counters()
        
        # Vérifier limite journalière
        if abs(self.daily_loss) >= self.max_daily_loss:
            print(f"STOP: Limite de perte journalière atteinte (${abs(self.daily_loss)})")
            return False
            
        # Vérifier taille de position
        if trade_amount > self.max_position_size:
            print(f"STOP: Position trop importante (${trade_amount} > ${self.max_position_size})")
            return False
            
        return True
    
    def check_stop_loss(self, buy_price, current_price):
        if buy_price == 0:
            return False
        loss_percent = ((current_price - buy_price) / buy_price) * 100
        if loss_percent <= -self.stop_loss_percent:
            print(f"STOP LOSS: Perte de {loss_percent:.2f}%")
            return True
        return False
    
    def update_daily_loss(self, profit):
        if profit < 0:
            self.daily_loss += abs(profit)

class PortfolioManager:
    def __init__(self, max_crypto_allocation=0.7):
        self.max_crypto_allocation = max_crypto_allocation
        
    def should_diversify(self, bot):
        balance = bot.balance_manager.get_balance()
        total_usdt = balance.get('USDT', {}).get('free', 0)
        
        crypto_value = 0
        for symbol in ['BTC', 'ETH', 'BNB']:
            if symbol in balance:
                amount = balance[symbol]['free']
                if amount > 0:
                    try:
                        price = bot.get_price(f"{symbol}/USDT")
                        crypto_value += amount * price
                    except:
                        pass
        
        total_value = total_usdt + crypto_value
        if total_value == 0:
            return False
            
        crypto_ratio = crypto_value / total_value if total_value > 0 else 0
        
        if crypto_ratio > self.max_crypto_allocation:
            print(f"DIVERSIFICATION: {crypto_ratio:.1%} en crypto (max {self.max_crypto_allocation:.1%})")
            return True
        return False