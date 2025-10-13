from backtester import Backtester, PaperTrader
from optimizer import StrategyOptimizer
from strategy import ScalpingStrategy
import time

def run_backtest():
    print("=== BACKTEST SCALPING ===")
    backtester = Backtester('BTC/USDT', days=7)
    result = backtester.test_scalping_strategy()
    
    print(f"Balance initiale: ${result['initial_balance']}")
    print(f"Balance finale: ${result['final_balance']:.2f}")
    print(f"Profit total: ${result['total_profit']:.2f}")
    print(f"Profit %: {result['profit_percent']:.2f}%")
    print(f"Trades totaux: {result['total_trades']}")
    print(f"Taux de reussite: {result['win_rate']:.1f}%")

def run_optimization():
    print("\n=== OPTIMISATION ===")
    optimizer = StrategyOptimizer('BTC/USDT')
    best_params = optimizer.optimize_scalping_params()
    
    print(f"\nMeilleurs parametres:")
    print(f"Seuil achat: {best_params['buy_threshold']}%")
    print(f"Seuil vente: {best_params['sell_threshold']}%")
    print(f"Profit: ${best_params['profit']:.2f}")
    print(f"Taux reussite: {best_params['win_rate']:.1f}%")

def run_paper_trading():
    print("\n=== PAPER TRADING ===")
    paper_bot = PaperTrader(1000)
    strategy = ScalpingStrategy(paper_bot, 'BTC/USDT', amount_usdt=10)
    
    print("Demarrage paper trading (30 secondes)...")
    start_time = time.time()
    
    # Simuler quelques trades
    for i in range(3):
        paper_bot.buy_market('BTC/USDT', 10)
        time.sleep(2)
        paper_bot.sell_market('BTC/USDT', 0.0002)
        time.sleep(2)
    
    balance = paper_bot.get_balance()
    print(f"Balance finale USDT: {balance['USDT']['free']:.2f}")
    print(f"Trades executes: {len(paper_bot.trades)}")

def main():
    print("Suite de tests et optimisation")
    print("1. Backtest")
    print("2. Optimisation")
    print("3. Paper Trading")
    print("4. Tout")
    
    choice = input("Choisir (1-4): ")
    
    if choice == "1":
        run_backtest()
    elif choice == "2":
        run_optimization()
    elif choice == "3":
        run_paper_trading()
    elif choice == "4":
        run_backtest()
        run_optimization()
        run_paper_trading()

if __name__ == "__main__":
    main()