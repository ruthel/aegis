"""
Affichage transparent des décisions de trading
"""
import os

class DecisionDisplay:
    def __init__(self):
        pass
    
    def show_decision(self, decision_type, symbol, reason, progress=None):
        """Affiche décision de trading"""
        crypto = symbol.split('/')[0]
        icons = {'HOLD': '⏳', 'SKIP': '❌', 'BUY_READY': '🎯', 'SELL_READY': '🎯'}
        icon = icons.get(decision_type, '📊')
        
        msg = f"{icon} {decision_type} {crypto}: {reason}"
        if progress is not None:
            bar = self._progress_bar(progress)
            msg += f" {bar} {progress:.0f}%"
        
        print(msg)
    
    def show_analysis_summary(self, symbol, signal, confidence, price):
        """Résumé analyse technique"""
        crypto = symbol.replace('/USDT', '')
        conf_bar = self._progress_bar(confidence, 60)
        print(f"📊 {crypto} {price:.2f} | Signal: {signal} | Confiance: {conf_bar} {confidence:.0f}%")
    
    def _progress_bar(self, value, width=10):
        filled = int((value / 100) * width)
        return '[' + '█' * filled + '░' * (width - filled) + ']'
    
    def show_conditions_check(self, symbol, action, conditions):
        """Affiche vérification conditions"""
        crypto = symbol.split('/')[0]
        print(f"\n📊 CONDITIONS {action} {crypto}:")
        for name, status in conditions.items():
            icon = '✅' if status else '❌'
            print(f"  {icon} {name}")
