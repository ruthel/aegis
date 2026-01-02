"""Détecteur de Contagion et Corrélations Extrêmes"""
import time
import statistics

class ContagionDetector:
    def __init__(self):
        self.contagion_mode = False
        self.contagion_start = None
        self.contagion_duration = 6 * 3600  # 6h
        self.last_check = 0
        self.check_interval = 300  # Vérifier toutes les 5min
        self.price_history = {}
    
    def detect_market_contagion(self, bot, trading_pairs):
        """Détecte la contagion sur tous les marchés"""
        current_time = time.time()
        
        # Vérifier seulement toutes les 5 minutes
        if current_time - self.last_check < self.check_interval:
            return self.contagion_mode
        
        self.last_check = current_time
        
        try:
            # Collecter prix actuels
            current_prices = {}
            price_changes = {}
            
            for pair in trading_pairs:
                symbol = pair if '/' in pair else f"{pair[:3]}/{pair[3:]}"
                try:
                    current_price = bot.get_price(symbol)
                    current_prices[symbol] = current_price
                    
                    # Calculer changement sur 1h
                    if symbol in self.price_history:
                        old_price = self.price_history[symbol]
                        change_pct = ((current_price - old_price) / old_price) * 100
                        price_changes[symbol] = change_pct
                    
                except Exception as e:
                    print(f"⚠️ Erreur prix {symbol}: {e}")
                    continue
            
            # Mettre à jour historique
            self.price_history = current_prices.copy()
            
            if len(price_changes) >= 3:
                contagion_detected = self._analyze_contagion(price_changes)
                
                if contagion_detected and not self.contagion_mode:
                    self._activate_contagion_mode(price_changes)
                elif self.contagion_mode and self.contagion_start:
                    # Vérifier si sortie de contagion
                    if current_time - self.contagion_start > self.contagion_duration:
                        self._check_contagion_recovery(price_changes)
            
            return self.contagion_mode
            
        except Exception as e:
            print(f"❌ Erreur détection contagion: {e}")
            return self.contagion_mode
    
    def _analyze_contagion(self, price_changes):
        """Analyse les corrélations pour détecter contagion"""
        changes = list(price_changes.values())
        
        if len(changes) < 3:
            return False
        
        # Critères de contagion
        negative_count = sum(1 for change in changes if change < -5)  # Chutes >5%
        avg_change = statistics.mean(changes)
        
        # CONTAGION si:
        # - Plus de 70% des cryptos chutent >5%
        # - OU moyenne générale < -10%
        contagion_criteria = (
            (negative_count / len(changes)) > 0.7 or  # 70%+ en chute
            avg_change < -10  # Moyenne < -10%
        )
        
        return contagion_criteria
    
    def _activate_contagion_mode(self, price_changes):
        """Active le mode contagion avec ventes d'urgence"""
        self.contagion_mode = True
        self.contagion_start = time.time()
        
        avg_change = statistics.mean(price_changes.values())
        negative_count = sum(1 for change in price_changes.values() if change < -5)
        
        print(f"🦠 CONTAGION DÉTECTÉE")
        print(f"📉 Moyenne marché: {avg_change:.1f}%")
        print(f"🔴 Cryptos en chute: {negative_count}/{len(price_changes)}")
        print(f"🚨 ACTIVATION MODE DÉFENSIF")
        
        # Afficher détail par crypto
        for symbol, change in price_changes.items():
            crypto = symbol.split('/')[0]
            if change < -5:
                print(f"   🔴 {crypto}: {change:.1f}%")
    
    def _check_contagion_recovery(self, price_changes):
        """Vérifie si récupération de la contagion"""
        changes = list(price_changes.values())
        avg_change = statistics.mean(changes)
        positive_count = sum(1 for change in changes if change > 0)
        
        # Récupération si:
        # - Moyenne positive OU
        # - Plus de 50% en hausse
        recovery = avg_change > 0 or (positive_count / len(changes)) > 0.5
        
        if recovery:
            self.contagion_mode = False
            self.contagion_start = None
            print("✅ RÉCUPÉRATION CONTAGION - Reprise trading")
            print(f"📈 Moyenne marché: {avg_change:.1f}%")
    
    def can_trade(self, symbol=None):
        """Vérifie si trading autorisé pendant contagion"""
        if self.contagion_mode:
            remaining_time = (self.contagion_duration - (time.time() - self.contagion_start)) / 3600
            if remaining_time > 0:
                if symbol:
                    crypto = symbol.split('/')[0]
                    print(f"🚫 {crypto}: Contagion active ({remaining_time:.1f}h)")
                return False
        
        return True
    
    def should_emergency_sell(self, bot, symbol):
        """Détermine si vente d'urgence nécessaire"""
        if not self.contagion_mode:
            return False
        
        # Vendre si contagion détectée récemment (dans les 30 min)
        if self.contagion_start and (time.time() - self.contagion_start) < 1800:
            return True
        
        return False
    
    def get_market_health(self):
        """Retourne l'état de santé du marché"""
        if self.contagion_mode:
            return 'CONTAGION'
        else:
            return 'HEALTHY'