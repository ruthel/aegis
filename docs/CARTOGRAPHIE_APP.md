# Cartographie de l'Application Aegis

Derniere mise a jour : 2026-07-31

Ce document decrit l'etat actuel de l'application apres la migration SQLite, la fusion ML entree/sortie, la SPA React et les nettoyages de logs/decisions.

## Vue d'Ensemble

Aegis est compose de quatre blocs principaux :

| Bloc | Role | Source principale |
|------|------|-------------------|
| Bot trading | Analyse marche, decisions ML, execution paper/live, etat runtime | `core/trading_bot.py` + mixins `core/bot/*` |
| Cerveau ML | Modele entree, modele sortie, features, sauvegarde joblib | `core/ml_engine.py` |
| Memoire SQLite | Etat bot, positions, decisions, ML live, Telegram, analytics | `data/aegis_db.sqlite3` via `core/ml_live_logger.py` et `core/db_orm.py` |
| UI web | Flask API + WebSocket + SPA React/Vite | `ui/server.py` et `ui/app` |

Le navigateur ne fait que surveiller et piloter. Le bot continue de tourner tant que le processus Python lance par `start.py` ou le processus bot enfant reste actif.

## Demarrage

Point d'entree recommande :

```bash
python start.py
```

Effet :

1. charge `.env`, `.env.local`, puis `.env.ui`;
2. demarre le serveur Flask sur `http://127.0.0.1:8080` ou `DASHBOARD_PORT`;
3. si `AUTO_START_BOT=True`, lance le moteur bot en arriere-plan via `ui/server.py`;
4. sert la SPA compilee depuis `ui/public/spa`.

Scripts utiles :

| Fichier | Role |
|---------|------|
| `start.py` | Demarrage UI + bot auto si configure |
| `stop.py` | Arret propre des processus Aegis |
| `start_background.bat/.vbs` | Demarrage Windows sans console visible |
| `shutdown_background.bat/.vbs` | Arret Windows |
| `run.py` | Point d'entree bot historique/direct |

## Backend Trading

### `core/trading_bot.py`

Classe principale `TradingBot`, composee avec :

- `TradingMixin` : achat/vente, paper/live, frais, historique.
- `SyncMixin` : synchronisation exchange.
- `AnalysisMixin` : analyses et previsions.
- `DisplayMixin` : affichage console.

Responsabilites actuelles :

- charger/sauvegarder l'etat via SQLite;
- calculer contexte marche par symbole;
- alimenter les 52 features d'entree ML;
- demander au ML `P_win` pour l'entree;
- verifier seulement les securites operationnelles avant achat : cooldown, position deja ouverte, capital, minimum exchange;
- evaluer les positions ouvertes avec le modele de sortie;
- appliquer les decisions de sortie ML `HOLD` ou `FORCE_EXIT`;
- journaliser seulement les decisions finales utiles;
- traiter les commandes UI (`force_buy`, `force_sell`, cooldown, etc.).

### Sorties ML

`utils/exit_engine.py` ne vend plus par regles dures. Il calcule surtout :

- `ContinuationScore`;
- PnL brut/net;
- duree de position;
- contexte utile au modele.

La decision active vient du ML :

| Etat | Comportement |
|------|--------------|
| `HOLD` | conserve la position |
| `FORCE_EXIT` | annule les ordres de vente references puis vend au marche |

Seuils actuels :

```env
ML_EXIT_SELL_THRESHOLD=35.0
ML_EXIT_PROFIT_PROTECT_MIN_NET_PCT=0.05
ML_EXIT_PROFIT_PROTECT_THRESHOLD=70.0
```

Lecture : une position non profitable ne sort que si `P_continue < 35%`. Une position deja en profit net devient plus defensive et sort si `P_continue < 70%`.

## Core ML Engine

Fichier : `core/ml_engine.py`

Modele actuel :

- RandomForest entree;
- RandomForest sortie;
- modele champion actif : `data/aegis_model.joblib`;
- challenger possible : `data/aegis_challenger.joblib`.

Entree :

- environ 52 features multi-timeframe et contexte bot;
- decision d'achat si `P_win >= ML_MIN_PROBABILITY`;
- la sortie prevue est aussi prise en compte via `P_continue`.

Sortie :

- 37 features environ;
- calcule `P_continue`;
- decide `HOLD` ou `FORCE_EXIT`.

Les anciens verrous metier comme Support Touch, falling knife, bear mode, HTF ou timing ne sont plus des blocages durs redondants. Ils sont principalement injectes comme features ML.

## Donnees et SQLite

Base principale :

```text
data/aegis_db.sqlite3
data/aegis_db.sqlite3-wal
data/aegis_db.sqlite3-shm
```

SQLite est utilise en mode WAL. Ne pas supprimer `-wal` ou `-shm` pendant que le bot ou l'UI tourne.

### Couche ORM

Fichier : `core/db_orm.py`

SQLAlchemy cree les tables via `Base.metadata.create_all(...)`. `core/ml_live_logger.py` reste la facade applicative : migrations historiques, lecture/ecriture runtime, conversion ancien etat vers schema relationnel.

Tables principales :

| Table | Role |
|-------|------|
| `bot_state` | etat compact par mode (`paper`, `live`) |
| `bot_app_state` | cles applicatives persistantes : Telegram daily status, macro event actif |
| `bot_processes` | processus dashboard/bot |
| `bot_commands` | commandes envoyees depuis l'UI au bot |
| `bot_positions` | positions ouvertes/fermees |
| `bot_trailing_stops` | etat trailing/stop de suivi |
| `bot_symbol_cooldowns` | cooldowns operationnels |
| `bot_exit_recommendations` | dernier diagnostic de sortie par symbole |
| `bot_market_context` | regime marche, momentum, falling knife, retour |
| `bot_decision_journal` | decisions finales affichees dans le dashboard |
| `bot_decision_metrics` | metriques rattachees aux decisions |
| `bot_live_status*` | statut live WebSocket normalise |
| `crypto_score_history` | historique des scores pour analytics |
| `support_touch_results` | resultats de backtest Support Touch |
| `telegram_messages` | messages Telegram entrants/sortants |
| `ml_live_predictions` | dernier `P_win`, `P_continue`, decision/reason live |
| `ml_decisions` | decisions ML entree/sortie normalisees |
| `ml_feature_values` | features ML en lignes `event_id/feature_name/value` |
| `ml_open_entries` | entrees ouvertes liees a leur future sortie |
| `ml_trade_outcomes` | resultat final des trades |
| `ml_model_metadata` | metadata du modele entraine |
| `ml_feature_importances` | importances de features |
| `ml_analysis_runs` | runs d'analyse live |
| `ml_prediction_calibration` | calibration prediction/resultat |
| `ml_rejected_replay_results` | replay des trades refuses |
| `ml_drift_alerts` | alertes de drift |

Les fichiers JSON runtime ne sont plus la source de verite. Les vieux scripts scratch ont ete retires.

## API Flask

Fichier : `ui/server.py`

Routes pages SPA :

| Route | Vue React |
|-------|----------|
| `/` | Live |
| `/analytics` | Analytics |
| `/trades` | Trades |
| `/console` | Console |
| `/config` | Config |

Routes API principales :

| Endpoint | Role |
|----------|------|
| `GET /api/status` | payload dashboard complet |
| `GET /api/ml_status` | statut Core ML Engine et predictions live |
| `GET /api/live` | marche live normalise |
| `GET /api/analytics` | metriques, heatmap, capital, PnL history |
| `GET /api/analytics/scores` | historique score crypto par symbole/periode |
| `GET /api/trades` | trades fermes + positions ouvertes |
| `GET /api/decisions` | decisions finales compactees |
| `GET /api/bot/console` | lignes de `bot.log` |
| `GET/POST /api/config` | lecture/ecriture config autorisee |
| `POST /api/bot/start` | demarrer le bot |
| `POST /api/bot/stop` | arreter le bot |
| `POST /api/bot/restart` | redemarrer le bot |
| `POST /api/bot/command` | envoyer commande au bot |
| `POST /api/support_touch/run_backtest` | relancer backtest Support Touch |
| `GET /api/support_touch/backtest_status` | statut du backtest |

WebSocket :

| Route | Role |
|-------|------|
| `/ws/live` | pousse `live`, `status` et `ml_status` pour reduire le polling HTTP |

## SPA React

Source :

```text
ui/app
```

Build servi par Flask :

```text
ui/public/spa
```

Stack :

- React + Vite + TypeScript;
- pnpm;
- axios pour REST;
- Zustand non persistant pour l'etat UI;
- shadcn/Radix pour les dropdowns;
- lucide-react pour les icones;
- amCharts 5 pour les graphiques;
- police principale Outfit.

Commandes :

```bash
cd ui/app
pnpm install
pnpm build
```

Vues :

| Fichier | Route | Role |
|---------|-------|------|
| `LiveView.tsx` | `/` | dashboard live : cartes, marche, ML, positions, decisions |
| `AnalyticsView.tsx` | `/analytics` | metriques, PnL, scores crypto, daily/hourly bar charts |
| `TradesView.tsx` | `/trades` | positions ouvertes et trades fermes |
| `ConsoleView.tsx` | `/console` | console bot/logs |
| `ConfigView.tsx` | `/config` | configuration editable |

Charts :

| Composant | Role |
|-----------|------|
| `LineChart.tsx` | PnL history |
| `ScoreHistoryChart.tsx` | historique des scores crypto |
| `DailyBarChart.tsx` | PnL par jour avec amCharts 5 |
| `HourlyBarChart.tsx` | PnL par heure avec amCharts 5 |
| `ColumnChart.tsx` | ancien composant generique, a conserver seulement si encore reutilise |

Les graphiques amCharts recents ne doivent pas blink : ils creent le chart une seule fois et mettent seulement a jour `xAxis.data` et `series.data`.

## Telegram

Fichier principal : `core/managers/notification.py`

Etat actuel :

- commandes Telegram disponibles a la demande;
- messages stockes dans `telegram_messages`;
- bilan automatique quotidien seulement a l'heure configuree;
- plus de status automatique toutes les 2h.

Configuration :

```env
TELEGRAM_DAILY_STATUS_ENABLED=True
TELEGRAM_DAILY_STATUS_HOUR=8
```

## Market Events Macro

Fichier : `utils/event_manager.py`

Evenements suivis :

- `FED_MEETING`;
- `INFLATION_DATA`;
- `MARKET_UNCERTAINTY`.

Le manager memorise l'evenement actif en memoire et dans `bot_app_state`.

Comportement actuel :

- premiere detection : log + notification Telegram si activee;
- meme evenement detecte pendant sa duree : silencieux;
- fin/annulation : nettoyage memoire + SQLite;
- une nouvelle instance du manager recupere l'evenement actif depuis SQLite.

## Scripts ML et Analyse

| Script | Role |
|--------|------|
| `scripts/train_ml_model.py` | entrainement entree avec replay learning |
| `scripts/train_ml_exit_model.py` | entrainement modele sortie |
| `scripts/walk_forward_validation.py` | validation temporelle sans fuite |
| `scripts/evaluate_champion_challenger.py` | comparaison/promotion/rollback champion-challenger |
| `scripts/analyze_ml_live_performance.py` | analyse live, calibration, drift, replay refuses |
| `scripts/backtest_support_touch.py` | backtest Support Touch vers SQLite |
| `scripts/backtest_ml_exit_comparison.py` | comparaison sorties ML |

## Flux d'une Decision d'Entree

1. WebSocket ou boucle bot recoit prix live.
2. `TradingBot.intelligent_strategy()` construit contexte marche.
3. Les anciens signaux metier deviennent features.
4. `MLEngine.predict_win_probability()` retourne `P_win`.
5. Le bot verifie les securites operationnelles : cooldown, position existante, capital, minimum exchange.
6. Si `P_win` et contexte sortie sont suffisants, achat.
7. L'entree et ses features sont stockees en SQLite.
8. Le dashboard recoit le nouvel etat via `/ws/live`.

## Flux d'une Decision de Sortie

1. Une position ouverte est rehydratee dans le trailing manager.
2. A chaque tick, `_evaluate_exit_engine_for_symbol()` calcule les metriques.
3. `MLEngine.predict_exit_decision()` calcule `P_continue`.
4. Si `HOLD`, la position reste ouverte.
5. Si `FORCE_EXIT`, le bot annule les ordres de reference et vend au marche.
6. La decision sortie et les features sont stockees.
7. Au sell, `ml_trade_outcomes` recoit le resultat final.

## Points de Vigilance

- Redemarrer le bot apres changement `.env.local` ou logique ML.
- Ne pas supprimer les fichiers SQLite WAL/SHM pendant execution.
- Les stores Zustand ne sont pas persistants : c'est volontaire, SQLite et le backend sont la source de verite.
- `/api/status` et `/api/ml_status` existent encore pour bootstrap/debug, mais le live normal passe par `/ws/live`.
- Les decisions cooldown/position bloquee ne doivent pas spammer `bot_decision_journal`.
- Les anciennes docs qui parlent de `ui/frontend`, `ui/static/spa`, Chart.js ou JSON runtime sont obsoletes.
