# Aegis — Journal des Modifications 2026-07-22

Ce fichier résume toutes les modifications effectuées lors de la session du **22 juillet 2026**.

---

## 1. Moteur ML Multi-Timeframe Active en Mode Actif (Filtre en Direct)

**Objectif :** Passer le Core ML Engine du mode observation (Shadow) au mode **Filtre Actif En Direct**.

**Modifications :**
- ML actif par defaut dans le bot et la configuration.
- Tout signal avec `P_win < 65%` est automatiquement rejeté avec la raison `ml_filter_rejected_XX.X%`.

**Fichiers modifiés :**
- `.env`
- `.env.local`

---

## 2. Upgrade MLEngine — 52 Features Entree + Sorties ML

**Objectif :** etendre le modele d'entree pour qu'il comprenne le contexte reel du trade, puis connecter la logique de sortie au cerveau ML.

**Etat actuel :**
- Modele d'entree RandomForest avec **52 features**.
- Modele de sortie avec **37 features**.
- Les anciens verrous metier deviennent des features ML : Support Touch, regime, bear mode, reversal, falling knife, timing, score, signal technique, frais et valeur de position.

**Résultats :**
- Entrees filtrees ML + sorties ML : **892 trades**, **82.2% win rate**, **+1438.60% PnL backtest**.
- Moyenne estimee : **environ 4.4 trades/jour** sur le dataset teste.

**Fichiers modifiés :**
- `core/ml_engine.py`
- `core/trading_bot.py`

---

## 3. Entraînement Récursif avec Grid Search Optimisé

**Objectif :** Réentraîner le modèle de façon récursive pour atteindre un score optimal.

**Modifications :**
- Split 80% Train / 20% Out-of-Sample Test.
- 6 combinaisons d'hyperparamètres évaluées récursivement.
- Modèle champion : `n_estimators=200, max_depth=8, criterion=entropy`.
- Sauvegarde du modele dans `data/aegis_model.joblib` et des metadata dans `data/aegis_db.sqlite3`.

**Fichiers modifiés :**
- `scripts/train_ml_model.py`

---

## 4. Architecture de Decision — ML proprietaire des filtres d'entree

Les anciens verrous Support Touch, score, timing, regime detaille, signal technique, falling knife et contexte bear sont transmis au ML comme features. Le bot garde uniquement les securites operationnelles necessaires avant achat : cooldown, position/capital, capital disponible et minimums exchange.

Support Touch ne produit plus de verdict `allowed/blocked` ni de fast-path. Son backtest sert à fournir au ML des métriques historiques : nombre de trades, win rate, PnL total, PnL moyen et régime.

---

## 5. Dashboard — Analytics ML & Prévisions Hebdomadaires

**Objectif :** Afficher sur le Dashboard toutes les statistiques quantitatives calculées sur le dataset 2026.

**Métriques ajoutées dans la section "📊 Analytics Quantitatives & Prévisions IA" :**
- Précision Hors-Échantillon : **67.1% Test**
- Gain / Perte Moyen Net : **+1.64% / -0.87%**
- Risk-Reward & Profit Factor : **1.89x (PF 3.13)**
- Meilleur Jour : **Mercredi (68.5% winrate)**
- Heures Idéales : **13h-17h & 08h-11h UTC**
- Prévision Gain Hebdo (Solde $1k) : **+$150 à +$285 USD**

**Fichiers modifiés :**
- `dashboard/templates/index.html`
- `dashboard/static/dashboard.js`
- `dashboard/app.py` (endpoint `/api/ml_status`)

---

## 6. Widget "🔮 Radar Prochain Achat (Next Buy Forecast)"

**Objectif :** Afficher en temps réel sur le Dashboard quelle crypto le bot surveille et quand il est susceptible d'acheter.

**Informations affichees :**
- Symbole candidat #1 (ex: `ETH/USD`)
- Etat ML reel : `Pret ML maintenant` ou `En attente ML`
- Raisons explicites : `P_win`, continuation, seuils et contexte utile
- Plus de compte a rebours artificiel si le ML n'a pas de setup valide

**Fichiers modifiés :**
- `dashboard/app.py` (fonction `compute_next_buy_forecast`)
- `dashboard/templates/index.html` (carte `#nextBuyRadarCard`)
- `dashboard/static/dashboard.js` (fonction `renderNextBuyRadar`)

---

## 7. Prédictions ML en Temps Réel via WebSocket

**Objectif :** Remplacer le polling HTTP (toutes les X secondes) par un push WebSocket instantané.

**Architecture :**
- Le serveur Dashboard charge `MLEngine` une fois en mémoire au démarrage (`_get_ws_ml_engine()`).
- Toutes les 3 secondes, il fetche les bougies 5m, 15m, 1H depuis Kraken via CCXT.
- Il calcule `P_win` pour les 4 paires et pousse un message `{'__type': 'ml_predictions', 'predictions': {...}}` via WebSocket.
- Le client JS reçoit et affiche instantanément sans dépendre du fichier d'état du bot.

**Fichiers modifiés :**
- `dashboard/app.py` (route `/ws/live`, fonctions `_get_ws_ml_engine`)
- `dashboard/static/dashboard.js` (fonctions `connectLiveWs`, `renderMLFromWs`)

---

## 8. Cache ML en Mémoire (Anti-Régression `50%`)

**Objectif :** Empêcher le Dashboard de revenir aux valeurs par défaut `50%` quand le fichier d'état est momentanément vide.

**Solution :** `ML_PREDS_CACHE` — dictionnaire module-level qui conserve les dernières vraies valeurs calculées. Il n'est jamais réinitialisé à des valeurs hardcodées.

**Fichiers modifiés :**
- `dashboard/app.py`

---

## 9. Mise à Jour ML au Démarrage du Bot

**Objectif :** Calculer et sauvegarder les prédictions ML dès que le bot démarre, avant même le premier cycle d'analyse.

**Modifications :**
- Ajout de la méthode `update_ml_predictions_for_all_pairs()` dans `TradingBot`.
- Appelée automatiquement après `_optimize_all_positions_at_startup()`.

**Fichiers modifiés :**
- `core/trading_bot.py`

---

## 10. Mise a Jour 2026-07-23 — Nettoyage Architecture ML Active

**Objectif :** retirer les anciennes options et les logs devenus trompeurs depuis que le ML possede les filtres d'entree et la sortie.

**Modifications :**
- Suppression des toggles inutiles : `ML_FILTER_ENABLED`, `ML_SHADOW_MODE`, `ML_EXIT_ENTRY_FILTER_ENABLED`, `ML_OWNS_ENTRY_FILTERS`.
- Suppression de `EXIT_ENGINE_SHADOW_MODE` : la sortie ML est active, pas en observation.
- Suppression des blocages durs redondants avant ML : Support Touch fast-path, HTF hard lock, falling knife hard lock et bear context hard lock.
- Decision log recentre sur les decisions finales et leurs raisons ML.
- Dashboard nettoye : retrait des badges "Feature ML" / "ml feature only", correction du contexte d'entree et du rendu des decisions.
- Sauvegarde d'etat rendue robuste avec fichiers temporaires uniques et lock interne.
- Intervalle Telegram status augmente a 2h.

---

## 11. Mise a Jour 2026-07-23 — Phase 4 Dataset Live ML

**Objectif :** donner au ML une memoire exploitable de ses decisions live sans changer le comportement de trading actuel.

**Modifications :**
- Ajout de `core/ml_live_logger.py`.
- Trace brute `ml_raw_events` dans `data/aegis_db.sqlite3` pour les decisions ML d'entree, les decisions ML de sortie et les resultats de trades fermes.
- Base SQLite structuree `data/aegis_db.sqlite3` avec WAL active, `busy_timeout=5000` et transactions courtes.
- Documentation ajoutee dans `README.md` pour expliquer `data/aegis_db.sqlite3`, `data/aegis_db.sqlite3-wal`, `data/aegis_db.sqlite3-shm` et le checkpoint WAL vers la base principale.
- Tables SQLite : `bot_state`, `bot_positions`, `bot_pending_orders`, `bot_trailing_stops`, `bot_symbol_cooldowns`, `bot_exit_recommendations`, `bot_market_context`, `ml_live_predictions`, `bot_decision_journal`, `ml_raw_events`, `ml_entry_decisions`, `ml_entry_feature_values`, `ml_exit_decisions`, `ml_exit_feature_values`, `ml_trade_outcomes`, `ml_open_entries`, `telegram_messages`, `support_touch_results`, `ml_model_metadata`, `ml_feature_importances`, `ml_analysis_runs`, `ml_prediction_calibration`, `ml_rejected_replay_results`, `ml_drift_alerts`.
- Historique Telegram entrant/sortant ajoute a `data/aegis_db.sqlite3`; les anciens fichiers JSON Telegram ont ete retires.
- Anti-doublon status Telegram : `telegram_last_status_time` est stocke dans `bot_state` avec `mode='app'` pour respecter `TELEGRAM_STATUS_INTERVAL=7200` meme apres redemarrage.
- Etat du process dashboard/bot deplace de `data/bot_process.json`, `data/bot.pid` et `bot_process_state` vers `bot_state` avec `mode='process'`.
- Etat trading recree proprement : `bot_state` garde une ligne par mode avec colonnes pour les scalaires, tandis que positions, ordres, trailing stops, cooldowns, recommandations de sortie, contexte marche, predictions ML live et journal de decisions ont leurs tables dediees.
- Audit global ajoute : toutes les tables applicatives ont `created_at` et `updated_at`; la ligne `last_update` a ete retiree de `bot_state` car `updated_at` porte deja cette information.
- Normalisation ML ajoutee : `ml_entry_feature_values` et `ml_exit_feature_values` permettent d'analyser chaque feature par `event_id` et `feature_name`; `bot_market_context` et `ml_live_predictions` exposent les champs metier principaux en colonnes.
- Support Touch backtest ajoute a `data/aegis_db.sqlite3` dans une table unique `support_touch_results`; les infos du run sont repetees par paire pour eviter une structure inutilement normalisee.
- Metadata du modele ML ajoute a `data/aegis_db.sqlite3` avec les snapshots de modele et les importances de features entree/sortie.
- Suppression des fichiers JSON `data/support_touch_backtest.json` et `data/aegis_ml_metadata.json`; la DB devient la source principale.

---

## 12. Mise a Jour 2026-07-23 — Phase 4B Analyse des Erreurs ML

**Objectif :** transformer la memoire live en audit exploitable pour le futur reentrainement.

**Modifications :**
- Ajout de `scripts/analyze_ml_live_performance.py`.
- Automatisation par le bot via `run_ml_live_analysis_if_due()` et `ML_LIVE_ANALYSIS_INTERVAL_SECONDS`.
- Calibration des entrees acceptees par buckets de `P_win` dans `ml_prediction_calibration`.
- Resume d'analyse dans `ml_analysis_runs` : accepted, closed, rejected, replayed, Brier score, calibration MAE, win rate live, PnL moyen.
- Replay des entrees refusees dans `ml_rejected_replay_results` avec statut `pending_more_candles`, `replayed` ou `unavailable`.
- Detection de drift dans `ml_drift_alerts`.

**Etat observe au premier run :**
- 126 entrees refusees conservees.
- 0 entree acceptee fermee, donc calibration reelle encore insuffisante.
- Les refus recents sont marques `pending_more_candles` tant que l'horizon de replay n'est pas complet.
- Table SQLite `ml_open_entries` pour lier une entree acceptee a sa future sortie.
- Enregistrement des 52 features d'entree pour les achats acceptes et les candidats refuses.
- Enregistrement des 37 features de sortie au moment des decisions `HOLD`, `PROTECT_BREAKEVEN`, `TIGHTEN_STOP`, `TAKE_PROFIT`, `FORCE_EXIT`.
- Enregistrement du resultat final : prix d'achat, prix de vente, PnL, PnL %, duree, raison de sortie.

**Important :**
Cette phase est non intrusive : elle ne change pas les seuils, ne force aucune entree/sortie et ne remplace pas encore le modele actif. Elle prepare le dataset live pour le futur reentrainement champion/challenger.
