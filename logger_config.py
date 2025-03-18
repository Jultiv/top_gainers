# logger_config.py
import logging
import os
from datetime import datetime
import sys
from logging.handlers import RotatingFileHandler

# Configuration des dossiers de logs
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Création de sous-dossiers par date
current_date = datetime.now().strftime("%Y-%m-%d")
DAILY_LOG_DIR = os.path.join(LOG_DIR, current_date)
if not os.path.exists(DAILY_LOG_DIR):
    os.makedirs(DAILY_LOG_DIR)

# Définition des formats de logs
CONSOLE_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
FILE_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s'

# Niveaux de logs pour les différents composants
DEFAULT_LEVEL = logging.INFO
TRADING_ENGINE_LEVEL = logging.INFO
API_LEVEL = logging.INFO
EVENT_LEVEL = logging.INFO

def setup_logger(name, log_file=None, level=DEFAULT_LEVEL):
    """
    Configure un logger avec un nom spécifique
    
    Args:
        name: Nom du logger à configurer
        log_file: Nom du fichier de log (optionnel)
        level: Niveau de log (DEBUG, INFO, etc.)
    
    Returns:
        Logger configuré
    """
    # Nettoyer d'abord le logger existant pour éviter la duplication
    cleanup_logger(name)
    
    # Récupérer ou créer un logger avec ce nom
    logger = logging.getLogger(name)
    
    # Configurer le logger
    logger.setLevel(level)
    logger.propagate = False  # Empêcher la propagation aux loggers parents
    
    # Formateur pour les fichiers de logs
    file_formatter = logging.Formatter(FILE_FORMAT)
    
    # Formateur pour la console (plus concis)
    console_formatter = logging.Formatter(CONSOLE_FORMAT)
    
    # Handler pour la console - UN SEUL handler par logger
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Handler pour fichier si spécifié - UN SEUL handler de fichier par logger
    if log_file:
        file_path = os.path.join(DAILY_LOG_DIR, log_file)
        # Utilisation de RotatingFileHandler pour limiter la taille des fichiers
        file_handler = RotatingFileHandler(
            file_path, 
            maxBytes=10*1024*1024,  # 10 MB max
            backupCount=5
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger

def get_trading_logger():
    return setup_logger('trading', 'trading.log', TRADING_ENGINE_LEVEL)

def get_api_logger():
    return setup_logger('api', 'api.log', API_LEVEL)

def get_event_logger():
    return setup_logger('event', 'events.log', EVENT_LEVEL)

def get_order_logger():
    return setup_logger('orders', 'orders.log', DEFAULT_LEVEL)

def get_error_logger():
    logger = logging.getLogger('error')
    logger.setLevel(logging.ERROR)
    
    # Formateur pour les erreurs (plus détaillé)
    formatter = logging.Formatter('%(asctime)s - ERROR - %(name)s - %(filename)s:%(lineno)d - %(message)s')
    
    # Fichier d'erreurs dédié
    error_file = os.path.join(DAILY_LOG_DIR, 'errors.log')
    file_handler = RotatingFileHandler(error_file, maxBytes=5*1024*1024, backupCount=10)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

def cleanup_logger(name):
    """
    Nettoie tous les handlers d'un logger spécifique
    
    Args:
        name: Nom du logger à nettoyer (chaîne vide pour le logger root)
    
    Cette fonction:
    1. Récupère le logger par son nom
    2. Ferme proprement chaque handler (libère les ressources comme les fichiers ouverts)
    3. Supprime le handler du logger
    """
    logger = logging.getLogger(name)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    return logger

def cleanup_all_loggers():
    """
    Nettoie tous les handlers de tous les loggers connus dans l'application
    
    Cette fonction:
    1. Nettoie d'abord le logger root (base de la hiérarchie)
    2. Nettoie ensuite tous les loggers spécifiques créés par notre application
    3. Parcourt enfin le dictionnaire des loggers pour s'assurer qu'aucun n'est oublié
    
    À utiliser au démarrage de l'application ou avant une reconfiguration complète
    """
    # Nettoyer le logger root
    cleanup_logger('')
    
    # Nettoyer les loggers spécifiques de notre application
    for logger_name in ['trading', 'api', 'event', 'orders', 'error', 'main']:
        cleanup_logger(logger_name)
    
    # Vérifier s'il reste des loggers non nettoyés (bibliothèques tierces, etc.)
    for logger_name in logging.root.manager.loggerDict:
        if logger_name not in ['trading', 'api', 'event', 'orders', 'error', 'main']:
            cleanup_logger(logger_name)
    
    print("Tous les loggers ont été nettoyés.")