"""Gestionnaire des valeurs crypto très petites (dust)"""
import os

class DustManager:
    """Gère les valeurs crypto très petites pour éviter les erreurs Binance"""
    
    def __init__(self, bot):
        self.bot = bot
        
        # Seuils minimums pour considérer une crypto comme "dust"
        self.dust_thresholds_usdt = {
            'BTC': 0.50,    # < 0.50 USDT = dust
            'ETH': 0.50,
            'SOL': 0.50,
            'BNB': 0.50,
            'ADA': 0.10,    # Cryptos moins chères
            'DOT': 0.20,
            'MATIC': 0.10,
            'AVAX': 0.30,
            'LINK': 0.30,
            'UNI': 0.20,
            'LTC': 0.50,
            'BCH': 0.50
        }
        
        # Minimums Binance sécurisés (fallback)
        self.safe_minimums = {
            'BTC/USDT': {'min_amount': 0.00001, 'min_cost': 1.0},
            'ETH/USDT': {'min_amount': 0.0001, 'min_cost': 1.0},
            'SOL/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'BNB/USDT': {'min_amount': 0.001, 'min_cost': 1.0},
            'ADA/USDT': {'min_amount': 1.0, 'min_cost': 1.0},
            'DOT/USDT': {'min_amount': 0.1, 'min_cost': 1.0},
            'MATIC/USDT': {'min_amount': 1.0, 'min_cost': 1.0},
            'AVAX/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'LINK/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'UNI/USDT': {'min_amount': 0.01, 'min_cost': 1.0},
            'LTC/USDT': {'min_amount': 0.001, 'min_cost': 1.0},
            'BCH/USDT': {'min_amount': 0.001, 'min_cost': 1.0}
        }
    
    def is_dust(self, asset, amount):
        """Vérifie si une quantité de crypto est considérée comme dust"""
        try:
            if asset == 'USDT':
                return amount < 1.0  # Moins de 1 USDT = dust
            
            # Calculer valeur USDT
            symbol = f"{asset}/USDT"
            price = self.bot.get_price(symbol)
            usdt_value = amount * price
            
            # Seuil dust pour cette crypto
            dust_threshold = self.dust_thresholds_usdt.get(asset, 0.50)
            
            return usdt_value < dust_threshold
            
        except Exception as e:
            print(f"⚠️ Erreur vérification dust {asset}: {e}")
            return True  # En cas d'erreur, considérer comme dust par sécurité
    
    def is_tradeable_amount(self, symbol, amount):
        """Vérifie si une quantité peut être tradée (respecte minimums Binance)"""
        try:
            # Récupérer minimums sécurisés
            minimums = self.safe_minimums.get(symbol, {'min_amount': 0.001, 'min_cost': 1.0})
            
            # Vérifier montant minimum
            if amount < minimums['min_amount']:
                return False
            
            # Vérifier coût minimum
            price = self.bot.get_price(symbol)
            cost = amount * price
            
            if cost < minimums['min_cost']:
                return False
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur vérification tradeable {symbol}: {e}")
            return False
    
    def filter_dust_balances(self, balances):
        """Filtre les balances pour exclure le dust"""
        filtered_balances = {}
        dust_detected = {}
        
        for asset, balance_data in balances.items():
            total_amount = balance_data.get('total', 0)
            
            if asset == 'USDT':
                # USDT toujours inclus (même petites quantités)
                filtered_balances[asset] = balance_data
            elif not self.is_dust(asset, total_amount):
                # Crypto avec valeur suffisante
                filtered_balances[asset] = balance_data
            else:
                # Dust détecté
                dust_detected[asset] = {
                    'amount': total_amount,
                    'usdt_value': self._get_usdt_value(asset, total_amount)
                }
        
        return filtered_balances, dust_detected
    
    def _get_usdt_value(self, asset, amount):
        """Calcule la valeur USDT d'un asset"""
        try:
            if asset == 'USDT':
                return amount
            
            symbol = f"{asset}/USDT"
            price = self.bot.get_price(symbol)
            return amount * price
            
        except:
            return 0
    
    def show_dust_summary(self, dust_detected):
        """Affiche un résumé du dust détecté"""
        if not dust_detected:
            return
        
        print(f"\n🧹 DUST DÉTECTÉ (valeurs trop petites pour trader):")
        total_dust_usdt = 0
        
        for asset, data in dust_detected.items():
            amount = data['amount']
            usdt_value = data['usdt_value']
            total_dust_usdt += usdt_value
            
            print(f"   • {asset}: {amount:.8f} (~{usdt_value:.4f} USDT)")
        
        print(f"   Total dust: {total_dust_usdt:.4f} USDT")
        
        if total_dust_usdt > 0.10:
            print(f"   💡 Conseil: Convertir le dust en BNB via Binance (Convert Small Assets)")
    
    def get_tradeable_balance(self, symbol):
        """Retourne la balance tradeable (sans dust) pour un symbole"""
        try:
            balance = self.bot.balance_manager.get_balance()
            base_currency = symbol.split('/')[0]
            
            if base_currency not in balance:
                return 0
            
            total_amount = balance[base_currency].get('free', 0)
            
            # Vérifier si tradeable
            if self.is_tradeable_amount(symbol, total_amount):
                return total_amount
            else:
                return 0
                
        except Exception as e:
            print(f"⚠️ Erreur balance tradeable {symbol}: {e}")
            return 0
    
    def suggest_dust_cleanup(self):
        """Suggère des actions pour nettoyer le dust"""
        try:
            balance = self.bot.balance_manager.get_balance()
            filtered_balance, dust_detected = self.filter_dust_balances(balance)
            
            if dust_detected:
                self.show_dust_summary(dust_detected)
                
                print(f"\n🔧 ACTIONS RECOMMANDÉES:")
                print(f"   1. Binance Web → Wallet → Convert Small Assets to BNB")
                print(f"   2. Ou ignorer (le bot ne tentera pas de trader ces montants)")
                
                return dust_detected
            
            return {}
            
        except Exception as e:
            print(f"⚠️ Erreur suggestion cleanup: {e}")
            return {}
    
    def validate_trade_amount(self, symbol, amount):
        """Valide qu'un montant peut être tradé sans erreur"""
        try:
            # Vérifier minimums sécurisés
            if not self.is_tradeable_amount(symbol, amount):
                base_currency = symbol.split('/')[0]
                minimums = self.safe_minimums.get(symbol, {'min_amount': 0.001, 'min_cost': 1.0})
                
                print(f"❌ {base_currency}: Montant trop petit pour trader")
                print(f"   Minimum: {minimums['min_amount']} {base_currency}")
                print(f"   Coût minimum: {minimums['min_cost']} USDT")
                
                return False
            
            return True
            
        except Exception as e:
            print(f"⚠️ Erreur validation trade: {e}")
            return False
    
    def get_minimum_trade_amount(self, symbol):
        """Retourne le montant minimum pour trader un symbole"""
        minimums = self.safe_minimums.get(symbol, {'min_amount': 0.001, 'min_cost': 1.0})
        
        try:
            price = self.bot.get_price(symbol)
            
            # Calculer montant minimum basé sur le coût
            min_amount_by_cost = minimums['min_cost'] / price
            
            # Prendre le maximum entre min_amount et min_amount_by_cost
            return max(minimums['min_amount'], min_amount_by_cost)
            
        except:
            return minimums['min_amount']