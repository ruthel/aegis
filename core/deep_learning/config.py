"""
Configuration complète du système Deep Learning AEGIS
=====================================================

Tous les hyperparamètres pour:
- Architecture LSTM-Attention
- Feature engineering (78 features)
- Entraînement et optimisation
- Évolution continue (EWC, replay buffer)
- Shadow mode et comparaison RF
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from pathlib import Path
import torch


@dataclass
class FeatureConfig:
    """Configuration des 78 features"""
    
    # === FEATURES PRIX (12) ===
    price_features: List[str] = field(default_factory=lambda: [
        'price_change_1m',      # Changement prix 1 minute
        'price_change_5m',      # Changement prix 5 minutes
        'price_change_15m',     # Changement prix 15 minutes
        'price_change_1h',      # Changement prix 1 heure
        'price_change_4h',      # Changement prix 4 heures
        'price_change_24h',     # Changement prix 24 heures
        'high_low_range',       # Range haut-bas normalisé
        'close_to_high',        # Distance au plus haut
        'close_to_low',         # Distance au plus bas
        'price_momentum',       # Momentum court terme
        'price_acceleration',   # Accélération du prix
        'price_volatility',     # Volatilité instantanée
    ])
    
    # === FEATURES TECHNIQUES (20) ===
    technical_features: List[str] = field(default_factory=lambda: [
        # RSI multi-périodes
        'rsi_7', 'rsi_14', 'rsi_21',
        'rsi_divergence',       # Divergence prix/RSI
        # MACD
        'macd_line', 'macd_signal', 'macd_histogram',
        'macd_cross_distance',  # Distance au croisement
        # Bollinger Bands
        'bb_position',          # Position dans les bandes (0-1)
        'bb_width',             # Largeur des bandes
        'bb_squeeze',           # Indicateur de squeeze
        # Moyennes mobiles
        'ema_9_21_cross',       # Croisement EMA 9/21
        'ema_21_50_cross',      # Croisement EMA 21/50
        'price_to_ema_9',       # Distance prix/EMA9
        'price_to_ema_21',      # Distance prix/EMA21
        'price_to_ema_50',      # Distance prix/EMA50
        # Autres
        'stoch_k', 'stoch_d',   # Stochastique
        'adx',                  # Force de tendance
        'cci',                  # Commodity Channel Index
    ])
    
    # === FEATURES VOLUME (8) ===
    volume_features: List[str] = field(default_factory=lambda: [
        'volume_change_1h',     # Changement volume 1h
        'volume_change_24h',    # Changement volume 24h
        'volume_ma_ratio',      # Ratio volume/MA volume
        'volume_trend',         # Tendance du volume
        'buy_volume_ratio',     # Ratio volume achat
        'volume_price_corr',    # Corrélation volume/prix
        'obv_trend',            # On-Balance Volume trend
        'volume_volatility',    # Volatilité du volume
    ])
    
    # === FEATURES STRUCTURE MARCHÉ (10) ===
    structure_features: List[str] = field(default_factory=lambda: [
        'support_distance',     # Distance au support
        'resistance_distance',  # Distance à la résistance
        'sr_strength',          # Force du S/R le plus proche
        'trend_strength',       # Force de la tendance
        'trend_duration',       # Durée de la tendance actuelle
        'higher_highs',         # Compteur higher highs
        'lower_lows',           # Compteur lower lows
        'consolidation_score',  # Score de consolidation
        'breakout_potential',   # Potentiel de breakout
        'market_regime',        # Régime de marché (trending/ranging)
    ])
    
    # === FEATURES BTC CORRELATION (8) ===
    btc_features: List[str] = field(default_factory=lambda: [
        'btc_price_change_1h',  # Changement prix BTC 1h
        'btc_price_change_24h', # Changement prix BTC 24h
        'btc_correlation_24h',  # Corrélation avec BTC 24h
        'btc_correlation_7d',   # Corrélation avec BTC 7j
        'btc_dominance',        # Dominance BTC
        'btc_dominance_change', # Changement dominance
        'btc_volatility',       # Volatilité BTC
        'btc_trend',            # Tendance BTC
    ])
    
    # === FEATURES TEMPORELLES (8) ===
    temporal_features: List[str] = field(default_factory=lambda: [
        'hour_sin',             # Heure (encodage cyclique sin)
        'hour_cos',             # Heure (encodage cyclique cos)
        'day_of_week_sin',      # Jour semaine (sin)
        'day_of_week_cos',      # Jour semaine (cos)
        'is_weekend',           # Weekend flag
        'is_asian_session',     # Session asiatique
        'is_european_session',  # Session européenne
        'is_american_session',  # Session américaine
    ])
    
    # === FEATURES PATTERNS (8) ===
    pattern_features: List[str] = field(default_factory=lambda: [
        'doji_pattern',         # Pattern doji
        'engulfing_pattern',    # Pattern engulfing
        'hammer_pattern',       # Pattern hammer/hanging man
        'morning_star',         # Morning/evening star
        'three_soldiers',       # Three white soldiers/black crows
        'pin_bar',              # Pin bar
        'inside_bar',           # Inside bar
        'double_pattern',       # Double top/bottom
    ])
    
    # === FEATURES MULTI-TIMEFRAME (4) ===
    mtf_features: List[str] = field(default_factory=lambda: [
        'mtf_trend_alignment',  # Alignement tendance multi-TF
        'mtf_momentum_score',   # Score momentum multi-TF
        'mtf_volatility_ratio', # Ratio volatilité TF
        'mtf_volume_confirm',   # Confirmation volume multi-TF
    ])
    
    @property
    def all_features(self) -> List[str]:
        """Retourne la liste complète des 78 features"""
        return (
            self.price_features +
            self.technical_features +
            self.volume_features +
            self.structure_features +
            self.btc_features +
            self.temporal_features +
            self.pattern_features +
            self.mtf_features
        )
    
    @property
    def num_features(self) -> int:
        """Nombre total de features"""
        return len(self.all_features)
    
    @property
    def feature_groups(self) -> Dict[str, List[str]]:
        """Retourne les features groupées par catégorie"""
        return {
            'price': self.price_features,
            'technical': self.technical_features,
            'volume': self.volume_features,
            'structure': self.structure_features,
            'btc': self.btc_features,
            'temporal': self.temporal_features,
            'patterns': self.pattern_features,
            'mtf': self.mtf_features,
        }


@dataclass
class ModelConfig:
    """Configuration de l'architecture LSTM-Attention"""
    
    # === DIMENSIONS ===
    input_size: int = 78                # Nombre de features
    hidden_size: int = 256              # Taille couche cachée LSTM
    num_lstm_layers: int = 3            # Nombre de couches LSTM
    
    # === ATTENTION ===
    num_attention_heads: int = 8        # Nombre de têtes d'attention
    attention_dropout: float = 0.1      # Dropout attention
    
    # === SORTIES (3 heads) ===
    output_heads: Dict[str, int] = field(default_factory=lambda: {
        'win_probability': 1,           # P(trade gagnant) - sigmoid
        'continue_probability': 1,      # P(continuer position) - sigmoid
        'optimal_sizing': 1,            # Taille optimale (0-1) - sigmoid
    })
    
    # === RÉGULARISATION ===
    dropout: float = 0.3                # Dropout général
    lstm_dropout: float = 0.2           # Dropout entre couches LSTM
    layer_norm: bool = True             # Layer normalization
    residual_connections: bool = True   # Connexions résiduelles
    
    # === SÉQUENCE ===
    sequence_length: int = 60           # Longueur séquence (60 pas = 1h en 1min)
    bidirectional: bool = True          # LSTM bidirectionnel
    
    # === EMBEDDING ADDITIONNEL ===
    use_positional_encoding: bool = True
    max_position: int = 500             # Position max pour encoding


@dataclass  
class TrainingConfig:
    """Configuration de l'entraînement"""
    
    # === OPTIMISATION ===
    learning_rate: float = 3e-5         # Reduced for stability
    weight_decay: float = 1e-5          # L2 regularization
    optimizer: str = 'adamw'            # adamw, adam, sgd
    scheduler: str = 'cosine'           # cosine, step, plateau
    
    # === BATCHING ===
    batch_size: int = 2048              # Maximum batch for speed
    accumulation_steps: int = 1         # No accumulation needed with large batch
    
    # === EPOCHS ===
    max_epochs: int = 100
    early_stopping_patience: int = 15
    min_epochs: int = 20
    
    # === VALIDATION ===
    validation_split: float = 0.15
    test_split: float = 0.10
    
    # === LOSS FUNCTION ===
    # Focal Loss pour gérer le déséquilibre classes
    focal_alpha: float = 0.25           # Poids classe positive
    focal_gamma: float = 2.0            # Facteur de focus
    
    # Poids des différentes loss
    loss_weights: Dict[str, float] = field(default_factory=lambda: {
        'win_probability': 1.0,
        'continue_probability': 0.5,
        'optimal_sizing': 0.3,
    })
    
    # === MÉTRIQUES TRADING ===
    profit_factor_weight: float = 0.3   # Poids profit factor dans loss
    sharpe_weight: float = 0.2          # Poids Sharpe ratio
    
    # === AUGMENTATION ===
    use_augmentation: bool = True
    noise_std: float = 0.01             # Bruit gaussien
    time_warp_prob: float = 0.1         # Probabilité time warping
    
    # === DEVICE ===
    device: str = 'cuda' if torch.cuda.is_available() else 'cpu'
    mixed_precision: bool = True        # FP16 for 2x speed boost
    num_workers: int = 4                # DataLoader workers


@dataclass
class EvolutionConfig:
    """Configuration de l'évolution continue"""
    
    # === ELASTIC WEIGHT CONSOLIDATION (EWC) ===
    ewc_enabled: bool = True
    ewc_lambda: float = 1000.0          # Importance de la régularisation EWC
    ewc_gamma: float = 0.95             # Decay pour Fisher information
    fisher_sample_size: int = 1000      # Échantillons pour Fisher
    
    # === REPLAY BUFFER ===
    replay_buffer_size: int = 50000     # Taille buffer expériences
    replay_sample_ratio: float = 0.3    # Ratio replay vs nouvelles données
    prioritized_replay: bool = True     # Replay priorisé par importance
    priority_alpha: float = 0.6         # Exposant priorité
    priority_beta: float = 0.4          # Importance sampling
    
    # === DRIFT DETECTION ===
    drift_detection_enabled: bool = True
    drift_window_size: int = 1000       # Fenêtre détection drift
    drift_threshold: float = 0.05       # Seuil de drift (KL divergence)
    drift_adaptation_rate: float = 0.1  # Taux d'adaptation après drift
    
    # === ONLINE LEARNING ===
    online_learning_rate: float = 1e-5  # LR pour updates online
    update_frequency: int = 100         # Update tous les N trades
    min_samples_update: int = 50        # Minimum samples pour update
    
    # === CHECKPOINTING ===
    checkpoint_frequency: int = 1000    # Checkpoint tous les N updates
    keep_n_checkpoints: int = 10        # Nombre de checkpoints gardés
    
    # === PERFORMANCE MONITORING ===
    performance_window: int = 500       # Fenêtre évaluation performance
    min_performance_threshold: float = 0.45  # Seuil minimum win rate
    rollback_on_degradation: bool = True     # Rollback si dégradation


@dataclass
class ShadowConfig:
    """Configuration du mode shadow"""
    
    # === SHADOW MODE ===
    enabled: bool = True
    log_all_predictions: bool = True
    compare_with_rf: bool = True
    
    # === SEUILS DE PRÉDICTION ===
    min_confidence: float = 0.6         # Confiance minimum pour signal
    high_confidence: float = 0.8        # Haute confiance
    
    # === COMPARAISON RF ===
    track_agreement: bool = True        # Track accord DL/RF
    track_disagreement: bool = True     # Track désaccord DL/RF
    
    # === MÉTRIQUES SHADOW ===
    metrics_window: int = 1000          # Fenêtre pour métriques
    log_frequency: int = 100            # Log tous les N prédictions
    
    # === PROMOTION VERS PRODUCTION ===
    min_shadow_trades: int = 500        # Minimum trades shadow avant promo
    min_shadow_winrate: float = 0.55    # Win rate minimum pour promo
    min_rf_outperformance: float = 0.05 # Surperformance vs RF requise


@dataclass
class DLConfig:
    """Configuration principale regroupant tout"""
    
    features: FeatureConfig = field(default_factory=FeatureConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    shadow: ShadowConfig = field(default_factory=ShadowConfig)
    
    # === CHEMINS ===
    base_path: Path = field(default_factory=lambda: Path('data/deep_learning'))
    model_path: Path = field(default_factory=lambda: Path('data/deep_learning/models'))
    checkpoint_path: Path = field(default_factory=lambda: Path('data/deep_learning/checkpoints'))
    logs_path: Path = field(default_factory=lambda: Path('data/deep_learning/logs'))
    
    def __post_init__(self):
        """Crée les dossiers nécessaires"""
        for path in [self.base_path, self.model_path, self.checkpoint_path, self.logs_path]:
            path.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def from_dict(cls, config_dict: Dict) -> 'DLConfig':
        """Crée une config depuis un dictionnaire"""
        return cls(
            features=FeatureConfig(**config_dict.get('features', {})),
            model=ModelConfig(**config_dict.get('model', {})),
            training=TrainingConfig(**config_dict.get('training', {})),
            evolution=EvolutionConfig(**config_dict.get('evolution', {})),
            shadow=ShadowConfig(**config_dict.get('shadow', {})),
        )
    
    def to_dict(self) -> Dict:
        """Exporte la config en dictionnaire"""
        from dataclasses import asdict
        return {
            'features': asdict(self.features),
            'model': asdict(self.model),
            'training': asdict(self.training),
            'evolution': asdict(self.evolution),
            'shadow': asdict(self.shadow),
        }
    
    def validate(self) -> bool:
        """Valide la cohérence de la configuration"""
        assert self.model.input_size == self.features.num_features, \
            f"Mismatch: model.input_size ({self.model.input_size}) != features ({self.features.num_features})"
        assert 0 < self.training.validation_split < 1
        assert 0 < self.training.test_split < 1
        assert self.training.validation_split + self.training.test_split < 1
        return True


# Configuration par défaut
DEFAULT_CONFIG = DLConfig()
