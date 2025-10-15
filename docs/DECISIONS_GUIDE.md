# 🎯 GUIDE AFFICHAGE DÉCISIONS + NOTIFICATIONS

## ✅ Implémenté

### 1. Affichage décisions transparentes
### 2. Notifications Telegram périodiques (5min)

---

## 🚀 Installation (2 minutes)

### Étape 1: Configuration .env
```env
# Affichage décisions
SHOW_DECISIONS=True
SHOW_DECISION_DETAILS=False

# Notifications périodiques
TELEGRAM_STATUS_INTERVAL=300  # 5min en secondes
```

### Étape 2: Intégration dans bot

Ouvrir `core/binance_spot_bot.py`:

**A) Dans `__init__`, après `self.notifier = NotificationManager()`:**
```python
from utils.decision_display import DecisionDisplay
self.decision_display = DecisionDisplay()
if self.notify_trades:
    self.notifier.set_bot(self)
```

**B) Dans `scalping_strategy`, remplacer logique achat par:**
```python
# Après analyse
self.decision_display.show_analysis_summary(symbol, global_signal['action'], global_signal['confidence'], current_price)

# Si confiance insuffisante
if global_signal['confidence'] < 60:
    self.decision_display.show_decision(
        symbol, 'HOLD', 
        f"Confiance {global_signal['confidence']:.0f}% < 60%",
        f"Confiance ≥60%"
    )
    return

# Si solde insuffisant
if usdt < min_cost:
    self.decision_display.show_decision(
        symbol, 'SKIP',
        f'Solde {usdt:.2f} < {min_cost} USDT',
        f'+{min_cost - usdt:.2f} USDT'
    )
    return

# Si achat prêt
self.decision_display.show_decision(symbol, 'BUY_READY', f'Signal {global_signal["confidence"]:.0f}%', 'Exécution')
```

**C) Dans `run()`, après `show_realtime_prices()`:**
```python
# Notification status périodique
if self.notify_trades:
    self.notifier.send_status_update()
```

---

## 📊 Résultat Affichage

### Avant:
```
⚡ SOL/USDT 193.78 (+0.41%)
⚡ ETH/USDT 3958.61 (-3.33%)
```

### Après:
```
⚡ SOL/USDT 193.78 (+0.41%)
📊 SOL 193.78 | Signal: HOLD | Confiance: [████░░░░░░] ✗ 45%
⏳ SOL → HOLD (Confiance 45% < 60%) | Attente: Confiance ≥60%

⚡ ETH/USDT 3958.61 (-3.33%)
📊 ETH 3958.61 | Signal: BUY | Confiance: [████████░░] ✓ 72%
❌ ETH → SKIP (Solde 9.86 < 10 USDT) | Attente: +0.14 USDT
```

---

## 📱 Notifications Telegram

### Message toutes les 5min:
```
🤖 📊 STATUS 13:25

💰 USDT: 9.86
📈 P&L: +0.00 USDT
🔄 Trades: 0 (0% win)

⏳ Aucune position

⏰ Prochain: 5min
```

### Avec positions:
```
🤖 📊 STATUS 14:30

💰 USDT: 5.23
📈 P&L: +1.45 USDT
🔄 Trades: 3 (67% win)

📦 Positions:
  • BTC: 0.0001
  • SOL: 0.0234

⏰ Prochain: 5min
```

---

## ⚙️ Configuration

### Intervalle notifications (secondes):
```env
TELEGRAM_STATUS_INTERVAL=300   # 5min
TELEGRAM_STATUS_INTERVAL=600   # 10min
TELEGRAM_STATUS_INTERVAL=1800  # 30min
```

### Niveau détails:
```env
SHOW_DECISIONS=True              # Afficher décisions
SHOW_DECISION_DETAILS=False      # Détails complets (verbose)
```

### Mode détails activé:
```
📊 SOL 193.78 | Signal: HOLD | Confiance: [████░░░░░░] ✗ 45%

🔍 SOL - Conditions:
   ✅ Score: 45 ≥ 50
   ✅ Solde: 9.86 ≥ 5 USDT
   ❌ Confiance: 45% < 60%
   ✅ Volatilité: 15% OK

⏳ SOL → HOLD (Confiance 45% < 60%) | Attente: Confiance ≥60%
```

---

## 🎯 Types de décisions

| Icône | Type | Signification |
|-------|------|---------------|
| ⏳ | HOLD | Signal neutre, attente |
| ❌ | SKIP | Bloqué (solde, limite, etc) |
| 🎯 | BUY_READY | Achat imminent |
| 🎯 | SELL_READY | Vente imminente |
| ⏸️ | WAITING | Position ouverte, attente profit |

---

## 🔧 Désactivation

```env
SHOW_DECISIONS=False
TELEGRAM_STATUS_INTERVAL=0  # Désactive notifications périodiques
```

---

## 📈 Avantages

✅ **Transparence totale** - Comprendre chaque décision
✅ **Confiance** - Savoir pourquoi le bot attend
✅ **Monitoring** - Status régulier sur Telegram
✅ **Debugging** - Identifier problèmes rapidement
✅ **Apprentissage** - Comprendre la stratégie

---

*Installation: 2 minutes*
*Impact: Transparence maximale*
