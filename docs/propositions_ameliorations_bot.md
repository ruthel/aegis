# Propositions D'Amelioration Du Bot Aegis

Ce fichier regroupe les ameliorations proposees pour mieux detecter si un mouvement a des chances de continuer ou de se retourner.

Important: le bot ne peut pas savoir avec certitude si le prix va monter ou descendre. L'objectif est de mesurer des probabilites et d'adapter la gestion du risque.

## 1. Ajouter Un ExitDecisionEngine

Objectif: separer la logique d'entree et la logique de gestion apres achat.

Aujourd'hui, le bot detecte une entree puis laisse surtout le trailing stop gerer la sortie. Une meilleure architecture serait:

```text
Signal d'achat -> position ouverte -> ExitDecisionEngine -> decision de gestion
```

Decisions possibles:

```text
HOLD
PROTECT_BREAKEVEN
TIGHTEN_STOP
TAKE_PROFIT
FORCE_EXIT
```

Exemples:

```text
HOLD: momentum fort, BTC positif, prix au-dessus VWAP
TIGHTEN_STOP: PnL net positif mais momentum faible
TAKE_PROFIT: rejet clair proche resistance
FORCE_EXIT: retournement BTC + score continuation tres faible
```

Impact attendu:

- moins de trades verts qui finissent rouges
- sorties plus lisibles
- decision log plus explicite
- risque de sorties trop rapides si les seuils sont trop agressifs

## 2. Ajouter Un ContinuationScore

Objectif: calculer apres achat si le mouvement reste sain.

Score propose: 0 a 100.

Facteurs positifs:

- prix au-dessus EMA 9 ou EMA courte
- prix au-dessus VWAP
- higher lows sur les dernieres bougies
- volume relatif en hausse
- BTC positif sur 5m/15m
- score crypto stable ou en hausse
- spread stable

Facteurs negatifs:

- cassure sous EMA courte
- volume qui baisse pendant la montee
- longues meches hautes
- rejet sous resistance
- BTC qui se retourne
- RSI qui plafonne puis baisse
- prix qui stagne trop longtemps

Interpretation possible:

```text
score >= 75: laisser courir
score 55-75: trailing normal
score 35-55: serrer le stop
score < 35: sortir si PnL net positif ou proteger agressivement
```

Impact attendu:

- meilleure distinction entre un vrai mouvement et un simple rebond
- moins de sorties au hasard
- meilleure protection des petits gains

Risque:

- un mauvais scoring peut couper des trades qui seraient repartis.

## 3. Mode Profit Fragile

Objectif: gerer les trades qui sont legerement verts mais pas encore solides.

Zone proposee:

```text
0% <= PnL net <= 0.40%
```

Regles possibles:

```text
si continuation_score fort:
    HOLD
si continuation_score moyen:
    stop >= breakeven net + mini marge
si continuation_score faible:
    stop tres serre
si rejet resistance:
    TAKE_PROFIT
```

Cas typique:

```text
Achat ETH: 1923.45
Prix monte: 1930.00
PnL net: +0.12%
Score continuation: 38
```

Sans amelioration:

```text
le bot attend, le prix redescend, trade fini rouge net
```

Avec amelioration:

```text
le bot protege ou sort, trade fini flat ou petit vert
```

Impact attendu:

- reduire la frustration des petits gains perdus
- augmenter le win rate net
- reduire les pertes dues aux frais

Risque:

- couper trop tot certains trades qui auraient finalement monte.

## 4. Stop Dynamique Selon La Qualite Du Mouvement

Objectif: remplacer un trailing trop fixe par un trailing adapte.

Exemple:

```text
score >= 75:
    trailing = 0.8% a 1.0%
score 55-75:
    trailing = 0.5%
score 35-55:
    trailing = 0.25%
score < 35:
    trailing = 0.10% ou sortie
```

Impact attendu:

- laisser respirer les bons mouvements
- proteger vite les mouvements faibles
- ameliorer le ratio gain/perte

Risque:

- trop de changements de stop si le score varie trop souvent.

Mitigation:

- lisser le score sur plusieurs ticks ou bougies
- imposer un cooldown entre deux changements de trailing

## 5. Detection De Rejet Resistance

Objectif: detecter quand le prix echoue sous une resistance.

Signaux:

- longue meche haute
- plusieurs echecs au meme niveau
- volume fort mais cloture faible
- prix proche resistance puis retour rapide
- cassure ratee au-dessus de l'objectif

Regle possible:

```text
si PnL net > 0.25% et rejet resistance detecte:
    TAKE_PROFIT ou TIGHTEN_STOP
```

Cas:

```text
Objectif ETH: 1946.53
Prix touche 1944 puis retombe a 1939
Score passe de 72 a 41
```

Impact attendu:

- capturer plus souvent les gains avant retournement
- eviter de rendre une grande partie du profit

Risque:

- vendre avant une vraie cassure si le rejet etait temporaire.

## 6. Time Stop Intelligent

Objectif: sortir ou proteger les trades qui stagnent.

Regles possibles:

```text
apres 8 minutes:
    si PnL net < 0.10% et score < 50:
        stop serre

apres 15 minutes:
    si PnL net <= 0 et score faible:
        sortie ou stop agressif
```

Impact attendu:

- moins de capital bloque
- moins de pertes lentes
- moins de trades mous qui finissent rouges

Risque:

- sortir juste avant un mouvement tardif.

## 7. Utiliser Le Contexte BTC Et Marche Global

Objectif: eviter que le bot gere ETH/SOL/ADA sans tenir compte du marche global.

Signaux utiles:

- momentum BTC 5m
- momentum BTC 15m
- regime BTC
- volatilite globale
- correlation courte periode

Regles possibles:

```text
si position altcoin legerement verte et BTC se retourne:
    serrer le stop

si BTC pousse et score local fort:
    laisser courir
```

Impact attendu:

- meilleure defense contre les retournements de marche
- sorties plus rapides quand tout le marche faiblit

Risque:

- ETH ou SOL peuvent parfois continuer meme si BTC ralentit.

## 8. Journaliser Les Decisions De Sortie

Objectif: rendre les decisions auditables.

Evenement propose:

```json
{
  "action": "exit_decision",
  "symbol": "ETH/USD",
  "decision": "TIGHTEN_STOP",
  "continuation_score": 42,
  "pnl_net_pct": 0.18,
  "reason": "profit_fragile_momentum_weak"
}
```

Impact attendu:

- comprendre pourquoi le bot a tenu, vendu ou serre le stop
- pouvoir comparer les recommandations avec le resultat reel
- faciliter le backtest des sorties

## 9. Phase Observation Avant Execution

Objectif: eviter d'activer trop vite une logique de sortie agressive.

Plan:

1. Calculer les recommandations sans agir.
2. Logger les recommandations dans le decision log.
3. Comparer avec ce qui s'est passe reellement.
4. Activer seulement les protections de stop.
5. Activer les sorties automatiques plus tard.

Impact attendu:

- risque trading quasi nul au debut
- donnees utiles pour calibrer les seuils

## 10. Backtest Des Regles De Sortie

Objectif: comparer l'ancien comportement avec les nouvelles regles.

Scenarios a comparer:

```text
trailing actuel
trailing fee-aware
profit fragile
continuation score
rejet resistance
time stop
```

Metriques:

- PnL brut
- PnL net
- fees
- win rate
- profit factor
- max drawdown
- duree moyenne des trades
- nombre de petits verts sauves
- nombre de gros winners coupes trop tot

Impact attendu:

- eviter les intuitions trompeuses
- choisir les seuils avec des donnees

## 11. Parametres Proposes

Exemple de configuration future:

```env
EXIT_ENGINE_ENABLED=True
CONTINUATION_SCORE_ENABLED=True
PROFIT_FRAGILE_ENABLED=True
PROFIT_FRAGILE_MAX_NET_PCT=0.40
PROFIT_FRAGILE_MIN_SCORE_HOLD=65
PROFIT_FRAGILE_EXIT_SCORE=35
DYNAMIC_TRAILING_ENABLED=True
RESISTANCE_REJECTION_EXIT=True
TIME_STOP_ENABLED=True
TIME_STOP_MINUTES=12
```

## 12. Priorite Recommandee

Ordre recommande:

1. Ajouter `exit_decision` en mode observation seulement.
2. Ajouter `ContinuationScore`.
3. Ajouter le mode `Profit Fragile` pour serrer le stop, sans vendre directement.
4. Ajouter la detection de rejet resistance.
5. Backtester.
6. Activer les sorties automatiques seulement si les logs montrent un vrai avantage.

La meilleure amelioration pour le probleme actuel est:

```text
Profit fragile + ContinuationScore + stop dynamique
```

Ce trio devrait reduire les trades qui passent verts puis finissent rouges, tout en laissant respirer les mouvements vraiment solides.

