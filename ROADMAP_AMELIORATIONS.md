# Feuille de Route & État d'Avancement — Améliorations Bot Aegis

Dernière mise à jour : 2026-07-21

---

## 📊 Résumé du Statut Actuel

* **Phase 0 (Assainissement & Frais réels)** :  **Terminé**
* **Phase 1 (ExitEngine & ContinuationScore - Shadow Mode)** :  **Terminé & Actif**
* **Phase 2 (Resserrage Dynamique du Stop)** : ⏳ **Prochaine étape**
* **Phase 3 (Sorties Automatiques TAKE_PROFIT / FORCE_EXIT)** : ⏳ **En attente validation Phase 2**
* **Phase 4 (Backtest & Calibration Fine)** : ⏳ **Planifié**

---

##  Phase 0 : Correctifs Core & Calculs Financiers (COMPLÉTÉ)

- [x] **Gestion des Frais Réels (`Fee-Aware`)** : Calcul centralisé et enregistrement systématique des frais d'achat/vente (`buy_fee`, `sell_fee`, `fee_rate`).
- [x] **Transparence PnL** : Affichage clair **PnL Brut**, **Frais Total** et **PnL Net** dans l'historique des trades et la carte Live.
- [x] **Trailing Stop Réactif & Breakeven Net** : Mise à jour du stop à chaque tick WebSocket. Le Breakeven Net ne s'active que si le prix couvre l'intégralité des frais A/R + mini profit net.
- [x] **Protection Anti-Achats Simultanés** : Verrouillage thread-safe (`Lock`) et vérification ultime avant l'exécution dans `execute_buy()`.
- [x] **Améliorations Ergonomie Dashboard** : Menu d'actions par position ouverte (Vendre, Pause 15m/1h/4h/24h), lisibilité de l'axe X des graphiques.

---

##  Phase 1 : ExitDecisionEngine & ContinuationScore — Mode Shadow (COMPLÉTÉ)

- [x] **Module ExitEngine (`utils/exit_engine.py`)** :
  - Calcul du `ContinuationScore` (0-100) basé sur EMA9/20, VWAP, structure de bougies, volume relatif, RSI et tendance BTC.
  - Moteur de décision : `HOLD`, `PROTECT_BREAKEVEN`, `TIGHTEN_STOP`, `TAKE_PROFIT`, `FORCE_EXIT`.
- [x] **Variables de Configuration (.env & config.py)** :
  - `EXIT_ENGINE_ENABLED=True`
  - `EXIT_ENGINE_SHADOW_MODE=True` (Mode observation sans risque)
  - `PROFIT_FRAGILE_MAX_NET_PCT=0.40`
  - `TIME_STOP_MINUTES=12`
- [x] **Intégration au Bot (`core/trading_bot.py`)** : Évaluation automatique sur chaque tick temps réel et dans la boucle de gestion des positions.
- [x] **Journalisation (`data/decision_journal.jsonl`)** : Enregistrement des recommandations sous `action: exit_decision`.
- [x] **Badge Visuel Dashboard (`dashboard/static/dashboard.js`)** : Affichage du badge de santé (ex: `📊 85/100 (HOLD)` ou `📊 42/100 (TIGHTEN_STOP)`) dans le tableau des positions ouvertes.
- [x] **Validation & Unit Tests (`scratch/test_exit_engine.py`)** : Tests automatisés passés avec succès.

---

## ⏳ Phase 2 : Resserrage Dynamique du Stop-Loss (PROCHAINE ÉTAPE)

- [ ] **Connexion au Trailing Stop** : Si PnL net dans la zone *Profit Fragile* (0.0% à +0.40%) et `ContinuationScore` < 50, resserrer automatiquement le stop au Breakeven Net + mini marge sans vendre au marché.
- [ ] **Lissage du Score** : Appliquer une moyenne glissante du score sur 3 ticks pour éviter les micro-oscillations.
- [ ] **Validation en Paper Trading** : Vérifier que le nombre de trades verts finissant rouges diminue.

---

## ⏳ Phase 3 : Sorties Anticipées Automatiques

- [ ] **Détection de Rejet sous Résistance (`TAKE_PROFIT`)** : Clôturer la position si le PnL net > +0.20% et que des mèches hautes / rejets apparaissent sous résistance.
- [ ] **Time Stop Intelligent (`FORCE_EXIT`)** : Clôturer les positions stagnantes après 12 minutes avec un score faible.
- [ ] **Protection Retournement BTC** : Réaction rapide si le Bitcoin entame une chute brutale sur 5m.

---

## ⏳ Phase 4 : Backtest & Calibration Fine

- [ ] Script de backtest comparatif entre l'ancien système et le nouveau système d'exit.
- [ ] Ajustement fin des paramètres selon les résultats historiques.
