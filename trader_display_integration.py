# trader_display_integration.py
import asyncio
import sys
from terminal_display import TerminalDisplay
from logger_config import get_trading_logger, VerbosityLevel, set_verbosity

async def integrate_display_with_trader(trader):
    """
    Intègre le système d'affichage au trader.
    
    Args:
        trader: Instance de CryptoTrader à laquelle connecter l'affichage
    """
    # Créer l'instance du gestionnaire d'affichage
    display = TerminalDisplay(
        position_manager=trader.position_manager,
        price_manager=trader.price_manager,
        config=trader.config
    )
    
    # Stocker la référence sur le trader pour y accéder depuis ailleurs
    trader.display = display
    
    # Afficher le message de bienvenue
    display.display_welcome_message()
    
    # S'abonner aux événements
    if trader.event_manager:
        import time
        # Définir des fonctions asynchrones de rappel pour gérer les événements
        # Note: nous utilisons des fonctions auxiliaires qui créent des tâches asynchrones
        # car le système d'événements s'attend à recevoir des coroutines
        
        async def position_opened_handler(data):
            """
            Handler asynchrone pour l'événement position_opened.
            Journalise les données brutes et enrichit les données si nécessaire.
            
            Args:
                data: Données de l'événement position_opened
            """
            # Journaliser les données brutes pour débogage
            logger = get_trading_logger()
            logger.debug(f"Données brutes de position ouverte reçues: {data}")
            
            # Enrichir les données si des champs importants sont manquants
            # Ces valeurs sont importantes pour l'affichage dans le tableau
            
            # S'assurer que entry_price est présent (utiliser 'price' s'il est fourni à la place)
            if 'entry_price' not in data and 'price' in data:
                data['entry_price'] = data['price']
            
            # S'assurer que position_size est présent
            if 'position_size' not in data and 'quantity' in data and 'entry_price' in data:
                # Estimation approximative
                data['position_size'] = data['quantity'] * data['entry_price']
            
            # Ajouter l'heure d'ouverture si non présente
            if 'open_time' not in data:
                data['open_time'] = time.time()
                
            await display.on_position_opened(data)
            
        async def position_closed_handler(data):
            """
            Handler asynchrone pour l'événement position_closed.
            Journalise les données brutes et enrichit les données si nécessaire.
            
            Args:
                data: Données de l'événement position_closed
            """
            # Journaliser les données brutes pour débogage
            logger = get_trading_logger()
            logger.debug(f"Données brutes de position fermée reçues: {data}")
            
            # Enrichir les données si nécessaire pour l'affichage dans le tableau
            
            # Récupérer la position active pour obtenir les données manquantes
            pair = data.get('pair')
            position_data = {}
            
            # Tenter de récupérer les données de la position active si disponible
            if pair and hasattr(display, 'position_manager') and pair in display.position_manager.active_positions:
                position_data = display.position_manager.active_positions[pair]
                
                # Enrichir les données avec les informations de position
                if 'entry_price' not in data and 'entry_price' in position_data:
                    data['entry_price'] = position_data['entry_price']
                    
                if 'position_type' not in data and 'position_type' in position_data:
                    data['position_type'] = position_data['position_type']
                    
                if 'position_size' not in data and 'position_size' in position_data:
                    data['position_size'] = position_data['position_size']
            
            # S'assurer que exit_price est présent
            if 'exit_price' not in data:
                if hasattr(display, 'price_manager'):
                    data['exit_price'] = display.price_manager.get_current_price(pair) or 0.0
                else:
                    data['exit_price'] = 0.0
            
            # Calculer le profit/perte si non fourni
            if 'profit_loss' not in data and 'entry_price' in data and 'exit_price' in data:
                entry_price = data['entry_price']
                exit_price = data['exit_price']
                position_size = data.get('position_size', 0.0)
                
                if entry_price > 0:
                    data['profit_loss'] = position_size * ((exit_price / entry_price) - 1)
            
            # Ajouter l'heure de fermeture si non présente
            if 'close_time' not in data:
                data['close_time'] = time.time()
            
            await display.on_position_closed(data)
        
        # S'abonner aux événements avec les handlers asynchrones
        trader.event_manager.subscribe("position_opened", position_opened_handler)
        trader.event_manager.subscribe("position_closed", position_closed_handler)
    
    # Démarrer la tâche périodique pour les résumés
    summary_task = asyncio.create_task(display.start_auto_summary_task(interval_seconds=3600))  # 1 heure
    
    # Démarrer une tâche pour lire les commandes utilisateur
    command_task = asyncio.create_task(read_user_commands(display))
    
    # Retourner les tâches pour les intégrer dans la boucle principale
    return summary_task, command_task

async def read_user_commands(display):
    """
    Lit les commandes de l'utilisateur depuis la console en arrière-plan.
    
    Cette version utilise run_in_executor pour lire l'entrée de manière non bloquante
    sans avoir besoin de threads séparés, évitant ainsi les problèmes de synchronisation.
    
    Args:
        display: Instance de TerminalDisplay pour traiter les commandes
    """
    logger = get_trading_logger()
    logger.info("Appuyez sur Entrée pour afficher l'aide, ou tapez une commande.")
    
    # Obtenir la boucle d'événements courante
    loop = asyncio.get_running_loop()
    
    while True:
        try:
            # Lecture non-bloquante de l'entrée utilisateur via un executor
            # Cela permet de lire l'entrée sans bloquer la boucle d'événements asyncio
            command = await loop.run_in_executor(None, input)
            
            # Traiter la commande
            if not command.strip():  # Si l'utilisateur a juste appuyé sur Entrée
                display.process_command("help")
            else:
                continue_running = display.process_command(command)
                if not continue_running:
                    # L'utilisateur a demandé de quitter
                    logger.info("Commande d'arrêt reçue...")
                    return
                
        except asyncio.CancelledError:
            # Capture l'annulation de la tâche pour permettre un arrêt propre
            logger.info("Lecture des commandes interrompue")
            break
        except Exception as e:
            # Gestion des autres erreurs
            logger.error(f"Erreur lors du traitement des commandes: {e}")
            # Continuer malgré l'erreur pour maintenir l'interactivité
            await asyncio.sleep(1)  # Petit délai pour éviter une consommation CPU excessive en cas d'erreur répétée

def modify_trader_start_method(trader_class):
    """
    Modifie la méthode start de la classe CryptoTrader pour intégrer l'affichage.
    Cette fonction doit être appelée avant d'instancier CryptoTrader.
    
    Args:
        trader_class: La classe CryptoTrader à modifier
    """
    # Sauvegarder l'ancienne méthode start
    original_start = trader_class.start
    
    # Définir la nouvelle méthode start
    async def new_start(self):
        """Version modifiée de la méthode start qui intègre l'affichage"""
        # Intégrer l'affichage
        display_tasks = await integrate_display_with_trader(self)
        
        try:
            # Exécuter la méthode start originale
            await original_start(self)
        finally:
            # Annuler les tâches d'affichage si elles sont toujours en cours
            for task in display_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
    
    # Remplacer la méthode start par la nouvelle version
    trader_class.start = new_start

def init_display_system():
    """
    Initialise le système d'affichage et modifie la classe CryptoTrader.
    Doit être appelée avant d'instancier CryptoTrader.
    """
    # Importer la classe CryptoTrader
    from topgainers23 import CryptoTrader
    
    # Modifier la méthode start
    modify_trader_start_method(CryptoTrader)
    
    # Définir le niveau de verbosité initial
    set_verbosity(VerbosityLevel.NORMAL)
    
    return CryptoTrader
