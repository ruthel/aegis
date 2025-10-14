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

### Trading Actif
- **Stratégie Intelligente** : Choix automatique scalping/DCA selon marché
- **Scalping Multi-Timeframes** : Analyse 1m/5m/15m avec indicateurs avancés
- **DCA Intelligent** : Accumulation progressive optimisée
- **Trailing Stop** : Protection automatique des profits
- **Position Sizing** : Basé sur volatilité et corrélation
- **Crypto Scoring** : Sélection automatique des meilleures cryptos (0-100)

### Revenus Passifs (Binance Earn)
- **Flexible Savings** : Fonds < 50 USDT (3-5% APY)
- **Locked Staking** : Fonds > 50 USDT (5-15% APY)
- **Auto-Allocation** : Optimisation automatique des fonds inactifs
- **Retrait Intelligent** : Disponible instantanément pour trading

### Sécurité & Monitoring
- **Gestion des risques** : Circuit breakers, limites journalières
- **Multi-timeframe analysis** : RSI, MACD, Bollinger Bands
- **Notifications Telegram** : Alertes temps réel
- **Paper trading** : Tests sans risque
- **Affichages ultra-compacts** : Optimisés pour scalping haute fréquence (5s)
- **Filtrage intelligent** : Analyse uniquement cryptos avec opportunités

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

## 🖥️ Interface

### Affichage compact optimisé
```
🤖 Bot INTELLIGENT | LIVE ⚡ TEMPS RÉEL | 0 positions
📊 BTC, ETH, SOL, BNB | 8.0 USDT/trade | Seuil 70% | Earn ON
🛑 Ctrl+C pour arrêter

📊 0.00 | 0 trades (0% win)
💳 SPOT: USDT 100.00 | BTC 0.001234
💰 Earn: 0.00 USDT (vide)

⚡ 12:34:56 | BTC 111.6K | ETH 3.98K | SOL 194 | BNB 1.20K

🎯 NOUVEAUX ACHATS: BTC (85: V8.2% S0.01% H+), ETH (72: V5.1% S0.02% H+)

⚡ BTC/USDT 111645.23 (+2.34%) | Vol 2.1B
⚡ BTC/USDT 111645.23 → BUY (bullish 75%)
```

## 📁 Structure

```
binance-bot-v2/
├── core/
│   ├── binance_spot_bot.py      # Bot principal
│   ├── earn_manager.py          # Binance Earn (tirelire)
│   ├── websocket_manager.py     # WebSocket temps réel
│   └── technical_indicators.py  # Indicateurs techniques
├── utils/
│   ├── crypto_scorer.py         # Scoring cryptos 0-100
│   ├── advanced_risk_manager.py # Gestion risques avancée
│   └── multi_timeframe_analyzer.py # Analyse 1m/5m/15m
├── setup_guide.py           # Guide de configuration
└── deploy.py                # Déploiement sécurisé
```

## ⚠️ Avertissements

- Trading = risque de perte
- Testez avant d'investir
- Ne tradez que ce que vous pouvez perdre
- Surveillez régulièrement le bot