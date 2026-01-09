import time
import json
from datetime import datetime, timedelta
from utils.market_analyzer import MarketAnalyzer

class StuckPositionManager:
    def __init__(self, max_loss_percent=15, stuck_threshold_hours=24):
        self.max_loss_percent = max_loss_percent
        self.stuck_threshold_hours = stuck_threshold_hours
        self.stuck_positions = {}
        self.recovery_strategies = {}
        
    def check_stuck_position(self, symbol, current_price, buy_price, buy_time):
        """Vérifie si une position est bloquée"""
        loss_percent = MarketAnalyzer.calculate_loss_percent(current_price, buy_price)
        hours_held = MarketAnalyzer.calculate_hours_held(buy_time)
        
        is_stuck = (
            loss_percent < -5 and  # Perte > 5%
            hours_held > self.stuck_threshold_hours  # Détenu > 24h
        )
        
        if is_stuck:
            if symbol not in self.stuck_positions:
                self.stuck_positions[symbol] = {
                    'buy_price': buy_price,
                    'buy_time': buy_time,
                    'detected_at': time.time(),
                    'max_loss': loss_percent,
                    'recovery_attempts': 0
                }
                print(f"⚠️ POSITION BLOQUÉE: {symbol}")
                print(f"   💸 Perte: {loss_percent:.2f}%")
                print(f"   ⏰ Détenu: {hours_held:.1f}h")
            else:
                # Mettre à jour la perte max
                if loss_percent < self.stuck_positions[symbol]['max_loss']:
                    self.stuck_positions[symbol]['max_loss'] = loss_percent
        
        return is_stuck, loss_percent
    
    def get_recovery_strategy(self, symbol, loss_percent, current_price, buy_price):
        """Détermine la stratégie de récupération"""
        
        # STRATÉGIE 1: DCA Agressif (perte -5% à -10%)
        if -10 < loss_percent <= -5:
            return {
                'strategy': 'dca_aggressive',
                'action': 'buy_more',
                'amount_multiplier': 1.5,  # Acheter 1.5x le montant initial
                'reason': 'Moyenner à la baisse pour réduire prix moyen',
                'target_profit': 2.0  # Viser 2% de profit
            }
        
        # STRATÉGIE 2: DCA Modéré (perte -10% à -15%)
        elif -15 < loss_percent <= -10:
            return {
                'strategy': 'dca_moderate',
                'action': 'buy_more',
                'amount_multiplier': 1.0,  # Acheter montant égal
                'reason': 'Accumulation progressive',
                'target_profit': 1.0  # Viser 1% de profit
            }
        
        # STRATÉGIE 3: Stop Loss d'urgence (perte > -15%)
        elif loss_percent <= -15:
            return {
                'strategy': 'emergency_exit',
                'action': 'sell_all',
                'reason': f'Perte critique {loss_percent:.1f}% - Limiter dégâts',
                'force': True
            }
        
        # STRATÉGIE 4: Attente rebond (perte -3% à -5%)
        else:
            return {
                'strategy': 'wait_bounce',
                'action': 'hold',
                'reason': 'Attendre rebond technique',
                'sell_target': buy_price * 1.005  # Vendre à +0.5%
            }
    
    def execute_recovery(self, bot, symbol, current_price):
        """Exécute la stratégie de récupération"""
        if symbol not in self.stuck_positions:
            return False
        
        stuck_data = self.stuck_positions[symbol]
        buy_price = stuck_data['buy_price']
        loss_percent = MarketAnalyzer.calculate_loss_percent(current_price, buy_price)
        
        strategy = self.get_recovery_strategy(symbol, loss_percent, current_price, buy_price)
        
        print(f"\n🔧 RÉCUPÉRATION: {symbol}")
        print(f"📊 Stratégie: {strategy['strategy'].upper()}")
        print(f"💡 Raison: {strategy['reason']}")
        
        # Si vente d'urgence, blacklister la crypto
        if strategy['action'] == 'sell_all':
            if hasattr(bot, 'crypto_scorer'):
                bot.crypto_scorer.add_to_blacklist(symbol)
        
        # Exécuter l'action
        if strategy['action'] == 'buy_more':
            # DCA pour moyenner
            import os
            base_amount = float(os.getenv('TRADE_AMOUNT', '8'))
            dca_amount = base_amount * strategy['amount_multiplier']
            
            print(f"🔄 DCA: Achat {dca_amount:.2f} USDT pour moyenner")
            trade_amount = dca_amount / current_price
            result = bot.buy_market(symbol, trade_amount)
            
            if result:
                stuck_data['recovery_attempts'] += 1
                # Recalculer prix moyen
                print(f"✅ DCA exécuté - Tentative #{stuck_data['recovery_attempts']}")
                return True
        
        elif strategy['action'] == 'sell_all':
            # Vente d'urgence
            print(f"🚨 VENTE D'URGENCE - Perte: {loss_percent:.2f}%")
            base_currency = symbol.split('/')[0]
            balance = bot.balance_manager.get_balance()
            available = balance.get(base_currency, {}).get('free', 0)
            
            if available > 0:
                result = bot.sell_market(symbol, available)
                if result:
                    del self.stuck_positions[symbol]
                    print(f"✅ Position liquidée - Perte acceptée")
                    if bot.notify_trades:
                        bot.notifier.notify(f"🚨 STOP LOSS: {symbol} vendu à {loss_percent:.1f}%")
                    return True
        
        elif strategy['action'] == 'hold':
            # Attendre rebond
            sell_target = strategy['sell_target']
            if current_price >= sell_target:
                print(f"🎯 Rebond atteint! Vente à {current_price:.6f}")
                base_currency = symbol.split('/')[0]
                balance = bot.balance_manager.get_balance()
                available = balance.get(base_currency, {}).get('free', 0)
                
                if available > 0:
                    result = bot.sell_market(symbol, available)
                    if result:
                        del self.stuck_positions[symbol]
                        print(f"✅ Position récupérée avec profit minimal")
                        return True
            else:
                print(f"⏳ Attente rebond: {current_price:.6f} → {sell_target:.6f}")
        
        return False
    
    def get_stuck_summary(self):
        """Résumé des positions bloquées"""
        if not self.stuck_positions:
            return None
        
        total_stuck = len(self.stuck_positions)
        total_loss = sum(pos['max_loss'] for pos in self.stuck_positions.values())
        avg_loss = total_loss / total_stuck if total_stuck > 0 else 0
        
        return {
            'count': total_stuck,
            'total_loss_percent': total_loss,
            'avg_loss_percent': avg_loss,
            'positions': self.stuck_positions
        }
    
    def show_stuck_positions(self):
        """Affiche les positions bloquées"""
        summary = self.get_stuck_summary()
        if summary:
            print(f"\n⚠️ POSITIONS BLOQUÉES: {summary['count']}")
            print(f"💸 Perte totale: {summary['total_loss_percent']:.2f}%")
            print(f"📊 Perte moyenne: {summary['avg_loss_percent']:.2f}%")
            
            for symbol, data in summary['positions'].items():
                hours_stuck = (time.time() - data['detected_at']) / 3600
                print(f"   • {symbol}: {data['max_loss']:.2f}% (bloqué {hours_stuck:.1f}h)")
