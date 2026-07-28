# Aegis UI SPA

Frontend moderne du ui Aegis.

## Stack

- React + Vite + TypeScript
- pnpm
- axios pour REST
- zustand pour l'etat global
- shadcn/Radix pour les composants interactifs
- lucide-react pour les icones
- amCharts 5 pour les graphiques
- Police principale : Outfit

## Commandes

```bash
pnpm install
pnpm dev
pnpm build
```

Le build production est genere dans `ui/static/spa`. Flask sert cette SPA si `ui/static/spa/index.html` existe.

## Structure

- `src/App.tsx` : routes et vues principales.
- `src/store/dashboard-store.ts` : etat global dashboard et appels API principaux.
- `src/lib/api.ts` : client axios.
- `src/components/ui/` : composants UI style shadcn.
- `src/components/charts/` : graphiques amCharts.

## Donnees

Le ui consomme principalement :

- `/ws/live` : push WebSocket pour `status`, `ml_status` et prix live.
- `/api/status` : fallback/refresh de statut.
- `/api/ml_status` : fallback/refresh ML.
- `/api/analytics` : metrics analytiques generales.
- `/api/analytics/scores` : historique des scores crypto par symbole/periode.
- `/api/trades` : trades fermes et positions ouvertes affichees dans la vue Trades.
- `/api/bot/console` : logs console quand la vue Console est ouverte.

## Notes UI

- Les dropdowns natifs ont ete remplaces par `Select` Radix/shadcn.
- Les sections Live reproduisent le design dense du ui HTML legacy.
- `Marche Live` affiche le volume en USD. Si le backend ne fournit pas un volume quote, le frontend calcule `volume base * prix live`.
- La vue `Trades` affiche les positions ouvertes avec badge `OPEN` et PnL `En cours`.
- Le journal des decisions affiche les decisions finales utiles. Les cooldowns sont des etats operationnels et restent dans la section `Cooldowns`, pas dans les decisions rejetees/approuvees.
- L'historique des scores crypto utilise un axe temporel amCharts afin d'eviter les labels X trop nombreux.
