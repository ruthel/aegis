# Feuille de Route & Etat d'Avancement — Ameliorations Bot Aegis

Derniere mise a jour : 2026-07-23

---

## Resume du Statut Actuel

* **Phase 0 (Assainissement & frais reels)** : ✅ **Termine**
* **Phase 1 (Sorties ML / ExitDecisionEngine fusionne)** : ✅ **Termine & actif**
* **Phase 2 (Core ML Engine entree 52 features)** : ✅ **Termine & actif**
* **Phase 3 (Suppression des anciens verrous durs)** : ✅ **Termine**
* **Phase 4 (Dataset live & apprentissage controle)** : ✅ **Termine**
* **Phase 5 (Walk-forward, champion/challenger, calibration PnL)** : ⏳ **Planifie**

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

- [x] **Decisions de sortie actives** : `HOLD`, `PROTECT_BREAKEVEN`, `TIGHTEN_STOP`, `TAKE_PROFIT`, `FORCE_EXIT`.
- [x] **ContinuationScore** : score de sante du mouvement base sur momentum, EMA, VWAP, structure bougies, volume, RSI et contexte BTC.
- [x] **Mode profit fragile** : protection des petits gains quand le mouvement devient faible.
- [x] **Time stop intelligent** : sortie/protection si la position stagne trop longtemps avec score faible.
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
| Decision sortie | moteur ML de gestion de position actif |

### Resultats de reference apres fusion entree + sortie ML

| Scenario | Trades | Win rate | PnL backtest |
|----------|--------|----------|--------------|
| Baseline ancienne logique | 2941 | 62.5% | +2055.45% |
| Memes entrees + sorties ML | 2941 | 58.3% | +2351.17% |
| Entrees filtrees ML + sorties ML | 892 | 82.2% | +1438.60% |

Lecture : le systeme retenu fait moins de trades, mais avec une qualite moyenne nettement superieure. La moyenne estimee est d'environ **4.4 trades/jour** sur le dataset teste.

- [x] **Mode ML actif par defaut** : les toggles `ML_FILTER_ENABLED`, `ML_SHADOW_MODE`, `ML_EXIT_ENTRY_FILTER_ENABLED` et `ML_OWNS_ENTRY_FILTERS` ont ete retires.
- [x] **Modele entree** : RandomForest, 52 features, seuil P_win 65%.
- [x] **Modele sortie** : 37 features, gestion active des positions.
- [x] **Support Touch** : conserve uniquement comme source statistique ML, plus comme fast-path.
- [x] **Falling knife / bear context / HTF / timing** : conserves comme features ML quand utiles, plus comme blocages durs redondants.

---

## ✅ Phase 3 : Assainissement des Anciens Verrous Durs

- [x] Suppression du fast-path Support Touch et des verdicts `allowed/blocked` durs.
- [x] Suppression des blocages durs avant ML sur contexte bear et falling knife, remplaces par features ML.
- [x] Suppression des logs intermediaires `htf_filter`, `support_touch_override`, `ml_feature_only` et equivalents.
- [x] Nettoyage dashboard : retrait des badges "Feature ML", correction du rendu Decision Log et Contexte d'entree.
- [x] Radar prochain achat : remplacement des ETA hasardeux par l'etat ML reel (`Pret ML maintenant` / `En attente ML`) et les raisons (`P_win`, continuation, seuils).
- [x] Telegram : intervalle de status augmente a 2h via `TELEGRAM_STATUS_INTERVAL=7200`.

---

## ✅ Phase 4 : Amelioration ML Prioritaire — Dataset Live

Le prochain vrai gain n'est pas d'ajouter un nouveau verrou. Il faut enrichir ce que le ML apprend du trading reel.

- [x] **Journal live complet des entrees** : sauvegarder exactement les 52 features vues au moment ou le bot accepte ou refuse une entree dans `data/aegis_db.sqlite3`.
- [x] **SQLite WAL structure** : base locale avec `journal_mode=WAL`, `busy_timeout=5000`, convention `{domain}_{entity_plural}` et tables relationnelles ML, Telegram et bot.
- [x] **Documentation WAL/SHM** : `README.md` explique le role de `aegis_db.sqlite3`, `aegis_db.sqlite3-wal`, `aegis_db.sqlite3-shm`, et le moment ou le WAL est fusionne dans la base principale.
- [x] **Telegram dans `aegis_db`** : messages entrants/sortants stockes dans la table `telegram_messages`; les anciens fichiers JSON Telegram ont ete retires.
- [x] **Process dashboard/bot dans `aegis_db`** : les anciens `data/bot_process.json`, `data/bot.pid` et `bot_process_state` sont remplaces par la table `bot_processes`.
- [x] **Bot state relationnel dans `aegis_db`** : `bot_state` garde uniquement les lignes de mode trading (`paper`, `live`); positions, ordres, trailing stops, cooldowns et recommandations de sortie ont leurs tables dediees.
- [x] **Etat app separe** : `bot_app_state` garde les valeurs applicatives persistantes comme `telegram_last_status_time`, sans polluer `bot_state` avec des colonnes NULL.
- [x] **Audit timestamps global** : toutes les tables applicatives ont `created_at` et `updated_at`; `last_update` n'est plus stocke comme ligne separee dans `bot_state`.
- [x] **Features ML relationnelles** : les 52 features d'entree et les features de sortie sont sauvegardees dans `ml_entry_feature_values` et `ml_exit_feature_values`.
- [x] **Contexte/predictions normalises** : `bot_market_context` expose regime, bear mode et signaux cles; `ml_live_predictions` expose `p_win`, `p_continue` et la prevision de sortie.
- [x] **Support Touch dans `aegis_db`** : backtests stockes dans une table unique `support_touch_results`.
- [x] **Metadata ML dans `aegis_db`** : snapshots de modele stockes dans `ml_model_metadata` et importances dans `ml_feature_importances`.
- [x] **Lien entree acceptee -> sortie reelle** : stocker l'entree ouverte dans la table SQLite `ml_open_entries`, puis fermer le sample au moment de la vente.
- [x] **Runtime JSON supprime** : decisions dashboard, commandes bot, statut live WebSocket, scores crypto et entrees ML ouvertes sont lus/ecrits dans `data/aegis_db.sqlite3`.
- [x] **Stats journalieres dans `aegis_db`** : les statistiques de risque journalieres sont stockees dans la table `bot_daily_stats`.
- [x] **Journal live des decisions de sortie** : sauvegarder les 37 features de sortie, la decision ML et l'etat courant (`HOLD`, `PROTECT_BREAKEVEN`, `TIGHTEN_STOP`, `TAKE_PROFIT`, `FORCE_EXIT`).
- [x] **Resultat final des trades** : enregistrer prix d'achat, prix de vente, PnL, PnL %, duree et raison de sortie quand le trade ferme.
- [x] **Candidats refuses conserves** : enregistrer les refus ML comme `candidate_rejected_pending_replay` pour analyse future.
- [x] **Labelliser les candidats refuses** : `scripts/analyze_ml_live_performance.py` cree `ml_rejected_replay_results` et rejoue les refus des que les bougies futures sont disponibles.
- [x] **Comparer prediction vs resultat reel** : calibration par buckets `P_win` dans `ml_prediction_calibration`, avec Brier score, win rate live et PnL moyen dans `ml_analysis_runs`.
- [x] **Detection de drift marche** : `ml_drift_alerts` signale `ok`, `warning` ou `insufficient_live_outcomes` selon les resultats live disponibles.
- [x] **Automatisation periodique** : `run_ml_live_analysis_if_due()` lance `scripts/analyze_ml_live_performance.py` en arriere-plan selon `ML_LIVE_ANALYSIS_INTERVAL_SECONDS`.

---

## ⏳ Phase 5 : Walk-Forward & Promotion Controlee des Modeles

- [ ] **Walk-forward validation** : entrainer sur une periode, tester sur la periode suivante, puis avancer la fenetre.
- [ ] **Champion / challenger** : ne remplacer le modele actif que si le challenger bat le champion sur win rate, PnL net, profit factor et drawdown.
- [ ] **Objectif PnL net** : optimiser le modele sur PnL net et drawdown, pas seulement sur accuracy/win rate.
- [ ] **Calibration des seuils** : recalibrer `P_win`, `P_continue`, time stop et force exit selon les resultats live.
- [ ] **Position sizing ML** : faire apprendre au modele quand reduire ou augmenter la taille de position selon la qualite du setup.

---

## Idees Futures

- [ ] Re-entrainement periodique controle, avec validation obligatoire avant promotion.
- [ ] Tableau dashboard "Prediction vs resultat" par symbole, regime, heure et type de sortie.
- [ ] Alertes Telegram uniquement pour decisions finales importantes ou drift ML.
- [ ] Export CSV/Parquet du dataset live pour audit externe.
- [ ] Dashboard multi-bot si plusieurs instances Aegis tournent en parallele.
