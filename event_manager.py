import asyncio
from typing import Dict, Any, Callable, List, Coroutine, Optional
from logger_config import get_event_logger

class EventManager:
    """Gestionnaire d'événements pour la communication entre modules"""
    
    def __init__(self):
        # File d'attente pour stocker les événements à traiter
        self.event_queue = asyncio.Queue()
        
        # Dictionnaire d'abonnés: {type_événement: [callbacks]}
        self.subscribers = {}
        
        # Flag pour contrôler l'exécution de la boucle de traitement
        self.is_running = True
        
        # Configuration du logging spécifique au gestionnaire d'événements
        self.logger = get_event_logger()
    
    def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], Coroutine]):
        """
        S'abonner à un type d'événement spécifique
        
        Args:
            event_type: Type d'événement à surveiller (ex: "open_position")
            callback: Fonction de rappel asynchrone à appeler quand l'événement se produit
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        
        # Ajouter le callback à la liste des abonnés pour ce type d'événement
        self.subscribers[event_type].append(callback)
        self.logger.debug(f"Nouvel abonnement pour l'événement '{event_type}'")
    
    async def emit(self, event_type: str, data: Dict[str, Any]):
        """
        Émettre un événement pour traitement
        
        Args:
            event_type: Type d'événement émis
            data: Données associées à l'événement
        """
        # Ajouter le type d'événement aux données pour référence
        event_data = data.copy()
        event_data['event_type'] = event_type
        
        # Placer l'événement dans la file d'attente pour traitement
        await self.event_queue.put((event_type, event_data))
        self.logger.debug(f"Événement '{event_type}' émis et mis en file d'attente")
    
    async def process_events(self):
        """
        Boucle principale de traitement des événements
        Cette méthode traite en continu les événements de la file d'attente
        """
        self.logger.info("Démarrage du traitement des événements")
        
        while self.is_running:
            try:
                # Récupérer le prochain événement dans la file
                event_type, data = await self.event_queue.get()
                
                # Vérifier s'il y a des abonnés pour ce type d'événement
                if event_type in self.subscribers:
                    # Exécuter tous les callbacks enregistrés pour ce type d'événement
                    for callback in self.subscribers[event_type]:
                        try:
                            # Exécuter le callback de façon asynchrone sans bloquer
                            # la boucle de traitement des événements
                            asyncio.create_task(callback(data))
                        except Exception as e:
                            self.logger.error(f"Erreur lors de l'exécution du callback: {e}")
                
                # Marquer l'événement comme traité
                self.event_queue.task_done()
                
            except asyncio.CancelledError:
                # Interruption propre de la boucle
                self.logger.info("Traitement des événements interrompu")
                break
            except Exception as e:
                # Capture des autres erreurs pour éviter l'arrêt de la boucle
                self.logger.error(f"Erreur lors du traitement de l'événement: {e}")
    
    def stop(self):
        """Arrêter le gestionnaire d'événements"""
        self.logger.info("Arrêt du gestionnaire d'événements")
        self.is_running = False