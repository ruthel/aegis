"""Gestionnaire d'environnement simplifié utilisant .env"""
import os
from config import CURRENT_ENVIRONMENT, BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET

class EnvironmentManager:
    def __init__(self):
        self.current_env = CURRENT_ENVIRONMENT
        self.bot_instances = {}
    
    def get_current_environment(self):
        return self.current_env
    
    def get_environment_info(self):
        env_info = {
            'testnet': {
                'name': 'Testnet (Simulation)',
                'description': 'Environnement de test sans argent réel',
                'safe': True,
                'color': '#00ff00'
            },
            'mainnet': {
                'name': 'Mainnet (Production)', 
                'description': 'Environnement de production avec argent réel',
                'safe': False,
                'color': '#ff4444'
            }
        }
        return env_info.get(self.current_env, env_info['testnet'])
    
    def create_bot_instance(self, environment=None):
        from core.binance_spot_bot import BinanceSpotBot
        
        env = environment or self.current_env
        
        if not BINANCE_API_KEY or not BINANCE_API_SECRET:
            raise ValueError(f"Clés API manquantes dans .env")
        
        # Utiliser TESTNET depuis .env
        bot = BinanceSpotBot(BINANCE_API_KEY, BINANCE_API_SECRET, TESTNET)
        self.bot_instances[env] = bot
        
        return bot
    
    def get_bot(self):
        if self.current_env not in self.bot_instances:
            return self.create_bot_instance()
        return self.bot_instances[self.current_env]
    
    def validate_environment(self):
        try:
            bot = self.get_bot()
            balance = bot.get_balance()
            
            return {
                'valid': True,
                'environment': self.current_env,
                'balance': balance.get('USDT', {}).get('free', 0),
                'message': f"Connexion {self.current_env} OK"
            }
        except Exception as e:
            return {
                'valid': False,
                'environment': self.current_env,
                'error': str(e),
                'message': f"Erreur connexion {self.current_env}"
            }