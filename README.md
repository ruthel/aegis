# 🤖 Bot Trading Binance v2

Bot de trading automatique professionnel pour Binance avec stratégies intelligentes, revenus passifs et optimisations ultra-rapides.

## 🚀 Démarrage Rapide (2 minutes)

### 1. Installation
```bash
git clone https://github.com/votre-repo/binance-bot-v2.git
cd binance-bot-v2
pip install -r requirements.txt
```

### 2. Configuration
```bash
# Copier le template
copy .env.example .env

# Modifier UNIQUEMENT les clés API dans .env
BINANCE_API_KEY=votre_cle_api_ici
BINANCE_API_SECRET=votre_cle_secrete_ici
```

### 3. Validation & Lancement
```bash
# Vérifier la configuration
python setup_guide.py

# Démarrer le bot
python run.py
```

## ⚡ Fonctionnalités Principales

### 🎯 Trading Intelligent
- **Stratégie Adaptive** : Choix automatique Scalping/DCA selon conditions marché
- **Timeframes Adaptatifs** : Sélection automatique 4H/1H/15M ou 15M/5M/1M selon volatilité
- **Détection Tendances Cumulatives** : Capture 6x -0.1% = -0.6% (variations progressives)
- **Crypto Scoring** : Sélection automatique des meilleures cryptos (score 0-100)
- **Latence Ultra-Faible** : 10-20ms (réduction 98% vs 1000ms initial)
- **Position Sizing** : Basé sur volatilité et corrélation entre positions

### 💰 Revenus Passifs (Binance Earn)
- **Flexible Savings** : Fonds < 50 USDT (3-5% APY)
- **Locked Staking** : Fonds > 50 USDT (5-15% APY)
- **Auto-Allocation** : 80% des fonds inactifs optimisés automatiquement
- **Retrait Intelligent** : Disponible instantanément pour trading

### 🛡️ Sécurité Professionnelle
- **Gestion Risques Avancée** : Circuit breakers, limites journalières
- **Trailing Stop** : Protection automatique des profits (3% configurable)
- **Paper Trading** : Tests sans risque avant mise en production
- **Notifications Telegram** : Alertes temps réel + status périodique

### 🖥️ Interface Optimisée
```
🤖 Bot INTELLIGENT | LIVE ⚡ TEMPS RÉEL | 0 positions
📊 BTC, ETH, SOL, BNB | 5.0 USDT/trade | Seuil 40% | Earn ON
🛑 Ctrl+C pour arrêter

📊 +1.45 USDT | 3 trades (67% win)
💳 SPOT: USDT 95.23 | BTC 0.001234 | ETH 0.0012
💰 Earn: 15.67 USDT (+0.02 rewards)

⚡ 12:34:56 | BTC 111.6K | ETH 3.98K | SOL 194 | BNB 1.20K

🎯 TOP: BTC 85 (V30 L20 M5) | ETH 72 (V25 L15 M10) → TRADING

⚡ BTC/USDT 111645.23 (+2.34%) | Vol 2.1B
📊 BTC 111645 | Signal: BUY | Confiance: [████████░░] ✓ 75%
🎯 BTC → BUY_READY (Signal 75%) | Exécution: Immédiate
```

## ⚙️ Configuration Avancée

### Gestion des Risques (.env)
```env
# Trading
TRADE_AMOUNT=5                    # Montant par trade
MAX_DAILY_LOSS=200               # Perte max par jour
STOP_LOSS_PERCENT=5              # Stop-loss à 5%
TRAILING_STOP_PERCENT=3          # Trailing stop à 3%
MAX_POSITION_SIZE=50             # Taille max position

# Sélection Cryptos
MIN_CRYPTO_SCORE=40              # Score minimum pour trader
MAX_TRADEABLE_CRYPTOS=2          # Max 2 cryptos simultanées

# Optimisations Latence
ENABLE_LATENCY_OPTIMIZER=True    # Réduction latence 98%
PARALLEL_WORKERS=10              # Workers parallèles
WS_PURE_MODE=True               # WebSocket pur
EVENT_DRIVEN=True               # Event-driven analysis
```

### Binance Earn (Revenus Passifs)
```env
ENABLE_EARN=True                 # Activer revenus passifs
MIN_TRADING_BALANCE=5            # Balance min pour trading
EARN_ALLOCATION_PERCENT=80       # % fonds vers Earn
FLEXIBLE_SAVINGS_THRESHOLD=0.01  # Seuil Flexible Savings
LOCKED_STAKING_THRESHOLD=50      # Seuil Locked Staking
```

## 📁 Architecture Modulaire

```
binance-bot-v2/
├── core/                        # Cœur du bot (pattern Mixin)
│   ├── binance_spot_bot.py     # Bot principal (400 lignes vs 2500)
│   ├── bot_trading.py          # TradingMixin - Ordres & exécution
│   ├── bot_strategies.py       # StrategiesMixin - Scalping/DCA/Intelligent
│   ├── bot_sync.py             # SyncMixin - Synchronisation Binance
│   ├── bot_analysis.py         # AnalysisMixin - Analyses & prévisions
│   ├── bot_display.py          # DisplayMixin - Affichage optimisé
│   ├── earn_manager.py         # Binance Earn (revenus passifs)
│   └── websocket_manager.py    # WebSocket temps réel
├── utils/                       # Utilitaires spécialisés
│   ├── crypto_scorer.py        # Scoring cryptos 0-100
│   ├── advanced_risk_manager.py # Gestion risques professionnelle
│   ├── multi_timeframe_analyzer.py # Timeframes adaptatifs (4H/1H/15M ou 15M/5M/1M)
│   ├── volatility_calculator.py # Calculs volatilité centralisés
│   └── market_calculator.py    # Métriques marché centralisées
├── config.py                   # Configuration centralisée (.env)
├── run.py                      # Point d'entrée sécurisé
└── setup_guide.py             # Guide configuration interactif
```

## 🔥 Optimisations Niveau 2

### Réduction Latence 98% (1000ms → 10-20ms)
- **Parallélisation** : 10 workers simultanés
- **WebSocket Pur** : Données temps réel sans REST API
- **Cache Adaptatif** : TTL intelligent selon volatilité
- **Event-Driven** : Analyse uniquement si changement significatif
- **NumPy Vectorisé** : Calculs ultra-rapides
- **Filtrage Précoce** : Skip analyses inutiles

### Métriques Performance
| Métrique | Avant | Après | Gain |
|----------|-------|-------|------|
| Latence totale | 1000ms | 10-20ms | 98% |
| Appels API | 100/min | 20/min | 80% |
| Analyses | 60/h | 15/h | 75% |
| Réactivité | 500ms | <50ms | 90% |

## 🛡️ Sécurité & Bonnes Pratiques

### Démarrage Sécurisé
1. **Commencez petit** : 5-10 USDT maximum
2. **Paper Trading** : Testez 24-48h avant live
3. **Surveillance** : Monitorer les premiers trades
4. **Limites strictes** : Configurez MAX_DAILY_LOSS

### Détection Clés d'Exemple
Le bot refuse de démarrer avec des clés par défaut :
```
❌ ERREUR: Clés API d'exemple détectées !
Modifiez .env avec vos vraies clés Binance.
```

## 📊 Monitoring & Notifications

### Telegram (Optionnel)
```env
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id
TELEGRAM_STATUS_INTERVAL=300     # Status toutes les 5min
```

### Logs & Données
- **Logs temps réel** : `tail -f bot.log`
- **État bot** : `data/bot_state.json`
- **Historique** : Binance → Orders → Trade History

## 🖥️ Hébergement VPS Recommandé

### Spécifications
- **CPU** : 2 vCores
- **RAM** : 1-2 GB
- **Stockage** : 20 GB SSD
- **Localisation** : Singapour/Tokyo (latence 10-50ms)
- **Coût** : $6-12/mois (Vultr, DigitalOcean, Linode)

### Installation VPS
```bash
ssh root@votre_ip
apt update && apt install python3.11 python3-pip git -y
git clone https://github.com/votre-repo/binance-bot-v2.git
cd binance-bot-v2
pip3 install -r requirements.txt
cp .env.example .env
# Modifier .env avec vos clés
python run.py
```

## 🔧 Mode Développement

### Hot Reload
```bash
python run.py  # Redémarrage automatique sur modification .py
```

### Fonctionnalités Dev
- ✅ Détection modifications automatique
- ✅ Redémarrage instantané
- ✅ Préservation état/positions
- ✅ Logs détaillés

## 📚 Documentation Complète

### Guides Spécialisés
- **[Timeframes Adaptatifs](docs/ADAPTIVE_TIMEFRAMES.md)** - Stratégie professionnelle multi-timeframes
- **[Détection Tendances Cumulatives](docs/CUMULATIVE_TREND_DETECTION.md)** - Capture variations progressives
- **[Optimisations Latence](docs/QUICK_START_OPTIMIZATIONS.md)** - Guide 2min réduction 98%
- **[Décisions Trading](docs/DECISIONS_GUIDE.md)** - Transparence signaux
- **[Architecture](docs/CENTRALIZATION_SUMMARY.md)** - Structure modulaire
- **[Roadmap](docs/TASKS.md)** - Évolutions niveau institutionnel

### Centralisation Code
- **Calculs dupliqués éliminés** : -200 lignes code
- **Utilitaires centralisés** : volatility_calculator, market_calculator
- **Maintenance simplifiée** : Une source de vérité par calcul
- **Performance optimisée** : NumPy automatique + cache partagé

## 🚀 Roadmap Niveau Institutionnel

### Priorité 1 - Analytics Avancées
- Sharpe Ratio, Max Drawdown, Profit Factor
- Métriques temps réel avec alertes
- Rapports performance automatiques

### Priorité 2 - Intelligence Artificielle
- Pattern Recognition (Head & Shoulders, Triangles)
- Sentiment Analysis (Fear & Greed Index)
- Market Regime Detection (Trending/Ranging)

### Priorité 3 - Optimisation Automatique
- Parameter Optimization (RSI, MACD, BB)
- A/B Testing Framework
- Adaptive Thresholds selon performance

## ⚠️ Avertissements Importants

- **Trading = Risque** : Ne tradez que ce que vous pouvez perdre
- **Tests Obligatoires** : Paper trading 24-48h minimum
- **Surveillance** : Monitorer régulièrement le bot
- **Limites** : Configurez MAX_DAILY_LOSS strictement
- **Bot Externe** : N'apparaît pas dans section "Bots" Binance (API externe)

## 📞 Support

- **Issues** : GitHub Issues pour bugs/suggestions
- **Documentation** : Dossier `docs/` pour guides détaillés
- **Configuration** : `python setup_guide.py` pour aide interactive

---

**Version** : 2.0 Professional  
**Latence** : 10-20ms (optimisé)  
**Architecture** : Modulaire (Mixins)  
**Revenus** : Trading + Binance Earn  
**Sécurité** : Niveau professionnel