import asyncio
import aiohttp
from logger_config import get_order_logger, get_error_logger
from typing import Dict, Any, Optional, List
from decimal import Decimal
import math
import time
from event_manager import EventManager
from binance_api_connection import BinanceAPIManager
from topgainers23 import TradingConfig

class OrderExecutor:
    """Exécuteur d'ordres qui interagit avec l'API Binance"""
    
    def __init__(self, event_manager: EventManager, api_key: str, api_secret: str, config: TradingConfig):
        """
        Initialise l'exécuteur d'ordres
        """
        self.event_manager = event_manager
        self.config = config
        
        # Stockage du mode d'exécution pour les décisions ultérieures
        self.execution_mode = config.ORDER_EXECUTION_MODE
        
        # Initialiser l'API manager en passant directement le mode d'exécution
        # Plus besoin de convertir en use_testnet dans cette classe
        self.api_manager = BinanceAPIManager(api_key, api_secret, self.execution_mode)
        
        self.order_history = []
        self.is_running = True
        self.symbol_rules = {}
        self.logger = get_order_logger()
        self.error_logger = get_error_logger()
        
        # Log du mode d'exécution et de la monnaie de référence
        modes = {
            0: "Ordres de test sur testnet (validation uniquement)",
            1: "Ordres réels sur testnet (avec fonds virtuels)",
            2: "Ordres réels sur mainnet (ATTENTION: fonds réels)"
        }
        
        self.logger.info(f"Mode d'exécution des ordres: {modes.get(self.execution_mode)}")
        self.logger.info(f"Monnaie de référence: {self.config.REFERENCE_CURRENCY}")
        
        # S'abonner aux événements de trading
        self.event_manager.subscribe("open_position", self.handle_open_position)
        self.event_manager.subscribe("close_position", self.handle_close_position)

    async def initialize(self):
        """Initialise la connexion à l'API et teste sa validité"""
        await self.api_manager.init_session()
        is_connected = await self.api_manager.test_connection()
        if not is_connected:
            self.error_logger.error("Impossible de se connecter à l'API Binance. Vérifiez vos clés API.")
            return False
        
        # Récupérer les règles de trading
        await self.fetch_exchange_info()
        
        return True
    
    async def fetch_exchange_info(self):
        """
        Récupère les informations sur les règles de trading pour toutes les paires
        et les stocke en cache pour une utilisation ultérieure
        """
        try:
            # Récupérer les informations de l'exchange
            exchange_info = await self.api_manager.get_exchange_info()
            
            # Initialiser le dictionnaire des règles
            self.symbol_rules = {}
            
            # Parcourir les symboles et extraire les règles
            for symbol_data in exchange_info.get('symbols', []):
                symbol = symbol_data.get('symbol')
                
                # Ignorer les symboles non actifs
                if symbol_data.get('status') != 'TRADING':
                    continue
                    
                # Extraire les filtres pertinents
                lot_size_filter = next((f for f in symbol_data.get('filters', []) 
                                    if f.get('filterType') == 'LOT_SIZE'), None)
                
                price_filter = next((f for f in symbol_data.get('filters', []) 
                                if f.get('filterType') == 'PRICE_FILTER'), None)
                
                min_notional_filter = next((f for f in symbol_data.get('filters', []) 
                                        if f.get('filterType') == 'MIN_NOTIONAL'), None)
                
                # Stocker les informations pertinentes
                if lot_size_filter and price_filter and min_notional_filter:
                    self.symbol_rules[symbol] = {
                        'min_qty': float(lot_size_filter.get('minQty', 0)),
                        'max_qty': float(lot_size_filter.get('maxQty', 0)),
                        'step_size': float(lot_size_filter.get('stepSize', 0)),
                        'min_price': float(price_filter.get('minPrice', 0)),
                        'tick_size': float(price_filter.get('tickSize', 0)),
                        'min_notional': float(min_notional_filter.get('minNotional', 0))
                    }
            
            self.logger.info(f"Règles de trading récupérées pour {len(self.symbol_rules)} paires")
            
        except Exception as e:
            self.error_logger.error(f"Erreur lors de la récupération des règles de trading: {e}")
            # Initialiser un dictionnaire vide en cas d'erreur
            self.symbol_rules = {}

    async def check_balance(self, asset: str, amount_required: float) -> bool:
        """
        Vérifie si le solde disponible est suffisant pour une opération
        
        Args:
            asset: Symbole de l'actif (ex: BTC, USDT)
            amount_required: Montant nécessaire
            
        Returns:
            True si le solde est suffisant, False sinon
        """
        try:
            # Récupérer les informations du compte
            account_info = await self.api_manager.get_account_info()
            
            # Extraire le solde pour l'actif spécifié
            asset_balance = next(
                (
                    float(balance['free']) 
                    for balance in account_info.get('balances', [])
                    if balance['asset'] == asset
                ),
                0.0
            )
            
            # Vérifier si le solde est suffisant
            is_sufficient = asset_balance >= amount_required
            
            # Journaliser le résultat
            if is_sufficient:
                self.logger.info(f"Solde suffisant pour {asset}: {asset_balance} (requis: {amount_required})")
            else:
                self.logger.warning(
                    f"Solde insuffisant pour {asset}: {asset_balance} (requis: {amount_required})"
                )
            
            return is_sufficient
        
        except Exception as e:
            self.logger.error(f"Erreur lors de la vérification du solde pour {asset}: {e}")
            # En cas d'erreur, supposer que le solde est insuffisant par sécurité
            return False

    async def get_symbol_rules(self, symbol: str, force_refresh=False) -> dict:
        """
        Récupère les règles de trading pour un symbole spécifique de manière synchrone.
        """
        if force_refresh or symbol not in self.symbol_rules:
            try:
                # Récupérer les informations d'échange directement
                exchange_info = await self.api_manager._make_request(
                    "GET", 
                    "/api/v3/exchangeInfo", 
                    {"symbol": symbol}
                )
                
                # Log détaillé pour déboguer
                self.logger.info(f"Réponse exchange_info pour {symbol}: {exchange_info.keys()}")
                
                if 'symbols' not in exchange_info:
                    self.logger.error(f"Format de réponse inattendu pour {symbol}: {exchange_info}")
                    return {}
                
                # Extraire les règles pour ce symbole spécifique
                symbol_data = next((s for s in exchange_info.get('symbols', []) 
                                if s.get('symbol') == symbol), None)
                
                if not symbol_data:
                    self.logger.warning(f"Règles non trouvées pour {symbol} dans la réponse API")
                    return {}
                    
                # Extraire les filtres pertinents avec logging pour déboguer
                self.logger.info(f"Filtres disponibles pour {symbol}: {[f.get('filterType') for f in symbol_data.get('filters', [])]}")
                
                lot_size_filter = next((f for f in symbol_data.get('filters', []) 
                                    if f.get('filterType') == 'LOT_SIZE'), None)
                
                price_filter = next((f for f in symbol_data.get('filters', []) 
                                if f.get('filterType') == 'PRICE_FILTER'), None)
                
                min_notional_filter = next((f for f in symbol_data.get('filters', []) 
                                        if f.get('filterType') == 'MIN_NOTIONAL'), None)
                
                # MODIFICATION: Accepter les paires même sans MIN_NOTIONAL
                # Si pas de MIN_NOTIONAL, chercher NOTIONAL (format alternatif)
                if min_notional_filter is None:
                    notional_filter = next((f for f in symbol_data.get('filters', []) 
                                        if f.get('filterType') == 'NOTIONAL'), None)
                    if notional_filter:
                        self.logger.info(f"Filtre NOTIONAL trouvé pour {symbol} au lieu de MIN_NOTIONAL")
                        min_notional_filter = notional_filter
                
                # MODIFICATION: Stocker les informations même si MIN_NOTIONAL est absent
                if lot_size_filter and price_filter:
                    # Soit on trouve le MIN_NOTIONAL, soit on utilise une valeur par défaut
                    min_notional_value = 10.0  # Valeur par défaut raisonnable
                    
                    if min_notional_filter:
                        # Vérifier le format du filtre (peut varier entre MIN_NOTIONAL et NOTIONAL)
                        if 'minNotional' in min_notional_filter:
                            min_notional_value = float(min_notional_filter.get('minNotional', min_notional_value))
                        elif 'minValue' in min_notional_filter:
                            min_notional_value = float(min_notional_filter.get('minValue', min_notional_value))
                    else:
                        self.logger.warning(f"Filtre MIN_NOTIONAL manquant pour {symbol}, utilisation de la valeur par défaut: {min_notional_value}")
                    
                    self.symbol_rules[symbol] = {
                        'min_qty': float(lot_size_filter.get('minQty', 0)),
                        'max_qty': float(lot_size_filter.get('maxQty', 0)),
                        'step_size': float(lot_size_filter.get('stepSize', 0)),
                        'min_price': float(price_filter.get('minPrice', 0)),
                        'tick_size': float(price_filter.get('tickSize', 0)),
                        'min_notional': min_notional_value
                    }
                    self.logger.info(f"Règles récupérées pour {symbol}: {self.symbol_rules[symbol]}")
                else:
                    self.logger.warning(f"Filtres incomplets pour {symbol}: LOT_SIZE={lot_size_filter is not None}, PRICE_FILTER={price_filter is not None}, MIN_NOTIONAL={min_notional_filter is not None}")
                
            except Exception as e:
                self.logger.error(f"Erreur lors de la récupération des règles pour {symbol}: {e}")
                return {}
        
        return self.symbol_rules.get(symbol, {})

    async def handle_open_position(self, data: Dict[str, Any]):
        """Gère l'ouverture d'une position"""
        try:
            pair = data['pair']
            position_type = data['position_type']
            position_size = data['position_size']
            
            # Conversion de la taille de position en quantité d'actif
            price = float(data['entry_price'])

            # Récupérer les règles de trading pour cette paire
            rules = await self.get_symbol_rules(pair, force_refresh=True)

            # Une paire est considérée valide si elle a au moins LOT_SIZE et PRICE_FILTER
            has_minimal_rules = rules and 'step_size' in rules and 'tick_size' in rules

        # Si nous sommes en testnet et que les règles sont insuffisantes
            if not has_minimal_rules and self.execution_mode < 2:  # Modes 0 et 1 utilisent testnet
                error_msg = f"Paire {pair} probablement non disponible sur testnet - ordre non exécuté"
                self.logger.warning(error_msg)
                await self.event_manager.emit("order_failed", {
                    "pair": pair,
                    "side": "BUY",
                    "reason": error_msg
                })
                return
                
            # Maintenant calculer la quantité avec les règles à jour
            quantity = self._calculate_quantity(pair, position_size, price)

            # Vérification de solde pour les ordres réels (modes 1 et 2)
            if self.execution_mode > 0:  # Si mode = 1 ou 2 (ordres réels)
                # Utiliser la monnaie de référence à partir de la configuration
                reference_currency = self.config.REFERENCE_CURRENCY
                
                has_sufficient_balance = await self.check_balance(
                    asset=reference_currency, 
                    amount_required=position_size
                )
                if not has_sufficient_balance:
                    self.logger.warning(f"Solde {reference_currency} insuffisant pour ouvrir une position sur {pair}")
                    await self.event_manager.emit("order_failed", {
                        "pair": pair,
                        "side": "BUY",
                        "reason": f"Solde {reference_currency} insuffisant"
                    })
                    return

            # Exécution d'ordre selon le mode
            if self.execution_mode == 0:
                # Mode 0: Ordres de test sur testnet (validation seulement)
                result = await self.api_manager.place_test_order(
                    symbol=pair,
                    side="BUY",
                    type="MARKET",
                    quantity=quantity
                )
                self.logger.info(f"Ordre de test exécuté avec succès: {result}")
            else:
                # Modes 1 et 2: Ordres réels (sur testnet ou mainnet)
                try:
                    result = await self.place_real_order(
                        symbol=pair,
                        side="BUY",
                        type="MARKET",
                        quantity=quantity
                    )
                    env = "testnet" if self.execution_mode == 1 else "PRODUCTION"
                    self.logger.info(f"Ordre d'achat réel exécuté sur {env} pour {pair} - ID: {result.get('orderId')}")
                
                except aiohttp.ClientResponseError as e:
                    self.logger.error(f"Échec de l'ordre d'achat réel pour {pair}: {e}")
                    # Modification: accéder au texte d'erreur correctement
                    error_text = "Erreur de l'API"
                    if hasattr(e, 'message'):
                        error_text = e.message
                    elif hasattr(e, 'text'):
                        error_text = e.text
                    # Émettre un événement d'échec pour notification
                    await self.event_manager.emit("order_failed", {
                        "pair": pair,
                        "side": "BUY",
                        "reason": error_text
                    })
                    return
                
                except Exception as e:
                    self.logger.error(f"Échec de l'ordre d'achat réel pour {pair}: {e}")
                    # Émettre un événement d'échec pour notification
                    await self.event_manager.emit("order_failed", {
                        "pair": pair,
                        "side": "BUY",
                        "reason": str(e)
                    })
                    return

            # Émettre un événement de confirmation
            await self.event_manager.emit("position_opened", {
                "pair": pair,
                "position_type": position_type,
                "quantity": quantity,
                "entry_price": price,  # Renommer "price" en "entry_price" pour plus de clarté
                "position_size": position_size,
                "take_profit": data.get('take_profit', price * 1.01),  # Valeur par défaut si non fournie
                "stop_loss": data.get('stop_loss', price * 0.99),      # Valeur par défaut si non fournie
                "status": "success",
                "open_time": time.time()  # Ajout de l'heure d'ouverture pour calculer la durée
            })
            
        except Exception as e:
            self.logger.error(f"Erreur lors de l'ouverture de position: {e}")
            await self.event_manager.emit("error", {
                "type": "open_position_error",
                "message": str(e),
                "data": data
            })
    
    async def handle_close_position(self, data: Dict[str, Any]):
        """Gère la fermeture d'une position"""
        try:
            pair = data['pair']
            position_type = data['position_type']
            close_reason = data['close_reason']
            quantity = data['quantity']
            
            self.logger.info(f"Exécution d'ordre de vente - {pair} - Raison: {close_reason}")
            
            # Formater la quantité selon les règles du symbole pour assurer la compatibilité
            # avec les exigences de précision de Binance
            symbol_rules = self.symbol_rules.get(pair, {})
            if symbol_rules and 'step_size' in symbol_rules:
                step_size = symbol_rules.get('step_size', 0.1)
                
                # Déterminer la précision à partir du step_size
                precision = 0
                if step_size < 1:
                    step_str = str(step_size).rstrip('0')
                    if '.' in step_str:
                        precision = len(step_str.split('.')[-1])
                
                # Arrondir la quantité au step_size inférieur
                original_quantity = quantity
                quantity = math.floor(quantity / step_size) * step_size
                
                # Formater avec la précision correcte
                quantity = float(f"{quantity:.{precision}f}")
                
                self.logger.info(f"Quantité ajustée pour vente: {quantity} (originale: {original_quantity}, step_size: {step_size})")
            else:
                # Si aucune règle n'est disponible, utiliser une précision conservatrice
                quantity = math.floor(quantity * 10) / 10  # Arrondir à 0.1 près
                self.logger.warning(f"Règles non disponibles pour {pair} - quantité arrondie à {quantity}")
        
            # Exécuter l'ordre de vente
            if self.execution_mode == 0:
                # Mode 0: Ordres de test sur testnet (validation seulement)
                result = await self.api_manager.place_test_order(
                    symbol=pair,
                    side="SELL",
                    type="MARKET",
                    quantity=quantity
                )
                self.logger.info(f"Ordre de vente de test exécuté: {result}")
            else:
                # Modes 1 et 2: Ordres réels (sur testnet ou mainnet)
                try:
                    result = await self.place_real_order(
                        symbol=pair,
                        side="SELL",
                        type="MARKET",
                        quantity=quantity
                    )
                    env = "testnet" if self.execution_mode == 1 else "PRODUCTION"
                    self.logger.info(f"Ordre de vente réel exécuté sur {env} pour {pair} - ID: {result.get('orderId')}")
                
                except aiohttp.ClientResponseError as e:
                    self.logger.error(f"Échec de l'ordre d'achat réel pour {pair}: {e}")
                    # Modification: accéder au texte d'erreur correctement
                    error_text = "Erreur de l'API"
                    if hasattr(e, 'message'):
                        error_text = e.message
                    elif hasattr(e, 'text'):
                        error_text = e.text
                    # Émettre un événement d'échec pour notification
                    await self.event_manager.emit("order_failed", {
                        "pair": pair,
                        "side": "BUY",
                        "reason": error_text
                    })
                    return
                
                except Exception as e:
                    self.logger.error(f"Échec de l'ordre d'achat réel pour {pair}: {e}")
                    # Émettre un événement d'échec pour notification
                    await self.event_manager.emit("order_failed", {
                        "pair": pair,
                        "side": "BUY",
                        "reason": str(e)
                    })
                    return

            # Émettre un événement de confirmation
            # Récupérer ou estimer le prix de sortie
            exit_price = data.get('exit_price', await self.api_manager._get_current_price(pair))

            # Calculer le profit/perte si non fourni
            profit_loss = data.get('profit_loss', 0.0)
            if profit_loss == 0.0 and 'entry_price' in data:
                # Calcul approximatif si non fourni
                entry_price = data.get('entry_price', 0.0)
                position_size = data.get('position_size', 0.0)
                profit_loss = position_size * (exit_price / entry_price - 1)

            await self.event_manager.emit("position_closed", {
                "pair": pair,
                "position_type": data.get('position_type', 'N/A'),
                "entry_price": data.get('entry_price', 0.0),
                "exit_price": exit_price,
                "quantity": quantity,
                "profit_loss": profit_loss,
                "close_reason": close_reason,
                "status": "success",
                "close_time": time.time()
            })
            
        except Exception as e:
            self.logger.error(f"Erreur lors de la fermeture de position: {e}")
            await self.event_manager.emit("error", {
                "type": "close_position_error",
                "message": str(e),
                "data": data
            })
    
    async def place_real_order(self, symbol: str, side: str, type: str, 
                               quantity: float, price: Optional[float] = None) -> Dict:
        """
        Place un ordre réel sur Binance
        
        Args:
            symbol: Symbole de la paire (ex: BTCUSDT)
            side: Direction (BUY/SELL)
            type: Type d'ordre (MARKET/LIMIT)
            quantity: Quantité à trader
            price: Prix pour les ordres LIMIT (optionnel)
        
        Returns:
            Réponse de l'API contenant les détails de l'ordre
        """
        # Construire les paramètres de base de l'ordre
        params = {
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": quantity,
            "recvWindow": 5000  # Fenêtre de réception en millisecondes
        }
        
        # Pour les ordres LIMIT, ajouter timeInForce et price
        if type == "LIMIT":
            params["timeInForce"] = "GTC"  # Good Till Cancel (valide jusqu'à annulation)
            # Utiliser le prix fourni ou récupérer le prix actuel
            params["price"] = price if price is not None else await self.api_manager._get_current_price(symbol)
        
        # Endpoint pour les ordres réels
        endpoint = "/api/v3/order"
        
        try:
            # Exécuter la requête à l'API
            result = await self.api_manager._make_request("POST", endpoint, params=params, signed=True)
            self.logger.info(f"Ordre réel placé avec succès: {result}")
            
            # NOUVEAU: Stocker les détails de l'ordre dans l'historique
            if 'orderId' in result:
                order_details = {
                    'order_id': result['orderId'],
                    'symbol': symbol,
                    'side': side,
                    'type': type,
                    'original_quantity': quantity,
                    'executed_quantity': result.get('executedQty', quantity),
                    'price': result.get('price', price if price is not None else 'market'),
                    'status': result.get('status', 'FILLED'),
                    'timestamp': result.get('transactTime', int(time.time() * 1000)),
                    'raw_response': result  # Conserver la réponse complète
                }
                self.order_history.append(order_details)
                self.logger.info(f"Ordre {result['orderId']} ajouté à l'historique ({len(self.order_history)} ordres)")
           
            return result
        except Exception as e:
            # Gestion des erreurs spécifiques à Binance
            error_msg = str(e)
            if "insufficient balance" in error_msg.lower():
                self.logger.error(f"Fonds insuffisants pour placer l'ordre {symbol} {side}: {error_msg}")
            elif "lot size" in error_msg.lower():
                self.logger.error(f"Erreur de taille de lot pour {symbol}: {error_msg}")
            else:
                self.logger.error(f"Erreur lors du placement de l'ordre {symbol} {side}: {error_msg}")
            
            # Réémettre l'exception pour la gestion en amont
            raise

    def _calculate_quantity(self, symbol: str, position_size: float, price: float) -> float:
        """
        Calcule la quantité à acheter en fonction de la taille de position,
        en respectant les règles de précision de Binance pour chaque actif
        """
        # Calculer la quantité brute
        raw_quantity = position_size / price
        
        try:
            # Obtenir les règles de la paire depuis le cache
            symbol_info = self.symbol_rules.get(symbol, {})
            
            # Si les règles sont disponibles dans le cache, les utiliser
            if symbol_info and 'step_size' in symbol_info:
                # Extraire les règles pertinentes pour ce symbole
                step_size = symbol_info.get('step_size', 0.00001)
                min_qty = symbol_info.get('min_qty', 0.00001)
                min_notional = symbol_info.get('min_notional', 10.0)  # Utiliser la valeur par défaut si absente
                
                # Calculer le nombre de décimales basé sur step_size
                precision = 0
                if step_size < 1:
                    step_str = str(step_size).rstrip('0')
                    if '.' in step_str:
                        precision = len(step_str.split('.')[-1])
                
                # Arrondir la quantité selon le step_size
                quantity = math.floor(raw_quantity / step_size) * step_size
                quantity = float('{:.{}f}'.format(quantity, precision))
                
                # Log détaillé pour le débogage
                self.logger.debug(
                    f"Calcul de quantité pour {symbol}: raw={raw_quantity}, step={step_size}, "
                    f"min={min_qty}, precision={precision}, calculated={quantity}"
                )
                
                # Vérifier que la quantité est supérieure au minimum
                if quantity < min_qty:
                    self.logger.warning(
                        f"Quantité calculée {quantity} inférieure au minimum {min_qty} pour {symbol}. "
                        f"Utilisation de la quantité minimum."
                    )
                    quantity = min_qty
                    
                # Vérifier que la valeur de l'ordre dépasse le min_notional
                order_value = quantity * price
                
                if order_value < min_notional:
                    self.logger.warning(
                        f"Valeur d'ordre {order_value} inférieure au minimum {min_notional} USDT pour {symbol}. "
                        f"Ajustement de la quantité."
                    )
                    # Augmenter la quantité pour atteindre le min_notional
                    quantity = min_notional / price
                    # Réarrondir selon le step_size
                    quantity = float('{:.{}f}'.format(
                        math.ceil(quantity / step_size) * step_size, 
                        precision
                    ))
                
                return quantity
            else:
                # MODIFICATION: Message plus précis si les règles sont partiellement disponibles
                if symbol_info:
                    missing_rules = [rule for rule in ['step_size', 'min_qty', 'min_notional'] if rule not in symbol_info]
                    self.logger.warning(f"Règles incomplètes pour {symbol}, règles manquantes: {missing_rules}")
                else:
                    self.logger.warning(f"Aucune règle disponible pour {symbol}")
                    
                # Utiliser des valeurs par défaut sécurisées
                return float('{:.4f}'.format(raw_quantity * 0.99))  # 0.99 pour légèrement réduire la quantité par sécurité
                    
        except Exception as e:
            self.logger.error(f"Erreur lors du calcul de la quantité pour {symbol}: {e}")
            # En cas d'erreur, utiliser un arrondi simple mais sécuritaire
            return math.floor(raw_quantity * 100000) / 100000 * 0.99
    
    def get_order_history(self, symbol: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        Récupère l'historique des ordres exécutés
        
        Args:
            symbol: Filtrer par symbole (optionnel)
            limit: Nombre maximum d'ordres à retourner
            
        Returns:
            Liste des ordres exécutés (du plus récent au plus ancien)
        """
        if symbol:
            # Filtrer les ordres pour un symbole spécifique
            filtered_history = [
                order for order in self.order_history 
                if order['symbol'] == symbol
            ]
            return filtered_history[-limit:]  # Retourner les n derniers ordres
        else:
            # Retourner tous les ordres (limités au nombre spécifié)
            return self.order_history[-limit:]

    async def stop(self):
        """Arrête l'exécuteur d'ordres"""
        self.is_running = False
        await self.api_manager.close_session()