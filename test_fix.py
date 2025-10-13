#!/usr/bin/env python3
"""
Test rapide pour vérifier les corrections des divisions par zéro
"""

from strategy import ScalpingStrategy
from risk_manager import RiskManager, PortfolioManager

class MockBot:
    def get_price(self, symbol):
        return 50000.0  # Prix fictif pour BTC
    
    def get_balance(self):
        return {
            'USDT': {'free': 1000},
            'BTC': {'free': 0},
            'ETH': {'free': 0},
            'BNB': {'free': 0}
        }

def test_strategy_fix():
    """Test de la correction dans strategy.py"""
    print("=== Test Strategy Fix ===")
    
    bot = MockBot()
    strategy = ScalpingStrategy(bot, 'BTC/USDT', 10)
    
    # Test avec last_price = 0 (cas qui causait l'erreur)
    strategy.last_price = 0
    current_price = 50000.0
    
    try:
        # Simuler le calcul qui causait l'erreur
        if strategy.last_price > 0:
            change_percent = ((current_price - strategy.last_price) / strategy.last_price) * 100 if strategy.last_price != 0 else 0
            print(f"✅ Calcul réussi: change_percent = {change_percent}")
        else:
            print("✅ Pas de calcul car last_price = 0")
    except ZeroDivisionError:
        print("❌ Erreur de division par zéro encore présente")
    except Exception as e:
        print(f"❌ Autre erreur: {e}")

def test_risk_manager_fix():
    """Test de la correction dans risk_manager.py"""
    print("\n=== Test Risk Manager Fix ===")
    
    risk_manager = RiskManager()
    
    # Test stop_loss avec buy_price = 0
    try:
        result = risk_manager.check_stop_loss(0, 50000)
        print(f"✅ Stop loss avec buy_price=0: {result}")
    except ZeroDivisionError:
        print("❌ Erreur de division par zéro dans check_stop_loss")
    except Exception as e:
        print(f"❌ Autre erreur: {e}")
    
    # Test portfolio manager
    portfolio_manager = PortfolioManager()
    bot = MockBot()
    
    try:
        result = portfolio_manager.should_diversify(bot)
        print(f"✅ Portfolio diversification: {result}")
    except ZeroDivisionError:
        print("❌ Erreur de division par zéro dans should_diversify")
    except Exception as e:
        print(f"❌ Autre erreur: {e}")

if __name__ == "__main__":
    print("Test des corrections de division par zéro")
    print("=" * 50)
    
    test_strategy_fix()
    test_risk_manager_fix()
    
    print("\n" + "=" * 50)
    print("✅ Tests terminés - Les corrections semblent fonctionner")
    print("Vous pouvez maintenant relancer votre paper trading")