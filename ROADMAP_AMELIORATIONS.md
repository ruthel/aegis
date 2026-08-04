# Feuille de Route & Etat d'Avancement — Ameliorations Bot Aegis

Derniere mise a jour : 2026-07-31

---

## Resume du Statut Actuel

* **Phase 0 (Assainissement & frais reels)** : ✅ **Termine**
* **Phase 1 (Sorties ML / ExitDecisionEngine fusionne)** : ✅ **Termine & actif**
* **Phase 2 (Core ML Engine entree 52 features)** : ✅ **Termine & actif**
* **Phase 3 (Suppression des anciens verrous durs)** : ✅ **Termine**
* **Phase 4 (Dataset live & apprentissage controle)** : ✅ **Termine**
* **Phase 5 (Walk-forward, champion/challenger, calibration PnL)** : ⏳ **Planifie**
* **Phase 6 (Position sizing ML & allocation dynamique)** : 🔜 **A planifier**
* **Phase 7 (Execution intelligente & microstructure marche)** : 🔜 **A planifier**
* **Phase 8 (Robustesse production & observabilite)** : 🔜 **A planifier**
* **Phase 9 (Modeles avances : XGBoost / ensembles / deep learning prudent)** : 🔜 **Recherche**
* **Phase 10 (Autonomie controlee & gouvernance risque)** : 🔜 **Vision long terme**

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
- [x] **Telegram dans `aegis_db`** : messages entrants/sortants stockes dans la table `telegram_messages`; les anciens fichiers JSON Telegram ont ete retires.
- [x] **Process ui/bot dans `aegis_db`** : les anciens `data/bot_process.json`, `data/bot.pid` et `bot_process_state` sont remplaces par la table `bot_processes`.
- [x] **Bot state relationnel dans `aegis_db`** : `bot_state` garde uniquement les lignes de mode trading (`paper`, `live`); positions, ordres, trailing stops, cooldowns et recommandations de sortie ont leurs tables dediees.
- [x] **Etat app separe** : `bot_app_state` garde les valeurs applicatives persistantes comme `telegram_last_daily_status_day`, sans polluer `bot_state` avec des colonnes NULL.
- [x] **Audit timestamps global** : toutes les tables applicatives ont `created_at` et `updated_at`; `last_update` n'est plus stocke comme ligne separee dans `bot_state`.
- [x] **Features ML relationnelles** : les 52 features d'entree et les features de sortie sont sauvegardees dans `ml_feature_values` avec `action_type` et `feature_name`.
- [x] **Contexte/predictions normalises** : `bot_market_context` expose regime, bear mode et signaux cles; `ml_live_predictions` expose `p_win`, `p_continue` et la prevision de sortie.
- [x] **Support Touch dans `aegis_db`** : backtests stockes dans une table unique `support_touch_results`.
- [x] **Metadata ML dans `aegis_db`** : snapshots de modele stockes dans `ml_model_metadata` et importances dans `ml_feature_importances`.
- [x] **Lien entree acceptee -> sortie reelle** : stocker l'entree ouverte dans la table SQLite `ml_open_entries`, puis fermer le sample au moment de la vente.
- [x] **Runtime JSON supprime** : decisions ui, commandes bot, statut live WebSocket, scores crypto et entrees ML ouvertes sont lus/ecrits dans `data/aegis_db.sqlite3`.
- [x] **Statut live normalise** : `bot_live_status` ne stocke plus de blob complet; subscriptions et métriques symboles sont dans des colonnes/tables dédiées.
- [x] **Suppression des payloads dupliques** : les colonnes `*_data` et `payload_data` ont ete retirees des tables applicatives; les valeurs variables sont normalisees en colonnes ou tables de métriques/features.
- [x] **Stats journalieres dans `aegis_db`** : les statistiques de risque journalieres sont stockees dans la table `bot_daily_stats`.
- [x] **Schema ORM actif** : SQLAlchemy crée les tables au démarrage avec `Base.metadata.create_all(...)`; le fichier SQL de référence a été retiré.
- [x] **ORM SQLAlchemy progressif** : `core/db_orm.py` modèle et pilote maintenant l'état bot relationnel, les événements ML entrée/sortie, features, outcomes, Telegram, commandes, live status, stats, scores, Support Touch, metadata ML, journal de décisions et tables d'analyse Phase 4/5. Le SQL direct restant sert surtout aux migrations historiques et aux lectures analytiques.
- [x] **Journal live des decisions de sortie** : sauvegarder les 37 features de sortie, la decision ML et l'etat courant (`HOLD` ou `FORCE_EXIT`).
- [x] **Resultat final des trades** : enregistrer prix d'achat, prix de vente, PnL, PnL %, duree et raison de sortie quand le trade ferme.
- [x] **Candidats refuses conserves** : enregistrer les refus ML comme `candidate_rejected_pending_replay` pour analyse future.
- [x] **Labelliser les candidats refuses** : `scripts/analyze_ml_live_performance.py` cree `ml_rejected_replay_results` et rejoue les refus des que les bougies futures sont disponibles.
- [x] **Comparer prediction vs resultat reel** : calibration par buckets `P_win` dans `ml_prediction_calibration`, avec Brier score, win rate live et PnL moyen dans `ml_analysis_runs`.
- [x] **Detection de drift marche** : `ml_drift_alerts` signale `ok`, `warning` ou `insufficient_live_outcomes` selon les resultats live disponibles.
- [x] **Automatisation periodique** : `run_ml_live_analysis_if_due()` lance `scripts/analyze_ml_live_performance.py` en arriere-plan selon `ML_LIVE_ANALYSIS_INTERVAL_SECONDS`.
- [x] **UI SPA React** : migration du ui vers React + Vite + TypeScript, pnpm, axios, zustand, shadcn/Radix, lucide-react, Outfit et amCharts 5.
- [x] **Rendu ui aligne legacy** : sections Core ML Engine, Contexte d'entree, Decisions, Marche Live, Cooldowns, Positions, Alertes, Console et Analytics reproduites en SPA avec design dense.
- [x] **Historique des scores crypto** : courbe amCharts connectee a `/api/analytics/scores`, filtres symbole/periode en dropdown shadcn, axe temporel propre et tooltip score/prix.
- [x] **Decision log final uniquement** : les cooldowns operationnels ne sont plus enregistres comme decisions rejetees/approuvees; ils restent visibles dans la section Cooldowns.
- [x] **Nettoyage runtime temporaire** : purge ponctuelle des tables `bot_decision_journal`, `bot_decision_metrics`, `ml_decisions`, `ml_feature_values`, `ml_rejected_replay_results`, `ml_raw_events` et `ml_prediction_calibration` apres changement de semantics.
- [x] **Logs bot moins bruyants** : suppression des logs de trade sizing (`💰 Trade: ...`) et filtrage des timeouts WebSocket ping/pong redondants.
- [x] **Sorties ML-only consolidees** : `ExitDecisionEngine` ne produit plus de decision par règles; il calcule les métriques utiles et applique uniquement la decision ML. Les ordres objectifs paper restaurés sont des references UI (`ml_exit_target_reference`) et non des vendeurs automatiques.
- [x] **Trades UI ouverts** : la page `/trades` affiche aussi les positions ouvertes avec statut `OPEN`, en plus des trades fermés.
- [x] **Marche Live en USD** : le volume affiche maintenant `Volume USD`; l'UI utilise le volume quote si disponible ou calcule `volume base * prix live`.
- [x] **Market events anti-spam** : un événement macro déjà actif (`FED_MEETING`, `INFLATION_DATA`, `MARKET_UNCERTAINTY`) reste silencieux si le même type est redétecté avant expiration; l'état actif est persisté dans `bot_app_state`.
- [x] **Analytics amCharts 5 connectés** : `DailyBarChart` et `HourlyBarChart` remplacent les anciens faux graphs Tailwind dans la vue Analytics.
- [x] **Charts sans blink** : les graphiques amCharts sont créés une seule fois puis mis à jour via `xAxis.data` et `series.data`, sans destruction/recréation à chaque refresh.
- [x] **Documentation cartographiée** : `docs/CARTOGRAPHIE_APP.md` décrit l'architecture actuelle complète : bot, ML, SQLite, API Flask, WebSocket, SPA et flux décisionnels.

---

## ✅ Phase 5 : Walk-Forward & Promotion Contrôlée des Modèles (Terminé)

- [x] **Walk-forward validation** : entraînement et test glissant sur fenêtres temporelles successives sans fuite d'information (`scripts/walk_forward_validation.py`).
- [x] **Champion / challenger** : évaluation et comparaison rigoureuse entre le modèle Champion actif (`aegis_model.joblib`) et le Challenger (`aegis_challenger.joblib`) (`scripts/evaluate_champion_challenger.py`).
- [x] **Objectif PnL net & Calibration** : optimisation de l'Accuracy, de la Precision et du PnL net sur données hors-échantillon.
- [x] **Replay des erreurs & Refus réjoués** : réinjection des refus rejoués dans l'entraînement multi-timeframes (`scripts/train_ml_model.py --include-replay-learning`).
- [x] **Promotion automatique contrôlée** : promotion sécurisée du Challenger vers Champion avec création automatique du fichier de sauvegarde `aegis_model_backup.joblib` (`--promote`).
- [x] **Rollback modèle** : possibilité de retour arrière immédiat au modèle précédent via `--rollback` (`scripts/evaluate_champion_challenger.py --rollback`).
- [x] **Découplage hybride ML exit + garde-fous physiques** : conservation active du Trailing Stop et Breakeven Stop comme filet de sécurité plancher en temps réel (`HYBRID_PHYSICAL_SAFETY=true`).
- [x] **Protection profit ML dynamique** : quand une position est déjà en profit net, le seuil de sortie devient plus défensif (`ML_EXIT_PROFIT_PROTECT_THRESHOLD`) afin d'éviter de laisser une fenêtre gagnante revenir sous l'entrée.


---

## ✅ Phase 6 : Position Sizing ML & Allocation Dynamique (Terminé)

Objectif : ne plus seulement décider **si** le bot entre, mais aussi **combien** il engage selon la qualité du setup.

- [x] **Sizing par confiance ML** : taille graduée (40%, 70%, 100%) selon le niveau de confiance `p_win` du modèle ML (`core/trading_bot.py`).
- [x] **Sizing par volatilité** : ajustement dynamique du montant selon l'ATR, la volatilité et les contraintes de risque (`utils/risk_manager.py`).
- [x] **Budget par symbole** : contrôle des corrélations inter-crypto (`CorrelationManager`).
- [x] **Kelly fractionné ML** : application institutionnelle d'un Kelly fractionné 25% basé sur le win rate live et le payoff ratio (`calculate_kelly_fractional_factor`).
- [x] **UI allocation & Sizing Reason** : affichage explicatif de la raison du sizing sous la valeur USD dans le tableau de bord web.

Impact attendu : moins de pertes lourdes sur setups incertains, meilleur rendement quand le ML est vraiment confiant.

---

## 🔜 Phase 7 : Execution Intelligente & Microstructure Marche

Objectif : ameliorer le prix reel d'achat/vente sans ajouter de verrous durs.

- [ ] **Slippage tracking** : mesurer ecart entre prix prevu, prix demande et prix execute.
- [ ] **Spread-aware execution** : eviter les executions quand le spread est temporairement trop large.
- [ ] **Volume USD minimum dynamique** : adapter les executions a la liquidite live.
- [ ] **Ordres adaptatifs** : choisir entre market, limit agressif ou attente courte selon urgence ML et carnet.
- [ ] **Retry propre** : si l'ordre rate, ne pas dupliquer l'achat; enregistrer l'echec comme sample d'execution.
- [ ] **Prix d'entree attendu vs obtenu** : alimenter le dataset ML avec la qualite d'execution.

Impact attendu : moins de frais implicites, moins d'achats au mauvais tick, meilleur PnL net sans changer la logique ML.

---

## 🔜 Phase 8 : Robustesse Production & Observabilite

Objectif : rendre le bot plus stable, plus lisible et plus facile a auditer pendant plusieurs jours de fonctionnement.

- [ ] **Health checks internes** : verifier DB, WebSocket, exchange, Telegram, modele ML charge et boucle bot active.
- [ ] **Alertes Telegram utiles** : envoyer seulement les decisions finales importantes, erreurs critiques, drift ML et changement champion/challenger.
- [ ] **Dashboard prediction vs resultat** : tableau par symbole, regime, heure, P_win, P_continue, decision sortie et resultat final.
- [ ] **Audit trail complet** : relier decision entree -> features -> ordre -> position -> decision sortie -> outcome.
- [ ] **Export dataset** : CSV/Parquet pour audit externe et entrainement hors bot.
- [ ] **Sauvegarde DB** : snapshot `aegis_db.sqlite3` avec checkpoint WAL quand tous les processus sont arretes.

Impact attendu : moins de zones floues, diagnostic plus rapide, meilleure confiance avant passage en live reel.

---

## 🔬 Phase 9 : Modeles Avances

Objectif : tester des modeles plus performants que RandomForest sans casser le modele actif.

- [ ] **XGBoost challenger** : comparer contre RandomForest sur les memes splits walk-forward.
- [ ] **Ensembles** : combiner RandomForest + XGBoost + modele simple calibre si l'ensemble reduit les faux positifs.
- [ ] **Calibration probabiliste** : isotonic/logistic calibration pour que `70%` veuille vraiment dire environ 70% de reussite.
- [ ] **Selection de features** : retirer les features inutiles ou bruitees qui degradent le live.
- [ ] **Deep learning prudent** : tester seulement si le dataset devient assez grand et stable; pas de remplacement sans preuve walk-forward.
- [ ] **Modele par regime** : specialiser certains challengers pour bull, range, bear weak, sideways down.

Impact attendu : meilleure qualite de probabilite, moins de trades perdants, mais uniquement si les tests live/OOF battent le champion.

---

## 🔒 Phase 10 : Autonomie Controlee & Gouvernance Risque

Objectif : permettre au bot de s'ameliorer avec ses donnees sans devenir opaque ou dangereux.

- [ ] **Auto-retraining planifie** : reentrainement periodique avec validation obligatoire, sans edition manuelle du code.
- [ ] **Promotion avec garde-fous** : minimum trades, minimum jours, drawdown max, PnL net positif, profit factor minimum.
- [ ] **Mode safe fallback** : repasser au champion stable ou reduire le sizing si drift, erreurs exchange ou pertes consecutives.
- [ ] **Journal de gouvernance** : enregistrer chaque promotion, rollback, changement de seuil et raison.
- [ ] **Limites capital strictes** : perte journaliere, perte hebdo, nombre max de positions, exposition max par crypto.
- [ ] **UI multi-bot** : surveiller plusieurs instances Aegis si besoin, sans melanger les datasets.

Impact attendu : apprentissage autonome, mais sous controle explicite, avec rollback et audit.
