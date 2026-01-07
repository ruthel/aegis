"""
Gestionnaire de frais dynamiques - Niveau Professionnel
Récupère et optimise les frais réels comme les traders institutionnels
"""
import time
import os
from datetime import datetime, timedelta

class DynamicFeesManager:
    def __init__(self, bot):
        self.bot = bot
        self.fees_cache = {}
        self.last_fees_update = 0
        self.fees_update_interval = 3600  # 1h comme les pros
        self.vip_level = None
        self.bnb_discount = False
        
    def get_real_trading_fees(self, symbol):
        """Récupère frais réels depuis Binance - Méthode Institutionnelle"""
        cache_key = f"{symbol}_fees"
        now = time.time()
        
        # Cache 1h comme les pros (évite spam API)
        if (cache_key in self.fees_cache and 
            now - self.fees_cache[cache_key]['timestamp'] < self.fees_update_interval):
            return self.fees_cache[cache_key]['fees']
        
        try:
            if not self.bot.paper_trading:
                # 1. Récupérer frais réels via API
                fees_data = self.bot.safe_request(self.bot.exchange.fetch_trading_fees)
                
                if symbol in fees_data:
                    maker_fee = fees_data[symbol]['maker']
                    taker_fee = fees_data[symbol]['taker']
                    
                    # 2. Détecter niveau VIP automatiquement
                    self._detect_vip_level(taker_fee)
                    
                    # 3. Vérifier discount BNB
                    self._check_bnb_discount()
                    
                    # 4. Calculer frais optimaux (Maker prioritaire)
                    optimal_fee = self._calculate_optimal_fee(maker_fee, taker_fee)
                    
                    # Cache avec timestamp
                    self.fees_cache[cache_key] = {
                        'fees': {
                            'maker': maker_fee,
                            'taker': taker_fee,
                            'optimal': optimal_fee
                        },
                        'timestamp': now
                    }
                    
                    return self.fees_cache[cache_key]['fees']
                
        except Exception as e:
            print(f"⚠️ Erreur récupération frais {symbol}: {e}")
        
        # Fallback intelligent selon niveau détecté
        return self._get_fallback_fees()
    
    def _detect_vip_level(self, taker_fee):
        """Détecte niveau VIP selon frais taker"""
        if taker_fee <= 0.0002:  # 0.02%
            self.vip_level = "VIP 9"
        elif taker_fee <= 0.0004:  # 0.04%
            self.vip_level = "VIP 5-8"
        elif taker_fee <= 0.0007:  # 0.07%
            self.vip_level = "VIP 1-4"
        else:
            self.vip_level = "Standard"
    
    def _check_bnb_discount(self):
        """Vérifie si discount BNB actif"""
        try:
            if not self.bot.paper_trading:
                balance = self.bot.balance_manager.get_balance()
                bnb_balance = balance.get('BNB', {}).get('free', 0)
                self.bnb_discount = bnb_balance > 0.1  # Minimum pour discount
        except:
            self.bnb_discount = False
    
    def _calculate_optimal_fee(self, maker_fee, taker_fee):
        """Calcule frais optimal - Stratégie Institutionnelle"""
        # Priorité aux ordres Maker (comme les pros)
        if maker_fee < taker_fee:
            optimal = maker_fee
        else:
            # Si pas d'avantage Maker, utiliser Taker
            optimal = taker_fee
        
        # Appliquer discount BNB si disponible
        if self.bnb_discount:
            optimal *= 0.75  # 25% réduction
        
        return optimal
    
    def _get_fallback_fees(self):
        """Frais fallback intelligents selon niveau VIP détecté"""
        if self.vip_level == "VIP 9":
            base_fee = 0.0002
        elif "VIP" in str(self.vip_level):
            base_fee = 0.0005
        else:
            base_fee = 0.001  # Standard
        
        # Appliquer discount BNB
        if self.bnb_discount:
            base_fee *= 0.75
        
        return {
            'maker': base_fee * 0.9,  # Maker généralement plus bas
            'taker': base_fee,
            'optimal': base_fee * 0.9 if self.bnb_discount else base_fee
        }
    
    def get_fee_for_trade(self, symbol, order_type='market'):
        """Récupère frais pour un trade spécifique"""
        fees = self.get_real_trading_fees(symbol)
        
        if order_type == 'limit':
            return fees['maker']  # Ordre limite = Maker
        else:
            return fees['taker']  # Ordre marché = Taker
    
    def calculate_trade_cost(self, symbol, amount_usdt, order_type='market'):
        """Calcule coût total réel d'un trade"""
        fee_rate = self.get_fee_for_trade(symbol, order_type)
        fee_cost = amount_usdt * fee_rate
        
        return {
            'amount': amount_usdt,
            'fee_rate': fee_rate,
            'fee_cost': fee_cost,
            'total_cost': amount_usdt + fee_cost,
            'vip_level': self.vip_level,
            'bnb_discount': self.bnb_discount
        }
    
    def optimize_order_type(self, symbol, urgency='normal'):
        """Recommande type d'ordre optimal - Logique Institutionnelle"""
        fees = self.get_real_trading_fees(symbol)
        
        maker_advantage = fees['taker'] - fees['maker']
        
        if urgency == 'high':
            return 'market'  # Exécution immédiate prioritaire
        elif maker_advantage > 0.0002:  # Avantage significatif
            return 'limit'   # Économiser sur les frais
        else:
            return 'market'  # Pas d'avantage notable
    
    def get_fees_summary(self):
        """Résumé des frais pour monitoring"""
        if not self.fees_cache:
            return "Frais non initialisés"
        
        sample_fees = next(iter(self.fees_cache.values()))['fees']
        
        return {
            'vip_level': self.vip_level or "Détection en cours",
            'bnb_discount': "Actif" if self.bnb_discount else "Inactif",
            'maker_fee': f"{sample_fees['maker']*100:.3f}%",
            'taker_fee': f"{sample_fees['taker']*100:.3f}%",
            'optimal_fee': f"{sample_fees['optimal']*100:.3f}%"
        }