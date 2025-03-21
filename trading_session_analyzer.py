#!/usr/bin/env python3
# trading_session_analyzer.py
# Outil d'analyse post-trading pour extraire les données de Binance

import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta
import hmac
import hashlib
import time
import uuid
from urllib.parse import urlencode
import aiohttp
from dotenv import load_dotenv
import json
from typing import Dict, List, Any, Optional, Tuple, Set
import pandas as pd
from decimal import Decimal
import matplotlib.pyplot as plt
from logger_config import get_trading_logger, setup_logger, log_separator, ConsoleTable, Colors

# Charger les variables d'environnement depuis .env
load_dotenv()

class BinanceAnalyzer:
    """Classe pour analyser les données de trading Binance après une session"""
    
    def __init__(self, reference_currency="USDC", days_back=1, execution_mode=2):
        """
        Initialise l'analyseur de session de trading
        
        Args:
            reference_currency: Monnaie de référence (USDC, USDT, etc.)
            days_back: Nombre de jours à analyser en arrière (peut être une valeur décimale pour les heures)
            execution_mode: Mode d'exécution (0=test sur testnet, 1=réel sur testnet, 2=réel sur mainnet)
        """
        # Configuration
        self.reference_currency = reference_currency
        self.days_back = days_back
        self.execution_mode = execution_mode
        
        # Générer un ID de session unique pour tracer cette analyse
        self.session_id = str(uuid.uuid4())
        self.logger = get_trading_logger()
        
        # Calcul du texte de période pour l'affichage
        if days_back < 1:
            hours = int(days_back * 24)
            self.period_text = f"{hours} heure{'s' if hours > 1 else ''}"
        else:
            self.period_text = f"{int(days_back) if days_back == int(days_back) else days_back} jour{'s' if days_back > 1 else ''}"
            
        # Stockage pour la capture des snapshots
        self.initial_snapshot = None
        self.final_snapshot = None
        
        # Dictionnaire pour stocker les positions complètes (entrée + sortie)
        # Clé: ID unique de position, Valeur: Données consolidées
        self.complete_positions = {}
        
        # Clés API
        self.api_key = os.environ.get('BINANCE_API_KEY', '')
        self.api_secret = os.environ.get('BINANCE_API_SECRET', '')
        
        # Sélectionner l'URL de base selon le mode d'exécution
        self.use_testnet = execution_mode < 2
        self.base_url = "https://testnet.binance.vision" if self.use_testnet else "https://api.binance.com"
        
        # Session HTTP pour les requêtes API
        self.session = None
        
        # Logger
        self.logger = get_trading_logger()
        
        # Données collectées
        self.account_info = None
        self.trades = []
        self.orders = []
        self.deposits_withdrawals = []
        
    async def init_session(self):
        """Initialise la session HTTP pour les requêtes API"""
        if self.session is None or self.session.closed:
            try:
                # Utilisation d'aiohttp
                connector = aiohttp.TCPConnector(ssl=True)
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
        
        try:
            if method == "GET":
                async with self.session.get(url, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            elif method == "POST":
                async with self.session.post(url, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            else:
                raise ValueError(f"Méthode HTTP non supportée: {method}")
        except aiohttp.ClientResponseError as e:
            self.logger.error(f"Erreur API Binance: {e.status}")
            error_text = await e.response.text() if hasattr(e, 'response') else "Erreur inconnue"
            self.logger.error(f"Détail de l'erreur: {error_text}")
            raise
        except Exception as e:
            self.logger.error(f"Erreur lors de la requête API: {str(e)}")
            raise
    
    async def get_account_info(self) -> Dict:
        """
        Récupère les informations du compte (soldes, permissions, etc.)
        
        Returns:
            Informations du compte Binance
        """
        account_info = await self._make_request("GET", "/api/v3/account", signed=True)
        self.account_info = account_info
        
        # Log détaillé des informations du compte pour débogage
        self.logger.debug(f"Session {self.session_id}: Informations du compte récupérées")
        
        return account_info
        
    async def capture_account_snapshot(self) -> Dict:
        """
        Capture un snapshot complet de l'état du compte
        
        Returns:
            Dictionnaire contenant le snapshot complet
        """
        try:
            # Récupérer les informations du compte
            account_info = await self.get_account_info()
            
            # Créer le snapshot avec horodatage précis
            snapshot = {
                'timestamp': datetime.now().isoformat(),
                'session_id': self.session_id,
                'balances': account_info.get('balances', []),
                'permissions': account_info.get('permissions', []),
                'account_type': account_info.get('accountType', 'unknown'),
                'reference_currency': self.reference_currency,
                'reference_balance': self.get_reference_currency_balance()
            }
            
            # Log de confirmation
            self.logger.info(f"Snapshot du compte capturé - Solde {self.reference_currency}: {snapshot['reference_balance']}")
            
            return snapshot
            
        except Exception as e:
            self.logger.error(f"Erreur lors de la capture du snapshot: {e}")
            return {
                'timestamp': datetime.now().isoformat(),
                'session_id': self.session_id,
                'error': str(e)
            }
    
    async def get_all_trades(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Récupère tous les trades historiques avec déduplication et organisation
        
        Args:
            symbol: Symbole spécifique (ex: BTCUSDC) ou None pour tous
            
        Returns:
            Liste des trades après déduplication
        """
        # Calculer la date de début (jours ou heures en arrière)
        start_time = int((datetime.now() - timedelta(days=self.days_back)).timestamp() * 1000)
        
        all_trades = []
        processed_pairs = set()  # Pour suivre les paires déjà traitées
        
        if symbol:
            # Récupérer les trades pour un symbole spécifique
            params = {"symbol": symbol, "startTime": start_time}
            trades = await self._make_request("GET", "/api/v3/myTrades", params=params, signed=True)
            all_trades.extend(trades)
            processed_pairs.add(symbol)
        else:
            # Récupérer les soldes de tous les actifs
            account_info = await self.get_account_info()
            
            # Filtrer uniquement les actifs avec un solde non nul ou récents
            assets = [balance['asset'] for balance in account_info['balances'] 
                     if float(balance['free']) > 0 or float(balance['locked']) > 0]
            
            # Récupérer les symboles liés à la monnaie de référence
            exchange_info = await self._make_request("GET", "/api/v3/exchangeInfo")
            all_symbols = [symbol_info['symbol'] for symbol_info in exchange_info['symbols']
                         if symbol_info['status'] == 'TRADING']
            
            # Construire la liste des paires à vérifier
            pairs_to_check = []
            
            # Ajouter les paires où l'actif est la base (BTCUSDC)
            for asset in assets:
                if asset != self.reference_currency:
                    potential_pair = f"{asset}{self.reference_currency}"
                    if potential_pair in all_symbols:
                        pairs_to_check.append(potential_pair)
            
            # Ajouter les paires où l'actif est la quote (USDCBTC)
            if self.reference_currency in assets:
                for symbol in all_symbols:
                    if symbol.endswith(self.reference_currency):
                        pairs_to_check.append(symbol)
            
            # Récupérer les trades pour chaque paire
            for pair in pairs_to_check:
                if pair in processed_pairs:
                    continue  # Éviter les doublons
                    
                processed_pairs.add(pair)
                try:
                    params = {"symbol": pair, "startTime": start_time}
                    trades = await self._make_request("GET", "/api/v3/myTrades", params=params, signed=True)
                    if trades:
                        all_trades.extend(trades)
                        self.logger.info(f"Récupéré {len(trades)} trades pour {pair}")
                except Exception as e:
                    self.logger.error(f"Erreur lors de la récupération des trades pour {pair}: {e}")
        
        # Déduplication et normalisation des trades
        deduplicated_trades = self._deduplicate_trades(all_trades)
        
        # Trier les trades par date
        deduplicated_trades.sort(key=lambda x: x['time'])
        
        # Essayer de regrouper les trades en positions complètes (entrée/sortie)
        self._reconstruct_complete_positions(deduplicated_trades)
        
        self.trades = deduplicated_trades
        return deduplicated_trades
        
    def _deduplicate_trades(self, trades: List[Dict]) -> List[Dict]:
        """
        Déduplique les trades en se basant sur l'ID d'ordre et normalise leur format
        
        Args:
            trades: Liste brute des trades à traiter
            
        Returns:
            Liste de trades dédupliqués et normalisés
        """
        unique_trades = {}
        processed_ids = set()
        
        for trade in trades:
            # Créer un identifiant unique pour ce trade
            trade_id = str(trade.get('id', ''))
            
            if trade_id in processed_ids:
                continue
                
            processed_ids.add(trade_id)
            
            # Normaliser et enrichir le trade
            normalized_trade = trade.copy()
            
            # Ajouter des métadonnées utiles
            normalized_trade['_normalized'] = True
            normalized_trade['_session_id'] = self.session_id
            
            # Calculer explicitement les valeurs en monnaie de référence
            if 'price' in trade and 'qty' in trade:
                price = float(trade['price'])
                qty = float(trade['qty'])
                
                # Calculer la valeur totale si non présente
                if 'quoteQty' not in trade:
                    normalized_trade['quoteQty'] = price * qty
            
            # Stocker le trade normalisé
            unique_trades[trade_id] = normalized_trade
            
        self.logger.info(f"Déduplication: {len(trades)} trades bruts -> {len(unique_trades)} trades uniques")
        return list(unique_trades.values())
    
    def _reconstruct_complete_positions(self, trades: List[Dict]) -> None:
        """
        Tente de reconstruire les positions complètes (entrée + sortie) à partir des trades individuels
        
        Args:
            trades: Liste des trades normalisés
        """
        # Grouper les trades par symbole
        trades_by_symbol = {}
        for trade in trades:
            symbol = trade.get('symbol', '')
            if symbol not in trades_by_symbol:
                trades_by_symbol[symbol] = []
            trades_by_symbol[symbol].append(trade)
        
        # Pour chaque symbole, essayer de reconstruire les positions
        for symbol, symbol_trades in trades_by_symbol.items():
            # Trier les trades par horodatage
            symbol_trades.sort(key=lambda x: x['time'])
            
            # Créer une pile de trades non associés
            unassociated_buys = []
            unassociated_sells = []
            
            # Classifier les trades
            for trade in symbol_trades:
                if trade.get('isBuyer', False):
                    unassociated_buys.append(trade)
                else:
                    unassociated_sells.append(trade)
            
            # Essayer d'associer les achats et ventes
            for buy_trade in unassociated_buys[:]:
                buy_time = buy_trade['time']
                buy_qty = float(buy_trade['qty'])
                
                # Chercher une vente correspondante (après l'achat)
                matching_sells = [sell for sell in unassociated_sells if sell['time'] > buy_time]
                
                if matching_sells:
                    # Prendre la vente la plus proche temporellement
                    sell_trade = min(matching_sells, key=lambda x: abs(x['time'] - buy_time))
                    
                    # Créer une position complète
                    position_id = f"pos_{symbol}_{buy_trade['id']}_{sell_trade['id']}"
                    
                    self.complete_positions[position_id] = {
                        'symbol': symbol,
                        'entry': buy_trade,
                        'exit': sell_trade,
                        'entry_time': datetime.fromtimestamp(buy_time / 1000).isoformat(),
                        'exit_time': datetime.fromtimestamp(sell_trade['time'] / 1000).isoformat(),
                        'duration_ms': sell_trade['time'] - buy_time,
                        'pnl': self._calculate_position_pnl(buy_trade, sell_trade)
                    }
                    
                    # Retirer les trades associés des listes
                    unassociated_buys.remove(buy_trade)
                    unassociated_sells.remove(sell_trade)
        
        self.logger.info(f"Positions reconstruites: {len(self.complete_positions)} positions complètes identifiées")
    
    def _calculate_position_pnl(self, entry_trade: Dict, exit_trade: Dict) -> Dict:
        """
        Calcule le P/L d'une position complète de manière standardisée
        
        Args:
            entry_trade: Trade d'entrée (achat)
            exit_trade: Trade de sortie (vente)
            
        Returns:
            Dictionnaire avec P/L brut, frais et P/L net
        """
        # Extraire les données nécessaires
        entry_price = float(entry_trade.get('price', 0))
        exit_price = float(exit_trade.get('price', 0))
        
        entry_qty = float(entry_trade.get('qty', 0))
        exit_qty = float(exit_trade.get('qty', 0))
        
        # Utiliser la quantité la plus petite (en cas de fill partiel)
        quantity = min(entry_qty, exit_qty)
        
        # Calculer les valeurs en monnaie de référence
        entry_value = entry_price * quantity
        exit_value = exit_price * quantity
        
        # Calculer le P/L brut (avant frais)
        gross_pnl = exit_value - entry_value
        
        # Calculer les frais
        entry_fee = float(entry_trade.get('commission', 0))
        exit_fee = float(exit_trade.get('commission', 0))
        total_fees = entry_fee + exit_fee
        
        # Calculer le P/L net (après frais)
        net_pnl = gross_pnl - total_fees
        
        # Calculer le ROI
        roi_percentage = (net_pnl / entry_value) * 100 if entry_value > 0 else 0
        
        return {
            'gross_pnl': gross_pnl,
            'entry_fee': entry_fee,
            'exit_fee': exit_fee,
            'total_fees': total_fees,
            'net_pnl': net_pnl,
            'roi_percentage': roi_percentage,
            'entry_value': entry_value,
            'exit_value': exit_value
        }
    
    async def get_open_orders(self) -> List[Dict]:
        """
        Récupère tous les ordres ouverts
        
        Returns:
            Liste des ordres ouverts
        """
        open_orders = await self._make_request("GET", "/api/v3/openOrders", signed=True)
        return open_orders
    
    async def get_order_history(self) -> List[Dict]:
        """
        Récupère l'historique des ordres
        
        Returns:
            Liste des ordres historiques
        """
        # Calculer la date de début (jours ou heures en arrière)
        start_time = int((datetime.now() - timedelta(days=self.days_back)).timestamp() * 1000)
        
        all_orders = []
        
        # Récupérer les symboles des trades récents
        symbols = set()
        if self.trades:
            symbols = set(trade['symbol'] for trade in self.trades)
        
        # Si pas de trades, utiliser les paires avec la monnaie de référence
        if not symbols:
            exchange_info = await self._make_request("GET", "/api/v3/exchangeInfo")
            symbols = set(symbol_info['symbol'] for symbol_info in exchange_info['symbols']
                        if symbol_info['status'] == 'TRADING' and 
                        symbol_info['symbol'].endswith(self.reference_currency))
        
        # Récupérer les ordres pour chaque symbole
        for symbol in symbols:
            try:
                params = {"symbol": symbol, "startTime": start_time}
                orders = await self._make_request("GET", "/api/v3/allOrders", params=params, signed=True)
                if orders:
                    all_orders.extend(orders)
                    self.logger.info(f"Récupéré {len(orders)} ordres pour {symbol}")
            except Exception as e:
                self.logger.error(f"Erreur lors de la récupération des ordres pour {symbol}: {e}")
        
        # Trier les ordres par date
        all_orders.sort(key=lambda x: x['time'])
        self.orders = all_orders
        return all_orders
    
    def get_balances(self) -> List[Dict]:
        """
        Retourne les soldes courants
        
        Returns:
            Liste de dictionnaires contenant les détails des soldes
        """
        if not self.account_info:
            raise ValueError("Les informations du compte n'ont pas été récupérées")
        
        # Filtrer uniquement les actifs avec un solde non nul
        balances = [
            {
                'asset': balance['asset'],
                'free': float(balance['free']),
                'locked': float(balance['locked']),
                'total': float(balance['free']) + float(balance['locked'])
            }
            for balance in self.account_info['balances']
            if float(balance['free']) > 0 or float(balance['locked']) > 0
        ]
        
        # Trier par valeur totale décroissante
        return sorted(balances, key=lambda x: x['total'], reverse=True)
    
    def get_reference_currency_balance(self) -> float:
        """
        Retourne le solde de la monnaie de référence
        
        Returns:
            Solde total de la monnaie de référence
        """
        balances = self.get_balances()
        for balance in balances:
            if balance['asset'] == self.reference_currency:
                return balance['total']
        return 0.0
    
    def calculate_pnl(self) -> Dict[str, float]:
        """
        Calcule le profit/perte pour la période analysée
        Utilise les positions complètes reconstruites quand disponibles, 
        sinon utilise la méthode traditionnelle
        
        Returns:
            Dictionnaire contenant les statistiques P/L
        """
        # Si nous avons des positions complètes reconstruites, les utiliser
        if self.complete_positions:
            return self._calculate_pnl_from_positions()
        # Sinon, utiliser la méthode traditionnelle basée sur les trades individuels
        else:
            return self._calculate_pnl_from_trades()
    
    def _calculate_pnl_from_positions(self) -> Dict[str, float]:
        """
        Calcule le P/L basé sur les positions complètes reconstruites (méthode préférée)
        
        Returns:
            Dictionnaire contenant les statistiques P/L
        """
        if not self.complete_positions:
            return {'total_pnl': 0.0, 'realized_pnl': 0.0, 'fees': 0.0, 'net_pnl': 0.0}
        
        total_pnl = 0.0
        total_fees = 0.0
        
        # Grouper les positions par symbole
        positions_by_symbol = {}
        for position_id, position in self.complete_positions.items():
            symbol = position['symbol']
            if symbol not in positions_by_symbol:
                positions_by_symbol[symbol] = []
            positions_by_symbol[symbol].append(position)
        
        # Calculer le P/L pour chaque symbole
        symbol_pnl = {}
        
        for symbol, positions in positions_by_symbol.items():
            symbol_realized_pnl = 0.0
            symbol_fees = 0.0
            
            for position in positions:
                pnl_data = position['pnl']
                symbol_realized_pnl += pnl_data['gross_pnl']
                symbol_fees += pnl_data['total_fees']
            
            symbol_pnl[symbol] = {
                'realized_pnl': symbol_realized_pnl,
                'fees': symbol_fees,
                'net_pnl': symbol_realized_pnl - symbol_fees
            }
            
            total_pnl += symbol_realized_pnl
            total_fees += symbol_fees
        
        self.logger.info(f"P/L calculé à partir de {len(self.complete_positions)} positions complètes")
        
        return {
            'total_pnl': total_pnl,
            'realized_pnl': total_pnl,
            'fees': total_fees,
            'net_pnl': total_pnl - total_fees,
            'by_symbol': symbol_pnl,
            'calculation_method': 'positions'
        }
    
    def _calculate_pnl_from_trades(self) -> Dict[str, float]:
        """
        Calcule le P/L basé sur les trades individuels (méthode traditionnelle)
        
        Returns:
            Dictionnaire contenant les statistiques P/L
        """
        if not self.trades:
            return {'total_pnl': 0.0, 'realized_pnl': 0.0, 'fees': 0.0, 'net_pnl': 0.0}
        
        total_pnl = 0.0
        total_fees = 0.0
        
        # Regrouper les trades par symbole
        trades_by_symbol = {}
        for trade in self.trades:
            symbol = trade['symbol']
            if symbol not in trades_by_symbol:
                trades_by_symbol[symbol] = []
            trades_by_symbol[symbol].append(trade)
        
        # Calculer le P/L pour chaque symbole
        symbol_pnl = {}
        for symbol, symbol_trades in trades_by_symbol.items():
            # Trier par date
            symbol_trades.sort(key=lambda x: x['time'])
            
            buy_qty = 0
            buy_value = 0
            sell_qty = 0
            sell_value = 0
            symbol_fees = 0
            
            for trade in symbol_trades:
                price = float(trade['price'])
                qty = float(trade['qty'])
                
                # Utiliser quoteQty si disponible, sinon calculer
                if 'quoteQty' in trade:
                    quote_qty = float(trade['quoteQty'])
                else:
                    quote_qty = price * qty
                
                fee_amount = float(trade.get('commission', 0))
                is_buyer = trade.get('isBuyer', False)
                
                # Calculer les frais
                symbol_fees += fee_amount
                
                if is_buyer:
                    # Achat
                    buy_qty += qty
                    buy_value += quote_qty
                else:
                    # Vente
                    sell_qty += qty
                    sell_value += quote_qty
            
            # Calculer le P/L réalisé pour ce symbole
            if buy_qty > 0 and sell_qty > 0:
                realized_qty = min(buy_qty, sell_qty)
                avg_buy_price = buy_value / buy_qty if buy_qty > 0 else 0
                avg_sell_price = sell_value / sell_qty if sell_qty > 0 else 0
                
                symbol_realized_pnl = (avg_sell_price - avg_buy_price) * realized_qty
                symbol_pnl[symbol] = {
                    'realized_pnl': symbol_realized_pnl,
                    'fees': symbol_fees,
                    'net_pnl': symbol_realized_pnl - symbol_fees,
                    'buy_qty': buy_qty,
                    'sell_qty': sell_qty,
                    'buy_value': buy_value,
                    'sell_value': sell_value
                }
                
                total_pnl += symbol_realized_pnl
                total_fees += symbol_fees
        
        self.logger.info(f"P/L calculé à partir de {len(self.trades)} trades individuels")
        
        return {
            'total_pnl': total_pnl,
            'realized_pnl': total_pnl,
            'fees': total_fees,
            'net_pnl': total_pnl - total_fees,
            'by_symbol': symbol_pnl,
            'calculation_method': 'trades'
        }
    
    def get_daily_pnl(self) -> Dict[str, float]:
        """
        Calcule le profit/perte par jour
        
        Returns:
            Dictionnaire avec les dates comme clés et le P/L comme valeurs
        """
        if not self.trades:
            return {}
        
        daily_pnl = {}
        
        for trade in self.trades:
            timestamp = trade['time'] / 1000  # Convertir en secondes
            date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
            
            price = float(trade['price'])
            qty = float(trade['qty'])
            quote_qty = float(trade['quoteQty'])
            fee_amount = float(trade['commission'])
            is_buyer = trade['isBuyer']
            
            if date not in daily_pnl:
                daily_pnl[date] = {
                    'buy_value': 0.0,
                    'sell_value': 0.0,
                    'fees': 0.0
                }
            
            if is_buyer:
                daily_pnl[date]['buy_value'] += quote_qty
            else:
                daily_pnl[date]['sell_value'] += quote_qty
            
            daily_pnl[date]['fees'] += fee_amount
        
        # Calculer le P/L net pour chaque jour
        for date, values in daily_pnl.items():
            values['pnl'] = values['sell_value'] - values['buy_value']
            values['net_pnl'] = values['pnl'] - values['fees']
        
        return daily_pnl
    
    def format_trades_summary(self) -> str:
        """
        Génère un résumé formaté des trades
        
        Returns:
            Texte formaté du résumé des trades
        """
        if not self.trades:
            return "Aucun trade trouvé pour la période spécifiée."
        
        # Regrouper les trades par paire
        trades_by_pair = {}
        for trade in self.trades:
            symbol = trade['symbol']
            if symbol not in trades_by_pair:
                trades_by_pair[symbol] = []
            trades_by_pair[symbol].append(trade)
        
        # Créer un résumé pour chaque paire
        summary = [f"Résumé des trades sur les {self.days_back} derniers jours:"]
        summary.append("=" * 80)
        
        for symbol, symbol_trades in trades_by_pair.items():
            total_buy_qty = 0
            total_sell_qty = 0
            total_buy_value = 0
            total_sell_value = 0
            total_fees = 0
            
            for trade in symbol_trades:
                qty = float(trade['qty'])
                quote_qty = float(trade['quoteQty'])
                fee = float(trade['commission'])
                
                if trade['isBuyer']:
                    total_buy_qty += qty
                    total_buy_value += quote_qty
                else:
                    total_sell_qty += qty
                    total_sell_value += quote_qty
                
                total_fees += fee
            
            # Calcul du P/L estimé
            pnl = total_sell_value - total_buy_value
            
            # Ajouter le résumé de cette paire
            summary.append(f"Paire: {symbol}")
            summary.append(f"  Nombre de trades: {len(symbol_trades)}")
            summary.append(f"  Volume d'achat: {total_buy_qty:.8f} ({total_buy_value:.2f} {self.reference_currency})")
            summary.append(f"  Volume de vente: {total_sell_qty:.8f} ({total_sell_value:.2f} {self.reference_currency})")
            summary.append(f"  Frais totaux: {total_fees:.8f}")
            summary.append(f"  P/L estimé: {pnl:.2f} {self.reference_currency}")
            summary.append("-" * 40)
        
        return "\n".join(summary)
    
    def format_orders_summary(self) -> str:
        """
        Génère un résumé formaté des ordres
        
        Returns:
            Texte formaté du résumé des ordres
        """
        if not self.orders:
            return "Aucun ordre trouvé pour la période spécifiée."
        
        # Compter les ordres par statut
        status_counts = {}
        type_counts = {}
        side_counts = {}
        
        for order in self.orders:
            status = order['status']
            order_type = order['type']
            side = order['side']
            
            status_counts[status] = status_counts.get(status, 0) + 1
            type_counts[order_type] = type_counts.get(order_type, 0) + 1
            side_counts[side] = side_counts.get(side, 0) + 1
        
        # Créer le résumé
        summary = [f"Résumé des ordres sur les {self.days_back} derniers jours:"]
        summary.append("=" * 80)
        summary.append(f"Nombre total d'ordres: {len(self.orders)}")
        
        summary.append("\nRépartition par statut:")
        for status, count in status_counts.items():
            summary.append(f"  {status}: {count} ({count/len(self.orders)*100:.1f}%)")
        
        summary.append("\nRépartition par type:")
        for order_type, count in type_counts.items():
            summary.append(f"  {order_type}: {count} ({count/len(self.orders)*100:.1f}%)")
        
        summary.append("\nRépartition par direction:")
        for side, count in side_counts.items():
            summary.append(f"  {side}: {count} ({count/len(self.orders)*100:.1f}%)")
        
        return "\n".join(summary)
    
    def create_balances_table(self) -> Optional[ConsoleTable]:
        """
        Crée un tableau des soldes actuels
        
        Returns:
            Tableau formaté des soldes ou None si pas de données
        """
        if not self.account_info:
            return None
        
        balances = self.get_balances()
        if not balances:
            return None
        
        table = ConsoleTable(
            ["Actif", "Disponible", "En ordre", "Total"],
            [10, 15, 15, 15]
        )
        
        for balance in balances:
            table.add_row([
                balance['asset'],
                f"{balance['free']:.8f}",
                f"{balance['locked']:.8f}",
                f"{balance['total']:.8f}"
            ])
        
        return table
    
    def create_pnl_table(self) -> Optional[ConsoleTable]:
        """
        Crée un tableau du profit/perte par symbole avec plus de détails
        
        Returns:
            Tableau formaté du P/L ou None si pas de données
        """
        if not self.trades:
            return None
        
        pnl_data = self.calculate_pnl()
        if not pnl_data or 'by_symbol' not in pnl_data:
            return None
        
        # Table améliorée avec plus de colonnes
        table = ConsoleTable(
            ["Symbole", "P/L Réalisé", "Frais", "P/L Net"],
            [10, 15, 15, 15]
        )
        
        for symbol, data in pnl_data['by_symbol'].items():
            table.add_row([
                symbol,
                f"{data['realized_pnl']:.2f}",
                f"{data['fees']:.4f}",
                f"{data['net_pnl']:.2f}"
            ])
        
        # Ajouter une ligne de total
        table.add_row([
            "TOTAL",
            f"{pnl_data['realized_pnl']:.2f}",
            f"{pnl_data['fees']:.4f}",
            f"{pnl_data['net_pnl']:.2f}"
        ])
        
        return table
        
    def create_positions_table(self) -> Optional[ConsoleTable]:
        """
        Crée un tableau des positions complètes reconstruites
        
        Returns:
            Tableau formaté des positions ou None si pas de données
        """
        if not self.complete_positions:
            return None
            
        table = ConsoleTable(
            ["Symbole", "Entrée", "Sortie", "Durée", "P/L Net", "ROI %"],
            [10, 15, 15, 12, 12, 10]
        )
        
        for position_id, position in self.complete_positions.items():
            symbol = position['symbol']
            entry_time = datetime.fromisoformat(position['entry_time']).strftime('%H:%M:%S')
            exit_time = datetime.fromisoformat(position['exit_time']).strftime('%H:%M:%S')
            
            # Calculer la durée en format lisible
            duration_seconds = position['duration_ms'] / 1000
            duration = f"{int(duration_seconds // 60)}m {int(duration_seconds % 60)}s"
            
            # Extraire les données de P/L
            pnl_data = position['pnl']
            net_pnl = pnl_data['net_pnl']
            roi = pnl_data['roi_percentage']
            
            table.add_row([
                symbol,
                entry_time,
                exit_time,
                duration,
                f"{net_pnl:.2f}",
                f"{roi:.2f}%"
            ])
            
        return table
    
    def generate_plots(self, output_dir="."):
        """
        Génère des graphiques d'analyse de la session de trading
        
        Args:
            output_dir: Répertoire de sortie pour les graphiques
        """
        if not self.trades:
            self.logger.warning("Aucun trade disponible pour générer des graphiques.")
            return
        
        # Créer le répertoire de sortie si nécessaire
        os.makedirs(output_dir, exist_ok=True)
        
        # Préparer les données pour DataFrame
        trades_data = []
        for trade in self.trades:
            timestamp = datetime.fromtimestamp(trade['time'] / 1000)
            symbol = trade['symbol']
            price = float(trade['price'])
            qty = float(trade['qty'])
            quote_qty = float(trade['quoteQty'])
            is_buyer = trade['isBuyer']
            fee = float(trade['commission'])
            
            trades_data.append({
                'timestamp': timestamp,
                'date': timestamp.strftime('%Y-%m-%d'),
                'symbol': symbol,
                'side': 'BUY' if is_buyer else 'SELL',
                'price': price,
                'quantity': qty,
                'value': quote_qty,
                'fee': fee
            })
        
        # Créer un DataFrame
        df = pd.DataFrame(trades_data)
        
        try:
            # 1. Graphique de l'activité de trading par jour
            plt.figure(figsize=(12, 6))
            df_daily = df.groupby('date').size()
            df_daily.plot(kind='bar', title="Nombre de trades par jour")
            plt.tight_layout()
            plt.savefig(f"{output_dir}/trades_per_day.png")
            plt.close()
            
            # 2. Graphique du P/L quotidien
            daily_pnl = self.get_daily_pnl()
            if daily_pnl:
                dates = list(daily_pnl.keys())
                net_pnl_values = [data['net_pnl'] for data in daily_pnl.values()]
                
                plt.figure(figsize=(12, 6))
                plt.bar(dates, net_pnl_values)
                plt.title("Profit/Perte quotidien")
                plt.xlabel("Date")
                plt.ylabel(f"P/L Net ({self.reference_currency})")
                plt.xticks(rotation=45)
                plt.tight_layout()
                plt.savefig(f"{output_dir}/daily_pnl.png")
                plt.close()
            
            # 3. Distribution des trades par symbole
            plt.figure(figsize=(10, 6))
            symbol_counts = df['symbol'].value_counts()
            symbol_counts.plot(kind='pie', autopct='%1.1f%%', title="Distribution des trades par symbole")
            plt.tight_layout()
            plt.savefig(f"{output_dir}/trades_by_symbol.png")
            plt.close()
            
            # 4. Distribution des trades par type (achat/vente)
            plt.figure(figsize=(8, 6))
            side_counts = df['side'].value_counts()
            side_counts.plot(kind='pie', autopct='%1.1f%%', title="Distribution des trades par type")
            plt.tight_layout()
            plt.savefig(f"{output_dir}/trades_by_side.png")
            plt.close()
            
            self.logger.info(f"Graphiques générés avec succès dans le répertoire {output_dir}")
            
        except Exception as e:
            self.logger.error(f"Erreur lors de la génération des graphiques: {e}")
    
    def reconcile_account_changes(self) -> Dict:
        """
        Réconcilie les changements de solde du compte avec les P/L calculés
        pour identifier et expliquer les écarts potentiels
        
        Returns:
            Dictionnaire contenant les données de réconciliation
        """
        # Vérifier que nous avons les snapshots initial et final
        if not self.initial_snapshot or not self.final_snapshot:
            self.logger.warning("Réconciliation impossible: snapshots manquants")
            return {}
        
        # Extraire les soldes initial et final
        initial_balance = self.initial_snapshot.get('reference_balance', 0)
        final_balance = self.final_snapshot.get('reference_balance', 0)
        balance_change = final_balance - initial_balance
        
        # Obtenir le P/L calculé
        pnl_data = self.calculate_pnl()
        net_pnl = pnl_data.get('net_pnl', 0)
        
        # Calculer la différence entre le changement réel et le P/L calculé
        discrepancy = balance_change - net_pnl
        
        # Déterminer la raison possible de l'écart
        discrepancy_reason = "Indéterminé"
        if abs(discrepancy) < 0.01:
            discrepancy_reason = "Aucun écart significatif (moins de 0.01)"
        elif discrepancy > 0:
            # Plus d'argent que prévu - possibles causes
            if len(self.orders) > len(self.trades) * 2:
                discrepancy_reason = "Ordres annulés ou partiellement exécutés"
            else:
                discrepancy_reason = "Revenu supplémentaire (intérêts, staking, etc.)"
        else:
            # Moins d'argent que prévu - possibles causes
            if self.execution_mode == 0:
                discrepancy_reason = "Mode test: certains frais peuvent ne pas être reflétés"
            else:
                discrepancy_reason = "Frais supplémentaires non comptabilisés ou prélèvements externes"
        
        self.logger.info(f"Réconciliation: Solde {self.reference_currency} {initial_balance:.2f} -> {final_balance:.2f}, P/L calculé: {net_pnl:.2f}")
        if abs(discrepancy) > 0.01:
            self.logger.warning(f"Écart détecté: {discrepancy:.2f} {self.reference_currency} - Raison probable: {discrepancy_reason}")
        else:
            self.logger.info(f"Réconciliation réussie (écart: {discrepancy:.4f} {self.reference_currency})")
            
        # Retourner les données de réconciliation
        return {
            'initial_balance': initial_balance,
            'final_balance': final_balance,
            'balance_change': balance_change,
            'calculated_pnl': net_pnl,
            'discrepancy': discrepancy,
            'discrepancy_reason': discrepancy_reason,
            'reconciliation_status': 'success' if abs(discrepancy) < 0.01 else 'warning'
        }

    async def generate_full_report(self, output_dir="."):
        """
        Génère un rapport complet de la session de trading
        
        Args:
            output_dir: Répertoire de sortie pour le rapport et les graphiques
        """
        # Créer le répertoire de sortie si nécessaire
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Collecter toutes les données
        try:
            self.logger.info("Capture du snapshot initial du compte...")
            self.initial_snapshot = await self.capture_account_snapshot()
            
            self.logger.info("Collecte des informations du compte...")
            await self.get_account_info()
            
            self.logger.info("Collecte des trades récents...")
            await self.get_all_trades()
            
            self.logger.info("Collecte de l'historique des ordres...")
            await self.get_order_history()
            
            # Capture du snapshot final après avoir collecté toutes les données
            self.logger.info("Capture du snapshot final du compte...")
            self.final_snapshot = await self.capture_account_snapshot()
            
            # 2. Générer des statistiques
            reference_balance = self.get_reference_currency_balance()
            pnl_data = self.calculate_pnl()
            daily_pnl = self.get_daily_pnl()
            
            # Réconciliation des données
            reconciliation_data = self.reconcile_account_changes()
            
            # 3. Créer les tableaux
            balances_table = self.create_balances_table()
            pnl_table = self.create_pnl_table()
            
            # 4. Générer le rapport texte
            report_lines = []
            
            # En-tête
            report_lines.append("=" * 80)
            report_lines.append(f"RAPPORT DE TRADING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            report_lines.append("=" * 80)
            
            # Informations générales
            report_lines.append(f"\nPériode analysée: dernières {self.period_text}")
            report_lines.append(f"Monnaie de référence: {self.reference_currency}")
            report_lines.append(f"Environnement: {'Testnet' if self.use_testnet else 'Mainnet'}")
            
            # Soldes
            report_lines.append("\n" + "=" * 80)
            report_lines.append("SOLDES ACTUELS")
            report_lines.append("=" * 80)
            report_lines.append(f"\nSolde {self.reference_currency}: {reference_balance:.2f}")
            
            if balances_table:
                report_lines.append("\nDétail des soldes:")
                report_lines.append(balances_table.render())
            
            # NOUVELLE SECTION: Réconciliation des soldes
            if reconciliation_data:
                report_lines.append("\n" + "=" * 80)
                report_lines.append("RÉCONCILIATION DES SOLDES")
                report_lines.append("=" * 80)
                report_lines.append(f"\nSolde initial {self.reference_currency}: {reconciliation_data['initial_balance']:.2f}")
                report_lines.append(f"Solde final {self.reference_currency}: {reconciliation_data['final_balance']:.2f}")
                report_lines.append(f"Variation nette: {reconciliation_data['balance_change']:.2f} {self.reference_currency}")
                report_lines.append(f"P/L calculé: {pnl_data['net_pnl']:.2f} {self.reference_currency}")
                
                if abs(reconciliation_data['discrepancy']) > 0.01:
                    report_lines.append(f"\nÉcart détecté: {reconciliation_data['discrepancy']:.2f} {self.reference_currency}")
                    report_lines.append(f"Cause possible: {reconciliation_data['discrepancy_reason']}")
                else:
                    report_lines.append(f"\nRéconciliation réussie (écart: {reconciliation_data['discrepancy']:.4f} {self.reference_currency})")
                
                report_lines.append(f"\nMéthode de calcul du P/L: {pnl_data.get('calculation_method', 'standard')}")
                
            # Activité de trading
            report_lines.append("\n" + "=" * 80)
            report_lines.append("ACTIVITÉ DE TRADING")
            report_lines.append("=" * 80)
            
            # MODIFIÉ: Afficher le nombre de positions reconstruites si disponible
            if self.complete_positions:
                report_lines.append(f"\nNombre total de positions complètes: {len(self.complete_positions)}")
                report_lines.append(f"Nombre total de trades individuels: {len(self.trades)}")
            else:
                report_lines.append(f"\nNombre total de trades: {len(self.trades)}")
            
            # Distribution par symbole
            trades_by_symbol = {}
            for trade in self.trades:
                symbol = trade['symbol']
                trades_by_symbol[symbol] = trades_by_symbol.get(symbol, 0) + 1
            
            if trades_by_symbol:
                report_lines.append("\nDistribution par symbole:")
                for symbol, count in sorted(trades_by_symbol.items(), key=lambda x: x[1], reverse=True):
                    report_lines.append(f"  {symbol}: {count} trades ({count/len(self.trades)*100:.1f}%)")
            
            # Profit/Perte
            report_lines.append("\n" + "=" * 80)
            report_lines.append("PROFIT/PERTE")
            report_lines.append("=" * 80)
            
            if pnl_data:
                report_lines.append(f"\nProfit total réalisé: {pnl_data['realized_pnl']:.2f} {self.reference_currency}")
                report_lines.append(f"Frais totaux: {pnl_data['fees']:.4f}")
                report_lines.append(f"Profit net: {pnl_data['net_pnl']:.2f} {self.reference_currency}")
                
                if pnl_table:
                    report_lines.append("\nDétail par symbole:")
                    report_lines.append(pnl_table.render())
            
            # Résumé quotidien
            if daily_pnl:
                report_lines.append("\n" + "=" * 80)
                report_lines.append("RÉSUMÉ QUOTIDIEN")
                report_lines.append("=" * 80)
                
                daily_table = ConsoleTable(
                    ["Date", "Valeur achetée", "Valeur vendue", "Frais", "P/L Net"],
                    [12, 15, 15, 12, 15]
                )
                
                total_buy = 0
                total_sell = 0
                total_fees = 0
                total_net = 0
                
                for date, data in sorted(daily_pnl.items()):
                    daily_table.add_row([
                        date,
                        f"{data['buy_value']:.2f}",
                        f"{data['sell_value']:.2f}",
                        f"{data['fees']:.4f}",
                        f"{data['net_pnl']:.2f}"
                    ])
                    
                    total_buy += data['buy_value']
                    total_sell += data['sell_value']
                    total_fees += data['fees']
                    total_net += data['net_pnl']
                
                # Ajouter une ligne de total
                daily_table.add_row([
                    "TOTAL",
                    f"{total_buy:.2f}",
                    f"{total_sell:.2f}",
                    f"{total_fees:.4f}",
                    f"{total_net:.2f}"
                ])
                
                report_lines.append(daily_table.render())
            
            # Détail des ordres
            report_lines.append("\n" + "=" * 80)
            report_lines.append("RÉSUMÉ DES ORDRES")
            report_lines.append("=" * 80)
            report_lines.append(f"\nNombre total d'ordres: {len(self.orders)}")
            
            # Compter les ordres par statut
            status_counts = {}
            for order in self.orders:
                status = order['status']
                status_counts[status] = status_counts.get(status, 0) + 1
            
            if status_counts:
                report_lines.append("\nDistribution par statut:")
                for status, count in status_counts.items():
                    report_lines.append(f"  {status}: {count} ({count/len(self.orders)*100:.1f}%)")
            
            # Générer les graphiques
            self.logger.info("Génération des graphiques...")
            self.generate_plots(output_dir)
            
            # Ajouter des informations sur les graphiques générés
            report_lines.append("\n" + "=" * 80)
            report_lines.append("GRAPHIQUES")
            report_lines.append("=" * 80)
            report_lines.append("\nLes graphiques suivants ont été générés dans le répertoire de sortie:")
            report_lines.append("  1. trades_per_day.png - Nombre de trades par jour")
            report_lines.append("  2. daily_pnl.png - Profit/Perte quotidien")
            report_lines.append("  3. trades_by_symbol.png - Distribution des trades par symbole")
            report_lines.append("  4. trades_by_side.png - Distribution des trades par type (achat/vente)")
            
            # Conclusion
            report_lines.append("\n" + "=" * 80)
            report_lines.append("CONCLUSION")
            report_lines.append("=" * 80)
            
            if pnl_data and 'net_pnl' in pnl_data:
                if pnl_data['net_pnl'] > 0:
                    report_lines.append(f"\nLa session de trading a été profitable avec un gain net de {pnl_data['net_pnl']:.2f} {self.reference_currency}.")
                else:
                    report_lines.append(f"\nLa session de trading a résulté en une perte nette de {abs(pnl_data['net_pnl']):.2f} {self.reference_currency}.")
                
                # Calculer le ROI si possible
                if total_buy > 0:
                    roi = (pnl_data['net_pnl'] / total_buy) * 100
                    report_lines.append(f"ROI: {roi:.2f}%")
            
            # Écrire le rapport dans un fichier
            report_path = os.path.join(output_dir, f"trading_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(report_lines))
            
            self.logger.info(f"Rapport complet généré: {report_path}")
            
            return report_lines
        
        except Exception as e:
            self.logger.error(f"Erreur lors de la génération du rapport: {str(e)}")
            raise

async def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="Analyseur de session de trading Binance")
    
    parser.add_argument('--currency', type=str, default="USDC", 
                      help="Monnaie de référence (par défaut: USDC)")
    
    # Groupe exclusif pour la période (jours ou heures)
    period_group = parser.add_mutually_exclusive_group()
    period_group.add_argument('--days', type=int, default=None, 
                      help="Nombre de jours à analyser en arrière (par défaut: 1)")
    period_group.add_argument('--hours', type=int, default=None, 
                      help="Nombre d'heures à analyser en arrière (plus précis que --days)")
    
    parser.add_argument('--mode', type=int, choices=[0, 1, 2], default=2, 
                      help="Mode d'exécution: 0=test sur testnet, 1=réel sur testnet, 2=réel sur mainnet (par défaut: 2)")
    parser.add_argument('--output', type=str, default="./trading_reports", 
                      help="Répertoire de sortie pour le rapport (par défaut: ./trading_reports)")
    parser.add_argument('--save-snapshots', action='store_true',
                      help="Enregistre les snapshots du compte pour référence future")
    parser.add_argument('--reconcile', action='store_true',
                      help="Effectue une réconciliation détaillée entre les soldes et les P/L calculés")
    parser.add_argument('--detailed', action='store_true',
                      help="Génère un rapport plus détaillé avec analyses supplémentaires")
    
    args = parser.parse_args()
    
    # Déterminer la période en jours (par défaut 1 jour si ni jours ni heures ne sont spécifiés)
    days_back = 1  # Valeur par défaut
    period_text = "1 jour"
    
    if args.days is not None:
        days_back = args.days
        period_text = f"{args.days} jour{'s' if args.days > 1 else ''}"
    elif args.hours is not None:
        days_back = args.hours / 24.0  # Convertir les heures en jours (fraction décimale)
        period_text = f"{args.hours} heure{'s' if args.hours > 1 else ''}"
    
    # Configurer le logger
    setup_logger('analyzer')
    logger = get_trading_logger()
    log_separator(logger, "ANALYSEUR DE SESSION DE TRADING")
    logger.info(f"Période d'analyse: dernières {period_text}")
    
    try:
        # Créer l'analyseur
        analyzer = BinanceAnalyzer(
            reference_currency=args.currency,
            days_back=days_back,
            execution_mode=args.mode
        )
        
        # Créer le répertoire de sortie
        os.makedirs(args.output, exist_ok=True)
        
        # Si l'option de sauvegarde des snapshots est activée
        if args.save_snapshots:
            # Créer un sous-répertoire pour les snapshots
            snapshots_dir = os.path.join(args.output, "snapshots")
            os.makedirs(snapshots_dir, exist_ok=True)
            logger.info(f"Les snapshots seront sauvegardés dans {snapshots_dir}")
            
            # Capturer et sauvegarder le snapshot initial
            initial_snapshot = await analyzer.capture_account_snapshot()
            with open(os.path.join(snapshots_dir, f"snapshot_initial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"), 'w') as f:
                json.dump(initial_snapshot, f, indent=2)
                
        # Générer le rapport complet
        report_lines = await analyzer.generate_full_report(args.output)
        
        # Si l'option de réconciliation est activée et que le rapport a été généré
        if args.reconcile and report_lines:
            # Ajouter des informations supplémentaires de réconciliation
            reconciliation_data = analyzer.reconcile_account_changes()
            if reconciliation_data:
                logger.info(f"Réconciliation: Variation {reconciliation_data['balance_change']:.2f} vs P/L calculé {reconciliation_data['calculated_pnl']:.2f}")
                logger.info(f"Statut: {reconciliation_data['reconciliation_status']}")
                
                # Si un écart significatif est détecté
                if abs(reconciliation_data['discrepancy']) > 0.01:
                    logger.warning(f"Écart de réconciliation: {reconciliation_data['discrepancy']:.2f} {args.currency}")
                    logger.warning(f"Raison probable: {reconciliation_data['discrepancy_reason']}")
                else:
                    logger.info(f"Réconciliation réussie (écart: {reconciliation_data['discrepancy']:.4f} {args.currency})")
        
        # Afficher un résumé dans la console
        for line in report_lines:
            if "=" * 10 in line:
                logger.info(f"{Colors.BOLD}{Colors.BRIGHT_CYAN}{line}{Colors.RESET}")
            elif line.startswith("  "):
                logger.info(f"  {line}")
            else:
                logger.info(line)
        
        # Si l'option détaillée est activée, afficher des statistiques supplémentaires
        if args.detailed and analyzer.complete_positions:
            log_separator(logger, "ANALYSE DÉTAILLÉE DES POSITIONS")
            
            # Créer et afficher le tableau des positions reconstruites
            positions_table = analyzer.create_positions_table()
            if positions_table:
                logger.info("Détail des positions reconstruites:")
                positions_table.log_table(logger)
                
            # Statistiques supplémentaires
            durations = [pos['duration_ms']/1000 for pos_id, pos in analyzer.complete_positions.items()]
            if durations:
                avg_duration = sum(durations) / len(durations)
                logger.info(f"Durée moyenne des positions: {avg_duration:.2f} secondes")
                
            # Analyse de performance par symbole
            roi_by_symbol = {}
            for pos_id, pos in analyzer.complete_positions.items():
                symbol = pos['symbol']
                if symbol not in roi_by_symbol:
                    roi_by_symbol[symbol] = []
                roi_by_symbol[symbol].append(pos['pnl']['roi_percentage'])
            
            if roi_by_symbol:
                logger.info("ROI moyen par symbole:")
                for symbol, rois in roi_by_symbol.items():
                    avg_roi = sum(rois) / len(rois)
                    logger.info(f"  {symbol}: {avg_roi:.2f}% ({len(rois)} positions)")
        
        # Fermer proprement la session
        await analyzer.close_session()
        
    except Exception as e:
        logger.error(f"Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
        # Générer le rapport complet
        report_lines = await analyzer.generate_full_report(args.output)
        
        # Afficher un résumé dans la console
        for line in report_lines:
            if "=" * 10 in line:
                logger.info(f"{Colors.BOLD}{Colors.BRIGHT_CYAN}{line}{Colors.RESET}")
            elif line.startswith("  "):
                logger.info(f"  {line}")
            else:
                logger.info(line)
        
        # Fermer proprement la session
        await analyzer.close_session()
        
    except Exception as e:
        logger.error(f"Erreur: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    # Afficher des exemples d'utilisation si aucun argument n'est fourni
    if len(sys.argv) == 1:
        print("Trading Session Analyzer - Outil d'analyse post-trading pour Binance")
        print("==================================================================")
        print("\nExemples d'utilisation:")
        print("# Exemple d'utilisation pour analyser les 4 dernières heures de trading:")
        print("python trading_session_analyzer.py --hours 4 --currency USDC --mode 2")
        print("")
        print("# Pour analyser les 12 dernières heures sur le testnet avec réconciliation des soldes:")
        print("python trading_session_analyzer.py --hours 12 --mode 1 --reconcile")
        print("")
        print("# Pour une analyse détaillée des 24 dernières heures avec sauvegarde des snapshots:")
        print("python trading_session_analyzer.py --hours 24 --detailed --save-snapshots")
        print("")
        print("# Exemple avec l'ancienne option des jours pour référence:")
        print("python trading_session_analyzer.py --days 7 --currency USDT")
        print("")
        print("Exécutez avec --help pour plus d'informations sur les options disponibles.")
        sys.exit(0)
    
    # Configurer asyncio pour Windows si nécessaire
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Exécuter la fonction principale
    asyncio.run(main())