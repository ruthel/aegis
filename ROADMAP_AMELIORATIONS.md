# Feuille de Route & Etat d'Avancement — Ameliorations Bot Aegis

Derniere mise a jour : 2026-08-29

---

## Resume du Statut Actuel

* **Phase 0 (Assainissement & frais reels)** : ✅ **Termine**
* **Phase 1 (Sorties ML / ExitDecisionEngine fusionne)** : ✅ **Termine & actif**
* **Phase 2 (Core ML Engine entree 52 features)** : ✅ **Termine & actif**
* **Phase 3 (Suppression des anciens verrous durs)** : ✅ **Termine**
* **Phase 4 (Dataset live & apprentissage controle)** : ✅ **Termine, schema actuel aligne SQLite**
* **Phase 5 (Walk-forward, champion/challenger, calibration PnL)** : ✅ **Termine**
* **Phase 6 (Position sizing ML & allocation dynamique)** : ✅ **Termine**
* **Phase 7 (Execution intelligente & microstructure marche)** : ✅ **Termine (Phase 12)**
* **Phase 8 (Robustesse production & observabilite)** : ✅ **Termine**
* **Phase 10 (Autonomie controlee & gouvernance risque)** : ✅ **Termine**
* **Phase 11 (Sizing ML dedie & nettoyage sizing legacy)** : ✅ **Termine**
* **Phase 12 (Optimisation latence & execution)** : ✅ **Termine**
* **Phase 13 (Correction frais & coherence PnL)** : ✅ **Termine**
* **Phase 14 (Nettoyage code mort)** : ✅ **Termine**
* **Phase 15 (Amelioration ML exit & training)** : ✅ **Termine**
* **Phase 16 (Vers l'autonomie complete)** : 🔜 **À venir**

---

## ✅ Phase 0 : Correctifs Core & Calculs Financiers

- [x] **Gestion des frais reels (`Fee-Aware`)** : calcul centralise et enregistrement systematique des frais d'achat/vente (`buy_fee`, `sell_fee`, `fee_rate`).
- [x] **Transparence PnL** : affichage clair PnL brut, frais total et PnL net dans l'historique des trades et la carte Live.
- [x] **Trailing stop reactif & breakeven net** : mise a jour du stop a chaque tick WebSocket. Le breakeven net ne s'active que si le prix couvre l'integralite des frais A/R + mini profit net.
- [x] **Protection anti-achats simultanes** : verrouillage thread-safe (`Lock`) et verification ultime avant l'execution dans `execute_buy()`.
- [x] **Sauvegarde d'etat robuste Windows** : ecriture atomique avec fichier temporaire unique, `fsync`, retry `os.replace` et lock interne pour eviter les erreurs `[WinError 2]` / `[WinError 32]`.

---

## ✅ Phase 1 : Sorties ML / ExitDecisionEngine Fusionne

Le moteur de sortie n'est plus un module en shadow mode. Il est greffe au cerveau ML et sert directement a gerer la sortie d'une position.

- [x] **Decisions de sortie actives** : le chemin live est maintenant pilote par le ML en mode simple `HOLD` / `FORCE_EXIT`.
- [x] **ContinuationScore** : score de sante du mouvement base sur momentum, EMA, VWAP, structure bougies, volume, RSI et contexte BTC.
- [x] **Anciennes protections retirees du chemin actif** : profit fragile, time stop, trailing stop et objectifs paper ne vendent plus automatiquement quand `ML_OWNS_EXITS=true`.
- [x] **Shadow mode supprime** : `EXIT_ENGINE_SHADOW_MODE` n'est plus necessaire.
- [x] **Journalisation finale** : le decision log doit afficher les decisions finales utiles, pas chaque signal intermediaire transmis comme feature.

---

## ✅ Phase 2 : Core ML Engine Entree 52 Features

Le bot ne fonctionne plus comme une cascade de 7 verrous. Les anciens verrous metier sont devenus des features ML.

| Couche | Etat actuel |
|--------|-------------|
| Pre-ML operationnel | cooldown, position/capital, minimums exchange, securites d'execution |
| Features ML | regime symbole/BTC, bear mode, reversal, falling knife, Support Touch, score crypto, signal technique, timing, frais, valeur position, contexte de sortie |
| Decision entree | `P_win >= 65%` + probabilite de continuation suffisante |
| Decision sortie | ML actif : `HOLD` ou `FORCE_EXIT`; stops/objectifs servent au suivi, pas a vendre seuls |

### Resultats de reference apres fusion entree + sortie ML

| Scenario | Trades | Win rate | PnL backtest |
|----------|--------|----------|--------------|
| Baseline ancienne logique | 2941 | 62.5% | +2055.45% |
| Memes entrees + sorties ML | 2941 | 58.3% | +2351.17% |
| Entrees filtrees ML + sorties ML | 892 | 82.2% | +1438.60% |

Lecture : le systeme retenu fait moins de trades, mais avec une qualite moyenne nettement superieure. La moyenne estimee est d'environ **4.4 trades/jour** sur le dataset teste.

- [x] **Mode ML actif par defaut** : les toggles `ML_FILTER_ENABLED`, `ML_SHADOW_MODE`, `ML_EXIT_ENTRY_FILTER_ENABLED` et `ML_OWNS_ENTRY_FILTERS` ont ete retires.
- [x] **Modele entree** : RandomForest, 52 features, seuil P_win 65%.
- [x] **Modele sortie** : 37 features, gestion active des positions en `HOLD` / `FORCE_EXIT`.
- [x] **Support Touch** : conserve uniquement comme source statistique ML, plus comme fast-path.
- [x] **Falling knife / bear context / HTF / timing** : conserves comme features ML quand utiles, plus comme blocages durs redondants.

---

## ✅ Phase 3 : Assainissement des Anciens Verrous Durs

- [x] Suppression du fast-path Support Touch et des verdicts `allowed/blocked` durs.
- [x] Suppression des blocages durs avant ML sur contexte bear et falling knife, remplaces par features ML.
- [x] Suppression des logs intermediaires `htf_filter`, `support_touch_override`, `ml_feature_only` et equivalents.
- [x] Nettoyage ui : retrait des badges "Feature ML", correction du rendu Decision Log et Contexte d'entree.
- [x] Radar prochain achat : remplacement des ETA hasardeux par l'etat ML reel (`Pret ML maintenant` / `En attente ML`) et les raisons (`P_win`, continuation, seuils).
- [x] Telegram : status automatique remplace par un bilan quotidien a 08h (`TELEGRAM_DAILY_STATUS_HOUR=8`); `/status` reste disponible a la demande.

---

## ✅ Phase 4 : Amelioration ML Prioritaire — Dataset Live

Le prochain vrai gain n'est pas d'ajouter un nouveau verrou. Il faut enrichir ce que le ML apprend du trading reel.

- [x] **Journal live complet des entrees** : sauvegarder exactement les 52 features vues au moment ou le bot accepte ou refuse une entree dans `data/aegis_db.sqlite3`.
- [x] **SQLite WAL structure** : base locale avec `journal_mode=WAL`, `busy_timeout=5000`, convention `{domain}_{entity_plural}` et tables relationnelles ML, Telegram et bot.
- [x] **Documentation WAL/SHM** : `README.md` explique le role de `aegis_db.sqlite3`, `aegis_db.sqlite3-wal`, `aegis_db.sqlite3-shm`, et le moment ou le WAL est fusionne dans la base principale.
- [x] **Telegram dans `aegis_db`** : messages entrants/sortants stockes dans la table `notifications`; les anciens fichiers JSON Telegram ont ete retires.
- [x] **Process ui/bot dans `aegis_db`** : les anciens `data/bot_process.json`, `data/bot.pid` et `bot_process_state` sont remplaces par la table `bot_processes`.
- [x] **Bot state relationnel dans `aegis_db`** : `bot_state` garde uniquement les lignes de mode trading (`paper`, `live`); positions ouvertes, ordres, fills, ledger et soldes sont reconstruits depuis la comptabilite relationnelle.
- [x] **Etat app separe** : `bot_app_state` garde les valeurs applicatives persistantes comme `telegram_last_daily_status_day`, sans polluer `bot_state` avec des colonnes NULL.
- [x] **Audit timestamps global** : toutes les tables applicatives ont `created_at` et `updated_at`; `last_update` n'est plus stocke comme ligne separee dans `bot_state`.
- [x] **Features ML relationnelles** : les 52 features d'entree et les features de sortie sont sauvegardees dans `ml_feature_values` avec `action_type` et `feature_name`.
- [x] **Contexte/predictions normalises** : la table `cryptos` expose prix live, regime, bear mode, momentum, cooldowns, `p_win`, `p_continue` et prevision de sortie.
- [x] **Support Touch dans `aegis_db`** : backtests stockes dans une table unique `support_touch_results`.
- [x] **Metadata ML dans `aegis_db`** : snapshots de modele stockes dans `ml_model_metadata` et importances dans `ml_feature_importances`.
- [x] **Lien entree acceptee -> sortie reelle** : stocker l'entree ouverte dans la table SQLite `ml_open_entries`, puis fermer le sample au moment de la vente.
- [x] **Runtime JSON supprime** : decisions ui, commandes bot, statut live WebSocket, scores crypto et entrees ML ouvertes sont lus/ecrits dans `data/aegis_db.sqlite3`.
- [x] **Statut live normalise** : les anciennes tables `bot_live_status*` ont ete migrees/supprimees; le live est expose via `cryptos`, `bot_app_state` et le WebSocket `/ws/live`.
- [x] **Suppression des payloads dupliques** : les colonnes `*_data` et `payload_data` ont ete retirees des tables applicatives; les valeurs variables sont normalisees en colonnes ou tables de métriques/features.
- [x] **Stats journalieres dans `aegis_db`** : les statistiques de risque journalieres sont stockees dans la table `bot_daily_stats`.
- [x] **Schema ORM actif** : SQLAlchemy crée les tables au démarrage avec `Base.metadata.create_all(...)`; le fichier SQL de référence a été retiré.
- [x] **ORM SQLAlchemy progressif** : `core/db_orm.py` modèle et pilote maintenant l'état bot relationnel, les événements ML entrée/sortie, features, outcomes, Telegram, commandes, live status, stats, scores, Support Touch, metadata ML, journal de décisions et tables d'analyse Phase 4/5. Le SQL direct restant sert surtout aux migrations historiques et aux lectures analytiques.
- [x] **Journal live des decisions de sortie** : sauvegarder les 37 features de sortie, la decision ML et l'etat courant (`HOLD` ou `FORCE_EXIT`).
- [x] **Resultat final des trades** : enregistrer prix d'achat, prix de vente, PnL, PnL %, duree et raison de sortie quand le trade ferme.
- [x] **Candidats refuses conserves** : enregistrer les refus ML comme `candidate_rejected_pending_replay` pour analyse future.
- [x] **Labelliser les candidats refuses** : `scripts/analyze_ml_live_performance.py` cree `ml_rejected_replay_results` et rejoue les refus des que les bougies futures sont disponibles. ✅ Corrigé 2026-08-29 : le tri des refus à rejouer traitait les plus RÉCENTS d'abord (sans bougies futures -> 0 replay effectif, backlog de ~2900 vieux refus jamais atteint). Nouveau tri par âge : refus assez vieux (rejouables) d'abord, les trop récents repoussés aux runs suivants. Plafond `--max-replay` câblé sur `ML_LIVE_ANALYSIS_MAX_REPLAY` (défaut 500). 505 lignes orphelines (post-reset paper, features non reliées) purgées.
- [x] **Comparer prediction vs resultat reel** : calibration par buckets `P_win` dans `ml_prediction_calibration`, avec Brier score, win rate live et PnL moyen dans `ml_analysis_runs`.
- [x] **Detection de drift marche** : `ml_drift_alerts` signale `ok`, `warning` ou `insufficient_live_outcomes` selon les resultats live disponibles.
- [x] **Automatisation periodique** : `run_ml_live_analysis_if_due()` lance `scripts/analyze_ml_live_performance.py` en arriere-plan selon `ML_LIVE_ANALYSIS_INTERVAL_SECONDS`.
- [x] **UI SPA React** : migration du ui vers React + Vite + TypeScript, pnpm, axios, zustand, shadcn/Radix, lucide-react, Outfit et amCharts 5.
- [x] **Rendu ui aligne legacy** : sections Core ML Engine, Contexte d'entree, Decisions, Marche Live, Cooldowns, Positions, Alertes, Console et Analytics reproduites en SPA avec design dense.
- [x] **Historique des scores crypto** : courbe amCharts connectee a `/api/analytics/scores`, filtres symbole/periode en dropdown shadcn, axe temporel propre et tooltip score/prix.
- [x] **Decision log final uniquement** : les cooldowns operationnels ne sont plus enregistres comme decisions rejetees/approuvees; ils restent visibles dans la section Cooldowns.
- [x] **Nettoyage runtime temporaire** : purge ponctuelle des anciennes tables redondantes (`bot_decision_journal`, `bot_decision_metrics`, `ml_decisions`, `ml_raw_events`, etc.). Les tables utiles actuelles `ml_feature_values`, `ml_rejected_replay_results` et `ml_prediction_calibration` restent actives.
- [x] **Logs bot moins bruyants** : suppression des logs de trade sizing (`💰 Trade: ...`) et filtrage des timeouts WebSocket ping/pong redondants.
- [x] **Sorties ML-only consolidees** : `ExitDecisionEngine` ne produit plus de decision par règles; il calcule les métriques utiles et applique uniquement la decision ML. Les ordres objectifs paper restaurés sont des references UI (`ml_exit_target_reference`) et non des vendeurs automatiques.
- [x] **Trades UI ouverts** : la page `/trades` affiche aussi les positions ouvertes avec statut `OPEN`, en plus des trades fermés.
- [x] **Marche Live en USD** : le volume affiche maintenant `Volume USD`; l'UI utilise le volume quote si disponible ou calcule `volume base * prix live`.
- [x] **Market events anti-spam** : un événement macro déjà actif (`FED_MEETING`, `INFLATION_DATA`, `MARKET_UNCERTAINTY`) reste silencieux si le même type est redétecté avant expiration; l'état actif est persisté dans `bot_app_state`.
- [x] **Analytics amCharts 5 connectés** : `DailyBarChart` et `HourlyBarChart` remplacent les anciens faux graphs Tailwind dans la vue Analytics.
- [x] **Charts sans blink** : les graphiques amCharts sont créés une seule fois puis mis à jour via `xAxis.data` et `series.data`, sans destruction/recréation à chaque refresh.
- [x] **Documentation cartographiée** : `docs/CARTOGRAPHIE_APP.md` décrit l'architecture actuelle complète : bot, ML, SQLite, API Flask, WebSocket, SPA et flux décisionnels.

---

## 🟡 Phase 5 : Walk-Forward & Promotion Contrôlée des Modèles (Partiel actif)

- [x] **Walk-forward validation** : entraînement et test glissant sur fenêtres temporelles successives sans fuite d'information (`scripts/walk_forward_validation.py`).
- [x] **Champion / challenger** : entraînement et comparaison entre Champion (`aegis_model.joblib`) et Challenger (`aegis_challenger.joblib`) dans le pipeline unifié `scripts/train_and_evaluate_ml_model.py`.
- [x] **Objectif PnL net & Calibration** : optimisation de l'Accuracy, de la Precision et du PnL net sur données hors-échantillon.
- [x] **Replay des erreurs & Refus rejoués** : réinjection des refus rejoués dans l'entraînement via `ml_rejected_replay_results` et `load_phase5_replay_samples()`. ✅ Corrigé 2026-08-29 : la fonction `load_phase5_replay_samples()` existait mais **n'était jamais appelée** (boucle rompue). Elle est désormais branchée dans `train_challenger_model()` : les refus rejoués (statut `replayed`, label `would_win`) sont ajoutés à `X_samples/y_labels` avec un poids modéré configurable (`ML_REPLAY_TRAIN_WEIGHT_WIN=1.2` / `LOSS=1.0`, plafond `ML_REPLAY_TRAIN_MAX_SAMPLES=2000`). Le split train/test de `train_model` a aussi été corrigé pour aligner `sample_weight` sur les lignes mélangées.
- [x] **Promotion automatique contrôlée** : promotion sécurisée du Challenger vers Champion avec sauvegarde automatique `aegis_model_backup.joblib`.
- [x] **Découplage hybride ML exit + garde-fous physiques** : conservation active du Trailing Stop et Breakeven Stop comme filet de sécurité plancher en temps réel (`HYBRID_PHYSICAL_SAFETY=true`).
- [x] **Protection profit ML dynamique** : quand une position est déjà en profit net, le seuil de sortie devient plus défensif (`ML_EXIT_PROFIT_PROTECT_THRESHOLD`) afin d'éviter de laisser une fenêtre gagnante revenir sous l'entrée.


---

## ✅ Phase 6 : Position Sizing & Allocation Dynamique (Remplace par Phase 11 pour la decision de taille)

Objectif : ne plus seulement décider **si** le bot entre, mais aussi **combien** il engage selon la qualité du setup.

- [x] **Sizing par confiance ML historique** : ancienne taille graduée (40%, 70%, 100%) retirée du chemin actif; la decision de taille est maintenant portée par le `sizing_model` Phase 11.
- [x] **Sizing par volatilité** : ajustement dynamique du montant selon l'ATR, la volatilité et les contraintes de risque (`utils/risk_manager.py`).
- [x] **Budget par symbole** : contrôle des corrélations inter-crypto (`CorrelationManager`).
- [x] **Kelly fractionné ML historique** : retiré du chemin actif pour éviter une double decision de sizing avant le `sizing_model`.
- [x] **UI allocation & Sizing Reason** : affichage explicatif de la raison du sizing sous la valeur USD dans le tableau de bord web.

Impact attendu : moins de pertes lourdes sur setups incertains, meilleur rendement quand le ML est vraiment confiant.

---

## 🟡 Phase 7 : Execution Intelligente & Microstructure Marche (Partiel actif)

Objectif : ameliorer le prix reel d'achat/vente sans ajouter de verrous durs.

- [x] **Slippage tracking** : mesurer ecart entre prix prevu, prix demande et prix execute (`ExecutionManager`).
- [x] **Spread-aware execution** : eviter les executions quand le spread est temporairement trop large (`wait_for_tight_spread`).
- [ ] **Volume USD minimum dynamique** : adapter réellement les executions a la liquidite live. `adjust_size_for_depth()` existe, mais retourne encore la taille inchangée.
- [x] **Ordres adaptatifs** : choisir entre market, limit agressif ou attente courte selon urgence ML et carnet (`execute_smart_buy`).
- [x] **Retry propre** : si l'ordre rate, ne pas dupliquer l'achat; enregistrer l'echec comme sample d'execution.
- [x] **Prix d'entree attendu vs obtenu** : alimenter le dataset ML avec la qualite d'execution (`log_execution_metric`).

Impact attendu : moins de frais implicites, moins d'achats au mauvais tick, meilleur PnL net sans changer la logique ML.

---

## 🟡 Phase 8 : Robustesse Production & Observabilite (Partiel actif)

Objectif : rendre le bot plus stable, plus lisible et plus facile a auditer pendant plusieurs jours de fonctionnement.

- [x] **Health checks internes actifs** : `HealthManager` est planifié dans la boucle bot, journalise les changements dans `governance_logs` et notifie Telegram en cas de WARN/CRITICAL.
- [x] **Alertes Telegram utiles** : envoyer seulement les decisions finales importantes, erreurs critiques, drift ML et changement champion/challenger (`notify_ml_drift`).
- [x] **Dashboard prediction vs resultat** : tableau par symbole, regime, heure, P_win, P_continue, decision sortie et resultat final (`decision_logs`).
- [x] **Audit trail complet** : lien decision entree -> features -> ordre -> position -> decision sortie -> outcome fiabilise via `entry_id`, avec relink automatique depuis `ml_open_entries` ou la derniere entree ML acceptee non fermee.
- [x] **Sauvegarde DB** : snapshot `aegis_db.sqlite3` avec checkpoint WAL quand tous les processus sont arretes (`backup_db`).

Impact attendu : moins de zones floues, diagnostic plus rapide, meilleure confiance avant passage en live reel.

## 🔒 Phase 10 : Autonomie Controlee & Gouvernance Risque

Objectif : permettre au bot de s'ameliorer avec ses donnees sans devenir opaque ou dangereux.

Etat actuel : quelques briques existent deja (`governance_logs`, sauvegarde champion, safe fallback interne, limites de capital de base), mais elles ne forment pas encore un cycle autonome complet.

- [x] **Auto-retraining planifie** : `run_ml_auto_retraining_if_due()` peut lancer `scripts/train_and_evaluate_ml_model.py` en arriere-plan selon `ML_AUTO_RETRAIN_INTERVAL_SECONDS`; il est desactive par defaut et tourne en `--check-only` par defaut.
- [x] **Promotion avec garde-fous complets** : minimum trades, minimum jours, drawdown max, PnL net positif, profit factor minimum, calibration acceptable et statut drift autorise avant promotion.
- [x] **Mode safe fallback automatise** : active le mode safe si pertes consecutives, perte journaliere/hebdo, drift ML critique ou health CRITICAL persistant depassent les seuils configures.
- [x] **Journal de gouvernance complet** : enregistre evaluation des garde-fous, promotions/refus, retraining, health status/action required et safe fallback avec raison + metriques JSON.
- [x] **Limites capital strictes** : perte journaliere, perte hebdo, nombre max de positions, exposition globale, positions max par crypto et blocage automatique si limite atteinte.
- [x] **Surveillance health checks** : `HealthManager.run_checks()` est planifie; les WARN/CRITICAL notifient et journalisent, les CRITICAL repetes peuvent declencher le safe fallback si `HEALTH_SAFE_FALLBACK_ENABLED=true`.

Impact attendu : apprentissage autonome, mais sous controle explicite, avec audit complet.

---

## 🟡 Phase 11 : Sizing ML Dedie & Nettoyage Sizing Legacy

Objectif : ajouter un troisieme modele dans le champion ML pour decider **combien engager** sur un trade, sans remplacer les garde-fous de risque.

Architecture visee :

```text
data/aegis_model.joblib
├── model         -> entree / P_win
├── exit_model    -> sortie / P_continue
└── sizing_model  -> taille recommandee / sizing_factor
```

Le `sizing_model` ne decide pas d'acheter ou vendre. Il propose un facteur de taille, puis le Risk Manager garde le veto final.

### Etapes de creation

- [x] **Definition cible sizing initiale** : facteurs de taille (`0.25x`, `0.40x`, `0.50x`, `0.75x`, `1.00x`, `1.25x`) derives du PnL net historique dans `sizing_factor_target_from_pnl()`.
- [ ] **Features sizing** : reutiliser les features d'entree/sortie utiles et ajouter les metriques deja connues du trade prevu : capital disponible, exposition globale, exposition symbole, volatilite, Kelly, regime, spread et liquidite.
- [x] **Modele sizing champion/challenger** : entrainer un `sizing_model` separe et le sauvegarder dans le meme `aegis_model.joblib` / `aegis_challenger.joblib`.
- [x] **Prediction live sizing** : `MLEngine.predict_position_size_factor()` retourne `sizing_factor`, `raw_sizing_factor` et `reason`, avec fallback `1.0x` si le modele est absent.
- [x] **Integration trading initiale** : dans `TradingBot`, le facteur ML sizing ajuste la taille de base calculee quand le modele sizing est disponible; sinon un fallback neutre `1.0x` reste actif.
- [x] **Garde-fous risk manager** : conserver les plafonds stricts : exposition globale, exposition par symbole, capital disponible, minimum exchange, perte journaliere/hebdo et safe fallback.
- [x] **Journalisation sizing** : enregistrer la recommandation sizing dans SQLite (`ml_sizing_recommendations`) avec facteur propose, facteur final applique, exposition et plafonds risk manager.
- [x] **UI Config & Live** : afficher le statut du modele sizing, son facteur recommande et la raison du sizing dans les cartes ML/Config.
- [x] **Backtest / replay sizing** : comparer sizing legacy vs sizing ML sur trades fermes et refus rejoues via `scripts/backtest_ml_sizing.py`, avec sauvegarde dans `ml_sizing_backtests`.

### Etapes de nettoyage apres validation

- [x] **Retirer sizing fixe redondant** : seuils durs `40% / 70% / 100%`, `_confidence_sizing_factor()` et branche `ml_neutral_sizing` retires du chemin actif.
- [x] **Nettoyer anciennes variables inutiles** : suppression des sorties runtime `ml_factor`, `ml_position_factor`, `ml_neutral_sizing` et Kelly fractionne legacy.
- [x] **Simplifier `risk_manager.calculate_position_size()`** : conserve une taille de base neutre, volatilite et limites; la decision cible de taille est deplacee vers le ML.
- [x] **Audit code mort sizing** : `docs/AUDIT_CODE_MORT.md` mis a jour apres suppression des branches sizing legacy confirmees.
- [x] **Documentation finale** : `README.md` et `docs/CARTOGRAPHIE_APP.md` mis a jour avec le cerveau ML entree/sortie/sizing.

Impact attendu : moins de capital sur setups fragiles, plus de capital sur opportunites propres, et rendement mieux optimise sans augmenter le capital total.

---

## ✅ Phase 12 : Optimisation Latence & Execution (Terminé 2026-08-24/26)

Objectif : réduire le temps entre la décision ML et l'exécution réelle sur Kraken.

- [x] **Skip ledger sync sur ventes urgentes** : `get_balance(skip_ledger_sync=True)` évite le fetch ledger (~3-5s) pendant les exits ML.
- [x] **Cancel orders optimisé** : vérification `pending_orders` en mémoire avant d'appeler l'API Kraken. Skip complet si rien à annuler.
- [x] **Resolve execution fast-path** : si l'ordre Kraken retourne déjà les infos de fill (market orders), return immédiat sans re-fetch.
- [x] **Délais réduits** : sleep de confirmation passé de (0.4s, 1.0s, 1.8s) à (0.15s, 0.5s, 1.5s).
- [x] **Fetch klines parallèle (exit)** : klines symbole + BTC fetchées en parallèle via ThreadPoolExecutor (~3s au lieu de 6s).
- [x] **Fetch klines parallèle (entry)** : 5 timeframes (15m, 5m, 1h, 4h, 1d) fetchés en parallèle (~3s au lieu de 15s).
- [x] **Suppress sell limit quand ML_OWNS_EXITS=true** : plus de `optimize_existing_position` inutile, élimine le besoin de cancel orders.
- [x] **Watchdog WebSocket** : reconnexion forcée si aucun tick reçu depuis 90s (évite les déconnexions silencieuses de 2h).
- [x] **Preload klines parallèle au démarrage** : les 4 symboles fetchés en parallèle au boot (~3s au lieu de 12s).

Résultats mesurés :
- Latence exit (décision → vente) : **~16-21s → ~9-12s**
- Intervalle évaluation exit : **~55s → ~15s**
- Latence entry (score → achat) : **~20-25s → ~12s**

---

## ✅ Phase 13 : Correction Frais & Cohérence PnL (Terminé 2026-08-24/26)

Objectif : aligner les frais utilisés partout dans le bot avec les frais réels Kraken (0.40% taker).

- [x] **TRADING_FEE_PERCENT=0.4** dans `.env.local` et tous les fallbacks code.
- [x] **Tous les hardcoded 0.001 remplacés** : trading_bot.py, train script, walk_forward, backtest, position_manager, capital_manager, ml_live_logger, ml_engine.
- [x] **Frais ledger Kraken** : les imports `kraken_ledger` n'ajoutent plus de fee (le prix est déjà net après frais dans le ledger Kraken).
- [x] **Déduplication live_trade vs kraken_ledger** : `_has_matching_local_live_trade()` empêche la création de doublons.
- [x] **Limite perte journalière** : remplacée de "10 trades perdants max" par "5% du capital total" avec override manuel (`OVERRIDE_DAILY_LOSS_LIMIT`).
- [x] **Capital total correct** : `_total_balance_usd()` retourne USD libre + valeur crypto détenue (pas juste l'USD libre).

---

## ✅ Phase 14 : Nettoyage Code Mort (Terminé 2026-08-24)

- [x] Suppression `manage_trailing_stops()` (dead avec ML_OWNS_EXITS=true)
- [x] Suppression boucle `optimize_existing_position` dans `run()`
- [x] Suppression `check_and_recover_stuck_positions()` (remplacé par version _filtered)
- [x] Suppression `get_entry_signal()` (remplacé par intelligent_strategy)
- [x] Suppression `adjust_size_for_depth()` stub
- [x] Suppression `optimize_thresholds_daily()` + `_analyze_threshold_performance()`
- [x] Suppression dead code CorrelationManager (market_sentiment, add/remove_position)
- [x] Suppression variables mortes RiskManager
- [x] Suppression `test_all_balances()` + `show_balance_summary()`
- [x] Suppression `check_paper_limit_orders()` dupliqué
- [x] Suppression code Binance WebSocket
- [x] Fix clés dupliquées `get_min_amount()`
- [x] Suppression imports dupliqués trading_bot.py

---

## ✅ Phase 15 : Amélioration ML Exit & Training (Terminé 2026-08-26)

- [x] **Labeling P_exit amélioré** : "rester est-il mieux que sortir maintenant ?" au lieu de "le trade finit-il positif ?". Le modèle apprend à prendre les profits au bon moment.
- [x] **Exit model entraîné avec les bonnes features** : 37 features exit (PnL, durée, continuation_score...) au lieu des 68 features entrée.
- [x] **Multi-TF réelles** : fetch 5m/1h/4h/1d depuis Binance au lieu d'agréger les 15m.
- [x] **Métriques sauvegardées** : precision, accuracy, recall, F1, OOB score stockés dans le `.joblib` et affichés au training.
- [x] **Dynamic Breakeven Lock** : protection par paliers (0%/50%/70% du plus haut gain) empêche un profit de devenir une perte.

---

## 🔜 Phase 16 : Vers l'Autonomie Complète (À venir)

### Étape 1 — Consolidation (1 mois)

- [x] **Auto-retraining bi-hebdomadaire** : réentraîner automatiquement avec les nouvelles données live toutes les 2 semaines. ✅ `ML_AUTO_RETRAIN_ENABLED=true`, intervalle 14 jours (`ML_AUTO_RETRAIN_INTERVAL_SECONDS=1209600`), promotion automatique via garde-fous.
- [x] **Augmentation dataset** : objectif 15-20k samples atteint (**15346 samples**). ✅ Méthode retenue : extension de l'historique d'entraînement à **3 ans** (`ML_TRAINING_HISTORY_DAYS=1095`) via Coinbase, au lieu de la diversification des signaux d'entrée (testée puis abandonnée car elle dégradait la précision : 78.8% → 70.2%). Bonus : le dataset couvre désormais bear 2023-2024 + remontée + régime haussier actuel, ce qui rend le modèle robuste aux changements de régime.
- [x] **P_target model** : régresseur ML qui prédit le gain max atteignable pour fixer un take-profit intelligent. ✅ `RandomForestRegressor` à 78 features intégré au champion (`target_model` dans `aegis_model.joblib`), prédiction clampée entre `ML_TARGET_MIN_PCT=0.8` et `ML_TARGET_MAX_PCT=12.0`, pose un take-profit à l'entrée via `predict_target()` + `_check_take_profit_target()` (`ML_TAKE_PROFIT_ENABLED=true`).

### Étape 2 — Apprentissage par Renforcement (1-3 mois)

- [ ] **Agent DQN ou PPO** : remplace le RandomForest par un agent qui maximise le PnL cumulé (pas trade par trade).
- [ ] **État complet** : l'agent voit positions ouvertes, capital, prix, indicateurs et choisit buy/sell/hold.
- [ ] **Reward shaping** : récompense = PnL net réalisé + pénalité drawdown + bonus Sharpe.
- [ ] **Self-play simulation** : entraînement sur simulateur avant déploiement live.

### Étape 3 — Modèles Séquentiels (3-6 mois)

- [ ] **LSTM / Transformer** : modèles qui traitent des séquences (30 derniers états) pour comprendre tendances et retournements.
- [ ] **Attention mechanism** : le modèle apprend quelles bougies passées sont pertinentes pour la décision actuelle.
- [ ] **Multi-horizon prediction** : prédire le prix à +15min, +1h, +4h simultanément.

### Étape 4 — Multi-Agent Spécialisé (6-12 mois)

- [ ] **Market Regime Detector** : identifie bull/bear/range en temps réel.
- [ ] **Entry Specialist** : trouve les points d'entrée optimaux.
- [ ] **Position Manager** : gère sorties, trailing, sizing dynamique.
- [ ] **Risk Controller** : override les agents si risque global trop élevé.
- [ ] **Meta-Learner** : sélectionne quel agent écouter selon le contexte.

### Étape 5 — Système Auto-Évolutif (12+ mois)

- [ ] **Online learning** : mise à jour continue du modèle avec chaque trade.
- [ ] **Détection de régime automatique** : switch de stratégie sans intervention humaine.
- [ ] **Multi-exchange / multi-asset** : diversification automatique selon les opportunités.
- [ ] **Self-monitoring** : le système détecte quand il perd sa calibration et se met en pause.
- [ ] **Capital scaling** : augmentation automatique des positions quand la performance est stable.
