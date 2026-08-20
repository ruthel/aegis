# Audit Code Mort Aegis

Derniere mise a jour : 2026-08-09

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
