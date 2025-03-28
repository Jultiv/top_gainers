# main_enhanced.py
import asyncio
import os
import logging
from typing import Optional
from event_manager import EventManager
from order_executor import OrderExecutor
from dotenv import load_dotenv
from logger_config import setup_logger, cleanup_all_loggers, set_verbosity, VerbosityLevel
from trader_display_integration import init_display_system
import argparse  # Pour le traitement des arguments en ligne de commande

# Charger les variables d'environnement depuis .env
load_dotenv()

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
    
    # Argument pour la monnaie de référence
    parser.add_argument(
        "--reference-currency",
        type=str,
        default="USDC",
        help="Monnaie de référence à utiliser pour le trading (ex: USDT, USDC, BUSD)"
    )
    
    # Argument pour le niveau de verbosité
    parser.add_argument(
        "--verbosity",
        type=str,
        choices=["minimal", "normal", "detailed", "debug"],
        default="normal",
        help="Niveau de verbosité des logs dans le terminal"
    )

    return parser.parse_args()

async def main():
    """Point d'entrée de l'application avec architecture événementielle et affichage amélioré"""
    # Parser les arguments en ligne de commande
    args = parse_arguments()
    
    # Configuration depuis les variables d'environnement
    api_key = os.environ.get('BINANCE_API_KEY', '')
    api_secret = os.environ.get('BINANCE_API_SECRET', '')
    
    # Initialisation du système d'affichage amélioré
    # Cette fonction modifie la classe CryptoTrader pour intégrer l'affichage
    CryptoTrader = init_display_system()
    
    # Configurer le niveau de verbosité
    set_verbosity(args.verbosity)
    
    # Créer la configuration avec le mode d'exécution spécifié
    # Importer la classe après l'initialisation du système d'affichage
    from topgainers23 import TradingConfig
    
    config = TradingConfig()
    config.ORDER_EXECUTION_MODE = args.execution_mode
    config.REFERENCE_CURRENCY = args.reference_currency  # Définir la monnaie de référence
    
    # Log le mode d'exécution sélectionné et la monnaie de référence
    execution_modes = {
        0: "Ordres de test sur testnet (validation uniquement)",
        1: "Ordres réels sur testnet (avec fonds virtuels)",
        2: "ATTENTION: Ordres réels sur mainnet (fonds réels)"
    }
    logger.info(f"Mode d'exécution sélectionné: {execution_modes.get(args.execution_mode)}")
    logger.info(f"Monnaie de référence sélectionnée: {config.REFERENCE_CURRENCY}")
    logger.info(f"Niveau de verbosité: {args.verbosity}")
    
    # Stockage de la monnaie de référence dans une variable d'environnement pour les autres modules
    os.environ['REFERENCE_CURRENCY'] = config.REFERENCE_CURRENCY
    
    # Vérification de sécurité pour le mode production
    if args.execution_mode == 2:
        logger.warning("!!! ATTENTION !!! Vous avez activé le mode d'exécution réel sur mainnet.")
        logger.warning(f"Ce mode utilise de vrais fonds et exécute de vrais ordres sur Binance avec {config.REFERENCE_CURRENCY}.")
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
        # Démarrer le trader (la méthode start a été modifiée pour intégrer l'affichage)
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