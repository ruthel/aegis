# Bot Trading Binance

Bot de trading automatique pour Binance avec stratégies de scalping et DCA.

## 🚀 Démarrage rapide

### 1. Configuration
```bash
# Copier le fichier d'exemple
copy .env.example .env

# Modifier .env avec vos clés API Binance
BINANCE_API_KEY=votre_cle_api
BINANCE_API_SECRET=votre_cle_secrete
TESTNET=False
```

### 2. Installation
```bash
pip install -r requirements.txt
```

### 3. Validation
```bash
python setup_guide.py
```

### 4. Déploiement
```bash
python deploy.py
```

## 📊 Fonctionnalités

- **Scalping BTC/USDT** : Trading haute fréquence
- **DCA ETH/USDT & BNB/USDT** : Accumulation progressive
- **Gestion des risques** : Stop-loss, limites journalières
- **Monitoring** : Dashboard temps réel, logs
- **Backtesting** : Tests sur données historiques
- **Paper trading** : Tests sans risque

## ⚙️ Configuration des risques

Modifiez `config_risk.py` :
```python
MAX_DAILY_LOSS = 100        # Perte max par jour
MAX_POSITION_SIZE = 50      # Taille max position
STOP_LOSS_PERCENT = 5       # Stop-loss à 5%
```

## 🛡️ Sécurité

- Commencez avec de petits montants (5-10 USDT)
- Testez en paper trading 24-48h
- Surveillez les premiers trades
- Utilisez les limites de risque

## 📁 Structure

```
binance-bot-v2/
├── binance_spot_bot.py     # Bot principal
├── strategy.py             # Stratégies de trading
├── risk_manager.py         # Gestion des risques
├── monitor.py              # Monitoring et alertes
├── backtester.py           # Tests historiques
├── setup_guide.py          # Guide de configuration
└── deploy.py               # Déploiement sécurisé
```

## ⚠️ Avertissements

- Trading = risque de perte
- Testez avant d'investir
- Ne tradez que ce que vous pouvez perdre
- Surveillez régulièrement le bot