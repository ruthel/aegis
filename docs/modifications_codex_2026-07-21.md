# Modifications Appliquees Par Codex - 2026-07-21

Ce fichier resume les modifications effectuees pendant la session sur le bot Aegis.

## 1. Frais Sur Les Positions Paper Sell

Objectif: verifier puis corriger le fait que les positions `sell` paper ne sauvegardaient pas toujours les frais.

Modifications:

- Ajout d'un calcul centralise des frais dans `core/bot/trading.py`.
- Les ventes paper sauvegardent maintenant:
  - `fee_rate`
  - `buy_fee`
  - `sell_fee`
  - `fee`
  - `fee_currency`
- Les chemins de vente paper couverts incluent:
  - vente marche paper
  - execution d'ordre limite paper
  - verification des ordres paper depuis le bot principal

Fichiers modifies:

- `core/bot/trading.py`
- `core/trading_bot.py`
- `data/paper_bot_state.json`

Note: les frais futurs utilisent `self.trading_fee`, qui est synchronise avec les frais temps reel du bot. Les anciens trades ont ete backfill avec un taux historique de fallback.

## 2. Historique Des Trades: Brut, Net Et Fees

Objectif: afficher clairement le PnL brut, les frais et le PnL net dans Trade History.

Modifications:

- Calcul du PnL brut par trade.
- Calcul des frais par trade.
- Calcul du PnL net par trade.
- Conservation de `pnl` comme alias du net pour compatibilite.
- Mise a jour du tableau Trade History.
- Mise a jour de l'export CSV.
- Resume en bas du tableau avec Brut, Fees et Net.

Fichiers modifies:

- `dashboard/app.py`
- `dashboard/static/dashboard.js`
- `dashboard/templates/index.html`

## 3. Card Live: Croissance / Balance Brut Et Net

Objectif: remplacer la lecture unique du PnL total par une vue brut/net.

Modifications:

- La card `Croissance / Balance` affiche maintenant:
  - PnL brut
  - PnL net
- Le calcul backend expose:
  - `total_pnl_gross`
  - `total_fees`
  - `total_pnl_net`
- La coloration de la card se base sur le net.

Fichiers modifies:

- `dashboard/app.py`
- `dashboard/static/dashboard.js`
- `dashboard/templates/index.html`

## 4. Trailing Stop Plus Reactif

Objectif: reduire la latence observee dans la montee du trailing stop.

Modifications:

- `TrailingStopManager.update_position()` retourne maintenant `True` quand un changement reel a eu lieu.
- Le bot met a jour le trailing stop a chaque tick WebSocket.
- Sauvegarde du state limitee par `TRAILING_STOP_SAVE_INTERVAL_SECONDS` pour eviter trop d'ecritures.
- Correction de la normalisation des symboles dans les ticks live.

Fichiers modifies:

- `utils/risk_manager.py`
- `core/trading_bot.py`

## 5. Protection Breakeven Net Avec Frais

Objectif: eviter les trades qui montent juste assez pour couvrir les frais, puis redescendent et finissent en perte nette.

Modifications:

- Le trailing stop est devenu fee-aware.
- Le fee reel du bot est passe au trailing stop au moment de l'achat.
- Le `fee_rate` est sauvegarde dans `trailing_stops`.
- Le stop net protege est active quand le prix couvre:
  - frais achat
  - frais vente
  - petit profit net minimum
  - petit espace stop/prix
- Le mode resistance ne peut plus retarder la protection minimum des frais.
- La position ouverte existante a recu un `fee_rate` dans `data/paper_bot_state.json`.

Nouveaux parametres:

```env
BREAKEVEN_MIN_NET_PROFIT_PCT=0.02
BREAKEVEN_TRIGGER_BUFFER_PCT=0.0
BREAKEVEN_MIN_STOP_GAP_PCT=0.01
```

Fichiers modifies:

- `.env`
- `config.py`
- `dashboard/app.py`
- `core/trading_bot.py`
- `utils/risk_manager.py`
- `data/paper_bot_state.json`

Tests effectues:

- 30 cas de test manuels sur le trailing fee-aware.
- Resultat: 30 pass, 0 fail.
- Cas couverts:
  - frais normaux
  - frais eleves
  - frais zero
  - resistance active
  - trailing large
  - trailing serre
  - prix qui redescend
  - ancien state sans `fee_rate`
  - breakeven desactive
  - cas ETH proche de la position reelle

## 6. Blocage Des Achats Simultanes

Objectif: verifier si des achats avaient ete executes simultanement au lieu d'etre bloques.

Constat:

- Le `paper_bot_state` etait coherent apres nettoyage.
- Le `decision_journal` contenait des `buy_executed` fantomes ou dupliques.

Modifications:

- Ajout d'une derniere barriere dans `execute_buy()`:
  - re-verification du cooldown juste avant l'achat
  - re-verification de `can_open_position()` juste avant l'achat
- Les achats bloques a cette etape sont journalises avec une raison explicite.
- Les faux achats ont ete supprimes du journal selon la preference utilisateur.
- Les lignes JSONL cassees ont ete nettoyees.

Fichiers modifies:

- `core/trading_bot.py`
- `data/decision_journal.jsonl`

Backups crees:

- `data/decision_journal.jsonl.bak_cleanup_coherence_20260721_104527`
- autres backups de nettoyage precedents dans `data/`

Verification finale:

- Paper positions: 35
- Paper buys: 18
- Paper sells: 17
- Journal `buy_executed`: 18
- `buy_executed` simultanes sous 300s: 0
- `buy_executed` sans position paper: 0
- positions paper sans execution correspondante: 0
- lignes JSONL cassees: 0

## 7. Dashboard: Axe X Du Graphique Des Scores

Objectif: rendre les heures du graphique plus lisibles.

Modifications:

- Rotation des heures a 0 degre.
- Nombre de ticks limite selon la periode.
- Sur 12h/24h: affichage `HH:mm`.
- Sur 3j/7j: affichage `MM-DD HH:mm`.

Fichiers modifies:

- `dashboard/static/dashboard.js`
- `dashboard/templates/index.html`

## 8. Latence De Vente Forcee

Objectif: reduire la sensation de latence au clic sur vente forcee.

Constat:

- Le dashboard ecrit une commande dans `data/bot_commands.json`.
- Le bot execute ensuite la commande lors de sa boucle.
- En paper, la vente forcee faisait un refresh balance inutile avant de vendre.

Modifications:

- En paper trading, la vente forcee evite le refresh balance exchange.
- Les commandes `force_sell` sont prioritaires.
- Le bot relit les commandes plusieurs fois dans la boucle.
- Le dashboard affiche immediatement une confirmation visuelle.
- Le dashboard force des refreshs rapides apres envoi de commande.

Fichiers modifies:

- `core/trading_bot.py`
- `dashboard/static/dashboard.js`
- `dashboard/templates/index.html`

## 9. Menu Trois Points Deplace Sur Les Positions

Objectif: deplacer les actions depuis les crypto cards vers les lignes de positions ouvertes.

Modifications:

- Suppression du menu trois points sur les live crypto cards.
- Ajout d'une colonne action dans la table Positions.
- Ajout du menu trois points directement sur chaque ligne de position.
- Actions disponibles:
  - vendre
  - pause 15 min
  - pause 1 heure
  - pause 4 heures
  - pause 24 heures
- Correction de l'overflow du menu:
  - le menu passe en `position: fixed`
  - il n'est plus coupe par le tableau
  - il reste dans les limites de l'ecran

Fichiers modifies:

- `dashboard/static/dashboard.js`
- `dashboard/static/dashboard.css`
- `dashboard/templates/index.html`

## 10. Validations Techniques

Commandes de validation executees pendant la session:

```powershell
python -m py_compile core\bot\trading.py core\trading_bot.py
python -m py_compile dashboard\app.py
python -m py_compile core\trading_bot.py utils\risk_manager.py
python -m py_compile utils\risk_manager.py core\trading_bot.py dashboard\app.py config.py
node --check dashboard\static\dashboard.js
```

Les validations lancees apres les derniers changements sont passees.

