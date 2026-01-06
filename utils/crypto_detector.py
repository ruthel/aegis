"""Détecteur automatique de toutes les cryptos présentes dans le compte"""

class CryptoDetector:
    """Détecte et analyse toutes les cryptos présentes dans le compte Binance"""
    
    def __init__(self, bot):
        self.bot = bot
        
    def _get_allowed_assets(self):
        """Récupère la liste des cryptos autorisées depuis TRADING_PAIRS"""
        import os
        trading_pairs = os.getenv('TRADING_PAIRS', 'BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT').split(',')
        allowed_assets = set(['USDT'])  # USDT toujours autorisé
        
        for pair in trading_pairs:
            if '/' in pair:
                base = pair.split('/')[0]
            else:
                base = pair.replace('USDT', '')
            allowed_assets.add(base)
        
        return allowed_assets
    
    def detect_all_cryptos(self, min_value_usdt=0.01):
        """Détecte toutes les cryptos avec leurs balances dans tous les portefeuilles"""
        try:
            all_cryptos = {}
            allowed_assets = self._get_allowed_assets()
            
            # Récupérer toutes les balances
            balances = self.bot.balance_manager.get_all_balances()
            
            # Analyser Spot (seulement cryptos autorisées)
            for asset, balance in balances['spot'].items():
                if balance['total'] > 0 and asset in allowed_assets:
                    all_cryptos[asset] = {
                        'spot': balance['total'],
                        'funding': 0,
                        'earn': 0,
                        'total': balance['total']
                    }
            
            # Analyser Funding (seulement cryptos autorisées)
            for asset, balance in balances['funding'].items():
                if balance['total'] > 0 and asset in allowed_assets:
                    if asset not in all_cryptos:
                        all_cryptos[asset] = {'spot': 0, 'funding': 0, 'earn': 0, 'total': 0}
                    all_cryptos[asset]['funding'] = balance['total']
                    all_cryptos[asset]['total'] += balance['total']
            
            # Analyser Earn (seulement cryptos autorisées)
            for asset, balance in balances['earn'].items():
                if balance['total'] > 0 and asset in allowed_assets:
                    if asset not in all_cryptos:
                        all_cryptos[asset] = {'spot': 0, 'funding': 0, 'earn': 0, 'total': 0}
                    all_cryptos[asset]['earn'] = balance['total']
                    all_cryptos[asset]['total'] += balance['total']
            
            # Filtrer le dust et calculer valeur USDT
            if hasattr(self.bot, 'dust_manager'):
                filtered_cryptos, dust_detected = self.bot.dust_manager.filter_dust_balances(all_cryptos)
                
                # Afficher dust si détecté
                if dust_detected:
                    self.bot.dust_manager.show_dust_summary(dust_detected)
                
                # Calculer valeurs USDT pour les cryptos non-dust
                final_cryptos = {}
                for asset, data in filtered_cryptos.items():
                    if data['total'] > 0:
                        usdt_value = self._get_usdt_value(asset, data['total'])
                        if usdt_value >= min_value_usdt:
                            data['usdt_value'] = usdt_value
                            final_cryptos[asset] = data
                
                return final_cryptos
            else:
                # Fallback sans dust manager
                filtered_cryptos = {}
                for asset, data in all_cryptos.items():
                    if data['total'] > 0:
                        usdt_value = self._get_usdt_value(asset, data['total'])
                        if usdt_value >= min_value_usdt:
                            data['usdt_value'] = usdt_value
                            filtered_cryptos[asset] = data
                
                return filtered_cryptos
            
        except Exception as e:
            print(f"❌ Erreur détection cryptos: {e}")
            return {}
    
    def _get_usdt_value(self, asset, amount):
        """Calcule la valeur USDT approximative d'un asset"""
        if asset == 'USDT':
            return amount
        
        # En paper trading, utiliser les prix réels mais pas l'exchange
        if self.bot.paper_trading:
            try:
                # Utiliser get_price du bot qui gère déjà le paper trading
                symbol = f"{asset}/USDT"
                price = self.bot.get_price(symbol)
                return amount * price
            except:
                pass
        else:
            try:
                # Mode live - utiliser l'exchange directement
                if hasattr(self.bot, 'exchange') and self.bot.exchange:
                    symbol = f"{asset}/USDT"
                    ticker = self.bot.exchange.fetch_ticker(symbol)
                    return amount * ticker['last']
            except:
                pass
        
        # Valeurs approximatives pour les principales cryptos (fallback)
        approximate_prices = {
            'BTC': 67000, 'ETH': 4000, 'BNB': 600, 'SOL': 200,
            'ADA': 0.5, 'DOT': 8, 'MATIC': 1, 'AVAX': 40,
            'LINK': 15, 'UNI': 8, 'LTC': 100, 'BCH': 500
        }
        
        return amount * approximate_prices.get(asset, 0)
    
    def show_crypto_portfolio(self):
        """Affiche un résumé complet du portefeuille crypto (limité aux TRADING_PAIRS)"""
        cryptos = self.detect_all_cryptos()
        allowed_assets = self._get_allowed_assets()
        
        if not cryptos:
            print("📭 Aucune crypto autorisée détectée dans votre compte")
            return
        
        print(f"\n🔍 CRYPTOS AUTORISÉES DÉTECTÉES (TRADING_PAIRS):")
        print(f"{'Asset':<8} {'Spot':<12} {'Funding':<12} {'Earn':<12} {'Total':<12} {'Valeur USDT':<12}")
        print("─" * 80)
        
        total_portfolio_usdt = 0
        
        # Trier par valeur USDT décroissante
        sorted_cryptos = sorted(cryptos.items(), key=lambda x: x[1]['usdt_value'], reverse=True)
        
        for asset, data in sorted_cryptos:
            spot = data['spot']
            funding = data['funding'] 
            earn = data['earn']
            total = data['total']
            usdt_value = data['usdt_value']
            
            print(f"{asset:<8} {spot:<12.6f} {funding:<12.6f} {earn:<12.6f} {total:<12.6f} {usdt_value:<12.2f}")
            total_portfolio_usdt += usdt_value
        
        print("─" * 80)
        print(f"{'TOTAL':<8} {'':<48} {total_portfolio_usdt:<12.2f}")
        
        # Statistiques
        print(f"\n📊 STATISTIQUES PORTEFEUILLE (TRADING_PAIRS):")
        print(f"   • {len(cryptos)} cryptos autorisées")
        print(f"   • Valeur totale: {total_portfolio_usdt:.2f} USDT")
        print(f"   • Cryptos autorisées: {', '.join(sorted(allowed_assets))}")
        
        # Répartition par type
        spot_total = sum(data['spot'] * data['usdt_value'] / data['total'] for data in cryptos.values() if data['total'] > 0)
        funding_total = sum(data['funding'] * data['usdt_value'] / data['total'] for data in cryptos.values() if data['total'] > 0)
        earn_total = sum(data['earn'] * data['usdt_value'] / data['total'] for data in cryptos.values() if data['total'] > 0)
        
        if total_portfolio_usdt > 0:
            print(f"   • Spot: {spot_total:.2f} USDT ({spot_total/total_portfolio_usdt*100:.1f}%)")
            print(f"   • Funding: {funding_total:.2f} USDT ({funding_total/total_portfolio_usdt*100:.1f}%)")
            print(f"   • Earn: {earn_total:.2f} USDT ({earn_total/total_portfolio_usdt*100:.1f}%)")
        
        return cryptos
    
    def get_tradeable_cryptos(self):
        """Retourne les cryptos qui peuvent être tradées (limitées aux TRADING_PAIRS)"""
        allowed_assets = self._get_allowed_assets()
        all_cryptos = self.detect_all_cryptos()
        tradeable = []
        
        for asset in all_cryptos.keys():
            if asset != 'USDT' and asset in allowed_assets:
                tradeable.append(asset)
        
        return tradeable
    
    def suggest_trading_pairs(self):
        """Suggère les meilleures paires à trader basées sur le portefeuille"""
        tradeable = self.get_tradeable_cryptos()
        cryptos = self.detect_all_cryptos()
        
        suggestions = []
        for asset in tradeable:
            if asset in cryptos:
                usdt_value = cryptos[asset]['usdt_value']
                if usdt_value >= 10:  # Minimum 10 USDT pour trader
                    suggestions.append({
                        'pair': f"{asset}USDT",
                        'balance': cryptos[asset]['total'],
                        'usdt_value': usdt_value
                    })
        
        # Trier par valeur
        suggestions.sort(key=lambda x: x['usdt_value'], reverse=True)
        
        print(f"\n💡 SUGGESTIONS TRADING:")
        for suggestion in suggestions[:5]:  # Top 5
            print(f"   • {suggestion['pair']} - Balance: {suggestion['balance']:.6f} (~{suggestion['usdt_value']:.2f} USDT)")
        
        return suggestions