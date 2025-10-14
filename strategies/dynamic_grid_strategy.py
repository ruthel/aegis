import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np

@dataclass
class GridConfig:
    range_percent: float
    num_levels: int
    min_profit_percent: float
    recalibration_hours: int

class DynamicGridStrategy:
    def __init__(self, binance_client, symbol: str = "BTCUSDT", base_amount: float = 10.0):
        # Support pour BinanceSpotBot et client direct
        if hasattr(binance_client, 'client'):
            self.client = binance_client.client
        elif hasattr(binance_client, 'exchange'):
            self.client = binance_client.exchange
        else:
            self.client = binance_client
        self.symbol = symbol
        self.base_amount = base_amount
        self.logger = logging.getLogger(__name__)
        
        # Configuration dynamique
        self.volatility_configs = {
            'low': GridConfig(1.5, 12, 0.3, 6),      # Volatilité < 2%
            'medium': GridConfig(3.0, 8, 0.5, 4),   # Volatilité 2-5%
            'high': GridConfig(6.0, 6, 0.8, 2)      # Volatilité > 5%
        }
        
        self.current_config = self.volatility_configs['medium']
        self.grid_orders = {}
        self.last_recalibration = datetime.now()
        self.volatility_history = []
        self.center_price = None
        self.active = False
        self.auto_recalibration = True
        self.is_running = False
        
    def calculate_volatility(self, hours: int = 24) -> float:
        """Calcule la volatilité sur les dernières heures"""
        try:
            # Utiliser ccxt pour récupérer les données
            ohlcv = self.client.fetch_ohlcv(self.symbol, '1h', limit=hours)
            
            prices = [float(candle[4]) for candle in ohlcv]  # Prix de clôture
            if len(prices) < 2:
                return 3.0
                
            returns = np.diff(np.log(prices))
            volatility = np.std(returns) * np.sqrt(24) * 100  # Annualisée en %
            
            self.volatility_history.append({
                'timestamp': datetime.now(),
                'volatility': volatility
            })
            
            return volatility
            
        except Exception as e:
            self.logger.error(f"Erreur calcul volatilité: {e}")
            return 3.0  # Valeur par défaut
    
    def get_optimal_config(self, volatility: float) -> GridConfig:
        """Détermine la configuration optimale selon la volatilité"""
        if volatility < 2.0:
            return self.volatility_configs['low']
        elif volatility < 5.0:
            return self.volatility_configs['medium']
        else:
            return self.volatility_configs['high']
    
    def get_current_price(self) -> float:
        """Récupère le prix actuel"""
        ticker = self.client.fetch_ticker(self.symbol)
        return float(ticker['last'])
    
    def should_recalibrate(self) -> bool:
        """Vérifie si une recalibration est nécessaire"""
        time_elapsed = datetime.now() - self.last_recalibration
        time_threshold = timedelta(hours=self.current_config.recalibration_hours)
        
        if time_elapsed > time_threshold:
            return True
            
        # Recalibration si volatilité change significativement
        current_vol = self.calculate_volatility(6)
        optimal_config = self.get_optimal_config(current_vol)
        
        return optimal_config != self.current_config
    
    def cancel_all_orders(self):
        """Annule tous les ordres de la grille"""
        try:
            for order_id in list(self.grid_orders.keys()):
                self.client.cancel_order(order_id, self.symbol)
                del self.grid_orders[order_id]
            self.logger.info("Tous les ordres de grille annulés")
        except Exception as e:
            self.logger.error(f"Erreur annulation ordres: {e}")
    
    def create_grid_levels(self, center_price: float, config: GridConfig) -> Tuple[List[float], List[float]]:
        """Crée les niveaux d'achat et de vente"""
        range_amount = center_price * config.range_percent / 100
        
        # Niveaux d'achat (en dessous du centre)
        buy_levels = []
        for i in range(1, config.num_levels // 2 + 1):
            level = center_price - (range_amount * i / (config.num_levels // 2))
            buy_levels.append(level)
        
        # Niveaux de vente (au dessus du centre)
        sell_levels = []
        for i in range(1, config.num_levels // 2 + 1):
            level = center_price + (range_amount * i / (config.num_levels // 2))
            sell_levels.append(level)
        
        return buy_levels, sell_levels
    
    def place_grid_orders(self, buy_levels: List[float], sell_levels: List[float]):
        """Place les ordres de la grille"""
        try:
            # Ordres d'achat
            for price in buy_levels:
                order = self.client.create_limit_buy_order(
                    self.symbol,
                    self.base_amount / price,
                    price
                )
                self.grid_orders[order['id']] = {
                    'side': 'BUY',
                    'price': price,
                    'quantity': self.base_amount / price
                }
            
            # Ordres de vente
            for price in sell_levels:
                order = self.client.create_limit_sell_order(
                    self.symbol,
                    self.base_amount / price,
                    price
                )
                self.grid_orders[order['id']] = {
                    'side': 'SELL',
                    'price': price,
                    'quantity': self.base_amount / price
                }
                
            self.logger.info(f"Grille créée: {len(buy_levels)} achats, {len(sell_levels)} ventes")
            
        except Exception as e:
            self.logger.error(f"Erreur création grille: {e}")
    
    def recalibrate_grid(self):
        """Recalibre la grille selon les nouvelles conditions"""
        try:
            self.logger.info("🔄 Recalibration de la grille dynamique...")
            
            # Calcul nouvelle volatilité
            volatility = self.calculate_volatility(12)
            new_config = self.get_optimal_config(volatility)
            
            # Annulation anciens ordres
            self.cancel_all_orders()
            
            # Nouveau prix centre
            self.center_price = self.get_current_price()
            
            # Nouvelle configuration
            self.current_config = new_config
            self.last_recalibration = datetime.now()
            
            # Création nouvelle grille
            buy_levels, sell_levels = self.create_grid_levels(
                self.center_price, self.current_config
            )
            self.place_grid_orders(buy_levels, sell_levels)
            
            self.logger.info(f"✅ Grille recalibrée - Vol: {volatility:.2f}% - Range: ±{new_config.range_percent}% - Niveaux: {new_config.num_levels}")
            
        except Exception as e:
            self.logger.error(f"Erreur recalibration: {e}")
    
    def force_recalibrate(self):
        """Force une recalibration manuelle"""
        self.recalibrate_grid()
    
    def set_auto_recalibration(self, enabled: bool):
        """Active/désactive la recalibration automatique"""
        self.auto_recalibration = enabled
        self.logger.info(f"Recalibration auto: {'ON' if enabled else 'OFF'}")
    
    def handle_filled_order(self, order_id: str):
        """Gère un ordre exécuté"""
        if order_id not in self.grid_orders:
            return
            
        filled_order = self.grid_orders[order_id]
        del self.grid_orders[order_id]
        
        try:
            # Crée l'ordre opposé
            if filled_order['side'] == 'BUY':
                # Ordre d'achat exécuté -> créer ordre de vente
                sell_price = filled_order['price'] * (1 + self.current_config.min_profit_percent / 100)
                
                order = self.client.create_limit_sell_order(
                    self.symbol,
                    filled_order['quantity'],
                    sell_price
                )
                
                self.grid_orders[order['id']] = {
                    'side': 'SELL',
                    'price': sell_price,
                    'quantity': filled_order['quantity']
                }
                
            else:
                # Ordre de vente exécuté -> créer ordre d'achat
                buy_price = filled_order['price'] * (1 - self.current_config.min_profit_percent / 100)
                
                order = self.client.create_limit_buy_order(
                    self.symbol,
                    self.base_amount / buy_price,
                    buy_price
                )
                
                self.grid_orders[order['id']] = {
                    'side': 'BUY',
                    'price': buy_price,
                    'quantity': self.base_amount / buy_price
                }
            
            self.logger.info(f"🔄 Cycle complété - {filled_order['side']} à {filled_order['price']:.2f}")
            
        except Exception as e:
            self.logger.error(f"Erreur gestion ordre exécuté: {e}")
    
    def start(self):
        """Démarre la stratégie Grid Dynamique"""
        try:
            self.active = True
            self.is_running = True
            self.logger.info("🚀 Démarrage Grid Dynamique")
            
            # Configuration initiale
            volatility = self.calculate_volatility()
            self.current_config = self.get_optimal_config(volatility)
            self.center_price = self.get_current_price()
            
            # Création grille initiale
            buy_levels, sell_levels = self.create_grid_levels(
                self.center_price, self.current_config
            )
            self.place_grid_orders(buy_levels, sell_levels)
            
            self.logger.info(f"✅ Grid Dynamique active - Vol: {volatility:.2f}% - Range: ±{self.current_config.range_percent}%")
            
        except Exception as e:
            self.logger.error(f"Erreur démarrage Grid Dynamique: {e}")
            self.active = False
            self.is_running = False
    
    def stop(self):
        """Arrête la stratégie"""
        self.active = False
        self.is_running = False
        self.cancel_all_orders()
        self.logger.info("🛑 Grid Dynamique arrêtée")
    
    def run(self):
        """Boucle principale de la stratégie"""
        import time
        while self.active:
            try:
                # Vérification recalibration (si auto activé)
                if self.auto_recalibration and self.should_recalibrate():
                    self.recalibrate_grid()
                
                # Vérification ordres exécutés
                open_orders = self.client.fetch_open_orders(self.symbol)
                open_order_ids = {str(order['id']) for order in open_orders}
                
                for order_id in list(self.grid_orders.keys()):
                    if order_id not in open_order_ids:
                        self.handle_filled_order(order_id)
                
                time.sleep(30)  # Vérification toutes les 30s
                
            except Exception as e:
                self.logger.error(f"Erreur boucle Grid Dynamique: {e}")
                time.sleep(60)
    
    def get_status(self) -> Dict:
        """Retourne le statut de la stratégie"""
        return {
            'active': self.active,
            'symbol': self.symbol,
            'center_price': self.center_price,
            'current_config': {
                'range_percent': self.current_config.range_percent,
                'num_levels': self.current_config.num_levels,
                'min_profit_percent': self.current_config.min_profit_percent
            },
            'active_orders': len(self.grid_orders),
            'last_recalibration': self.last_recalibration.isoformat(),
            'volatility_history': self.volatility_history[-10:]  # 10 dernières mesures
        }