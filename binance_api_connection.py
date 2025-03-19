"""
Extension pour topgainers21.py - Implémentation des connexions API Binance
Ce fichier ajoute les fonctionnalités de connexion à l'API Binance sans modifier le code existant.
"""

import os
import sys
import asyncio
from logger_config import get_api_logger, get_error_logger
import json
import hmac
import hashlib
import time
import aiohttp
import socket
from websockets.client import connect as ws_connect # type: ignore
from websockets.exceptions import ConnectionClosed
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlencode

class BinanceAPIManager:
    """
    Gestionnaire de la connexion à l'API Binance.
    Cette classe encapsule toutes les fonctionnalités liées à l'API Binance,
    y compris l'authentification, les requêtes REST et les signatures.
    """
    def __init__(self, api_key: str = "", api_secret: str = "", execution_mode: Optional[int] = None, reference_currency: Optional[str] = None):
        # Initialisation des loggers
        self.logger = get_api_logger()
        self.error_logger = get_error_logger()
        
        # Clés API
        self.api_key = api_key or os.environ.get('BINANCE_API_KEY', '')
        self.api_secret = api_secret or os.environ.get('BINANCE_API_SECRET', '')
        
        # Mode d'exécution (0, 1 = testnet, 2 = mainnet)
        # Si non spécifié, utiliser la valeur par défaut 0 (test sur testnet)
        self.execution_mode = 0 if execution_mode is None else execution_mode
        
        # Monnaie de référence (USDT par défaut)
        self.reference_currency = reference_currency or os.environ.get('REFERENCE_CURRENCY', 'USDT')
        
        # Déterminer si on utilise le testnet basé sur le mode d'exécution
        self.use_testnet = self.execution_mode < 2  # Modes 0 et 1 utilisent testnet
        
        # URLs de base selon le mode (testnet ou mainnet)
        self.base_url = "https://testnet.binance.vision" if self.use_testnet else "https://api.binance.com"
        self.base_ws_url = "wss://testnet.binance.vision/ws" if self.use_testnet else "wss://stream.binance.com:9443/ws"
        
        # Session HTTP pour les requêtes API
        self.session = None
        
        # Log explicite pour montrer que les deux paramètres sont alignés
        env_type = 'testnet' if self.use_testnet else 'production'
        order_type = 'test' if self.execution_mode == 0 else 'réel'
        self.logger.info(f"BinanceAPIManager initialisé - Environnement: {env_type}, Exécution d'ordres: {order_type}, Monnaie de référence: {self.reference_currency}")

    async def init_session(self):
        """Initialise la session HTTP pour les requêtes API"""
        if self.session is None or self.session.closed:
            try:
                # Utilisation d'aiohttp sans resolver DNS pour éviter les problèmes sur Windows
                connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
                self.session = aiohttp.ClientSession(
                    headers={"X-MBX-APIKEY": self.api_key},
                    connector=connector
                )
                self.logger.info("Session HTTP initialisée")
            except Exception as e:
                self.logger.error(f"Erreur lors de l'initialisation de la session HTTP: {str(e)}")
                self.session = None
                raise

    async def close_session(self):
        """Ferme proprement la session HTTP"""
        if self.session and not self.session.closed:
            try:
                await self.session.close()
                self.logger.info("Session HTTP fermée")
            except Exception as e:
                self.logger.error(f"Erreur lors de la fermeture de la session HTTP: {str(e)}")
            finally:
                self.session = None

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """
        Génère la signature HMAC-SHA256 requise pour les requêtes authentifiées à l'API Binance
        
        Args:
            params: Dictionnaire des paramètres de la requête
            
        Returns:
            Signature encodée en hexadécimal
        """
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    async def _make_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Dict[str, Any]:
        """
        Effectue une requête HTTP à l'API Binance
        
        Args:
            method: Méthode HTTP (GET, POST, DELETE)
            endpoint: Point de terminaison de l'API
            params: Paramètres de la requête
            signed: Si True, ajoute une signature à la requête
            
        Returns:
            Réponse JSON de l'API
        """
        # S'assurer que la session est initialisée
        await self.init_session()
        
        # Vérification que la session existe
        if self.session is None or self.session.closed:
            raise RuntimeError("La session HTTP n'a pas pu être initialisée")
        
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        
        # Pour les requêtes signées, ajouter timestamp et signature
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        # NOUVEAU: Log pour déboguer les paramètres de requête d'ordre
        # Ajouter ce bloc pour journaliser spécifiquement les requêtes d'ordres
        if endpoint.endswith('/order') or endpoint.endswith('/order/test'):
            self.logger.info(f"Requête d'ordre - Méthode: {method}, Paramètres: {params}")
        
        try:
            if method == "GET":
                async with self.session.get(url, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            elif method == "POST":
                async with self.session.post(url, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            elif method == "DELETE":
                async with self.session.delete(url, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            else:
                raise ValueError(f"Méthode HTTP non supportée: {method}")
        except aiohttp.ClientResponseError as e:
            # MODIFIÉ: Capturer et journaliser le contenu de la réponse d'erreur
            try:
                # Tenter de récupérer le texte de la réponse, s'il est disponible
                error_text = await e.response.text() if hasattr(e, 'response') else "Erreur inconnue"
            except Exception:
                # En cas d'erreur lors de la récupération du texte
                error_text = "Impossible de récupérer le contenu de l'erreur"
            
            # Journal détaillé de l'erreur
            self.logger.error(f"Erreur API Binance: {e.status}, {error_text}")
            
            # NOUVEAU: Log plus détaillé pour déboguer les ordres rejetés
            if endpoint.endswith('/order') or endpoint.endswith('/order/test'):
                self.logger.error(f"Paramètres de l'ordre rejeté: {params}")
                # Ajouter les détails spécifiques aux ordres comme la quantité et le symbole
                symbol = params.get('symbol', 'INCONNU')
                quantity = params.get('quantity', 'INCONNU')
                self.logger.error(f"Détails de l'ordre rejeté - Symbole: {symbol}, Quantité: {quantity}")
            
            # Propager l'erreur avec le texte original pour permettre le traitement en amont
            raise
        except Exception as e:
            # Journal pour les autres types d'erreurs
            self.logger.error(f"Erreur lors de la requête API: {str(e)}")
            
            # NOUVEAU: Ajouter plus de contexte pour faciliter le débogage
            self.logger.error(f"Détails de la requête: URL={url}, Méthode={method}, Endpoint={endpoint}")
            
            # Propager l'exception
            raise
        
    async def get_account_info(self) -> Dict:
        """
        Récupère les informations du compte (soldes, permissions, etc.)
        
        Returns:
            Informations du compte Binance
        """
        return await self._make_request("GET", "/api/v3/account", signed=True)

    async def get_exchange_info(self) -> Dict:
        """
        Récupère les informations de l'exchange (règles, limites, symboles, etc.)
        
        Returns:
            Informations de l'exchange
        """
        return await self._make_request("GET", "/api/v3/exchangeInfo")

    async def get_server_time(self) -> Dict:
        """
        Récupère l'heure du serveur Binance
        
        Returns:
            Timestamp du serveur
        """
        return await self._make_request("GET", "/api/v3/time")

    async def place_test_order(self, symbol: str, side: str, type: str, quantity: float) -> Dict:
        """
        Place un ordre de test (ne crée pas d'ordre réel)
        """
        try:
            params = {
                "symbol": symbol,
                "side": side,
                "type": type,
                "quantity": quantity,
                "recvWindow": 5000
            }
            
            # Pour les ordres LIMIT, ajouter timeInForce et price
            if type == "LIMIT":
                params["timeInForce"] = "GTC"
                params["price"] = await self._get_current_price(symbol)
            
            endpoint = "/api/v3/order/test"
            
            # Log des paramètres de l'ordre pour le débogage
            self.logger.debug(f"Paramètres de l'ordre de test: {params}")
            
            return await self._make_request("POST", endpoint, params=params, signed=True)
        except Exception as e:
            self.logger.error(f"Erreur lors du placement de l'ordre test {symbol} {side}: {str(e)}")
            # Réémettre l'exception avec des informations plus détaillées
            raise Exception(f"Erreur d'ordre test pour {symbol}: {str(e)}")

    async def _get_current_price(self, symbol: str) -> float:
        """
        Récupère le prix actuel d'une paire pour les ordres LIMIT
        
        Args:
            symbol: Symbole de la paire
            
        Returns:
            Prix actuel
        """
        ticker = await self._make_request("GET", "/api/v3/ticker/price", {"symbol": symbol})
        return float(ticker["price"])

    async def test_connection(self) -> bool:
        """
        Teste la connexion à l'API Binance
        
        Returns:
            True si la connexion est établie avec succès
        """
        try:
            # Ping pour tester la connectivité
            await self._make_request("GET", "/api/v3/ping")
            
            # Vérifier si les clés API sont correctes en récupérant les informations du compte
            if self.api_key and self.api_secret:
                await self.get_account_info()
                self.logger.info("Test de connexion API réussi avec authentification")
            else:
                self.logger.info("Test de connexion API réussi (sans authentification)")
            
            return True
        except Exception as e:
            self.logger.error(f"Échec du test de connexion API: {str(e)}")
            return False
