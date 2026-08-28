# Session Aegis — Résumé de reprise (handoff)

> Document de passation pour reprendre le travail sur un autre PC (plus puissant).
> Projet : bot de trading crypto Aegis (Python, Kraken live, UI React/Flask).
> Racine projet : `c:\Users\baloc\Projects\aegis`

---

## 1. Objectif global

Améliorer le bot vers un système **100% autonome** (roadmap phases 12-16).
Philosophie utilisateur : **améliorer petit à petit, incrémental**, valider chaque étape.

---

## 2. Contexte technique clé

- **Timeframe de trade principal : 15m** (`MAIN_TIMEFRAME`, défaut `15m`). Le ML décide aussi sur le 15m, mais consomme 5 timeframes en features (5m, 15m, 1h, 4h, 1d).
- **Exchange live : Kraken.** Frais réels = **0.4% taker** (`TRADING_FEE_PERCENT=0.4`).
- **Données d'entraînement : Coinbase** (paires USD réelles, pagination fiable).
  - Kraken OHLC public = limité ~720 bougies → inutilisable pour l'historique long.
  - Coinbase **ne supporte pas** `4h` en direct → le 4h est **agrégé depuis le 1h** (4 bougies 1h = 1 bougie 4h) via `aggregate_ohlcv`.
  - Coinbase donne bien **3 ans** en 15m ET en 5m (vérifié : ~105k bougies 15m, ~315k bougies 5m).
  - Rate limit Coinbase public : **3 req/s soutenu, 6 en burst** (par IP).
- **Modèles ML (RandomForest)** dans `core/ml_engine.py` :
  - Modèle d'ENTRÉE (P_win) : **78 features** (était 72, voir §4).
  - Modèle de SORTIE (P_exit) : 37 features — classifieur "continuer ou sortir ?".
  - Modèle de SIZING : régresseur, réutilise les features d'entrée.
  - Modèle P_TARGET : régresseur (NOUVEAU, voir §5).
- **Gate d'achat live** : `if ml_win_prob < 50.0: return` (50-65% = NEUTRAL achète quand même ; >=65% = HIGH_CONFIDENCE). L'utilisateur a choisi de **laisser le gate à 50%**.
- **Base de données** : `data/aegis_db.sqlite3`.

### Commandes utiles
- Training : `python scripts/train_and_evaluate_ml_model.py --dir data --db data/aegis_db.sqlite3 --trigger manual`
- Promotion sans réentraîner : `python scripts/promote_challenger.py` (options `--check-only`, `--force`)
- Build UI : `cmd /c "pnpm run build"` dans `ui/app` (pnpm bloqué par PS execution policy → utiliser `cmd /c`)
- Vérif parse : écrire un script temporaire `.py` (PowerShell mange les `python -c` inline).
- **IMPORTANT** : le terminal PowerShell de CETTE machine a un bug d'affichage (echo char-par-char, stdout souvent non capturé). Contournement : rediriger la sortie python vers un fichier `.json`/`.txt` puis le lire.

---

## 3. Historique du modèle : passage à 3 ans de données

- **Avant** : entraînement sur 1 an → modèle "mono-régime", trop prudent, hésite à acheter en marché haussier.
- **Décision** : passer à **3 ans** (`ML_TRAINING_HISTORY_DAYS=1095`) pour couvrir bear 2023-2024 + remontée + régime actuel.
- Dataset passé de ~5215 à **15346 samples**, win rate dataset ~50.2%.
- Le modèle 3-ans (72 features) a été **promu manuellement** via `promote_challenger.py` (le garde-fou `better_perf` le refusait car comparaison inéquitable 1-an vs 3-ans).
- Seuils de promotion assouplis dans `.env.local` : `ML_PROMOTION_MIN_PRECISION_DELTA=-3.0`, `ML_PROMOTION_MIN_ACCURACY_DELTA=-4.0`.
  - **À RESSERRER** plus tard (ex: -1.0/-1.5) une fois la base 3-ans stable, pour que l'auto-retraining reste exigeant.

---

## 4. Diagnostic hésitation du bot + enrichissement features (FAIT, à réentraîner)

### Diagnostic (analyse d'importance des features du champion)
Répartition du poids par timeframe du modèle 72-features :
| Timeframe | Poids total |
|-----------|-------------|
| 1h | **50.5%** (ema50_slope_1h 23.7% + ema20_slope_1h 20.3%) |
| 4h | 13.4% |
| 15m rebond | 13.1% (dont previous_drop_pct 8.9%) |
| context/bot | 9.9% |
| 15m base | 8.2% |
| 1d | 2.3% |
| **5m** | **1.3%** (quasi ignoré) |
| multi_tf | 1.2% |

**Cause de l'hésitation** : le modèle s'appuie à ~64% sur les tendances LENTES (1h/4h) qui réagissent en retard. Il ignore les signaux rapides (5m/15m) qui détecteraient un début de hausse. Biais de régime : entraîné majoritairement sur du bear → a appris à se méfier des rebonds (features `reversal_confirmed`, `falling_knife_active` à 0% d'importance).

### Correction appliquée dans `core/ml_engine.py` (FAIT, validé runtime, PAS ENCORE réentraîné)
Le modèle passe de **72 → 78 features** :
- **RETIRÉ (4 features, importance 0%, params de trade inutiles pour l'entrée)** :
  `fee_rate_bps`, `position_value_usd`, `position_value_pct_balance`, `planned_hold_minutes` (gardé `planned_exit_hour`).
- **AJOUTÉ (10 features rapides, en FIN de schéma pour compat)** :
  - Groupe A (cassure 15m) : `ema20_breakout_15m`, `ema9_cross_ema20_15m`, `breakout_high_20b`, `price_vs_vwap_pct`
  - Groupe B (momentum 5m) : `ema9_cross_ema20_5m`, `momentum_accel_5m`, `volume_surge_5m`, `consecutive_green_5m`
  - Groupe C (confirmation court terme) : `short_tf_alignment`, `rsi_rising_5m_15m`
- `feature_names`, `sizing_feature_names`, `target_feature_names` = 78 (auto-sync).
- Vérifié : `extract_features_from_klines` retourne bien 78 dans tous les cas (full / sans 5m / 15m seul), fallbacks OK.
- **NOTE** : ne PAS retirer `reversal_confirmed` / `falling_knife_active` malgré 0% — utiles en régime haussier, on veut qu'elles remontent.
- Note conceptuelle importante : on ne peut PAS fixer les poids à la main sur un RandomForest. On change les DONNÉES/features et le modèle recalcule les poids. Le gain n'est PAS garanti (à valider par réentraînement).

---

## 5. P_target (take-profit intelligent) — FAIT (code), PAS ENCORE réentraîné

Objectif : capturer les gains avant qu'ils s'évaporent (répond au problème "+3% qui redevient +0.5%").
Distinction P_exit vs P_target :
- **P_exit** = classifieur, réactif, "ça continue ou pas ?" (existant).
- **P_target** = régresseur, "quel gain max réaliste viser ?" fixé à l'entrée → pose un take-profit. NOUVEAU, complémentaire.

### Implémentation
- `core/ml_engine.py` : ajout `target_model`/`target_scaler`, `is_target_trained`, `target_feature_names`, `_target_model_feature_count`, `_align_target_features_for_loaded_model`, `train_target_model` (RandomForestRegressor), `predict_target` (clampé `ML_TARGET_MIN_PCT=0.8` / `ML_TARGET_MAX_PCT=12.0`). Sauvegarde/chargement dans le joblib + metadata.
- `scripts/train_and_evaluate_ml_model.py` : label P_target = **max favorable excursion** (plus haut atteint entre entrée et sortie, net de frais, borné >=0). Collecté dans `target_labels`, entraîné via `train_target_model`.
- `core/trading_bot.py` : au buy, `predict_target(features=ml_entry_features)` → stocke `ml_target_gain_pct` / `ml_target_price` sur position_data. Nouveau `_check_take_profit_target()` appelé dans `_update_trailing_stop_from_tick` AVANT le breakeven lock (priorité). Vend si gain net >= cible. Gate `ML_TAKE_PROFIT_ENABLED=true`.
- `core/managers/execution_manager.py` : persiste `ml_target_gain_pct`/`ml_target_price` dans state['positions'] + passe à `add_position`.
- `utils/risk_manager.py` : `add_position` accepte/stocke `target_gain_pct`.
- Rehydratation (`_rehydrate_open_positions_for_exit_evaluation`) : relit `ml_target_gain_pct` depuis state['positions'].
- **P_exit reste intact comme filet de sécurité.** Breakeven + stop loss inchangés.
- Validé runtime (train→save→load→predict OK sur données synthétiques).

---

## 6. Cache incrémental OHLCV — FAIT

Dans `scripts/train_and_evaluate_ml_model.py` :
- `_cache_path`, `_load_cache`, `_save_cache` (gzip JSON, **stdlib, zéro dépendance** — pandas/pyarrow NON installés).
- Fichiers : `data/ohlcv_cache/SYMBOL-TF.json.gz` (data/ déjà gitignore).
- `fetch_symbol_history_2026` refactoré : charge cache → fetch seulement le DELTA (depuis last_cached+1) → merge/dedup → purge < fenêtre 3 ans → save.
- 1er run : long (télécharge tout). Runs suivants : quasi instantané (delta only).
- Env : `ML_OHLCV_CACHE_ENABLED=true`, `ML_OHLCV_CACHE_DIR=data/ohlcv_cache`.
- Validé : round-trip save/load OK.

---

## 7. Fetch parallèle par batches — FAIT (réappliqué)

Dans `scripts/train_and_evaluate_ml_model.py` :
- `_fetch_ohlcv_range` : calcule TOUTES les fenêtres `since` à l'avance, puis lance **5 appels en parallèle par batch** (ThreadPoolExecutor).
- `_fetch_one_window` : fetch d'une fenêtre unique avec retry/backoff.
- Pacing : garantit <= 6 req/s (limite Coinbase burst). Env `ML_FETCH_CONCURRENCY=5`.
- Barre de progression en direct (env `ML_FETCH_PROGRESS=true`), se met à jour sur la même ligne (`\r`).
- Validé : test réel 7 jours BTC 15m = 672 bougies, triées, sans doublon, sans trou (gap max = 15min). Gain ~2-3x sur fetch complet.
- **ATTENTION** : cet edit avait été perdu une fois (le fichier était revenu à la version séquentielle). Réappliqué. VÉRIFIER sa présence (`_fetch_one_window`, `ThreadPoolExecutor` dans `_fetch_ohlcv_range`) avant de réentraîner.

### Barre de progression sur la GÉNÉRATION des samples — FAIT
- Dans la boucle de génération (`train_challenger_model`), affichage `🧪 SYMBOL génération [bar] X% — N samples` mis à jour sur la même ligne tous les 500 index.
- Même env `ML_FETCH_PROGRESS=true`. Une barre par symbole, terminée à 100%.
- Objectif : ne plus avoir le "temps mort silencieux" pendant la génération.

---

## 8. Optimisation génération des samples (lookup curseur) — FAIT

**Problème** : dans la boucle de génération (`train_challenger_model`, ~ligne 693), les lookups multi-TF re-scannaient TOUTE la liste à chaque itération :
`[k for k in klines_5m_full if k['timestamp'] <= candle_ts][-30:]` → 315k bougies × 105k itérations = ~33 milliards d'ops (5m seul). C'était le vrai "temps mort silencieux après le fetch".

**Correction** : `_advance_cursor(klines_full, cursor, candle_ts)` — curseur monotone O(1) amorti (candle_ts ne fait qu'augmenter). Remplace les 4 lookups O(n). Curseurs `cur_5m/cur_1h/cur_4h/cur_1d` init avant la boucle.
- Validé : résultat **strictement identique** à l'ancienne méthode (400 lookups, 0 diff).
- Gain effectif **dès le 1er run** (c'est un meilleur algo, pas un cache).
- Gain réel estimé sur la génération : **~3x à 10x** (le lookup était dominant, mais detect_trade_signal/extract_features/simulate_trade restent inchangés).

**Optimisation suivante possible (PAS FAITE, risquée)** : `history = klines_15m[:index]` copie jusqu'à 105k éléments à chaque itération. Passer un index plutôt qu'une copie — nécessite de vérifier comment `detect_trade_signal` et `build_training_bot_context` utilisent `history`.

---

## 9. Autres correctifs UI (FAIT)

Dans `ui/server.py` :
- **`total_samples` codé en dur (2952) → vraie valeur** lue depuis le joblib via `model_train_samples()` (retourne 15346).
- **Sizing par carte : bug ADA** — l'UI ne remontait que les 12 dernières recos globales, monopolisées par BTC → ADA absent. Corrigé via `get_latest_sizing_recommendation_per_symbol` (dans `core/ml_live_logger.py`) + `latest_sizing_by_symbol` (dans server.py) : une reco par symbole garantie. Validé : les 4 paires remontent.
- **ATTENTION restant** : le bloc `analytics` de `ml_status_payload` contient encore des valeurs CODÉES EN DUR trompeuses (precision 67.1%, profit_factor 3.13, cum_pnl 2049.9, winrates par jour...). NON corrigé (hors scope demandé). À traiter si ces chiffres s'affichent sur le dashboard.
- Redémarrer le serveur UI pour prendre en compte ces changements.

---

## 10. Gestion des backups (FAIT)

Dans `scripts/promote_challenger.py` ET `scripts/train_and_evaluate_ml_model.py` :
- `_prune_model_backups(backups_dir, keep=10)` : ne garde que les 10 archives les plus récentes dans `data/backups/`.
- Après création de l'archive horodatée dans `data/backups/`, le `data/aegis_model_backup.joblib` (redondant dans data/) est **supprimé**.
- Validé (13 backups → 10).
- Le `data/aegis_model_backup.joblib` existant sera supprimé automatiquement à la prochaine promotion.

---

## 11. Variables d'environnement ajoutées (`.env.local`)

```
ML_TRAINING_HISTORY_DAYS=1095          # 3 ans
ML_TRAINING_MAX_CANDLES=330000         # plafond (permet 5m sur 3 ans)
ML_PROMOTION_MIN_PRECISION_DELTA=-3.0  # tolérance promotion (à resserrer plus tard)
ML_PROMOTION_MIN_ACCURACY_DELTA=-4.0
ML_TAKE_PROFIT_ENABLED=true            # P_target take-profit
ML_TARGET_MIN_PCT=0.8
ML_TARGET_MAX_PCT=12.0
ML_OHLCV_CACHE_ENABLED=true            # cache incrémental
ML_OHLCV_CACHE_DIR=data/ohlcv_cache
ML_FETCH_CONCURRENCY=5                 # appels parallèles par batch (max 6)
ML_FETCH_PROGRESS=true                 # barre de progression fetch
```

Déjà présent avant : `ML_AUTO_RETRAIN_ENABLED=true`, `ML_AUTO_RETRAIN_INTERVAL_SECONDS=1209600` (14j), `ML_AUTO_RETRAIN_CHECK_ONLY=false`.

---

## 12. requirements.txt — mis à jour (FAIT)

Ajout des dépendances CRITIQUES manquantes : **`scikit-learn>=1.9.0` et `joblib>=1.5.3`** (le cœur ML était absent du requirements !). Plus versions à jour de ccxt, Flask, SQLAlchemy, etc. NON inclus : torch/nltk/google-api/httpx (transitives ou non importées directement dans le code).

---

## 13. PROCHAINE ÉTAPE IMMÉDIATE (à faire sur le PC puissant)

0. **VÉRIFIER D'ABORD que tous les edits sont présents** (un edit a déjà été perdu une fois — le fetch parallèle). Grep rapide à faire dans `scripts/train_and_evaluate_ml_model.py` : `_fetch_one_window`, `_advance_cursor`, `_prune_model_backups`, `train_target_model`, barre `🧪 génération`. Dans `core/ml_engine.py` : les 10 features (`ema20_breakout_15m`, `short_tf_alignment`, `volume_surge_5m`...), `train_target_model`, `predict_target`. Si git ne montre pas ces fichiers comme modifiés alors qu'ils devraient l'être, investiguer (les modifs de session ne sont PAS committées — penser à commit/push depuis la machine d'origine OU copier le dossier).

1. **RÉENTRAÎNER** — c'est le run qui active TOUT (78 features + P_target) d'un coup :
   ```
   python scripts/train_and_evaluate_ml_model.py --dir data --db data/aegis_db.sqlite3 --trigger manual
   ```
   - Le cache OHLCV déjà partiellement créé sera réutilisé (delta only pour ce qui existe).
   - La génération des samples sera BEAUCOUP plus rapide (fix curseur).
   - **La promotion sera probablement REFUSÉE** par le garde-fou `better_perf` (normal : 78 features vs champion 72 features, comparaison inéquitable). → promouvoir manuellement avec `promote_challenger.py` si le modèle est bon.

2. **Vérifier dans la sortie** :
   - `Features entrée: 78` sur le Challenger
   - `Modèle P_target entraîné (gain cible moyen: X%, médian: Y%)`
   - Nombre de samples du dataset

3. **Analyser la nouvelle importance des features** : est-ce que les features rapides (`ema20_breakout_15m`, `short_tf_alignment`, `volume_surge_5m`, etc.) prennent du poids ? Si oui → le bot devrait moins hésiter. C'est le VRAI test de l'hypothèse.

4. **Valider en live** quelques jours avant de conclure (le win rate réel est le juge, pas la precision test).

---

## 14. PISTES FUTURES (discutées, NON commencées)

- **Resserrer les seuils de promotion** une fois la base 3-ans/78-features stable.
- **Affichage P_target sur la vue web** (backend + carte position). Le champion doit d'abord avoir un modèle P_target (réentraîner).
- **Corriger le bloc analytics codé en dur** dans `ml_status_payload` (`ui/server.py`).
- **Parallélisation par PROCESSUS** de la génération (ProcessPoolExecutor, ~4x) — SEULEMENT si après le fix curseur c'est encore trop lent. Multiprocessing Windows délicat (réimport module, `__main__`, pickle).
- **Optimiser `history = klines_15m[:index]`** (copie coûteuse) — vérifier usages avant.
- **Chronomètre par symbole** dans le training pour mesurer le gain réel.
- **Phase 16 étape 2 = Reinforcement Learning** (agent DQN/PPO, reward shaping, self-play). Lourd et risqué, à ne considérer qu'après stabilisation de l'étape 1.
- **XGBoost** en remplacement du RandomForest (gain précision possible, mais mêmes données = même biais de régime ; corriger le biais d'abord).

---

## 15. Fichiers principaux modifiés cette session

- `core/ml_engine.py` — features 72→78, P_target (train/predict/save/load).
- `scripts/train_and_evaluate_ml_model.py` — 3 ans, cache incrémental, fetch parallèle, retry robuste, label+train P_target, lookup curseur, prune backups.
- `scripts/promote_challenger.py` — NOUVEAU (promotion sans réentraîner) + prune backups.
- `core/trading_bot.py` — predict_target au buy + `_check_take_profit_target` + rehydratation cible.
- `core/managers/execution_manager.py` — persistance cible P_target.
- `utils/risk_manager.py` — `add_position` accepte `target_gain_pct`.
- `core/ml_live_logger.py` — `get_latest_sizing_recommendation_per_symbol`.
- `ui/server.py` — vrai total_samples + sizing par symbole.
- `.env.local` — nouvelles variables (voir §11).
- `requirements.txt` — scikit-learn, joblib + versions à jour.
- `ROADMAP_AMELIORATIONS.md` — Phase 16 étape 1 mise à jour (auto-retrain + augmentation dataset cochées).
