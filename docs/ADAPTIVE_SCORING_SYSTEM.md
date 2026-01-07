# 🎯 Système de Scoring Adaptatif Professionnel

## 🚀 Vue d'Ensemble

Le bot utilise maintenant un **système de scoring adaptatif intelligent** qui ajuste automatiquement le seuil minimum selon le contexte, remplaçant le `MIN_CRYPTO_SCORE` statique.

## 📊 Fonctionnement du Système

### Score de Base
```env
MIN_CRYPTO_SCORE=40  # Score de référence (sera adapté automatiquement)
```

### Ajustements Automatiques

#### 1. **Adaptation selon Capital** 💰
```
Capital < 20 USDT   : Seuil -15 (micro-capital plus agressif)
Capital < 50 USDT   : Seuil -10 (petit capital légèrement agressif)
Capital ≥ 50 USDT   : Seuil normal
```

#### 2. **Adaptation selon Marché** 📈
```
Volatilité < 1.5    : Seuil -10 (marché calme = plus permissif)
Volume faible       : Seuil -5  (liquidité réduite = assouplir)
```

#### 3. **Adaptation selon Options** 🎲
```
< 2 cryptos dispo   : Seuil -15 (très peu d'options = agressif)
< 4 cryptos dispo   : Seuil -5  (peu d'options = légèrement agressif)
> 8 cryptos dispo   : Seuil +10 (beaucoup d'options = sélectif)
```

#### 4. **Adaptation Temporelle** ⏰
```
Weekend             : Seuil -5  (volume réduit = assouplir)
Nuit (22h-8h)       : Seuil -3  (sessions fermées = moins strict)
```

## 🎯 Exemple Concret

### Situation : Capital 8.52 USDT
```
Score de base       : 40
Capital < 20 USDT   : -15  (micro-capital)
Marché calme        : -10  (volatilité faible)
Peu d'options       : -15  (< 2 cryptos disponibles)
Weekend             : -5   (volume réduit)

Seuil final = 40 - 15 - 10 - 15 - 5 = -5
Seuil appliqué = max(15, -5) = 15

Résultat : Seuil adaptatif 15 au lieu de 40 !
```

## 📋 Configuration Avancée

### Variables .env Disponibles
```env
# Système adaptatif
ENABLE_ADAPTIVE_SCORING=True          # Active/désactive l'adaptation
MICRO_CAPITAL_THRESHOLD=20            # Seuil micro-capital
LOW_VOLATILITY_THRESHOLD=1.5          # Seuil volatilité faible

# Contraintes de sécurité (automatiques)
# Seuil minimum absolu : 15
# Seuil maximum absolu : 80
```

## 🔍 Monitoring en Temps Réel

### Affichage Amélioré
```
🎯 TOP: BTC 35 | ETH 28 → TRADING (Seuil adaptatif: 25 (Capital-15, Volatilité-10))
```

**Explication :**
- **BTC 35** : Score actuel de Bitcoin
- **Seuil adaptatif: 25** : Seuil calculé automatiquement
- **(Capital-15, Volatilité-10)** : Ajustements appliqués

## 🎲 Avantages du Système

### ✅ **Flexibilité Intelligente**
- S'adapte automatiquement aux conditions
- Plus de trading en micro-capital
- Réactivité selon volatilité du marché

### ✅ **Sécurité Maintenue**
- Contraintes min/max automatiques
- Pas de seuils dangereux
- Logique professionnelle

### ✅ **Configuration Simple**
- Un seul paramètre `MIN_CRYPTO_SCORE`
- Adaptation automatique transparente
- Pas de maintenance manuelle

## 🚨 Cas d'Usage Typiques

### Micro-Capital (< 20 USDT)
```
Avant : Aucune crypto ≥40/100 → Pas de trading
Après : Seuil adaptatif 25 → Trading possible !
```

### Marché Calme
```
Avant : Toutes cryptos < 40 → Attente
Après : Seuil adaptatif 30 → Opportunités détectées
```

### Weekend/Nuit
```
Avant : Volume faible = scores bas → Pas de trading
Après : Seuil adaptatif réduit → Trading adapté
```

## 🔧 Désactivation (si nécessaire)

```env
ENABLE_ADAPTIVE_SCORING=False  # Retour au seuil statique
```

---

**Le système adaptatif transforme un bot rigide en assistant intelligent qui s'adapte automatiquement à VOTRE situation et aux conditions du marché !**