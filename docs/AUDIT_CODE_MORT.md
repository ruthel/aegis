# Audit Code Mort Aegis

Derniere mise a jour : 2026-08-21

Objectif : lister uniquement les morceaux de code morts verifies apres les migrations SQLite, ML-only, SPA React et gouvernance Phase 8/10.

Important : ce fichier ne supprime rien. Il sert de base d'audit manuel avant nettoyage.

---

## Methode

Verification effectuee par :

- scan AST Python des definitions, imports et references ;
- recherches `rg` par nom de fonction/composant ;
- lint frontend `pnpm lint` ;
- recoupement manuel des faux positifs connus : routes Flask, decorateurs, mixins, appels dynamiques, composants shadcn/Radix.

Limite : certains appels peuvent etre dynamiques via `getattr`, routes, callbacks, CLI ou scripts externes. Ce fichier garde seulement les elements dont l'absence d'appel a ete revalidee.

---

## Code Mort Sur

Aucun element restant apres nettoyage.

---

## Nettoyage Sizing Legacy Termine

Elements confirmes redondants puis retires du chemin actif :

- `_confidence_sizing_factor()` dans `core/trading_bot.py`;
- branche runtime `ml_neutral_sizing` / `ml_position_factor`;
- seuils de taille fixes `40% / 70% / 100%` dans `utils/risk_manager.py`;
- `calculate_kelly_fractional_factor()` devenu inutilise apres passage au `sizing_model`.

Etat apres nettoyage : aucun code mort sizing confirme restant. Le sizing actif est :

1. taille de base neutre + volatilite dans `RiskManager.calculate_position_size()`;
2. facteur cible dans `MLEngine.predict_position_size_factor()`;
3. plafonds finaux dans `RiskManager.clamp_position_size()`.
