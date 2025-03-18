import asyncio
import os
import logging
from typing import Optional
from event_manager import EventManager
from order_executor import OrderExecutor
from topgainers23 import CryptoTrader, TradingConfig
from dotenv import load_dotenv
from logger_config import setup_logger, cleanup_all_loggers
import argparse  # Pour le traitement des arguments en ligne de commande


load_dotenv()  # Charger les variables d'environnement depuis .env

# Nettoyer tous les loggers au démarrage pour éviter les duplications
cleanup_all_loggers()

# Configurer le logger principal après le nettoyage
logger = setup_logger('main')

def parse_arguments():
    """
    Parse les arguments en ligne de commande pour configurer le bot
    
    Returns:
        Namespace contenant les arguments analysés
    """
    parser = argparse.ArgumentParser(description="Bot de trading de crypto-monnaies")
    
    # Argument pour le mode d'exécution
    parser.add_argument(
        "--execution-mode", 
        type=int, 
        choices=[0, 1, 2], 
        default=0,
        help=("Mode d'exécution des ordres: "
              "0=Tests sur testnet (validation seulement), "
              "1=Ordres réels sur testnet (fonds virtuels), "
              "2=Ordres réels sur mainnet (ATTENTION: fonds réels!)")
    )
    
    return parser.parse_args()

async def main():
    """Point d'entrée de l'application avec architecture événementielle"""
    # Parser les arguments en ligne de commande
    args = parse_arguments()
    
    # Configuration depuis les variables d'environnement
    api_key = os.environ.get('BINANCE_API_KEY', '')
    api_secret = os.environ.get('BINANCE_API_SECRET', '')
    
    # Créer la configuration avec le mode d'exécution spécifié
    config = TradingConfig()
    config.ORDER_EXECUTION_MODE = args.execution_mode
    
    # Log le mode d'exécution sélectionné
    execution_modes = {
        0: "Ordres de test sur testnet (validation uniquement)",
        1: "Ordres réels sur testnet (avec fonds virtuels)",
        2: "ATTENTION: Ordres réels sur mainnet (fonds réels)"
    }
    logger.info(f"Mode d'exécution sélectionné: {execution_modes.get(args.execution_mode)}")
    
    # Vérification de sécurité pour le mode production
    if args.execution_mode == 2:
        logger.warning("!!! ATTENTION !!! Vous avez activé le mode d'exécution réel sur mainnet.")
        logger.warning("Ce mode utilise de vrais fonds et exécute de vrais ordres sur Binance.")
        logger.warning("Appuyez sur Ctrl+C maintenant pour annuler si ce n'est pas intentionnel.")
        # Attente de 5 secondes pour permettre l'annulation
        await asyncio.sleep(5)
        logger.warning("Mode d'exécution réel confirmé. Démarrage du système...")
    
    logger.info("Démarrage du système de trading...")
    
    # Initialisation du gestionnaire d'événements
    event_manager = EventManager()
    event_processor_task = asyncio.create_task(event_manager.process_events())
    
    # Initialisation de l'exécuteur d'ordres avec la configuration
    order_executor = OrderExecutor(event_manager, api_key, api_secret, config)
    if not await order_executor.initialize():
        logger.error("Échec de l'initialisation de l'exécuteur d'ordres.")
        event_processor_task.cancel()
        return
    
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