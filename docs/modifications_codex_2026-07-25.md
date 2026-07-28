# Modifications Codex — 2026-07-25

## 1. UI React/Vite finalise

**Objectif :** remplacer progressivement le ui HTML legacy par une SPA React servie par Flask.

**Modifications :**
- Ajout du frontend `ui/frontend` en React + Vite + TypeScript.
- Gestionnaire de paquets : `pnpm`.
- Client REST : `axios`.
- Etat global : `zustand`.
- Composants interactifs : shadcn/Radix, notamment les dropdowns `Select`.
- Icones : `lucide-react`.
- Charts : amCharts 5.
- Police principale : Outfit.
- Flask sert `ui/static/spa/index.html` quand le build SPA existe, avec fallback legacy sinon.

## 2. Sections ui reproduites depuis le HTML legacy

**Sections retravaillees :**
- Core ML Engine.
- Contexte d'entree.
- Decisions.
- Marche Live.
- Cooldowns.
- Positions.
- Alertes.
- Console.
- Analytics.

**Details UI :**
- `Marche Live` affiche les valeurs WebSocket reelles (`price`, `bid`, `ask`, `candle_high`, `volume_24h`, `spread_percent`, `price_change_since_analysis_percent`).
- Le champ volume de `Marche Live` est affiche en USD : l'UI utilise `volume_usd`/`quote_volume` si disponible, sinon calcule `volume base * prix live`.
- Les symboles `BTC/USD` cote UI sont mappes avec les cles compactes `BTCUSD` venant du live status.
- Les pourcentages live sont limites a 2 decimales; le momentum est abrege en `Mom.`.
- `Contexte d'entree` lit correctement `support_touch.pairs[]` au lieu de chercher directement `support_touch["BTC/USD"]`.
- Les regimes sont abreges : `SIDEWAYS` -> `SIDE`, `SIDEWAYS DOWN` -> `SIDE. DO.`, `SIDEWAYS UP` -> `SIDE. UP`.
- Les timers cooldown utilisent un format lisible (`4 min 7 s`) et ne sont plus en uppercase.
- Les dropdowns ont maintenant un fond opaque via les tokens `popover`.
- La page `/trades` affiche aussi les positions ouvertes avec badge `OPEN`; les positions non vendues affichent `En cours` au lieu d'un PnL ferme.

## 3. Analytics — Historique des scores crypto

**Objectif :** reprendre le comportement de l'ancien HTML.

**Modifications :**
- Ajout d'un graphique amCharts dedie `ScoreHistoryChart`.
- Filtres shadcn : symbole (`BTC/USD`, `ETH/USD`, `SOL/USD`, `ADA/USD`) et periode (`12 heures`, `24 heures`, `3 jours`, `7 jours`).
- Appel reel a `/api/analytics/scores?symbol=...&hours=...`.
- Tooltip avec les memes champs que le legacy : score et prix.
- Remplacement de l'axe categorie par un vrai `DateAxis` pour eviter les labels X trop nombreux ou incomplets.
- Stabilisation du graphique avec `useMemo` et `memo` pour eviter le clignotement pendant les updates live.

## 4. Decision log recentre

**Objectif :** ne garder dans les decisions que les decisions finales utiles.

**Modifications :**
- Les cooldowns operationnels ne sont plus enregistres dans `bot_decision_journal`.
- `symbol_cooldown_active` et `symbol_cooldown_active_at_execution` sont filtres cote ui pour masquer les anciennes lignes deja en base.
- `set_symbol_cooldown()` ne cree plus de decision.
- Les cooldowns restent visibles dans la section dediee `Cooldowns`.

## 5. Nettoyage des tables de decisions

Purge ponctuelle effectuee apres changement de semantics :

- `bot_decision_metrics`
- `bot_decision_journal`
- `ml_entry_decisions`
- `ml_exit_decisions`
- `ml_entry_feature_values`
- `ml_rejected_replay_results`
- `ml_raw_events`
- `ml_prediction_calibration`

Ces suppressions repartent d'un journal propre sans effacer l'etat trading, les cooldowns, positions, metadata ML ou features importantes conservees ailleurs.

## 6. Logs runtime moins bruyants

**Modifications :**
- Suppression du log informatif de sizing :
  `💰 Trade: ... USD -> ... crypto (frais: ...)`
- Filtrage des logs WebSocket redondants :
  - `WS erreur: ping/pong timed out`
  - `ERROR - ping/pong timed out - goodbye`
- Conservation du log utile de reconnexion quand la deconnexion dure.

## 7. Verification

Commandes de verification utilisees :

```bash
pnpm build
python -m py_compile core/trading_bot.py ui/app.py
python -m py_compile core/websocket.py utils/position_manager.py
```

## 8. Mise a jour 2026-07-27 — Sorties ML-only

**Objectif :** retirer les regles de sortie devenues facultatives depuis que le ML possede l'entree et la sortie.

**Modifications :**
- `ExitDecisionEngine` ne produit plus de decision de sortie par regles. Il calcule les metriques utiles (`continuation_score`, PnL net/brut, duree) et relaie uniquement la decision ML.
- Les anciennes actions live `PROTECT_BREAKEVEN`, `TIGHTEN_STOP` et `TAKE_PROFIT` ne sont plus appliquees comme gestion automatique.
- Le modele de sortie live applique une action binaire : `HOLD` ou `FORCE_EXIT`.
- Quand `ML_OWNS_EXITS=true`, les trailing stops, stops durs et ordres objectifs paper ne vendent plus automatiquement.
- Les ordres objectifs restaurés sont conserves comme references UI avec la source `ml_exit_target_reference`.
