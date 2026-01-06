import requests
import time
import hmac
import hashlib
from urllib.parse import urlencode

class BinanceEarnAPI:
    def __init__(self, api_key, api_secret, testnet=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        # Earn APIs only work on mainnet - force mainnet URL
        self.base_url = "https://api.binance.com"
        
    def _generate_signature(self, params):
        """Génère la signature pour l'API Binance"""
        query_string = urlencode(params)
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, method, endpoint, params=None, signed=True):
        """Effectue une requête à l'API Binance"""
        # Skip Earn API calls if on testnet (not supported)
        if self.testnet:
            return None
            
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        headers = {
            'X-MBX-APIKEY': self.api_key
        }
        
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, data=params, headers=headers, timeout=10)
            
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            # Silencieux pour les erreurs 400 (permissions insuffisantes)
            return None
    
    def get_flexible_products(self):
        """Récupère la liste des produits Flexible (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/flexible/list"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def get_locked_products(self):
        """Récupère la liste des produits Locked (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/locked/list"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def subscribe_flexible_product(self, product_id, amount):
        """Souscrit à un produit Flexible Savings (nouvelle API)"""
        endpoint = "/sapi/v1/simple-earn/flexible/subscribe"
        params = {
            'productId': str(product_id),
            'amount': f"{float(amount):.8f}"
        }
        return self._make_request('POST', endpoint, params)
    
    def redeem_flexible_product(self, product_id, amount, type='FAST'):
        """Rachète un produit Flexible Savings (nouvelle API)"""
        endpoint = "/sapi/v1/simple-earn/flexible/redeem"
        params = {
            'productId': product_id,
            'amount': amount,
            'type': type
        }
        return self._make_request('POST', endpoint, params)
    
    def subscribe_locked_product(self, project_id, amount):
        """Souscrit à un produit Locked Staking (nouvelle API)"""
        endpoint = "/sapi/v1/simple-earn/locked/subscribe"
        params = {
            'projectId': project_id,
            'amount': amount
        }
        return self._make_request('POST', endpoint, params)
    
    def get_flexible_positions(self):
        """Récupère les positions Flexible (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/flexible/position"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def get_locked_positions(self):
        """Récupère les positions Locked (API 2025)"""
        endpoint = "/sapi/v1/simple-earn/locked/position"
        params = {}
        return self._make_request('GET', endpoint, params)
    
    def get_lending_account(self):
        """Récupère le compte Lending"""
        endpoint = "/sapi/v1/lending/union/account"
        return self._make_request('GET', endpoint)
    
    def find_usdt_flexible_product(self):
        """Trouve le produit USDT Flexible (API 2025)"""
        result = self.get_flexible_products()
        if result and 'rows' in result:
            for product in result['rows']:
                if product.get('asset') == 'USDT':
                    return {
                        'productId': product['productId'],
                        'asset': product['asset'],
                        'avgAnnualInterestRate': float(product.get('latestAnnualPercentageRate', 0)),
                        'canPurchase': product.get('canPurchase', True),
                        'canRedeem': product.get('canRedeem', True)
                    }
        return None
    
    def find_usdt_locked_product(self, duration_days=30):
        """Trouve un produit USDT Locked (API 2025)"""
        result = self.get_locked_products()
        if result and 'rows' in result:
            for product in result['rows']:
                if (product.get('asset') == 'USDT' and 
                    product.get('duration') == duration_days):
                    return {
                        'projectId': product['projectId'],
                        'asset': product['asset'],
                        'interestRate': float(product.get('interestRate', 0)),
                        'duration': product['duration'],
                        'lotSize': float(product.get('minPurchaseAmount', 1))
                    }
        return None