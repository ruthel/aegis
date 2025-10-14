import json
import os
from binance_spot_bot import BinanceSpotBot
from config import (
    BINANCE_MAINNET_API_KEY, BINANCE_MAINNET_API_SECRET,
    BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET
)

class EnvironmentManager:
    def __init__(self):
        self.current_env = "testnet"  # Par défaut testnet pour sécurité
        self.bot_instances = {}
        self.env_config_file = "environment_config.json"
        self.load_environment_config()
    
    def load_environment_config(self):
        """Charge la configuration d'environnement"""
        try:
            with open(self.env_config_file, 'r') as f:
                config = json.load(f)
                self.current_env = config.get('current_environment', 'testnet')
        except:
            # Créer le fichier de config par défaut
            self.save_environment_config()
    
    def save_environment_config(self):
        """Sauvegarde la configuration d'environnement"""
        config = {
            'current_environment': self.current_env,
            'last_switch': None,
            'environments': {
                'testnet': {
                    'name': 'Testnet (Simulation)',
                    'description': 'Environnement de test sans argent réel',
                    'safe': True
                },
                'mainnet': {
                    'name': 'Mainnet (Production)',
                    'description': 'Environnement de production avec argent réel',
                    'safe': False
                }
            }
        }
        
        with open(self.env_config_file, 'w') as f:
            json.dump(config, f, indent=2)
    
    def get_current_environment(self):
        """Retourne l'environnement actuel"""
        return self.current_env
    
    def get_environment_info(self):
        """Retourne les informations de l'environnement actuel"""
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
        """Crée une instance de bot pour l'environnement spécifié"""
        env = environment or self.current_env
        
        if env == "mainnet":
            api_key = BINANCE_MAINNET_API_KEY
            api_secret = BINANCE_MAINNET_API_SECRET
            testnet = False
        else:
            api_key = BINANCE_TESTNET_API_KEY
            api_secret = BINANCE_TESTNET_API_SECRET
            testnet = True
        
        # Vérifier que les clés API sont configurées
        if not api_key or not api_secret:
            raise ValueError(f"Clés API manquantes pour {env}")
        
        bot = BinanceSpotBot(api_key, api_secret, testnet)
        self.bot_instances[env] = bot
        
        return bot
    
    def switch_environment(self, new_env, confirmation_code=None):
        """Change d'environnement avec confirmation pour mainnet"""
        if new_env not in ['testnet', 'mainnet']:
            raise ValueError("Environnement invalide. Utilisez 'testnet' ou 'mainnet'")
        
        if new_env == self.current_env:
            return f"Déjà sur {new_env}"
        
        # Confirmation obligatoire pour passer en mainnet
        if new_env == "mainnet":
            if confirmation_code != "CONFIRM_MAINNET":
                raise ValueError("Confirmation requise pour mainnet. Utilisez le code: CONFIRM_MAINNET")
            
            print("⚠️  ATTENTION: Passage en mode MAINNET (argent réel)")
            print("🚨 Tous les trades seront exécutés avec de l'argent réel")
        
        old_env = self.current_env
        self.current_env = new_env
        self.save_environment_config()
        
        # Nettoyer l'ancienne instance de bot
        if old_env in self.bot_instances:
            if hasattr(self.bot_instances[old_env], 'websocket'):
                self.bot_instances[old_env].websocket.stop()
            del self.bot_instances[old_env]
        
        return f"Environnement changé: {old_env} → {new_env}"
    
    def get_bot(self):
        """Retourne l'instance de bot pour l'environnement actuel"""
        if self.current_env not in self.bot_instances:
            return self.create_bot_instance()
        
        return self.bot_instances[self.current_env]
    
    def validate_environment(self):
        """Valide que l'environnement actuel est correctement configuré"""
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
    
    def get_available_environments(self):
        """Retourne la liste des environnements disponibles"""
        return {
            'testnet': {
                'name': 'Testnet (Simulation)',
                'description': 'Environnement de test sans argent réel',
                'safe': True,
                'current': self.current_env == 'testnet'
            },
            'mainnet': {
                'name': 'Mainnet (Production)',
                'description': 'Environnement de production avec argent réel',
                'safe': False,
                'current': self.current_env == 'mainnet'
            }
        }