"""
Elastic Weight Consolidation (EWC)
==================================

Protège le modèle contre l'oubli catastrophique lors de 
l'apprentissage continu en pénalisant les changements aux
paramètres importants pour les tâches précédentes.

Basé sur: "Overcoming catastrophic forgetting in neural networks"
(Kirkpatrick et al., 2017)
"""

import torch
import torch.nn as nn
from torch.nn import functional as F
from typing import Dict, List, Optional, Tuple
import copy
import logging

logger = logging.getLogger(__name__)


class ElasticWeightConsolidation:
    """
    Implémentation de EWC pour l'apprentissage continu.
    
    Calcule l'importance de chaque paramètre via la Fisher Information
    et pénalise les changements aux paramètres importants.
    """
    
    def __init__(
        self,
        model: nn.Module,
        ewc_lambda: float = 1000.0,
        gamma: float = 0.95,
        online: bool = True
    ):
        """
        Args:
            model: Le modèle à protéger
            ewc_lambda: Poids de la régularisation EWC (plus grand = plus de protection)
            gamma: Decay factor pour l'importance des anciennes tâches
            online: Utiliser EWC online (accumule les Fisher de manière exponentielle)
        """
        self.model = model
        self.ewc_lambda = ewc_lambda
        self.gamma = gamma
        self.online = online
        
        # Stockage des paramètres optimaux et Fisher information
        self.optimal_params: Dict[str, torch.Tensor] = {}
        self.fisher_information: Dict[str, torch.Tensor] = {}
        
        # Compteur de tâches
        self.n_tasks = 0
        
        logger.info(f"EWC initialized with lambda={ewc_lambda}, gamma={gamma}, online={online}")
    
    def compute_fisher_information(
        self,
        data_loader,
        n_samples: int = 1000,
        device: str = 'cuda'
    ):
        """
        Calcule la Fisher Information Matrix (diagonale) pour chaque paramètre.
        
        La Fisher Information mesure l'importance d'un paramètre:
        F_i = E[(d log p(y|x; theta) / d theta_i)^2]
        
        Args:
            data_loader: DataLoader avec les données d'entraînement
            n_samples: Nombre d'échantillons pour estimer la Fisher
            device: Device pour le calcul
        """
        self.model.eval()
        
        # Initialiser la Fisher à zéro
        fisher = {
            name: torch.zeros_like(param, device=device)
            for name, param in self.model.named_parameters()
            if param.requires_grad
        }
        
        n_processed = 0
        
        for batch in data_loader:
            if n_processed >= n_samples:
                break
            
            # Récupérer les données
            if isinstance(batch, dict):
                sequences = batch['sequences'].to(device)
                masks = batch.get('masks')
                if masks is not None:
                    masks = masks.to(device)
            else:
                sequences = batch[0].to(device)
                masks = batch[1].to(device) if len(batch) > 1 else None
            
            batch_size = sequences.size(0)
            
            # Forward pass
            self.model.zero_grad()
            outputs = self.model(sequences, masks)
            
            # Pour chaque sortie, calculer les gradients
            for head_name, output in outputs.items():
                if not isinstance(output, torch.Tensor):
                    continue
                
                # Log-likelihood (on utilise la sortie directement comme log-prob)
                # Pour la classification binaire avec sigmoid
                log_prob = torch.log(output.clamp(min=1e-7, max=1-1e-7))
                
                # Calculer le gradient pour chaque sample
                for i in range(min(batch_size, n_samples - n_processed)):
                    self.model.zero_grad()
                    log_prob[i].sum().backward(retain_graph=True)
                    
                    # Accumuler le carré des gradients
                    for name, param in self.model.named_parameters():
                        if param.requires_grad and param.grad is not None:
                            fisher[name] += param.grad.data ** 2
            
            n_processed += batch_size
        
        # Normaliser par le nombre d'échantillons
        for name in fisher:
            fisher[name] /= n_processed
        
        # Mise à jour de la Fisher Information
        if self.online and self.n_tasks > 0:
            # EWC Online: moyenne exponentielle
            for name in fisher:
                if name in self.fisher_information:
                    self.fisher_information[name] = (
                        self.gamma * self.fisher_information[name] +
                        fisher[name]
                    )
                else:
                    self.fisher_information[name] = fisher[name]
        else:
            self.fisher_information = fisher
        
        # Sauvegarder les paramètres optimaux
        self.optimal_params = {
            name: param.data.clone()
            for name, param in self.model.named_parameters()
            if param.requires_grad
        }
        
        self.n_tasks += 1
        
        logger.info(f"Fisher Information computed on {n_processed} samples (task {self.n_tasks})")
    
    def penalty(self) -> torch.Tensor:
        """
        Calcule la pénalité EWC.
        
        L_EWC = (lambda/2) * sum_i(F_i * (theta_i - theta_i*)^2)
        
        Returns:
            Tensor scalar avec la pénalité EWC
        """
        if not self.fisher_information or not self.optimal_params:
            return torch.tensor(0.0)
        
        penalty = torch.tensor(0.0, device=next(self.model.parameters()).device)
        
        for name, param in self.model.named_parameters():
            if name in self.fisher_information and name in self.optimal_params:
                fisher = self.fisher_information[name]
                optimal = self.optimal_params[name]
                
                # Pénalité quadratique pondérée par la Fisher
                penalty += (fisher * (param - optimal) ** 2).sum()
        
        return (self.ewc_lambda / 2) * penalty
    
    def get_regularized_loss(
        self,
        base_loss: torch.Tensor
    ) -> torch.Tensor:
        """
        Ajoute la pénalité EWC à la loss de base.
        
        Args:
            base_loss: Loss de la tâche actuelle
            
        Returns:
            Loss totale avec régularisation EWC
        """
        ewc_penalty = self.penalty()
        return base_loss + ewc_penalty
    
    def get_parameter_importance(self) -> Dict[str, float]:
        """
        Retourne l'importance relative de chaque groupe de paramètres.
        
        Utile pour visualiser quels paramètres sont les plus critiques.
        """
        importance = {}
        
        total_fisher = 0.0
        for name, fisher in self.fisher_information.items():
            imp = fisher.sum().item()
            importance[name] = imp
            total_fisher += imp
        
        # Normaliser
        if total_fisher > 0:
            importance = {k: v / total_fisher for k, v in importance.items()}
        
        return importance
    
    def save(self, path: str):
        """Sauvegarde l'état EWC"""
        state = {
            'ewc_lambda': self.ewc_lambda,
            'gamma': self.gamma,
            'online': self.online,
            'n_tasks': self.n_tasks,
            'optimal_params': self.optimal_params,
            'fisher_information': self.fisher_information
        }
        torch.save(state, path)
        logger.info(f"EWC state saved to {path}")
    
    def load(self, path: str):
        """Charge l'état EWC"""
        state = torch.load(path)
        
        self.ewc_lambda = state['ewc_lambda']
        self.gamma = state['gamma']
        self.online = state['online']
        self.n_tasks = state['n_tasks']
        self.optimal_params = state['optimal_params']
        self.fisher_information = state['fisher_information']
        
        logger.info(f"EWC state loaded from {path}, {self.n_tasks} tasks")
