"""
Composants réutilisables pour le modèle Deep Learning
=====================================================

- MultiHeadAttention: Attention multi-têtes
- PositionalEncoding: Encodage positionnel pour séquences
- ResidualBlock: Bloc résiduel avec layer norm
- GatedLinearUnit: GLU pour gating
- TemporalConvBlock: Convolutions temporelles optionnelles
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import math
from typing import Optional, Tuple


class PositionalEncoding(nn.Module):
    """
    Encodage positionnel sinusoïdal pour donner au modèle
    une notion de position dans la séquence.
    """
    
    def __init__(
        self,
        d_model: int,
        max_len: int = 500,
        dropout: float = 0.1
    ):
        """
        Args:
            d_model: Dimension du modèle
            max_len: Longueur maximale de séquence
            dropout: Taux de dropout
        """
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        
        # Créer la matrice d'encodage positionnel
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        
        pe = pe.unsqueeze(0)  # (1, max_len, d_model)
        self.register_buffer('pe', pe)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Tensor shape (batch, seq_len, d_model)
        Returns:
            Tensor avec encodage positionnel ajouté
        """
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


class MultiHeadAttention(nn.Module):
    """
    Attention multi-têtes avec support pour masking.
    
    Permet au modèle d'apprendre différentes représentations
    d'attention en parallèle.
    """
    
    def __init__(
        self,
        d_model: int,
        num_heads: int = 8,
        dropout: float = 0.1,
        bias: bool = True
    ):
        """
        Args:
            d_model: Dimension du modèle
            num_heads: Nombre de têtes d'attention
            dropout: Taux de dropout
            bias: Utiliser des biais dans les projections
        """
        super().__init__()
        
        assert d_model % num_heads == 0, "d_model must be divisible by num_heads"
        
        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        self.scale = self.head_dim ** -0.5
        
        # Projections linéaires
        self.q_proj = nn.Linear(d_model, d_model, bias=bias)
        self.k_proj = nn.Linear(d_model, d_model, bias=bias)
        self.v_proj = nn.Linear(d_model, d_model, bias=bias)
        self.out_proj = nn.Linear(d_model, d_model, bias=bias)
        
        self.dropout = nn.Dropout(dropout)
        
        # Pour stocker les poids d'attention (debugging/visualisation)
        self.attention_weights: Optional[torch.Tensor] = None
    
    def forward(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        value: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
        return_attention: bool = False
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Args:
            query: (batch, seq_len_q, d_model)
            key: (batch, seq_len_k, d_model)
            value: (batch, seq_len_v, d_model)
            mask: Optional (batch, seq_len_q, seq_len_k) ou (batch, 1, seq_len_k)
            return_attention: Retourner les poids d'attention
            
        Returns:
            output: (batch, seq_len_q, d_model)
            attention_weights: Optional (batch, num_heads, seq_len_q, seq_len_k)
        """
        batch_size, seq_len_q, _ = query.shape
        seq_len_k = key.shape[1]
        
        # Projections
        Q = self.q_proj(query)
        K = self.k_proj(key)
        V = self.v_proj(value)
        
        # Reshape pour multi-head: (batch, seq_len, num_heads, head_dim)
        Q = Q.view(batch_size, seq_len_q, self.num_heads, self.head_dim).transpose(1, 2)
        K = K.view(batch_size, seq_len_k, self.num_heads, self.head_dim).transpose(1, 2)
        V = V.view(batch_size, seq_len_k, self.num_heads, self.head_dim).transpose(1, 2)
        
        # Attention scores: (batch, num_heads, seq_len_q, seq_len_k)
        scores = torch.matmul(Q, K.transpose(-2, -1)) * self.scale
        
        # Appliquer le masque
        if mask is not None:
            if mask.dim() == 2:
                # (batch, seq_len_k) -> (batch, 1, 1, seq_len_k)
                mask = mask.unsqueeze(1).unsqueeze(2)
            elif mask.dim() == 3:
                # (batch, seq_len_q, seq_len_k) -> (batch, 1, seq_len_q, seq_len_k)
                mask = mask.unsqueeze(1)
            
            scores = scores.masked_fill(mask == 0, float('-inf'))
        
        # Softmax et dropout
        attention_weights = F.softmax(scores, dim=-1)
        attention_weights = self.dropout(attention_weights)
        
        # Stocker pour visualisation
        self.attention_weights = attention_weights.detach()
        
        # Appliquer l'attention aux valeurs
        context = torch.matmul(attention_weights, V)
        
        # Reshape back: (batch, seq_len_q, d_model)
        context = context.transpose(1, 2).contiguous().view(batch_size, seq_len_q, self.d_model)
        
        # Projection de sortie
        output = self.out_proj(context)
        
        if return_attention:
            return output, attention_weights
        return output, None


class ResidualBlock(nn.Module):
    """
    Bloc résiduel avec Layer Normalization.
    
    Facilite l'entraînement de réseaux profonds en permettant
    aux gradients de circuler directement.
    """
    
    def __init__(
        self,
        d_model: int,
        dropout: float = 0.1,
        pre_norm: bool = True
    ):
        """
        Args:
            d_model: Dimension du modèle
            dropout: Taux de dropout
            pre_norm: Appliquer LayerNorm avant (True) ou après (False)
        """
        super().__init__()
        self.norm = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)
        self.pre_norm = pre_norm
    
    def forward(
        self,
        x: torch.Tensor,
        sublayer_output: torch.Tensor
    ) -> torch.Tensor:
        """
        Args:
            x: Input tensor
            sublayer_output: Output de la sous-couche (attention, FFN, etc.)
        """
        if self.pre_norm:
            return x + self.dropout(sublayer_output)
        else:
            return self.norm(x + self.dropout(sublayer_output))


class GatedLinearUnit(nn.Module):
    """
    Gated Linear Unit (GLU) pour gating non-linéaire.
    
    Permet au modèle de contrôler le flux d'information.
    """
    
    def __init__(self, d_model: int, d_ff: Optional[int] = None):
        """
        Args:
            d_model: Dimension d'entrée
            d_ff: Dimension cachée (défaut: 4 * d_model)
        """
        super().__init__()
        d_ff = d_ff or d_model * 4
        
        self.linear1 = nn.Linear(d_model, d_ff)
        self.linear2 = nn.Linear(d_model, d_ff)
        self.linear3 = nn.Linear(d_ff, d_model)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear3(F.gelu(self.linear1(x)) * self.linear2(x))


class FeedForward(nn.Module):
    """
    Feed-forward network avec GELU activation.
    """
    
    def __init__(
        self,
        d_model: int,
        d_ff: Optional[int] = None,
        dropout: float = 0.1
    ):
        super().__init__()
        d_ff = d_ff or d_model * 4
        
        self.linear1 = nn.Linear(d_model, d_ff)
        self.linear2 = nn.Linear(d_ff, d_model)
        self.dropout = nn.Dropout(dropout)
        self.activation = nn.GELU()
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.linear1(x)
        x = self.activation(x)
        x = self.dropout(x)
        x = self.linear2(x)
        return x


class TemporalConvBlock(nn.Module):
    """
    Bloc de convolution temporelle pour capturer des patterns locaux.
    
    Optionnel: peut être utilisé en complément du LSTM.
    """
    
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int = 3,
        dilation: int = 1,
        dropout: float = 0.1
    ):
        super().__init__()
        
        padding = (kernel_size - 1) * dilation // 2
        
        self.conv = nn.Conv1d(
            in_channels,
            out_channels,
            kernel_size,
            padding=padding,
            dilation=dilation
        )
        self.norm = nn.BatchNorm1d(out_channels)
        self.activation = nn.GELU()
        self.dropout = nn.Dropout(dropout)
        
        # Skip connection si dimensions différentes
        self.skip = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else nn.Identity()
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, seq_len, channels) ou (batch, channels, seq_len)
        """
        # Assurer format (batch, channels, seq_len) pour conv1d
        if x.dim() == 3 and x.shape[-1] != x.shape[1]:
            x = x.transpose(1, 2)
        
        residual = self.skip(x)
        
        x = self.conv(x)
        x = self.norm(x)
        x = self.activation(x)
        x = self.dropout(x)
        
        return x + residual


class AttentionPooling(nn.Module):
    """
    Pooling par attention pour agréger une séquence en un vecteur.
    
    Apprend quelles parties de la séquence sont importantes pour la sortie.
    """
    
    def __init__(self, d_model: int):
        super().__init__()
        self.attention = nn.Linear(d_model, 1)
    
    def forward(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Args:
            x: (batch, seq_len, d_model)
            mask: (batch, seq_len) - 1 pour positions valides
            
        Returns:
            (batch, d_model)
        """
        # Scores d'attention
        scores = self.attention(x).squeeze(-1)  # (batch, seq_len)
        
        # Masquer les positions invalides
        if mask is not None:
            scores = scores.masked_fill(mask == 0, float('-inf'))
        
        # Poids d'attention normalisés
        weights = F.softmax(scores, dim=-1)  # (batch, seq_len)
        
        # Somme pondérée
        output = torch.bmm(weights.unsqueeze(1), x).squeeze(1)  # (batch, d_model)
        
        return output


class OutputHead(nn.Module):
    """
    Tête de sortie pour une prédiction spécifique.
    
    Utilisé pour les 3 outputs: win_probability, continue_probability, sizing
    """
    
    def __init__(
        self,
        d_model: int,
        output_size: int = 1,
        hidden_size: Optional[int] = None,
        dropout: float = 0.1,
        activation: str = 'sigmoid'
    ):
        """
        Args:
            d_model: Dimension d'entrée
            output_size: Dimension de sortie
            hidden_size: Taille couche cachée (défaut: d_model // 2)
            dropout: Taux de dropout
            activation: 'sigmoid', 'softmax', 'tanh', 'none'
        """
        super().__init__()
        
        hidden_size = hidden_size or d_model // 2
        
        self.layers = nn.Sequential(
            nn.Linear(d_model, hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, output_size)
        )
        
        self.activation_name = activation
        if activation == 'sigmoid':
            self.activation = nn.Sigmoid()
        elif activation == 'softmax':
            self.activation = nn.Softmax(dim=-1)
        elif activation == 'tanh':
            self.activation = nn.Tanh()
        else:
            self.activation = nn.Identity()
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.layers(x)
        return self.activation(x)


class LayerScale(nn.Module):
    """
    Layer Scale pour stabiliser l'entraînement des réseaux profonds.
    Initialise les poids à une petite valeur et les apprend.
    """
    
    def __init__(self, d_model: int, init_value: float = 1e-5):
        super().__init__()
        self.gamma = nn.Parameter(init_value * torch.ones(d_model))
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x * self.gamma


class StochasticDepth(nn.Module):
    """
    Stochastic Depth pour régularisation.
    Désactive aléatoirement des couches pendant l'entraînement.
    """
    
    def __init__(self, drop_prob: float = 0.1):
        super().__init__()
        self.drop_prob = drop_prob
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if not self.training or self.drop_prob == 0:
            return x
        
        keep_prob = 1 - self.drop_prob
        shape = (x.shape[0],) + (1,) * (x.dim() - 1)
        random_tensor = keep_prob + torch.rand(shape, dtype=x.dtype, device=x.device)
        random_tensor = random_tensor.floor()
        
        return x / keep_prob * random_tensor
