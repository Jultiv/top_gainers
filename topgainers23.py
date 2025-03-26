from dataclasses import dataclass
from decimal import Decimal
import asyncio
import logging
from logger_config import get_trading_logger, get_error_logger
import json
from typing import Dict, List, Optional, Tuple, Union, Any
import websockets
from websockets.exceptions import ConnectionClosed
import csv
from datetime import datetime
import aiofiles
import aiohttp
import time
from event_manager import EventManager
from logger_config import cleanup_logger

# Mise en place des connexion avec l'API de Binance

@dataclass
class TradingConfig:
    
    # Par exemple: 'USDT', 'USDC', 'BUSD', etc.
    REFERENCE_CURRENCY: str = 'USDC'
    
    # Paramètres pour le mode d'exécution des ordres
    # 0 = Ordres de test sur testnet (validation seulement, pas de modification de solde)
    # 1 = Ordres réels sur testnet (exécution avec fonds virtuels)
    # 2 = Ordres réels sur mainnet (exécution avec fonds réels)
    ORDER_EXECUTION_MODE: int = 1
    
    # Paramètres temporels et d'analyse
    INTERVAL: int = 180
    TIME_SLICES: int = 2  
    MIN_CONSECUTIVE_TRENDS: int = 1
    USE_TREND_VERIFICATION: bool = False # contrôle si le bot doit vérifier ou non que les variations sont croissantes entre les tranches
    USE_TRAILING_STOP: bool = True # Active/désactive le trailing stop

    # Paramètres pour le warm-up
    ENABLE_WARMUP: bool = False # Active/désactive le mécanisme de warm-up
    WARMUP_MULTIPLIER: float = 1.0 # Multiplicateur optionnel pour ajuster la durée du warm-up

    # Paramètres ATR et Volatilité (nouveaux)
    ATR_PERIOD: int = 14  # Nombre de périodes pour le calcul de l'ATR (valeur standard)
    VOLATILITY_BASELINE: float = 1.0  # Valeur de référence pour la volatilité normale
    MIN_DATA_POINTS: int = 7  # Minimum de points requis pour calculer l'ATR (généralement égal à ATR_PERIOD)
    PRICE_PRECISION: int = 8  # Nombre de décimales pour les calculs de prix (standard pour les cryptos)
    
    # Seuils ATR (non actif)
    ATR_LOW_VOLATILITY: float = 0.5  # Seuil en dessous duquel la volatilité est considérée faible
    ATR_HIGH_VOLATILITY: float = 2.0  # Seuil au-dessus duquel la volatilité est considérée élevée
    MAX_VOLATILITY_RATIO: float = 5.0  # Ratio maximum accepté pour les calculs de volatilité
    # Paramètres pour le filtre de volatilité
    USE_VOLATILITY_FILTER: bool = False  # Active/désactive le filtre de volatilité
    MIN_VOLATILITY_RATIO: float = 2.5   # Ratio minimum de volatilité pour prendre une position

    # Paramètres pour le RSI
    RSI_PERIOD: int = 14  # Période standard pour le calcul du RSI
    RSI_OVERBOUGHT: float = 70.0  # Seuil de surachat
    RSI_OVERSOLD: float = 30.0  # Seuil de survente
    RSI_SMOOTHING: int = 1  # Facteur de lissage (généralement 1 pour la formule classique)
    # Seuils RSI spécifiques par stratégie
    RSI_MAX_SAFE: float = 80.0  # Seuil maximum pour une position prudente
    RSI_MIN_RISKY: float = 40.0  # Seuil minimum pour une position risquée

    # Paramètres de position
    MAX_PAIRS: int = 200  # Limitation du nombre de paires
    INITIAL_CAPITAL: float = 100
    POSITION_SIZE: float = 30.0  # Pourcentage du capital à utiliser par position (25%)
    MIN_POSITION_SIZE: float = 15.0  # Taille minimale d'une position pour éviter des positions trop petites

    # Seuils de tendance %
    TREND_THRESHOLD_SAFE_PER_SLICE: float = 0.2
    TREND_CONFIRMATION_SAFE: float = 1.5
    TREND_THRESHOLD_RISKY_PER_SLICE: float = 0.2
    TREND_CONFIRMATION_RISKY: float = 3.0

    # seuil de variation du volume
    MIN_VOLUME_CHANGE_THRESHOLD: float = 0.1  # Variation minimale de volume requise en %

    # Take Profit et Stop Loss %
    TAKE_PROFIT_SAFE: float = 3.5  
    STOP_LOSS_SAFE: float = -2.8
    TAKE_PROFIT_RISKY: float = 6.5
    STOP_LOSS_RISKY: float = -4.0

     # Paramètres pour le trailing stop poisition prudente
    TRAILING_STOP_ACTIVATION_SAFE: float = 1.2  # % de profit à partir duquel le trailing stop s'active
    TRAILING_STOP_DISTANCE_SAFE: float = 0.6    # Distance du trailing stop en % par rapport au prix le plus haut
    # Paramètres pour le trailing stop - Position Risquée
    TRAILING_STOP_ACTIVATION_RISKY: float = 1.2  # % de profit pour activation (risqué)
    TRAILING_STOP_DISTANCE_RISKY: float = 0.6   # Distance du trailing (risqué)
       
    # Paramètres de gestion des positions
    PAIR_COOLDOWN: int = 1800
    TRANSACTION_FEE: float = 0.00075
    OUTPUT_FILE: str = "crypto_prices.csv"
    POSITIONS_FILE: str = "positions.csv"
    LOG_FILE: str = "trading_bot.log"
    
    RECONNECT_DELAY: int = 5  # Délai initial de reconnexion en secondes
    MAX_RECONNECT_DELAY: int = 300  # Délai maximum de reconnexion (5 minutes)
    WEBSOCKET_PING_INTERVAL: int = 30  # Intervalle d'envoi des pings en secondes
    WEBSOCKET_PING_TIMEOUT: int = 30  # Timeout pour la réponse aux pings
    WEBSOCKET_CLOSE_TIMEOUT = 10

class WebSocketMetrics:
    def __init__(self):
        self.connection_attempts = 0
        self.successful_connections = 0
        self.disconnections = 0
        self.reconnection_times = []
        self.last_disconnect_time = None
        self.last_disconnect_reason = None
        self.connection_start_time = None
        
    def log_connection_attempt(self):
        self.connection_attempts += 1
        self.connection_start_time = time.time()
        
    def log_successful_connection(self):
        self.successful_connections += 1
        if self.connection_start_time:
            reconnect_time = time.time() - self.connection_start_time
            self.reconnection_times.append(reconnect_time)
            
    def log_disconnection(self, reason: str):
        self.disconnections += 1
        self.last_disconnect_time = time.time()
        self.last_disconnect_reason = reason
        
    def get_metrics_report(self) -> dict:
        avg_reconnect_time = (
            sum(self.reconnection_times) / len(self.reconnection_times)
            if self.reconnection_times else 0
        )
        return {
            "total_connection_attempts": self.connection_attempts,
            "successful_connections": self.successful_connections,
            "total_disconnections": self.disconnections,
            "average_reconnection_time": round(avg_reconnect_time, 2),
            "last_disconnect_reason": self.last_disconnect_reason,
            "connection_success_rate": round(
                (self.successful_connections / self.connection_attempts * 100)
                if self.connection_attempts > 0 else 0, 2
            )
        }

class PriceManager:
    """Gère la réception et l'analyse des prix"""
    def __init__(self, config: TradingConfig):
        # Attributs existants
        self.config = config
        self.logger = get_trading_logger()
        self.error_logger = get_error_logger()
        self.interval = config.INTERVAL
        self.current_prices: Dict[str, float] = {}
        self.price_history: Dict[str, List[Tuple[float, float]]] = {}
        self.last_analysis_time = time.time()
        
        # Attribut pour les variations par tranche
        self.slice_variations: Dict[str, List[float]] = {}

        # Attributs pour le volume
        self.volume_history: Dict[str, List[Tuple[float, float]]] = {}  # Stockage de l'historique des volumes (timestamp, volume)
        self.current_volumes: Dict[str, float] = {}  # Stockage des volumes actuels
        self.volume_changes: Dict[str, List[float]] = {}  # Stockage des variations de volume par tranche

        # Attributs pour l'ATR
        self.ohlc_data: Dict[str, List[Dict[str, float]]] = {}  # Stockage des données OHLC par symbole
        self.atr_values: Dict[str, float] = {}  # Stockage des valeurs ATR courantes
        self.volatility_ratios: Dict[str, float] = {}  # Stockage des ratios de volatilité
        self.high_prices: Dict[str, float] = {}  # Prix le plus haut dans l'intervalle courant
        self.low_prices: Dict[str, float] = {}  # Prix le plus bas dans l'intervalle courant

        # Attributs pour le RSI
        self.price_changes: Dict[str, List[float]] = {}  # Stockage des variations de prix
        self.gains: Dict[str, List[float]] = {}  # Stockage des gains (variations positives)
        self.losses: Dict[str, List[float]] = {}  # Stockage des pertes (variations négatives)
        self.avg_gains: Dict[str, float] = {}  # Moyenne des gains
        self.avg_losses: Dict[str, float] = {}  # Moyenne des pertes
        self.rsi_values: Dict[str, float] = {}  # Valeurs RSI calculées
    
    def update_price(self, pair: str, price: float) -> None:
        """Met à jour le prix actuel, l'historique et les données OHLC"""
        # Mise à jour du prix actuel dans le dictionnaire
        self.current_prices[pair] = price
        current_time = time.time()
        
        # Initialisation de l'historique des prix si nécessaire
        if pair not in self.price_history:
            self.price_history[pair] = []
        
        # Ajout du nouveau prix à l'historique avec son timestamp
        self.price_history[pair].append((current_time, price))
        
        # Nettoyage des données anciennes en conservant uniquement 
        # les données nécessaires pour l'analyse (basé sur le nombre total de tranches)
        total_interval = self.interval * self.config.TIME_SLICES
        cutoff_time = current_time - total_interval
        self.price_history[pair] = [
            (t, p) for t, p in self.price_history[pair] 
            if t > cutoff_time
        ]

        #Mise à jour des prix High/Low pour l'ATR
        if pair not in self.high_prices:
            self.high_prices[pair] = price
            self.low_prices[pair] = price
        else:
            self.high_prices[pair] = max(self.high_prices[pair], price)
            self.low_prices[pair] = min(self.low_prices[pair], price)

        # Calcule les variations de prix pour le RSI
        self.update_price_changes(pair)
        
        # Si nous avons assez de données, calcule le RSI
        if pair in self.price_changes and len(self.price_changes[pair]) >= self.config.RSI_PERIOD:
            self.calculate_rsi(pair)
        else:
            # S'assurer que la valeur par défaut est utilisée
            self.rsi_values[pair] = 50.0

    def calculate_rsi(self, pair: str) -> float:
        """Calcule le RSI pour une paire donnée"""
        # Vérification stricte du nombre de points de données
        if (pair not in self.gains or
            pair not in self.losses or
            len(self.gains[pair]) < self.config.RSI_PERIOD or
            len(self.losses[pair]) < self.config.RSI_PERIOD):
            
            # Log détaillé
            self.logger.debug(f"RSI {pair}: Données insuffisantes - retour valeur par défaut 50")
            # Garantir que le RSI reste à 50
            self.rsi_values[pair] = 50.0
            return 50.0
        
        # Calcul de la moyenne des gains et des pertes
        if pair not in self.avg_gains:
            # Premier calcul (moyenne simple)
            self.avg_gains[pair] = sum(self.gains[pair]) / self.config.RSI_PERIOD
            self.avg_losses[pair] = sum(self.losses[pair]) / self.config.RSI_PERIOD
        else:
            # Calculs suivants (moyenne lissée)
            self.avg_gains[pair] = (
                (self.avg_gains[pair] * (self.config.RSI_PERIOD - 1) + self.gains[pair][-1]) 
                / self.config.RSI_PERIOD
            )
            self.avg_losses[pair] = (
                (self.avg_losses[pair] * (self.config.RSI_PERIOD - 1) + self.losses[pair][-1]) 
                / self.config.RSI_PERIOD
            )
        
        # Éviter division par zéro
        if self.avg_losses[pair] == 0:
            rsi = 100
        else:
            rs = self.avg_gains[pair] / self.avg_losses[pair]
            rsi = 100 - (100 / (1 + rs))
        
        # Log pour voir les valeurs calculées
        self.logger.debug(f"RSI {pair}: Calculé à {rsi:.2f} (RS: {self.avg_gains[pair]/max(0.0001, self.avg_losses[pair]):.4f})")
    
        # Stocker et retourner la valeur RSI
        self.rsi_values[pair] = rsi
        return rsi
    
    def get_rsi_value(self, pair: str) -> float:
        """Retourne la valeur RSI actuelle pour une paire"""
        return self.rsi_values.get(pair, 50.0)  # 50 est la valeur neutre

    def update_price_changes(self, pair: str) -> None:
        """Calcule et stocke les variations de prix pour le RSI"""
        if pair not in self.price_history or len(self.price_history[pair]) < 2:
            return
            
        # Récupérer l'historique des prix triés par timestamp
        # Utiliser une copie triée pour garantir l'ordre chronologique
        sorted_history = sorted(self.price_history[pair], key=lambda x: x[0])
        prices = [price for _, price in sorted_history]

        # Initialiser les listes si nécessaires
        if pair not in self.price_changes:
            self.price_changes[pair] = []
            self.gains[pair] = []
            self.losses[pair] = []
            self.logger.debug(f"RSI {pair}: Initialisation des structures de données")

        # Calculer la dernière variation de prix
        last_change = prices[-1] - prices[-2]
        
        # Ajouter la variation à l'historique
        self.price_changes[pair].append(last_change)
        
        # Stocker les gains et pertes
        if last_change > 0:
            self.gains[pair].append(last_change)
            self.losses[pair].append(0)
        else:
            self.gains[pair].append(0)
            self.losses[pair].append(abs(last_change))
        
        # Limiter la taille des listes à la période RSI
        if len(self.price_changes[pair]) > self.config.RSI_PERIOD:
            self.price_changes[pair].pop(0)
            self.gains[pair].pop(0)
            self.losses[pair].pop(0)

        # Log pour suivre l'accumulation de données
        self.logger.debug(f"RSI {pair}: {len(self.price_changes[pair])}/{self.config.RSI_PERIOD} points accumulés")

    def debug_rsi(self, pair: str) -> None:
        """Affiche des informations de debug pour le RSI d'une paire"""
        if pair not in self.price_changes:
            self.logger.info(f"Debug RSI {pair}: Aucune donnée de variation de prix")
            return
            
        self.logger.info(f"Debug RSI {pair}:")
        self.logger.info(f"  - Nombres de variations: {len(self.price_changes[pair])}/{self.config.RSI_PERIOD}")
        
        if pair in self.gains and pair in self.losses:
            avg_gain = sum(self.gains[pair]) / len(self.gains[pair]) if self.gains[pair] else 0
            avg_loss = sum(self.losses[pair]) / len(self.losses[pair]) if self.losses[pair] else 0
            self.logger.info(f"  - Gain moyen: {avg_gain:.8f}, Perte moyenne: {avg_loss:.8f}")
            
        if pair in self.avg_gains and pair in self.avg_losses:
            self.logger.info(f"  - Gain lissé: {self.avg_gains[pair]:.8f}, Perte lissée: {self.avg_losses[pair]:.8f}")
            
        if pair in self.rsi_values:
            self.logger.info(f"  - Valeur RSI calculée: {self.rsi_values[pair]:.2f}")
        else:
            self.logger.info(f"  - Aucune valeur RSI calculée")

    def update_ohlc(self, pair: str) -> None:
        """Met à jour les données OHLC à la fin de chaque intervalle"""
        if pair not in self.price_history or len(self.price_history[pair]) < 2:
            return

        current_time = time.time()
        
        # Extraire toutes les données de prix dans l'intervalle actuel
        interval_data = [(t, p) for t, p in self.price_history[pair] 
                        if t > current_time - self.interval]

        if not interval_data:
            return

        # Extraire seulement les prix (sans timestamps) pour calculs min/max
        interval_prices = [p for _, p in interval_data]
        
        # Calcul explicite des vraies valeurs high et low
        high_price = max(interval_prices) if len(interval_prices) > 0 else interval_prices[0]
        low_price = min(interval_prices) if len(interval_prices) > 0 else interval_prices[0]

        ohlc = {
            'open': interval_prices[0],
            'high': high_price,
            'low': low_price,
            'close': interval_prices[-1]
        }

        if pair not in self.ohlc_data:
            self.ohlc_data[pair] = []
        
        self.ohlc_data[pair].append(ohlc)
        
        # Nettoyage des anciennes données OHLC
        if len(self.ohlc_data[pair]) > self.config.ATR_PERIOD:
            self.ohlc_data[pair].pop(0)

        # Réinitialisation des prix High/Low pour le prochain intervalle
        # en utilisant le dernier prix comme référence
        self.high_prices[pair] = interval_prices[-1]
        self.low_prices[pair] = interval_prices[-1]
        
        # Log pour debug des valeurs OHLC
        self.logger.debug(f"OHLC {pair} - O: {ohlc['open']:.8f}, H: {ohlc['high']:.8f}, "
                    f"L: {ohlc['low']:.8f}, C: {ohlc['close']:.8f}")

    def calculate_true_range(self, pair: str, current_ohlc: Dict[str, float], 
                           previous_close: Optional[float] = None) -> float:
        """Calcule le True Range pour une période"""
        if previous_close is None:
            return current_ohlc['high'] - current_ohlc['low']

        return max(
            current_ohlc['high'] - current_ohlc['low'],  # High-Low courant
            abs(current_ohlc['high'] - previous_close),  # High-Close précédent
            abs(current_ohlc['low'] - previous_close)    # Low-Close précédent
        )

    def update_atr(self, pair: str) -> None:
        """Calcule et met à jour l'ATR pour une paire"""
        if pair not in self.ohlc_data or len(self.ohlc_data[pair]) < 2:
            return

        ohlc_data = self.ohlc_data[pair]
        
        # Calcul du premier TR
        tr_values = []
        previous_close = None
        
        for i in range(len(ohlc_data)):
            tr = self.calculate_true_range(pair, ohlc_data[i], previous_close)
            tr_values.append(tr)
            previous_close = ohlc_data[i]['close']

        # Calcul de l'ATR
        if len(tr_values) >= self.config.ATR_PERIOD:
            if pair not in self.atr_values:
                # Premier calcul ATR (moyenne simple)
                self.atr_values[pair] = sum(tr_values[-self.config.ATR_PERIOD:]) / self.config.ATR_PERIOD
            else:
                # Mise à jour ATR avec la formule de Wilder
                current_tr = tr_values[-1]
                previous_atr = self.atr_values[pair]
                self.atr_values[pair] = (
                    (previous_atr * (self.config.ATR_PERIOD - 1) + current_tr) 
                    / self.config.ATR_PERIOD
                )

    def calculate_volatility_ratio(self, pair: str) -> float:
        """Calcule le ratio de volatilité par rapport à la baseline, normalisé par le prix"""
        if pair not in self.atr_values or pair not in self.current_prices:
            return 1.0  # Valeur par défaut si pas assez de données

        current_price = self.current_prices[pair]
        current_atr = self.atr_values[pair]
        
        # Pour éviter division par zéro
        if current_price <= 0:
            return 1.0
        
        # ATR en pourcentage du prix pour permettre des comparaisons équitables
        atr_percentage = (current_atr / current_price) * 100
        
        # Baseline en pourcentage (0.5% comme volatilité "normale")
        # Vous pouvez ajuster cette valeur selon votre analyse de marché
        baseline_percentage = 0.5
        
        # Calcul du ratio
        ratio = atr_percentage / baseline_percentage
        
        # Limitation et stockage
        ratio_limited = min(max(ratio, 0), self.config.MAX_VOLATILITY_RATIO)
        self.volatility_ratios[pair] = ratio_limited
        
        return ratio_limited

    def get_volatility_metrics(self, pair: str) -> Dict[str, float]:
        """Retourne les métriques de volatilité pour une paire"""
        # Calculer le ratio au besoin si l'ATR existe mais pas encore le ratio
        if pair in self.atr_values and (pair not in self.volatility_ratios or self.volatility_ratios[pair] == 0):
            self.calculate_volatility_ratio(pair)
        
        # Obtenir les valeurs actuelles des prix high/low si disponibles
        if pair in self.ohlc_data and len(self.ohlc_data[pair]) > 0:
            latest_ohlc = self.ohlc_data[pair][-1]
            high = latest_ohlc['high']
            low = latest_ohlc['low']
        else:
            high = self.high_prices.get(pair, 0)
            low = self.low_prices.get(pair, 0)
        
        return {
            'atr': round(self.atr_values.get(pair, 0), self.config.PRICE_PRECISION),
            'volatility_ratio': round(self.volatility_ratios.get(pair, 1.0), 2),
            'high': high,
            'low': low
        }

    def update_volume(self, pair: str, volume: float) -> None:
        """
        Met à jour le volume actuel et l'historique des volumes
        
        Args:
            pair: Le symbole de la paire
            volume: Le volume en USDT sur la période
        """
        # Stockage du volume actuel
        self.current_volumes[pair] = volume
        current_time = time.time()
        
        # Initialisation de l'historique des volumes si nécessaire
        if pair not in self.volume_history:
            self.volume_history[pair] = []
        
        # Ajout du nouveau volume à l'historique
        self.volume_history[pair].append((current_time, volume))
        
        # Nettoyage des données anciennes, comme pour les prix
        total_interval = self.interval * self.config.TIME_SLICES
        cutoff_time = current_time - total_interval
        self.volume_history[pair] = [
            (t, v) for t, v in self.volume_history[pair] 
            if t > cutoff_time
        ]

    def analyze_volume_slices(self, pair: str) -> Tuple[List[float], float]:
        """
        Analyse les volumes par tranche et calcule la variation du volume total
        
        Returns:
            Tuple contenant:
            - Liste des volumes par tranche
            - Variation du volume en pourcentage entre la première et dernière tranche
        """
        if pair not in self.volume_history:
            return [], 0.0
            
        current_time = time.time()
        volumes_by_slice = []
        history = self.volume_history[pair]
        
        # Analyse de chaque tranche
        for i in range(self.config.TIME_SLICES):
            start_time = current_time - (i + 1) * self.interval
            end_time = current_time - i * self.interval
            
            # Filtrer les volumes dans la tranche temporelle
            slice_volumes = [vol for t, vol in history if start_time <= t <= end_time]
            
            # Calculer le volume total de la tranche
            total_volume = sum(slice_volumes) if slice_volumes else 0
            volumes_by_slice.insert(0, total_volume)
        
        # Calcul de la variation de volume entre la première et dernière tranche
        if len(volumes_by_slice) >= 2 and volumes_by_slice[0] > 0:
            volume_change = ((volumes_by_slice[-1] - volumes_by_slice[0]) / volumes_by_slice[0]) * 100
        else:
            volume_change = 0.0
            
        return volumes_by_slice, volume_change

    def should_analyze(self) -> bool:
        """Vérifie si une analyse complète doit être effectuée"""
        current_time = time.time()
        if current_time - self.last_analysis_time >= self.interval:
            self.last_analysis_time = current_time
            return True
        return False

    def get_current_price(self, pair: str) -> Optional[float]:
        """Récupère le prix actuel d'une paire"""
        return self.current_prices.get(pair)

    def get_analysis_data(self, pair: str) -> Tuple[Optional[float], Optional[float]]:
        """Récupère les données pour l'analyse sur l'intervalle"""
        if pair in self.price_history and len(self.price_history[pair]) >= 2:
            prices = [p for _, p in self.price_history[pair]]
            return prices[0], prices[-1]
        return None, None

    def analyze_trend_slices(self, pair: str) -> Tuple[List[float], float]:
        """Analyse les variations de prix par tranche et la variation totale"""
        if pair not in self.price_history:
            return [], 0.0

        current_time = time.time()
        variations = []
        history = self.price_history[pair]
        
        # Analyse chaque tranche
        for i in range(self.config.TIME_SLICES):
            start_time = current_time - (i + 1) * self.interval
            end_time = current_time - i * self.interval
            
            slice_prices = [(t, p) for t, p in history 
                           if start_time <= t <= end_time]
            
            if len(slice_prices) >= 2:
                start_price = slice_prices[0][1]
                end_price = slice_prices[-1][1]
                variation = ((end_price - start_price) / start_price) * 100
                variations.insert(0, variation)
            else:
                variations.insert(0, 0.0)

        # Calcul de la variation totale
        if len(history) >= 2:
            total_variation = ((history[-1][1] - history[0][1]) / history[0][1]) * 100
        else:
            total_variation = 0.0
            
        return variations, total_variation

    def confirm_trend(self, pair: str, is_risky: bool = False) -> bool:
        """Confirme si la tendance respecte les critères définis"""
        variations, total_variation = self.analyze_trend_slices(pair)
        
        if len(variations) < self.config.MIN_CONSECUTIVE_TRENDS:
            self.logger.debug(f"{pair} - Pas assez de données ({len(variations)} tranches)")
            return False
        
        # Vérification des tendances croissantes uniquement si activée et si plus d'une tranche
        if self.config.USE_TREND_VERIFICATION and len(variations) > 1:
            for i in range(1, len(variations)):
                if variations[i] <= variations[i-1]:
                    self.logger.debug(f"{pair} - Tendance non croissante entre les tranches {i-1} et {i}")
                    return False
        
        # Vérifie les seuils par tranche
        threshold_per_slice = (self.config.TREND_THRESHOLD_RISKY_PER_SLICE 
                            if is_risky else 
                            self.config.TREND_THRESHOLD_SAFE_PER_SLICE)
        
        # Vérifie que le nombre minimum de variations est au-dessus du seuil
        variations_above_threshold = sum(1 for var in variations if var >= threshold_per_slice)
        if variations_above_threshold < self.config.MIN_CONSECUTIVE_TRENDS:
            self.logger.debug(f"{pair} - Pas assez de variations au-dessus du seuil")
            return False
        
        # Vérifie le seuil de tendance globale
        global_threshold = (self.config.TREND_CONFIRMATION_RISKY 
                        if is_risky else 
                        self.config.TREND_CONFIRMATION_SAFE)
        
        result = total_variation >= global_threshold
        if result:
            self.logger.info(f"{pair} - Tendance confirmée {'(risquée)' if is_risky else '(prudente)'} - "
                        f"Variation totale: {round(total_variation, 2)}% - "
                        f"Variations par tranche: {[round(v, 2) for v in variations]}%")
        
        return result

class DataRecorder:
    """Handles data recording to CSV files"""
    def __init__(self, config: TradingConfig):
        self.logger = get_trading_logger()
        self.error_logger = get_error_logger()
        self.config = config
        self._init_files()
        # Dictionnaire qui stocke les positions ouvertes
        # Clé: pair (symbole de la paire)
        # Valeur: tuple (numéro de ligne dans le CSV, données complètes)
        self.open_positions = {}
        # Compteur de lignes pour suivre où chaque position est enregistrée
        self.line_counter = 0
        
    def _init_files(self):
        """
        Initialisation des fichiers avec gestion propre des handlers
        Cette méthode:
        1. Nettoie les loggers existants pour éviter la duplication
        2. Configure les handlers de fichier et de console
        3. Applique des filtres pour limiter les logs verbeux
        4. Initialise les fichiers CSV avec les en-têtes appropriés
        """
       # Nettoyage des loggers existants pour éviter la duplication
        cleanup_logger('')  # Logger root
        cleanup_logger('trading')  # Notre logger principal

        # Configuration du logging
        file_handler = logging.FileHandler(self.config.LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        def filter_websocket_messages(record):
            # Filtrer les messages contenant du texte JSON brut
            if '{"e":"24hrTicker"' in str(record.msg):
                return False
            # Filtrer les messages de WebSocket debug
            if 'TEXT' in str(record.msg) and 'bytes' in str(record.msg):
                return False
            # Filtrer les messages d'analyse y compris les confirmations de tendance
            if "Analyse" in str(record.msg):
                return False
            # Filtrer explicitement les messages de tendance confirmée
            if "Tendance confirmée" in str(record.msg):
                return False
            # Conserver les messages de position ouverte/fermée et les autres messages importants
            return True

        file_handler.addFilter(filter_websocket_messages)
        console_handler.addFilter(filter_websocket_messages)

        # Configuration du logger root
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        # NOUVEAU: Informer notre propre logger personnalisé (sans modifier le comportement principal)
        self.logger.info(f"DataRecorder: Configuration des fichiers de logs initialisée")

        # Création des en-têtes avec gestion flexible des tranches
        price_headers = ["Timestamp", "Symbol", "Price"]
        
        # Ajouter les colonnes de variation selon la configuration
        if self.config.TIME_SLICES > 1:
            # Multiple tranches : ajouter les variations individuelles
            for i in range(self.config.TIME_SLICES):
                price_headers.append(f"Variation_T{i+1}")
        # Toujours ajouter la variation totale
        price_headers.append("Total_Variation")

        # Ajouter les colonnes pour le volume
        price_headers.append("Current_Volume")
        if self.config.TIME_SLICES > 1:
            for i in range(self.config.TIME_SLICES):
                price_headers.append(f"Volume_T{i+1}")
        price_headers.append("Volume_Change")

        # Nouvelles colonnes pour l'ATR
        price_headers.extend([
            "ATR",           # Valeur ATR actuelle
            "Period_High_Price",      # Prix le plus haut de la période
            "Period_Low_Price",       # Prix le plus bas de la période
            "Volatility_Ratio"  # Ratio de volatilité
        ])

        # NOUVELLE COLONNE POUR LE RSI
        price_headers.append("RSI")

        # Journaliser la configuration actuelle
        self.logger.info(f"Configuration d'analyse: {self.config.TIME_SLICES} tranche(s)")
        if self.config.TIME_SLICES > 1:
            self.logger.info(f"Nombre minimum de tendances requises: {self.config.MIN_CONSECUTIVE_TRENDS}")
            if self.config.USE_TREND_VERIFICATION:
                self.logger.info("Vérification des tendances croissantes activée")
        
        # Journaliser la configuration ATR
        self.logger.info(f"Configuration ATR - Période: {self.config.ATR_PERIOD}, "
                    f"Baseline: {self.config.VOLATILITY_BASELINE}")
        self.logger.info(f"Seuils de volatilité - Bas: {self.config.ATR_LOW_VOLATILITY}, "
                    f"Haut: {self.config.ATR_HIGH_VOLATILITY}")

        # NOUVEAU: Log pour le filtre de volatilité
        if self.config.USE_VOLATILITY_FILTER:
            self.logger.info(f"Filtre de volatilité ACTIVÉ - Ratio minimum: {self.config.MIN_VOLATILITY_RATIO}")
        else:
            self.logger.info("Filtre de volatilité DÉSACTIVÉ")

        # JOURNALISER LA CONFIGURATION RSI
        self.logger.info(f"Configuration RSI - Période: {self.config.RSI_PERIOD}, "
                    f"Seuil surachat: {self.config.RSI_OVERBOUGHT}, "
                    f"Seuil survente: {self.config.RSI_OVERSOLD}")

        # Initialisation du fichier de prix avec nouveaux en-têtes
        with open(self.config.OUTPUT_FILE, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(price_headers)
            self.logger.info(f"Fichier {self.config.OUTPUT_FILE} initialisé avec {len(price_headers)} colonnes")
        
         # En-têtes pour positions.csv
        position_headers = [
            "Heure",
            "Pair"
        ]

        # Ajout dynamique des colonnes de variation selon le nombre de tranches configuré
        for i in range(self.config.TIME_SLICES):
            position_headers.append(f"Variation_T{i+1}")

        # Ajout des autres en-têtes d'entrée
        position_headers.extend([
            "Total_Variation",
            "Volume",
            "Volume_Variation",
            "ATR",
            "Volatility_Ratio",
            "RSI",
            "Position_Type_Entry",  # Prudente ou Risquée
            "Entry_Price",
            "Position_Size",
            "Position_Size_Percent",
            "Entry_Fees"
        ])

        # Ajout des en-têtes de sortie
        position_headers.extend([
            "Heure_Sortie",
            "Position_Type_Exit",   # Take_Profit, Trailing_Stop ou Stop_Loss
            "Exit_Price",
            "Exit_Fees",
            "Profit_Loss",
            "Profit_Loss_Net",
            "Remaining_Capital"
        ])

         # Initialisation du fichier des positions avec nouveaux en-têtes
        with open(self.config.POSITIONS_FILE, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(position_headers)
            self.logger.info(f"Fichier {self.config.POSITIONS_FILE} initialisé")

        # Réinitialiser le compteur de lignes et le dictionnaire de positions ouvertes
        self.line_counter = 0
        self.open_positions = {}
        
    async def record_price(self, timestamp: str, pair: str, price: float, 
                      variation: float, detailed_variations: str = "", 
                      volatility_metrics: Optional[Dict[str, float]] = None, 
                      volume_metrics: Optional[Dict[str, Any]] = None,
                      rsi_value: float = 50.0) -> None:
    
        """Enregistre les données dans le fichier CSV"""
        try:
            # Initialiser volume_metrics avec des valeurs par défaut si non fourni
            if volume_metrics is None:
                volume_metrics = {
                    'current_volume': 0.0,
                    'volumes_by_slice': [0.0] * self.config.TIME_SLICES,
                    'volume_change': 0.0,
                }
            else:
                # Création d'une copie non None pour éviter les avertissements
                volume_metrics = dict(volume_metrics)
            
            # Initialiser volatility_metrics avec des valeurs par défaut si non fourni
            if volatility_metrics is None:
                volatility_metrics = {
                    'atr': 0.0,
                    'high': price,
                    'low': price,
                    'volatility_ratio': 1.0
                }
            # Extraire les variations
            variations_str = detailed_variations.split("Tranches: ")[1].split(", Total:")[0]
            total_var = detailed_variations.split("Total: ")[1].strip().replace("%", "")
            
            # Convertir la chaîne de variations en liste
            try:
                variations = eval(variations_str.replace("%", ""))  # Convertit la liste de variations
            except:
                variations = [0.0] * self.config.TIME_SLICES  # Liste de zéros de la bonne taille
                
            # S'assurer qu'on a le bon nombre de valeurs
            while len(variations) < self.config.TIME_SLICES:
                variations.append(0.0)
            
            # Créer la ligne de données de manière dynamique
            data = [
                timestamp,
                pair,
                f"{price:.8f}"
            ]
            # Ajouter chaque variation de tranche
            data.extend([f"{v:.2f}" for v in variations])
            # Ajouter la variation totale
            data.append(total_var.replace("%", ""))

            # Ajouter les données de volume avec conversion en entiers
            data.append(f"{int(volume_metrics.get('current_volume', 0))}")
            
            # Pour les volumes par tranche, convertir en entiers
            volumes = volume_metrics.get('volumes_by_slice', [])
            while len(volumes) < self.config.TIME_SLICES:
                volumes.append(0)
            data.extend([f"{int(v)}" for v in volumes])  # Entiers pour les volumes par tranche

            # Le volume_change avec 2 décimales
            data.append(f"{volume_metrics.get('volume_change', 0.0):.2f}")

            data.extend([
                f"{volatility_metrics['atr']:.8f}",
                f"{volatility_metrics['high']:.8f}",
                f"{volatility_metrics['low']:.8f}",
                f"{volatility_metrics['volatility_ratio']:.2f}"
            ])
             # AJOUTER LA VALEUR RSI
            data.append(f"{rsi_value:.2f}")  # RSI avec 2 décimales

            async with aiofiles.open(self.config.OUTPUT_FILE, mode='a', newline='', encoding='utf-8') as file:
                await file.write(','.join(map(str, data)) + '\n')

        except Exception as e:
            self.logger.error(f"Erreur lors de l'enregistrement du prix pour {pair}: {e}")

    async def record_position_entry(self, timestamp: str, pair: str, 
                               entry_type: str, entry_price: float, 
                               position_size: float, position_size_percent: float,
                               entry_fees: float,
                               volatility_metrics: Dict[str, float],
                               volume_metrics: Dict[str, Any],
                               variation_data: Dict[str, Any],
                               rsi_value: float) -> None:
        """
        Enregistre les données d'entrée d'une position
        """
        try:
            # Construction de la ligne pour les données d'entrée
            position_data = [
                timestamp,  # Heure d'entrée
                pair
            ]
            
            # Ajout des variations par tranche
            variations = variation_data.get('variations', [])
            while len(variations) < self.config.TIME_SLICES:
                variations.append(0.0)
            for var in variations:
                position_data.append(f"{var:.2f}")
            
            # Ajout des autres données d'entrée
            position_data.extend([
                f"{variation_data.get('total_variation', 0.0):.2f}",
                f"{int(volume_metrics.get('current_volume', 0))}",
                f"{volume_metrics.get('volume_change', 0.0):.2f}",
                f"{volatility_metrics.get('atr', 0.0):.{self.config.PRICE_PRECISION}f}",
                f"{volatility_metrics.get('volatility_ratio', 1.0):.2f}",
                f"{rsi_value:.2f}",
                entry_type,
                f"{entry_price:.{self.config.PRICE_PRECISION}f}",
                f"{position_size:.2f}",
                f"{position_size_percent:.2f}",
                f"{entry_fees:.{self.config.PRICE_PRECISION}f}"
            ])
            
            # Ajout de champs vides pour les données de sortie (qui seront remplies plus tard)
            # 7 champs de sortie: Heure_Sortie, Position_Type_Exit, Exit_Price, Exit_Fees, Profit_Loss, Profit_Loss_Net, Remaining_Capital
            position_data.extend([""] * 7)
            
            # Écriture dans le fichier
            async with aiofiles.open(self.config.POSITIONS_FILE, mode='a', newline='', encoding='utf-8') as file:
                await file.write(','.join(map(str, position_data)) + '\n')
            
            # Stockage de la position ouverte avec son numéro de ligne
            self.open_positions[pair] = (self.line_counter, position_data)
            self.line_counter += 1
            
            self.logger.info(f"Position ouverte enregistrée - {pair} - {entry_type} - "
                    f"Taille: {position_size:.2f} ({position_size_percent:.2f}%)")
                    
        except Exception as e:
            self.logger.error(f"Erreur lors de l'enregistrement de l'entrée pour {pair}: {e}")

    async def record_position_exit(self, timestamp: str, pair: str,
                              exit_type: str, exit_price: float,
                              exit_fees: float, profit_loss: float,
                              entry_fees: float, capital: float) -> None:
        """
        Met à jour une position existante avec les données de sortie
        """
        try:
            # Vérifier si la position existe
            if pair not in self.open_positions:
                self.logger.warning(f"Tentative de fermeture d'une position non enregistrée: {pair}")
                return
            
            # Récupérer la ligne et les données
            line_number, position_data = self.open_positions[pair]
            
            # Calcul du profit/perte net
            profit_loss_net = profit_loss - (entry_fees + exit_fees)
            
            # Déterminer l'indice de début des données de sortie (dépend du nombre de colonnes d'entrée)
            # 2 (Heure_Entrée, Pair) + TIME_SLICES (variations) + 11 (autres métriques d'entrée)
            exit_start_index = 2 + self.config.TIME_SLICES + 11
            
            # Mettre à jour les champs de sortie
            position_data[exit_start_index] = timestamp        # Heure_Sortie
            position_data[exit_start_index + 1] = exit_type    # Position_Type_Exit
            position_data[exit_start_index + 2] = f"{exit_price:.{self.config.PRICE_PRECISION}f}"  # Exit_Price
            position_data[exit_start_index + 3] = f"{exit_fees:.{self.config.PRICE_PRECISION}f}"   # Exit_Fees
            position_data[exit_start_index + 4] = f"{profit_loss:.{self.config.PRICE_PRECISION}f}" # Profit_Loss
            position_data[exit_start_index + 5] = f"{profit_loss_net:.{self.config.PRICE_PRECISION}f}" # Profit_Loss_Net
            position_data[exit_start_index + 6] = f"{capital:.{self.config.PRICE_PRECISION}f}"     # Remaining_Capital
            
            # Mise à jour de la ligne dans le fichier
            await self._update_position_in_file(line_number, position_data)
            
            # Supprimer la position du dictionnaire
            del self.open_positions[pair]
            
            self.logger.info(f"Position fermée mise à jour - {pair} - {exit_type} - "
                    f"P/L: {profit_loss:.2f}, Net: {profit_loss_net:.2f}")
                    
        except Exception as e:
            self.logger.error(f"Erreur lors de la mise à jour de la sortie pour {pair}: {e}")

    async def _update_position_in_file(self, line_number: int, position_data: List[str]) -> None:
        """
        Met à jour une ligne spécifique dans le fichier positions.csv
        
        Cette méthode lit tout le fichier, modifie la ligne spécifiée, puis réécrit tout le fichier.
        Plus efficace que de réécrire l'ensemble du fichier à chaque mise à jour.
        """
        try:
            # Lire tout le fichier
            lines = []
            async with aiofiles.open(self.config.POSITIONS_FILE, mode='r', encoding='utf-8') as file:
                lines = await file.readlines()
            
            # S'assurer que le nombre de lignes est suffisant
            if len(lines) <= line_number + 1:  # +1 pour tenir compte de l'en-tête
                self.logger.error(f"Impossible de mettre à jour la ligne {line_number}, fichier trop court")
                return
            
            # Mettre à jour la ligne spécifiée (en tenant compte de l'en-tête)
            lines[line_number + 1] = ','.join(map(str, position_data)) + '\n'
            
            # Réécrire tout le fichier
            async with aiofiles.open(self.config.POSITIONS_FILE, mode='w', encoding='utf-8') as file:
                await file.writelines(lines)
                
        except Exception as e:
            self.logger.error(f"Erreur lors de la mise à jour du fichier positions: {e}")

    def cleanup(self):
        """Nettoie les ressources utilisées par le DataRecorder"""
        logger = logging.getLogger()
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

class PositionManager:
    """Manages trading positions"""
    def __init__(self, config: TradingConfig, event_manager: Optional[EventManager] = None):
        self.config = config
        self.logger = get_trading_logger()
        self.error_logger = get_error_logger()
        self.active_positions: Dict[str, dict] = {}
        self.cooldown_pairs: Dict[str, float] = {}
        self.capital = config.INITIAL_CAPITAL
        self.total_invested = 0.0 # attribut pour suivre le montant total investi
        self.event_manager = event_manager  # Nouveau: gestionnaire d'événements

    def calculate_position_size(self) -> float:
        """
        Calcule la taille de position dynamiquement basée sur le capital disponible.
        Utilise un pourcentage du capital restant et applique une taille minimale.
        """
        # Capital disponible
        available_capital = self.capital
        
        # Calcul du montant basé sur le pourcentage configuré
        position_size = (available_capital * self.config.POSITION_SIZE / 100)
        
        # Appliquer une taille minimale si nécessaire
        position_size = max(position_size, self.config.MIN_POSITION_SIZE)
        
        # S'assurer que nous ne dépassons pas le capital disponible
        position_size = min(position_size, available_capital)
        
        return position_size

    def calculate_transaction_fees(self, amount: float) -> float:
        """Calcule les frais de transaction"""
        return amount * self.config.TRANSACTION_FEE

    def can_open_position(self, pair: str) -> bool:
        """
        Vérifie si une position peut être ouverte en tenant compte du cooldown
        et du capital disponible pour une taille minimale de position.
        """
        if pair in self.cooldown_pairs:
            current_time = time.time()
            if current_time - self.cooldown_pairs[pair] < self.config.PAIR_COOLDOWN:
                return False
            else:
                del self.cooldown_pairs[pair]

        # Vérifier si nous avons assez de capital pour une position minimale
        min_required = self.config.MIN_POSITION_SIZE
        
        # Seule vérification : capital suffisant pour la taille minimale
        return self.capital >= min_required

    def open_position(self, pair: str, price: float, position_type: str) -> tuple:
        """
        Ouvre une nouvelle position avec taille dynamique basée sur le capital disponible
        et émet un événement si un gestionnaire d'événements est configuré
        """
        if not self.can_open_position(pair):
            raise ValueError("Cannot open new position")

        # Calcul dynamique de la taille de position
        position_size = self.calculate_position_size()
        
        entry_fees = self.calculate_transaction_fees(position_size)
        self.capital -= entry_fees
        
        take_profit = price * (1 + (self.config.TAKE_PROFIT_RISKY if position_type == "Risquée" 
                                else self.config.TAKE_PROFIT_SAFE) / 100)
        stop_loss = price * (1 + (self.config.STOP_LOSS_RISKY if position_type == "Risquée" 
                                else self.config.STOP_LOSS_SAFE) / 100)
        
        # Structure avec la nouvelle taille de position dynamique
        self.active_positions[pair] = {
            'entry_price': price,
            'take_profit': take_profit,
            'stop_loss': stop_loss,
            'entry_fees': entry_fees,
            'position_size': position_size,  # Stockage de la taille effective utilisée
            'highest_price': price,
            'trailing_stop_active': False,
            'position_type': position_type
        }
        
        # Log détaillé des paramètres avec la taille de position
        activation_threshold = (self.config.TRAILING_STOP_ACTIVATION_RISKY 
                            if position_type == "Risquée" 
                            else self.config.TRAILING_STOP_ACTIVATION_SAFE)
        trailing_distance = (self.config.TRAILING_STOP_DISTANCE_RISKY 
                            if position_type == "Risquée" 
                            else self.config.TRAILING_STOP_DISTANCE_SAFE)
        
        self.logger.info(
            f"Position ouverte sur {pair} ({position_type}) - "
            f"Prix: {price}, Taille: {position_size:.2f} ({self.config.POSITION_SIZE:.1f}% du capital), "
            f"TP: {take_profit}, SL: {stop_loss}, "
            f"Trailing Stop: Activation à {activation_threshold}%, Distance {trailing_distance}%"
        )
        
        # Mise à jour du capital et du montant investi
        self.capital -= position_size
        self.total_invested += position_size
        
        # Nouveau: émettre un événement d'ouverture de position
        if self.event_manager:
            asyncio.create_task(self.event_manager.emit("open_position", {
                "pair": pair,
                "position_type": position_type,
                "entry_price": price,
                "position_size": position_size,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "order_type": "MARKET"
            }))
        self.logger.info(f"Événement d'ouverture de position émis pour {pair}")

        return price, take_profit, stop_loss, entry_fees, position_size  # Retourner la taille de position pour enregistrement

    def update_trailing_stop(self, pair: str, current_price: float) -> None:
        """Met à jour le trailing stop pour une position avec différenciation prudent/risqué"""
        if not self.config.USE_TRAILING_STOP or pair not in self.active_positions:
            return

        position = self.active_positions[pair]
        entry_price = position['entry_price']
        position_type = position['position_type']
        current_profit_pct = ((current_price - entry_price) / entry_price) * 100

        # Sélection des paramètres selon le type de position
        activation_threshold = (
            self.config.TRAILING_STOP_ACTIVATION_RISKY 
            if position_type == "Risquée" 
            else self.config.TRAILING_STOP_ACTIVATION_SAFE
        )
        trailing_distance = (
            self.config.TRAILING_STOP_DISTANCE_RISKY 
            if position_type == "Risquée" 
            else self.config.TRAILING_STOP_DISTANCE_SAFE
        )

        # Activation du trailing stop
        if not position['trailing_stop_active'] and current_profit_pct >= activation_threshold:
            position['trailing_stop_active'] = True
            position['highest_price'] = current_price
            new_stop_loss = current_price * (1 - trailing_distance / 100)
            if new_stop_loss > position['stop_loss']:
                position['stop_loss'] = new_stop_loss
                self.logger.info(
                    f"Trailing stop activé pour {pair} ({position_type}) à {new_stop_loss:.8f} "
                    f"(Activation: {activation_threshold}%, Distance: {trailing_distance}%)"
                )

        # Mise à jour du trailing stop
        elif position['trailing_stop_active'] and current_price > position['highest_price']:
            position['highest_price'] = current_price
            new_stop_loss = current_price * (1 - trailing_distance / 100)
            position['stop_loss'] = new_stop_loss
            self.logger.info(
                f"Trailing stop mis à jour pour {pair} ({position_type}) à {new_stop_loss:.8f} "
                f"(Distance: {trailing_distance}%)"
            )

    def close_position(self, pair: str, current_price: float) -> tuple:
        """
        Ferme une position existante en prenant en compte la taille spécifique de la position
        et émet un événement si un gestionnaire d'événements est configuré
        """
        if pair not in self.active_positions:
            raise ValueError(f"No active position for {pair}")
            
        position = self.active_positions[pair]
        entry_price = position['entry_price']
        entry_fees = position['entry_fees']
        position_size = position.get('position_size', self.config.MIN_POSITION_SIZE)  # Récupérer la taille réelle ou utiliser la valeur par défaut
        position_type = position.get('position_type', 'Prudente')

        # Calcul basé sur la taille réelle de la position
        position_value = position_size * (current_price / entry_price)
        exit_fees = self.calculate_transaction_fees(position_value)
        total_fees = entry_fees + exit_fees
        
        profit_loss = position_value - position_size
        
        # Détermination de la raison de fermeture (NOUVEAU)
        # Cette information sera utilisée par l'exécuteur d'ordres
        close_reason = "manual"  # Par défaut
        if current_price >= position.get('take_profit', 0):
            close_reason = "take_profit"
        elif position.get('trailing_stop_active', False) and current_price <= position.get('stop_loss', 0):
            close_reason = "trailing_stop"
        elif current_price <= position.get('stop_loss', 0):
            close_reason = "stop_loss"
        
        # NOUVEAU: Calcul approximatif de la quantité d'actif
        # Ceci est nécessaire pour passer l'ordre de vente via l'API
        approximate_quantity = position_size / entry_price
        
        # NOUVEAU: Émission d'un événement de fermeture de position
        if self.event_manager:
            asyncio.create_task(self.event_manager.emit("close_position", {
                "pair": pair,                       # Symbole de la paire
                "position_type": position_type,     # Type de position
                "entry_price": entry_price,         # Prix d'entrée original
                "exit_price": current_price,        # Prix de sortie
                "position_size": position_size,     # Taille de la position en USDT
                "profit_loss": profit_loss,         # Profit/perte estimé
                "close_reason": close_reason,       # Raison de la fermeture
                "quantity": approximate_quantity,   # Quantité approximative d'actif
                "order_type": "MARKET"              # Type d'ordre (par défaut Market)
            }))
            self.logger.info(f"Événement de fermeture de position émis pour {pair} - Raison: {close_reason}")

        # Mise à jour du capital et du total investi
        self.capital += position_value - exit_fees
        self.total_invested = max(0, self.total_invested - position_size)
        
        self.cooldown_pairs[pair] = time.time()
        del self.active_positions[pair]
        
        return profit_loss, total_fees, position_size  # Retourner la taille pour les logs

    def check_position_status(self, pair: str, current_price: float) -> Optional[str]:
        """Vérifie si une position doit être fermée, incluant le trailing stop"""
        if pair not in self.active_positions:
            return None
            
        position = self.active_positions[pair]
        
        # Met à jour le trailing stop avant de vérifier le status
        self.update_trailing_stop(pair, current_price)
        
        if current_price >= position['take_profit']:
            return "take_profit"
        elif current_price <= position['stop_loss']:
            return "trailing_stop" if position['trailing_stop_active'] else "stop_loss"
            
        return None

class CryptoTrader:
    """Main trading logic"""
    def __init__(self, config: TradingConfig, event_manager: Optional[EventManager] = None):
        self.config = config
        # Initialisation des loggers
        self.logger = get_trading_logger()
        self.error_logger = get_error_logger()
        self.event_manager = event_manager
        self.position_manager = PositionManager(config, event_manager)
        self.data_recorder = DataRecorder(config)
        self.price_manager = PriceManager(config)
        self.trend_confirmations: Dict[str, float] = {}
        self.is_running = True
        self.accepting_new_positions = True
        self.reconnect_delay = config.RECONNECT_DELAY
        self.max_reconnect_delay = config.MAX_RECONNECT_DELAY
        self.websocket_metrics = WebSocketMetrics()
        self.last_heartbeat_time = None
        # Attribut pour le suivi des intervalles
        self.last_ohlc_update: Dict[str, float] = {}
        # Attributs pour le warm-up
        self.is_warmed_up = not config.ENABLE_WARMUP  # Initialement False si le warm-up est activé
        self.warmup_start_time = None
        self.warmup_duration = config.ATR_PERIOD * config.INTERVAL * config.WARMUP_MULTIPLIER
        self.warmup_progress = 0.0  # Progression en pourcentage
        
    def check_warmup_status(self):
        """Vérifie si la période de warm-up est terminée et met à jour la progression"""
        if self.is_warmed_up:
            return True
            
        current_time = time.time()
        
        # Si le warm-up n'a pas encore démarré, on l'initialise
        if self.warmup_start_time is None:
            self.warmup_start_time = current_time
            self.logger.info(f"Démarrage de la période de warm-up ({self.warmup_duration:.0f} secondes)")
            return False
            
        # Calcul de la progression
        elapsed_time = current_time - self.warmup_start_time
        new_progress = min(100.0, (elapsed_time / self.warmup_duration) * 100)
        
        # Log uniquement si la progression a significativement changé (tous les 10%)
        if int(new_progress / 10) > int(self.warmup_progress / 10):
            self.logger.info(f"Warm-up en cours: {new_progress:.1f}% complété")
        
        self.warmup_progress = new_progress
        
        # Vérification si le warm-up est terminé
        if elapsed_time >= self.warmup_duration:
            self.is_warmed_up = True
            self.logger.info("Période de warm-up terminée. Début du trading actif.")
            return True
            
        return False

    def set_trading_status(self, accepting: bool) -> None:
        """
        Active ou désactive la prise de nouvelles positions.
        
        Args:
            accepting: True pour permettre les nouvelles positions, False pour les bloquer
        """
        # Modifier l'état seulement s'il change pour éviter des logs redondants
        if self.accepting_new_positions != accepting:
            self.accepting_new_positions = accepting
            status_str = "activée" if accepting else "désactivée"
            self.logger.info(f"Prise de nouvelles positions {status_str}")
                                                                                                                                                                                          
    async def heartbeat(self, websocket):
        """Maintient la connexion active avec des pings réguliers"""
        while True:
            try:
                await websocket.ping()
                self.last_heartbeat_time = time.time()
                await asyncio.sleep(self.config.WEBSOCKET_PING_INTERVAL / 2)
                
            except asyncio.CancelledError:
                self.logger.info("Heartbeat task annulée")
                break
            except ConnectionClosed:
                self.logger.warning("WebSocket fermé, arrêt du heartbeat")
                break
            except Exception as e:
                self.logger.error(f"Erreur heartbeat: {e}")
                break

    async def connect_websocket(self, pairs: List[str]):
        """Gère la connexion WebSocket avec reconnexion automatique et métriques"""
        current_delay = self.reconnect_delay
        
        while self.is_running:
            try:
                self.websocket_metrics.log_connection_attempt()
                uri = "wss://stream.binance.com:9443/ws"
                
                # Retiré max_queue_size des paramètres de connexion
                async with websockets.connect( # type: ignore
                    uri,
                    ping_interval=self.config.WEBSOCKET_PING_INTERVAL,
                    ping_timeout=self.config.WEBSOCKET_PING_TIMEOUT,
                    close_timeout=self.config.WEBSOCKET_CLOSE_TIMEOUT,
                    compression=None
                ) as websocket:
                    self.websocket_metrics.log_successful_connection()
                    self.logger.info("WebSocket connecté avec succès")
                    
                    # Démarrer le heartbeat
                    heartbeat_task = asyncio.create_task(self.heartbeat(websocket))
                    
                    # Réinitialiser le délai de reconnexion après succès
                    current_delay = self.reconnect_delay
                    
                    subscription = {
                        "method": "SUBSCRIBE",
                        "params": [f"{pair.lower()}@ticker" for pair in pairs],
                        "id": 1
                    }
                    await websocket.send(json.dumps(subscription))
                    self.logger.info(f"Souscription envoyée pour {len(pairs)} paires")
                    
                    while True:
                        try:
                            message = await websocket.recv()
                            if isinstance(message, bytes):
                                message = message.decode('utf-8')
                            await self.handle_websocket_message(message)
                        except ConnectionClosed as e:
                            self.websocket_metrics.log_disconnection(f"Connection fermée: {e.code} - {e.reason}")
                            self.logger.warning(f"Connexion WebSocket fermée (code: {e.code}, raison: {e.reason})")
                            break
                        except Exception as e:
                            self.websocket_metrics.log_disconnection(str(e))
                            self.logger.error(f"Erreur lors du traitement du message: {e}")
                            break
                    
                    # Annuler la tâche de heartbeat à la déconnexion
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                            
            except Exception as e:
                self.websocket_metrics.log_disconnection(str(e))
                self.logger.error(f"Erreur de connexion WebSocket: {e}")
                
                if self.is_running:
                    self.logger.info(f"Tentative de reconnexion dans {current_delay} secondes...")
                    await asyncio.sleep(current_delay)
                    current_delay = min(current_delay * 2, self.max_reconnect_delay)
                    
                    # Log des métriques toutes les 5 déconnexions
                    if self.websocket_metrics.disconnections % 5 == 0:
                        metrics = self.websocket_metrics.get_metrics_report()
                        self.logger.info(f"Métriques WebSocket: {json.dumps(metrics, indent=2)}")

    async def get_top_trading_pairs(self) -> List[str]:
        """
        Récupère les paires les plus tradées avec la monnaie de référence configurée
        
        Returns:
            Liste des symboles (ex: BTCUSDT, ETHUSDT si USDT est la référence)
        """
        retry_count = 0
        max_retries = 3
        
        # Récupérer la monnaie de référence depuis la configuration
        ref_currency = self.config.REFERENCE_CURRENCY
        
        self.logger.info(f"Recherche des meilleures paires en {ref_currency}...")
        
        while retry_count < max_retries:
            try:
                url = "https://api.binance.com/api/v3/ticker/24hr"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        data = await response.json()
                        
                # Filtrer les paires qui se terminent par la monnaie de référence (ex: BTCUSDT, ETHUSDT, etc.)
                sorted_pairs = sorted(data, key=lambda x: float(x['quoteVolume']), reverse=True)
                pairs = [item['symbol'] for item in sorted_pairs if item['symbol'].endswith(ref_currency)][:self.config.MAX_PAIRS]
                
                self.logger.info(f"Récupération réussie de {len(pairs)} paires {ref_currency}")
                return pairs
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Erreur lors de la récupération des paires (tentative {retry_count}): {e}")
                if retry_count < max_retries:
                    await asyncio.sleep(5)
        
        # Si toutes les tentatives ont échoué, on retourne une liste vide plutôt que None
        self.logger.critical(f"Impossible de récupérer les paires {ref_currency} après plusieurs tentatives. Utilisation d'une liste vide.")
        return []

    async def handle_websocket_message(self, message: str):
        """Traite les messages du WebSocket avec support OHLC"""
        data = json.loads(message)
        
        if 'result' in data and data['result'] is None:
            return
                
        if 's' in data and 'c' in data:
            pair = data['s']
            current_time = time.time()
            
             # Vérifier la présence du champ 'q' (volume)
            if 'q' not in data:
                self.logger.warning(f"Champ 'q' (volume) manquant dans le message WebSocket pour {pair}")
                self.logger.debug(f"Structure du message: {json.dumps(data)}")
                volume = 0.0  # Valeur par défaut si le champ est manquant
            else:
                volume = float(data['q']) #extraction du volume

            # Extraction du prix et du volume
            price = float(data['c'])
            
            # Mise à jour du prix
            self.price_manager.update_price(pair, price)

            # Mise à jour du volume (nouvelle méthode à créer)
            self.price_manager.update_volume(pair, volume)

            # Vérification de la mise à jour OHLC
            if pair not in self.last_ohlc_update:
                self.last_ohlc_update[pair] = current_time
            elif current_time - self.last_ohlc_update[pair] >= self.config.INTERVAL:
                # Mise à jour des données OHLC et ATR
                self.price_manager.update_ohlc(pair)
                self.price_manager.update_atr(pair)
                # Calcul explicite du ratio de volatilité après la mise à jour de l'ATR
                self.price_manager.calculate_volatility_ratio(pair)
                self.last_ohlc_update[pair] = current_time
                
                # Log des métriques de volatilité si changement significatif
                volatility_metrics = self.price_manager.get_volatility_metrics(pair)
                # if self._should_log_volatility(pair, volatility_metrics):
                #   logging.info(
                #        f"Volatilité {pair} - ATR: {volatility_metrics['atr']}, "
                #        f"Ratio: {volatility_metrics['volatility_ratio']}"
                #    )

            # Vérification des positions existantes
            await self.check_open_positions(pair)

    def _should_log_volatility(self, pair: str, metrics: Dict[str, float]) -> bool:
        """Détermine si les changements de volatilité doivent être loggés"""
        volatility_ratio = metrics['volatility_ratio']
        
        # Log si volatilité très haute ou très basse
        return (volatility_ratio >= self.config.ATR_HIGH_VOLATILITY or 
                volatility_ratio <= self.config.ATR_LOW_VOLATILITY)

    async def check_open_positions(self, pair: str):
        """Vérifie les positions ouvertes pour le TP/SL et trailing stop"""
        current_price = self.price_manager.get_current_price(pair)
        if not current_price:
            return

        # Vérifier d'abord si la paire existe toujours dans active_positions
        if pair not in self.position_manager.active_positions:
            return

        status = self.position_manager.check_position_status(pair, current_price)
        if status:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Stocker TOUTES les données de position AVANT de la fermer
            position_data = self.position_manager.active_positions[pair]
            entry_type = position_data['position_type']
            entry_price = position_data['entry_price']
            entry_fees = position_data['entry_fees']
            
            # Fermer la position (cela va supprimer la position de active_positions)
            profit_loss, total_fees, position_size = self.position_manager.close_position(pair, current_price)
            
            # Calcul des frais de sortie
            exit_fees = total_fees - entry_fees
            
            # Mappage du status de fermeture
            close_reason = {
                "take_profit": "Take_Profit",
                "stop_loss": "Stop_Loss",
                "trailing_stop": "Trailing_Stop"
            }.get(status, status)
            
            # Collection des données de variation et autres métriques
            variations, total_variation = self.price_manager.analyze_trend_slices(pair)
            variation_data = {'variations': variations, 'total_variation': total_variation}
            
            volatility_metrics = self.price_manager.get_volatility_metrics(pair)
            
            current_volume = int(self.price_manager.current_volumes.get(pair, 0))
            volume_change = 0.0
            
            if pair in self.price_manager.volume_history and len(self.price_manager.volume_history[pair]) >= 2:
                volumes_by_slice, volume_change = self.price_manager.analyze_volume_slices(pair)
            
            volume_metrics = {'current_volume': current_volume, 'volume_change': volume_change}
            
            # Calcul du capital total pour le pourcentage
            total_capital = self.position_manager.capital + position_size + total_fees
            
            # Récupération de la valeur RSI
            rsi_value = self.price_manager.get_rsi_value(pair)
            
            # Appel à record_position
            await self.data_recorder.record_position_exit(
                timestamp, 
                pair,
                close_reason,
                current_price,
                exit_fees,
                profit_loss,
                entry_fees,
                self.position_manager.capital
            )
                                    
            self.logger.info(
                f"Position fermée sur {pair} - Raison: {close_reason}, "
                f"Taille: {round(position_size, 2):.2f}, "
                f"P/L: {round(profit_loss, 2):.2f} ({round((profit_loss/position_size)*100, 2):.2f}%), "
                f"Frais: {round(total_fees, 2):.2f}, "
                f"Capital: {round(self.position_manager.capital, 2):.2f}, "
                f"RSI: {rsi_value:.2f}"            
            )

    async def analyze_trading_opportunities(self):
        """Analyse les opportunités de trading avec prise en compte de la volatilité et du warm-up"""
        while self.is_running:
            # Vérifier d'abord le statut du warm-up
            self.check_warmup_status()
            
            if self.price_manager.should_analyze():
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                for pair in list(self.price_manager.current_prices.keys()):
                    # Récupération des données de variation existantes
                    variations, total_variation = self.price_manager.analyze_trend_slices(pair)
                    detailed_variations = f"Tranches: {[round(v, 2) for v in variations]}%, Total: {round(total_variation, 2)}%"
                    
                    # Récupération des métriques de volatilité
                    self.price_manager.calculate_volatility_ratio(pair)
                    volatility_metrics = self.price_manager.get_volatility_metrics(pair)
                    
                    # Nouvelle section: Récupération des métriques de volume
                    volumes_by_slice, volume_change = self.price_manager.analyze_volume_slices(pair)
                    current_volume = self.price_manager.current_volumes.get(pair, 0)

                    volume_metrics = {
                        'current_volume': current_volume,
                        'volumes_by_slice': volumes_by_slice,
                        'volume_change': volume_change
                    }
                    # Récupération de la valeur RSI
                    rsi_value = self.price_manager.get_rsi_value(pair)

                    # Log de debug avec informations enrichies
                    self.logger.debug(
                        f"Analyse {pair} - {detailed_variations} - "
                        f"ATR: {volatility_metrics['atr']}, "
                        f"Ratio Volatilité: {volatility_metrics['volatility_ratio']}, "  
                        f"Volume: {current_volume:.2f}, Var: {volume_change:.2f}%"
                        f"RSI: {rsi_value:.2f}"
                    )
                    
                    initial_price, current_price = self.price_manager.get_analysis_data(pair)
                    if initial_price and current_price:
                        variation = ((current_price - initial_price) / initial_price) * 100
                        
                        # Enregistrement avec données ATR et volume
                        await self.data_recorder.record_price(
                            timestamp, 
                            pair, 
                            current_price, 
                            variation,
                            detailed_variations,
                            volatility_metrics,
                            volume_metrics,
                            rsi_value
                        )

                    # Vérification des opportunités de trading uniquement si le warm-up est terminé
                    # et si le système accepte de nouvelles positions
                    if self.is_warmed_up and self.accepting_new_positions and pair not in self.position_manager.active_positions:
                        if not self.position_manager.can_open_position(pair):
                            continue

                        # Vérification préliminaire des tendances
                        trend_confirmed_risky = self.price_manager.confirm_trend(pair, is_risky=True)
                        trend_confirmed_safe = self.price_manager.confirm_trend(pair, is_risky=False)
                        
                        # Si aucune tendance confirmée, passer à la paire suivante
                        if not (trend_confirmed_risky or trend_confirmed_safe):
                            continue
                        
                        # NOUVEAU: Vérification du ratio de volatilité si le filtre est activé
                        if self.config.USE_VOLATILITY_FILTER:
                            volatility_ratio = volatility_metrics['volatility_ratio']
                            if volatility_ratio < self.config.MIN_VOLATILITY_RATIO:
                                self.logger.info(
                                    f"Tendance confirmée sur {pair} mais volatilité insuffisante - "
                                    f"Ratio: {volatility_ratio:.2f} < {self.config.MIN_VOLATILITY_RATIO:.2f}"
                                )
                                continue
                        
                        # Déterminer le type de position (risquée a priorité sur prudente)
                        position_type = "Risquée" if trend_confirmed_risky else "Prudente"
                        
                        # Vérification du seuil de variation de volume
                        if volume_change < self.config.MIN_VOLUME_CHANGE_THRESHOLD:
                            self.logger.info(
                                f"Tendance confirmée sur {pair} ({position_type}) mais volume insuffisant - "
                                f"Variation volume: {volume_change:.2f}% < {self.config.MIN_VOLUME_CHANGE_THRESHOLD:.2f}%"
                            )
                            continue

                        try:
                            current_price = self.price_manager.get_current_price(pair)
                            
                            # Vérification que current_price n'est pas None avant d'ouvrir une position
                            if current_price is None:
                                self.logger.warning(f"Impossible d'ouvrir une position sur {pair}: prix actuel non disponible")
                                continue
                                
                            # Stocker le capital total avant l'ouverture pour calculer le pourcentage
                            total_capital_before = self.position_manager.capital
                            
                            # La méthode open_position pour ouvrir une position retourne aussi la taille de position
                            entry_price, take_profit, stop_loss, entry_fees, position_size = \
                                self.position_manager.open_position(pair, current_price, position_type)

                            # Collection des données de variation
                            variations, total_variation = self.price_manager.analyze_trend_slices(pair)
                            variation_data = {
                                'variations': variations,
                                'total_variation': total_variation
                            }

                            # Appel à la nouvelle version de record_position
                            await self.data_recorder.record_position_entry(
                                timestamp, 
                                pair, 
                                position_type,
                                entry_price,
                                position_size,
                                (position_size / total_capital_before) * 100,
                                entry_fees,
                                volatility_metrics,
                                volume_metrics,
                                variation_data,
                                rsi_value
                            )

                            # Log enrichi avec information sur la variation de volume et de volatilité
                            self.logger.info(
                                f"Position ouverte sur {pair} ({position_type}) avec "
                                f"variation de volume: {volume_change:.2f}% >= {self.config.MIN_VOLUME_CHANGE_THRESHOLD:.2f}%, "
                                f"ratio de volatilité: {volatility_metrics['volatility_ratio']:.2f}" + 
                                (f" ≥ {self.config.MIN_VOLATILITY_RATIO:.2f}" if self.config.USE_VOLATILITY_FILTER else "")
                            )

                        except Exception as e:
                            self.logger.error(f"Erreur lors de l'ouverture de position sur {pair}: {e}")

            await asyncio.sleep(1)

    async def start(self):
        """Démarre le bot de trading avec monitoring amélioré"""
        self.logger.info(f"Démarrage du bot de trading avec {self.config.REFERENCE_CURRENCY} comme monnaie de référence...")

        if self.config.ENABLE_WARMUP:
            warmup_duration_mins = self.warmup_duration / 60
            self.logger.info(f"Mode warm-up activé. Durée prévue: {warmup_duration_mins:.1f} minutes")
        else:
            self.logger.info("Mode warm-up désactivé. Trading actif dès le démarrage.")

        try:
            # Utiliser la nouvelle méthode pour récupérer les paires avec la monnaie de référence configurée
            pairs = await self.get_top_trading_pairs()
            
            # Démarrage des tâches en parallèle
            websocket_task = asyncio.create_task(self.connect_websocket(pairs))
            analysis_task = asyncio.create_task(self.analyze_trading_opportunities())
            
            # Attendre les tâches
            await asyncio.gather(websocket_task, analysis_task)
            
        except Exception as e:
            self.logger.error(f"Erreur critique: {e}")
            raise
        finally:
            if self.is_running:
                self.is_running = False
                # Log final des métriques
                metrics = self.websocket_metrics.get_metrics_report()
                self.logger.info(f"Métriques finales WebSocket: {json.dumps(metrics, indent=2)}")
                self.logger.info("Arrêt du bot de trading")
