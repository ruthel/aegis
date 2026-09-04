"""
Modèle LSTM-Attention pour prédiction de trading
================================================

Architecture:
1. Input Projection: 78 features -> hidden_size
2. Positional Encoding
3. LSTM bidirectionnel 3 couches
4. Multi-Head Self-Attention (8 têtes)
5. Attention Pooling
6. 3 Output Heads:
   - win_probability: P(trade gagnant)
   - continue_probability: P(maintenir position)
   - optimal_sizing: Taille optimale (0-1)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Optional, Tuple, List
import logging

from .components import (
    PositionalEncoding,
    MultiHeadAttention,
    ResidualBlock,
    FeedForward,
    AttentionPooling,
    OutputHead,
    LayerScale,
    StochasticDepth
)

logger = logging.getLogger(__name__)


class LSTMAttentionModel(nn.Module):
    """
    Modèle principal combinant LSTM bidirectionnel et Multi-Head Attention.
    
    Conçu pour capturer à la fois:
    - Les dépendances séquentielles (LSTM)
    - Les relations longue distance (Attention)
    """
    
    def __init__(
        self,
        input_size: int = 78,
        hidden_size: int = 256,
        num_lstm_layers: int = 3,
        num_attention_heads: int = 8,
        dropout: float = 0.3,
        lstm_dropout: float = 0.2,
        attention_dropout: float = 0.1,
        bidirectional: bool = True,
        use_layer_norm: bool = True,
        use_residual: bool = True,
        use_positional_encoding: bool = True,
        max_sequence_length: int = 500
    ):
        """
        Args:
            input_size: Nombre de features en entrée (78)
            hidden_size: Taille des couches cachées LSTM
            num_lstm_layers: Nombre de couches LSTM
            num_attention_heads: Nombre de têtes d'attention
            dropout: Dropout général
            lstm_dropout: Dropout entre couches LSTM
            attention_dropout: Dropout dans l'attention
            bidirectional: LSTM bidirectionnel
            use_layer_norm: Utiliser layer normalization
            use_residual: Utiliser connexions résiduelles
            use_positional_encoding: Ajouter encodage positionnel
            max_sequence_length: Longueur max de séquence
        """
        super().__init__()
        
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_lstm_layers = num_lstm_layers
        self.bidirectional = bidirectional
        self.use_residual = use_residual
        
        # Dimension après LSTM bidirectionnel
        self.lstm_output_size = hidden_size * 2 if bidirectional else hidden_size
        
        # === INPUT PROJECTION ===
        self.input_projection = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size)
        )
        
        # === POSITIONAL ENCODING ===
        self.use_positional_encoding = use_positional_encoding
        if use_positional_encoding:
            self.positional_encoding = PositionalEncoding(
                hidden_size,
                max_len=max_sequence_length,
                dropout=dropout
            )
        
        # === LSTM LAYERS ===
        self.lstm = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=num_lstm_layers,
            batch_first=True,
            dropout=lstm_dropout if num_lstm_layers > 1 else 0,
            bidirectional=bidirectional
        )
        
        # Layer norm après LSTM
        self.lstm_norm = nn.LayerNorm(self.lstm_output_size) if use_layer_norm else nn.Identity()
        
        # === PROJECTION POST-LSTM ===
        # Projette de lstm_output_size vers hidden_size pour l'attention
        self.post_lstm_projection = nn.Linear(self.lstm_output_size, hidden_size)
        
        # === SELF-ATTENTION LAYERS ===
        self.attention_layers = nn.ModuleList()
        self.attention_norms = nn.ModuleList()
        self.ff_layers = nn.ModuleList()
        self.ff_norms = nn.ModuleList()
        
        num_attention_layers = 2  # 2 couches d'attention
        
        for _ in range(num_attention_layers):
            # Self-attention
            self.attention_layers.append(
                MultiHeadAttention(
                    d_model=hidden_size,
                    num_heads=num_attention_heads,
                    dropout=attention_dropout
                )
            )
            self.attention_norms.append(nn.LayerNorm(hidden_size))
            
            # Feed-forward
            self.ff_layers.append(
                FeedForward(
                    d_model=hidden_size,
                    d_ff=hidden_size * 4,
                    dropout=dropout
                )
            )
            self.ff_norms.append(nn.LayerNorm(hidden_size))
        
        # === ATTENTION POOLING ===
        self.attention_pooling = AttentionPooling(hidden_size)
        
        # === OUTPUT HEADS ===
        self.output_heads = nn.ModuleDict({
            'win_probability': OutputHead(
                hidden_size,
                output_size=1,
                dropout=dropout,
                activation='sigmoid'
            ),
            'continue_probability': OutputHead(
                hidden_size,
                output_size=1,
                dropout=dropout,
                activation='sigmoid'
            ),
            'optimal_sizing': OutputHead(
                hidden_size,
                output_size=1,
                dropout=dropout,
                activation='sigmoid'
            )
        })
        
        # === DROPOUT FINAL ===
        self.final_dropout = nn.Dropout(dropout)
        
        # Initialisation des poids
        self._init_weights()
        
        logger.info(f"LSTMAttentionModel initialized: {self._count_parameters():,} parameters")
    
    def _init_weights(self):
        """Initialisation des poids avec Xavier/Kaiming"""
        for name, param in self.named_parameters():
            if 'weight' in name:
                if 'lstm' in name:
                    # LSTM: orthogonal init
                    if len(param.shape) >= 2:
                        nn.init.orthogonal_(param)
                elif 'norm' in name:
                    # LayerNorm: ones
                    nn.init.ones_(param)
                elif len(param.shape) >= 2:
                    # Linear layers: xavier
                    nn.init.xavier_uniform_(param)
            elif 'bias' in name:
                nn.init.zeros_(param)
    
    def _count_parameters(self) -> int:
        """Compte le nombre de paramètres entraînables"""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
    
    def forward(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
        return_attention: bool = False
    ) -> Dict[str, torch.Tensor]:
        """
        Forward pass du modèle.
        
        Args:
            x: Input tensor shape (batch, seq_len, input_size)
            mask: Optional mask shape (batch, seq_len), 1 pour positions valides
            return_attention: Retourner les poids d'attention
            
        Returns:
            Dict avec:
                - 'win_probability': (batch, 1)
                - 'continue_probability': (batch, 1)
                - 'optimal_sizing': (batch, 1)
                - 'attention_weights': Optional list de tensors
        """
        batch_size, seq_len, _ = x.shape
        attention_weights = []
        
        # === INPUT PROJECTION ===
        x = self.input_projection(x)  # (batch, seq_len, hidden_size)
        
        # === POSITIONAL ENCODING ===
        if self.use_positional_encoding:
            x = self.positional_encoding(x)
        
        # === LSTM ===
        # Pack si mask disponible pour efficacité
        if mask is not None:
            lengths = mask.sum(dim=1).cpu().long()
            packed = nn.utils.rnn.pack_padded_sequence(
                x, lengths, batch_first=True, enforce_sorted=False
            )
            lstm_out, (hidden, cell) = self.lstm(packed)
            lstm_out, _ = nn.utils.rnn.pad_packed_sequence(
                lstm_out, batch_first=True, total_length=seq_len
            )
        else:
            lstm_out, (hidden, cell) = self.lstm(x)
        
        # Layer norm
        lstm_out = self.lstm_norm(lstm_out)  # (batch, seq_len, lstm_output_size)
        
        # Projection pour matcher la dimension d'attention
        x = self.post_lstm_projection(lstm_out)  # (batch, seq_len, hidden_size)
        
        # === SELF-ATTENTION LAYERS ===
        for i, (attn, attn_norm, ff, ff_norm) in enumerate(zip(
            self.attention_layers,
            self.attention_norms,
            self.ff_layers,
            self.ff_norms
        )):
            # Self-attention avec résiduel
            residual = x
            x_normed = attn_norm(x)
            attn_out, attn_w = attn(
                x_normed, x_normed, x_normed,
                mask=mask,
                return_attention=return_attention
            )
            
            if return_attention and attn_w is not None:
                attention_weights.append(attn_w)
            
            if self.use_residual:
                x = residual + attn_out
            else:
                x = attn_out
            
            # Feed-forward avec résiduel
            residual = x
            x_normed = ff_norm(x)
            ff_out = ff(x_normed)
            
            if self.use_residual:
                x = residual + ff_out
            else:
                x = ff_out
        
        # === ATTENTION POOLING ===
        # Agrège la séquence en un vecteur
        pooled = self.attention_pooling(x, mask)  # (batch, hidden_size)
        
        # === DROPOUT FINAL ===
        pooled = self.final_dropout(pooled)
        
        # === OUTPUT HEADS ===
        outputs = {}
        for head_name, head in self.output_heads.items():
            outputs[head_name] = head(pooled)
        
        if return_attention:
            outputs['attention_weights'] = attention_weights
        
        return outputs
    
    def predict(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None
    ) -> Dict[str, float]:
        """
        Prédiction avec conversion en scalaires.
        
        Args:
            x: Input tensor (peut être unbatched)
            mask: Optional mask
            
        Returns:
            Dict avec probabilités en float
        """
        self.eval()
        
        # Ajouter dimension batch si nécessaire
        if x.dim() == 2:
            x = x.unsqueeze(0)
            if mask is not None:
                mask = mask.unsqueeze(0)
        
        with torch.no_grad():
            outputs = self.forward(x, mask)
        
        return {
            'win_probability': outputs['win_probability'].item(),
            'continue_probability': outputs['continue_probability'].item(),
            'optimal_sizing': outputs['optimal_sizing'].item()
        }
    
    def get_feature_importance(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Calcule l'importance des features via gradients.
        
        Returns:
            Tensor shape (batch, seq_len, input_size) avec importance par feature
        """
        x.requires_grad_(True)
        
        outputs = self.forward(x, mask)
        
        # Backprop depuis la sortie principale
        loss = outputs['win_probability'].sum()
        loss.backward()
        
        # L'importance est le gradient absolu
        importance = x.grad.abs()
        
        return importance


class LSTMAttentionEnsemble(nn.Module):
    """
    Ensemble de modèles LSTM-Attention pour réduire la variance.
    
    Combine les prédictions de plusieurs modèles avec différentes
    initialisations ou hyperparamètres.
    """
    
    def __init__(
        self,
        num_models: int = 3,
        **model_kwargs
    ):
        super().__init__()
        
        self.models = nn.ModuleList([
            LSTMAttentionModel(**model_kwargs)
            for _ in range(num_models)
        ])
        
        # Poids apprenables pour l'ensemble
        self.ensemble_weights = nn.Parameter(
            torch.ones(num_models) / num_models
        )
    
    def forward(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None
    ) -> Dict[str, torch.Tensor]:
        """Combine les prédictions des modèles"""
        all_outputs = [model(x, mask) for model in self.models]
        
        # Normaliser les poids
        weights = F.softmax(self.ensemble_weights, dim=0)
        
        # Moyenne pondérée
        combined = {}
        for key in ['win_probability', 'continue_probability', 'optimal_sizing']:
            combined[key] = sum(
                w * out[key] for w, out in zip(weights, all_outputs)
            )
        
        return combined


def create_model(config: dict) -> LSTMAttentionModel:
    """
    Factory function pour créer un modèle depuis une config.
    
    Args:
        config: Dict avec les hyperparamètres
        
    Returns:
        Instance de LSTMAttentionModel
    """
    return LSTMAttentionModel(
        input_size=config.get('input_size', 78),
        hidden_size=config.get('hidden_size', 256),
        num_lstm_layers=config.get('num_lstm_layers', 3),
        num_attention_heads=config.get('num_attention_heads', 8),
        dropout=config.get('dropout', 0.3),
        lstm_dropout=config.get('lstm_dropout', 0.2),
        attention_dropout=config.get('attention_dropout', 0.1),
        bidirectional=config.get('bidirectional', True),
        use_layer_norm=config.get('use_layer_norm', True),
        use_residual=config.get('use_residual', True),
        use_positional_encoding=config.get('use_positional_encoding', True),
        max_sequence_length=config.get('max_sequence_length', 500)
    )
