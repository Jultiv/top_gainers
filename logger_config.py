# logger_config.py - Version améliorée
import logging
import os
import sys
from datetime import datetime
import time
from logging.handlers import RotatingFileHandler
from enum import Enum, auto

# Configuration des dossiers de logs
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Création de sous-dossiers par date
current_date = datetime.now().strftime("%Y-%m-%d")
DAILY_LOG_DIR = os.path.join(LOG_DIR, current_date)
if not os.path.exists(DAILY_LOG_DIR):
    os.makedirs(DAILY_LOG_DIR)

# ===== NOUVELLE PARTIE: CONFIGURATION DES COULEURS ET FORMATAGE TERMINAL =====

# Codes ANSI pour les couleurs et le formatage
class Colors:
    """Codes ANSI pour les couleurs et le formatage"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    
    # Couleurs de base
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Couleurs de fond
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"
    
    # Couleurs vives
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

# Classe pour définir les niveaux de verbosité
class VerbosityLevel(Enum):
    MINIMAL = auto()     # Seulement les erreurs et les événements critiques
    NORMAL = auto()      # Événements importants (positions ouvertes/fermées, démarrage/arrêt du système)
    DETAILED = auto()    # Informations détaillées sur les trades et analyses
    DEBUG = auto()       # Tous les détails techniques

# Configuration par défaut des niveaux de verbosité
CURRENT_VERBOSITY = VerbosityLevel.NORMAL

# ===== FORMATAGE ET FILTRES PERSONNALISÉS =====

class ColoredFormatter(logging.Formatter):
    """Formatter personnalisé pour ajouter des couleurs selon le niveau du message"""
    
    level_colors = {
        logging.DEBUG: Colors.BLUE,
        logging.INFO: Colors.RESET,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.RED,
        logging.CRITICAL: Colors.BG_RED + Colors.WHITE + Colors.BOLD,
    }
    
    def format(self, record):
        # Format de base
        log_message = super().format(record)
        
        # Ajouter des couleurs selon le niveau
        level_color = self.level_colors.get(record.levelno, Colors.RESET)
        
        # Ajouter des couleurs spécifiques basées sur le contenu du message
        if "Position ouverte" in record.getMessage():
            return f"{Colors.BRIGHT_GREEN}{Colors.BOLD}OUVERTURE →{Colors.RESET} {log_message}"
        elif "Position fermée" in record.getMessage():
            # Détecter si c'est un profit ou une perte
            if "P/L: " in record.getMessage():
                try:
                    msg = record.getMessage()
                    profit_index = msg.find("P/L: ") + 5
                    comma_index = msg.find(",", profit_index)
                    profit_str = msg[profit_index:comma_index if comma_index > 0 else None]
                    profit = float(profit_str)
                    if profit > 0:
                        return f"{Colors.BRIGHT_GREEN}{Colors.BOLD}FERMETURE ↑{Colors.RESET} {log_message}"
                    else:
                        return f"{Colors.BRIGHT_RED}{Colors.BOLD}FERMETURE ↓{Colors.RESET} {log_message}"
                except:
                    # En cas d'échec du parsing, utiliser la couleur par défaut
                    return f"{Colors.BRIGHT_YELLOW}{Colors.BOLD}FERMETURE ↓{Colors.RESET} {log_message}"
            else:
                return f"{Colors.BRIGHT_YELLOW}{Colors.BOLD}FERMETURE ↓{Colors.RESET} {log_message}"
        # Coloration des événements de système importants
        elif any(keyword in record.getMessage() for keyword in ["Démarrage", "Arrêt", "Initialisation"]):
            return f"{Colors.BRIGHT_CYAN}{Colors.BOLD}SYSTÈME{Colors.RESET} {log_message}"
        elif "Erreur" in record.getMessage() or "erreur" in record.getMessage():
            return f"{Colors.BRIGHT_RED}{log_message}{Colors.RESET}"
        else:
            return f"{level_color}{log_message}{Colors.RESET}"

# Classe de filtre avancée qui combine plusieurs critères
class AdvancedFilter(logging.Filter):
    """
    Filtre avancé pour le logging qui contrôle ce qui est affiché 
    en fonction du niveau de verbosité et d'autres critères
    """
    
    def __init__(self, verbosity_level=VerbosityLevel.NORMAL, target="console"):
        super().__init__()
        self.verbosity_level = verbosity_level
        self.target = target  # 'console' ou 'file'
        self.last_summary_time = time.time()
        self.summary_interval = 3600  # 1 heure entre les résumés par défaut
    
    def filter(self, record):
        # Pour les fichiers de log, tout est enregistré
        if self.target == "file":
            return True
        
        # Pour la console, filtrer selon le niveau de verbosité
        message = record.getMessage()
        
        # NIVEAU MINIMAL: Erreurs, ouverture/fermeture de positions, démarrage/arrêt
        if self.verbosity_level == VerbosityLevel.MINIMAL:
            if record.levelno >= logging.WARNING:
                return True
            if any(keyword in message for keyword in [
                "Position ouverte", "Position fermée", 
                "Démarrage", "Arrêt du", "Erreur", "erreur"
            ]):
                return True
            return False
        
        # NIVEAU NORMAL: Événements importants + résumés
        elif self.verbosity_level == VerbosityLevel.NORMAL:
            # Filtrer les messages très verbeux
            if any(keyword in message for keyword in [
                "WebSocket", "Analyse", "Debug", "OHLC", 
                '{"e":"24hrTicker"', "TEXT", "bytes",
                "Tendance confirmée", "Règles de trading"
            ]) and record.levelno < logging.WARNING:
                return False
                
            # Filtrer les messages de debug sauf événements importants
            if record.levelno == logging.DEBUG and not any(keyword in message for keyword in [
                "Position", "Capital", "Démarrage", "Arrêt", "Ordre", "ordre"
            ]):
                return False
            
            return True
        
        # NIVEAU DÉTAILLÉ: Presque tout sauf les messages trop techniques
        elif self.verbosity_level == VerbosityLevel.DETAILED:
            if any(keyword in message for keyword in [
                '{"e":"24hrTicker"', "TEXT", "bytes"
            ]):
                return False
            return True
        
        # NIVEAU DEBUG: Tout afficher
        elif self.verbosity_level == VerbosityLevel.DEBUG:
            return True
        
        return True

# Fonction pour définir le niveau de verbosité global
def set_verbosity(level):
    """
    Change le niveau de verbosité global
    
    Args:
        level: Un élément de l'enum VerbosityLevel ou une chaîne parmi
               'minimal', 'normal', 'detailed', 'debug'
    """
    global CURRENT_VERBOSITY
    
    if isinstance(level, str):
        level = level.lower()
        if level == 'minimal':
            CURRENT_VERBOSITY = VerbosityLevel.MINIMAL
        elif level == 'normal':
            CURRENT_VERBOSITY = VerbosityLevel.NORMAL
        elif level == 'detailed':
            CURRENT_VERBOSITY = VerbosityLevel.DETAILED
        elif level == 'debug':
            CURRENT_VERBOSITY = VerbosityLevel.DEBUG
    else:
        CURRENT_VERBOSITY = level
    
    # Mettre à jour tous les filtres pour les handlers de console
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if hasattr(handler, 'stream') and handler.stream == sys.stdout:
            for filter_obj in handler.filters:
                if isinstance(filter_obj, AdvancedFilter):
                    filter_obj.verbosity_level = CURRENT_VERBOSITY

# ===== FORMAT DES MESSAGES =====

# Définition des formats de logs
CONSOLE_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
FILE_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s'

# Niveaux de logs pour les différents composants
DEFAULT_LEVEL = logging.INFO
TRADING_ENGINE_LEVEL = logging.INFO
API_LEVEL = logging.INFO
EVENT_LEVEL = logging.INFO

# ===== FONCTIONS DE CONFIGURATION DES LOGGERS =====

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
    
    # Formateur pour les fichiers de logs (standard)
    file_formatter = logging.Formatter(FILE_FORMAT)
    
    # Formateur pour la console (avec couleurs)
    console_formatter = ColoredFormatter(CONSOLE_FORMAT)
    
    # Handler pour la console - UN SEUL handler par logger
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(AdvancedFilter(CURRENT_VERBOSITY, "console"))
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
        file_handler.addFilter(AdvancedFilter(VerbosityLevel.DEBUG, "file"))
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

# ===== NOUVELLES FONCTIONS POUR LES RÉSUMÉS ET L'AFFICHAGE AMÉLIORÉ =====

def log_separator(logger, title=None, char='='):
    """Affiche un séparateur visuel dans les logs pour marquer les sections importantes"""
    width = 80
    if title:
        padding = (width - len(title) - 2) // 2
        separator = char * padding + ' ' + title + ' ' + char * padding
        # Ajuster si la longueur est impaire
        if len(separator) < width:
            separator += char
    else:
        separator = char * width
    
    logger.info(separator)

def log_summary(logger, data, title="Résumé des opérations"):
    """
    Affiche un résumé formaté des opérations
    
    Args:
        logger: Logger à utiliser
        data: Dictionnaire contenant les données du résumé
        title: Titre du résumé
    """
    log_separator(logger, title)
    
    for key, value in data.items():
        # Formatage selon le type de donnée
        if isinstance(value, float):
            logger.info(f"  {key}: {value:.2f}")
        else:
            logger.info(f"  {key}: {value}")
    
    log_separator(logger)

# Exemple d'utilisation du résumé:
# log_summary(logger, {
#     "Positions ouvertes": 3,
#     "Capital total": 1254.32,
#     "Profit total": 87.65,
#     "Rendement": 7.52,
#     "Durée moyenne des positions": "2h35m"
# })

# ===== CLASSE POUR LA CRÉATION DE TABLEAUX DANS LE TERMINAL =====

class ConsoleTable:
    """Classe pour créer des tableaux formatés dans le terminal"""
    
    def __init__(self, headers, widths=None):
        """
        Initialise un tableau pour l'affichage console
        
        Args:
            headers: Liste des en-têtes de colonnes
            widths: Liste des largeurs de colonnes (optionnel)
        """
        self.headers = headers
        self.rows = []
        
        # Définir les largeurs par défaut si non spécifiées
        if widths is None:
            self.widths = [max(15, len(h) + 2) for h in headers]
        else:
            self.widths = widths
    
    def add_row(self, row_data):
        """Ajoute une ligne au tableau"""
        # S'assurer que la ligne a le bon nombre de colonnes
        if len(row_data) != len(self.headers):
            row_data = row_data[:len(self.headers)]
            while len(row_data) < len(self.headers):
                row_data.append("")
        
        self.rows.append(row_data)
    
    def render(self):
        """Renvoie une représentation sous forme de chaîne du tableau"""
        result = []
        
        # Créer la ligne de séparation
        separator = "+"
        for width in self.widths:
            separator += "-" * width + "+"
        
        # Ajouter l'en-tête
        result.append(separator)
        header_row = "|"
        for i, header in enumerate(self.headers):
            header_row += header.center(self.widths[i]) + "|"
        result.append(header_row)
        result.append(separator)
        
        # Ajouter les données
        for row in self.rows:
            data_row = "|"
            for i, cell in enumerate(row):
                # Formater selon le type
                if isinstance(cell, float):
                    cell_str = f"{cell:.2f}"
                else:
                    cell_str = str(cell)
                
                data_row += cell_str.ljust(self.widths[i]) + "|"
            result.append(data_row)
        
        # Ajouter la ligne de séparation finale
        result.append(separator)
        
        return "\n".join(result)
    
    def log_table(self, logger):
        """Affiche le tableau via le logger spécifié"""
        table_str = self.render()
        for line in table_str.split("\n"):
            logger.info(line)

# Exemple d'utilisation du tableau:
# positions_table = ConsoleTable(["Paire", "Type", "Prix", "P/L", "Durée"], [10, 10, 12, 10, 10])
# positions_table.add_row(["BTCUSDT", "Prudente", 27500.45, 32.5, "1h25m"])
# positions_table.add_row(["ETHUSDT", "Risquée", 1820.75, -12.3, "35m"])
# positions_table.log_table(logger)