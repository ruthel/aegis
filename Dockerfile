# Multi-stage build pour optimiser la taille
FROM python:3.11-slim as builder

# Variables d'environnement pour optimiser Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt

# Stage final - image de production
FROM python:3.11-slim

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

# Créer utilisateur non-root pour sécurité
RUN useradd --create-home --shell /bin/bash botuser

# Copier les dépendances installées
COPY --from=builder /root/.local /home/botuser/.local

# Créer répertoire de travail
WORKDIR /app

# Copier le code source
COPY --chown=botuser:botuser . .

# Créer répertoires nécessaires
RUN mkdir -p data logs && \
    chown -R botuser:botuser /app

# Passer à l'utilisateur non-root
USER botuser

# Port d'exposition (si interface web future)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Point d'entrée
CMD ["python", "run.py"]