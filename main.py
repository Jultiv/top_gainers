import asyncio
import os
import logging
from typing import Optional
from event_manager import EventManager
from order_executor import OrderExecutor
from topgainers23 import CryptoTrader, TradingConfig
from dotenv import load_dotenv
from logger_config import setup_logger, cleanup_all_loggers

load_dotenv()  # Charger les variables d'environnement depuis .env

# Nettoyer tous les loggers au démarrage pour éviter les duplications
cleanup_all_loggers()

# Configurer le logger principal après le nettoyage
logger = setup_logger('main')

async def main():
    """Point d'entrée de l'application avec architecture événementielle"""
    # Configuration depuis les variables d'environnement ou arguments
    api_key = os.environ.get('BINANCE_API_KEY', '')
    api_secret = os.environ.get('BINANCE_API_SECRET', '')
    test_mode = os.environ.get('BINANCE_TEST_MODE', 'True').lower() == 'true'
    
    logger.info("Démarrage du système de trading...")
    
    # Initialisation du gestionnaire d'événements
    event_manager = EventManager()
    event_processor_task = asyncio.create_task(event_manager.process_events())
    
    # Initialisation de l'exécuteur d'ordres
    order_executor = OrderExecutor(event_manager, api_key, api_secret, test_mode)
    if not await order_executor.initialize():
        logger.error("Échec de l'initialisation de l'exécuteur d'ordres.")
        event_processor_task.cancel()
        return
    
    # Utilisation de la configuration existante
    config = TradingConfig()
    
    # Créer une instance du trader avec le gestionnaire d'événements
    trader = CryptoTrader(config, event_manager)
    
    try:
        # Démarrer le trader
        await trader.start()
    except KeyboardInterrupt:
        logger.info("Arrêt manuel du bot...")
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
    finally:
        # Arrêt propre
        trader.is_running = False
        event_manager.stop()
        await order_executor.stop()
        
        # Annulation de la tâche de traitement des événements
        event_processor_task.cancel()
        try:
            await event_processor_task
        except asyncio.CancelledError:
            pass
        
        logger.info("Système de trading arrêté proprement")

if __name__ == "__main__":
    try:
        import platform
        if platform.system() == 'Windows':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # L'arrêt est géré dans la fonction main