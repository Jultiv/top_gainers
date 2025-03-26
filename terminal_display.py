# terminal_display.py
import time
import asyncio
from typing import Optional
from datetime import datetime, timedelta
from logger_config import get_trading_logger, ConsoleTable, log_separator, log_summary, set_verbosity, VerbosityLevel, Colors

# Ajoutez cette fonction d'aide dans terminal_display.py
# juste avant la classe TerminalDisplay ou à l'intérieur comme méthode statique

def get_price_precision(price):
    """
    Détermine la précision appropriée pour l'affichage d'un prix en fonction de sa valeur.
    
    Args:
        price (float): Prix à évaluer
        
    Returns:
        int: Nombre de décimales à utiliser pour l'affichage
    """
    if price is None or price == 0:
        return 2  # Valeur par défaut
    
    # Ajuster la précision en fonction de la valeur
    if price < 0.0001:
        return 10  # Très petites valeurs (ex: certains tokens)
    elif price < 0.01:
        return 8   # Petites valeurs (ex: XRP, ADA...)
    elif price < 1.0:
        return 6   # Valeurs moyennes-basses
    elif price < 100:
        return 4   # Valeurs moyennes
    elif price < 1000:
        return 2   # Valeurs élevées (ex: ETH)
    else:
        return 0   # Très grandes valeurs (ex: BTC)

class TerminalDisplay:
    """
    Classe responsable de l'affichage des informations dans le terminal.
    Gère les résumés périodiques et les tableaux d'informations.
    """
    
    def __init__(self, position_manager, price_manager, config):
        """
        Initialise le gestionnaire d'affichage.
        
        Args:
            position_manager: Instance de PositionManager pour accéder aux positions actives
            price_manager: Instance de PriceManager pour accéder aux données de prix
            config: Configuration du bot
        """
        self.position_manager = position_manager
        self.price_manager = price_manager
        self.config = config
        self.logger = get_trading_logger()
        self.trader = None # référence au trader (sera définie dans integrate_display_with_trader)

        # État de l'affichage
        self.last_summary_time = time.time()
        self.summary_interval = 3600  # 1 heure par défaut
        self.trades_since_last_summary = 0
        self.profit_since_last_summary = 0.0
        
        # Statistiques globales
        self.start_time = time.time()
        self.positions_opened = 0
        self.positions_closed = 0
        self.profitable_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.peak_capital = config.INITIAL_CAPITAL
        
        # Verbosité par défaut
        self.verbosity = VerbosityLevel.NORMAL
    
    def set_verbosity(self, level):
        """Change le niveau de verbosité de l'affichage"""
        self.verbosity = level
        set_verbosity(level)
        self.logger.info(f"Niveau de verbosité changé à: {level.name}")
    
    async def on_position_opened(self, data):
        """
        Appelé lorsqu'une position est ouverte.
        Met à jour les statistiques et affiche les informations pertinentes.
        
        Args:
            data: Données de la position ouverte
        """
        self.positions_opened += 1
        self.trades_since_last_summary += 1
        
        # Afficher un tableau avec les détails de la position
        self.display_position_details(data, is_opening=True)
    
    async def on_position_closed(self, data):
        """
        Appelé lorsqu'une position est fermée.
        Met à jour les statistiques et affiche les informations pertinentes.
        
        Args:
            data: Données de la position fermée
        """
        self.positions_closed += 1
        self.trades_since_last_summary += 1
        
        # Extraire le profit/perte
        profit_loss = data.get('profit_loss', 0.0)
        self.total_profit += profit_loss
        self.profit_since_last_summary += profit_loss
        
        if profit_loss > 0:
            self.profitable_trades += 1
        
        # Mettre à jour le pic de capital et le drawdown
        current_capital = self.position_manager.capital
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
        
        drawdown = (self.peak_capital - current_capital) / self.peak_capital * 100
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        # Afficher un tableau avec les détails de la position fermée
        self.display_position_details(data, is_opening=False)
        
        # Vérifier si un résumé périodique est nécessaire
        current_time = time.time()
        if current_time - self.last_summary_time >= self.summary_interval:
            self.display_periodic_summary()

    def display_position_details(self, data, is_opening=True):
        """
        Affiche les détails d'une position sous forme de tableau avec précision adaptative pour les prix.
        
        Args:
            data: Données de la position
            is_opening: True si c'est une ouverture de position, False si c'est une fermeture
        """
        pair = data.get('pair', 'N/A')
        position_type = data.get('position_type', 'N/A')
        
        # Utiliser la fonction d'aide pour déterminer la précision
        entry_price = data.get('entry_price', 0.0)
        price_precision = get_price_precision(entry_price)
        
        # Journaliser les données brutes pour diagnostic en mode debug
        self.logger.debug(f"Affichage des détails de position - Données: {data}")
        
        if is_opening:
            # Tableau pour une ouverture de position
            table = ConsoleTable(
                ["Paire", "Type", "Prix d'entrée", "Taille", "Take Profit", "Stop Loss"],
                [12, 10, 15, 12, 15, 15]
            )
            
            # Formater chaque valeur avec la précision appropriée
            table.add_row([
                pair,
                position_type,
                f"{entry_price:.{price_precision}f}",
                f"{data.get('position_size', 0.0):.2f}",
                f"{data.get('take_profit', 0.0):.{price_precision}f}",
                f"{data.get('stop_loss', 0.0):.{price_precision}f}"
            ])
            
            log_separator(self.logger, "NOUVELLE POSITION OUVERTE")
            table.log_table(self.logger)
            
        else:
            # Tableau pour une fermeture de position
            table = ConsoleTable(
                ["Paire", "Type", "Prix entrée", "Prix sortie", "P/L", "Raison", "Durée"],
                [12, 10, 12, 12, 10, 15, 12]
            )
            
            # Calculer la durée approximative de la position si possible
            duration = "N/A"
            if 'open_time' in data and 'close_time' in data:
                open_time = data.get('open_time', 0)
                close_time = data.get('close_time', 0)
                duration_seconds = close_time - open_time
                duration = str(timedelta(seconds=int(duration_seconds)))
            
            # Formater le profit/perte avec 2 décimales (en valeur monétaire)
            profit_loss = data.get('profit_loss', 0.0)
            profit_display = f"{profit_loss:.2f}"
            
            # Utiliser la même précision pour prix d'entrée et de sortie
            exit_price = data.get('exit_price', 0.0)
            
            table.add_row([
                pair,
                position_type,
                f"{entry_price:.{price_precision}f}",
                f"{exit_price:.{price_precision}f}",
                profit_display,
                data.get('close_reason', 'N/A').capitalize(),
                duration
            ])
            
            log_separator(self.logger, "POSITION FERMÉE")
            table.log_table(self.logger)
            
            # Afficher l'état du capital actuel
            self.logger.info(f"Capital actuel: {self.position_manager.capital:.2f} " +
                        f"({'+' if self.total_profit >= 0 else ''}{self.total_profit:.2f} total)")

    def display_active_positions(self):
        """
        Affiche un tableau de toutes les positions actuellement actives
        avec une précision adaptative pour les prix
        """
        active_positions = self.position_manager.active_positions
        
        if not active_positions:
            self.logger.info("Aucune position active actuellement.")
            return
        
        table = ConsoleTable(
            ["Paire", "Type", "Prix d'entrée", "Prix actuel", "P/L", "P/L %", "Durée"],
            [12, 10, 15, 15, 12, 12, 15]
        )
        
        current_time = time.time()
        
        for pair, position in active_positions.items():
            entry_price = position.get('entry_price', 0.0)
            position_size = position.get('position_size', 0.0)
            current_price = self.price_manager.get_current_price(pair) or entry_price
            
            # Utiliser la fonction d'aide pour déterminer la précision appropriée
            price_precision = get_price_precision(entry_price)
            
            # Calcul du P/L
            pl_value = position_size * (current_price / entry_price - 1)
            pl_percent = (current_price / entry_price - 1) * 100
            
            # Estimer la durée de la position
            entry_time = position.get('entry_time', current_time)
            duration = str(timedelta(seconds=int(current_time - entry_time)))
            
            table.add_row([
                pair,
                position.get('position_type', 'N/A'),
                f"{entry_price:.{price_precision}f}",   # Précision adaptative
                f"{current_price:.{price_precision}f}", # Précision adaptative
                f"{pl_value:.2f}",                      # Toujours 2 décimales pour les montants
                f"{pl_percent:.2f}%",                   # Toujours 2 décimales pour les pourcentages
                duration
            ])
        
        log_separator(self.logger, f"POSITIONS ACTIVES ({len(active_positions)})")
        table.log_table(self.logger)
    
    def display_periodic_summary(self):
        """
        Affiche un résumé périodique des activités de trading
        """
        current_time = time.time()
        time_since_start = current_time - self.start_time
        hours_running = time_since_start / 3600
        
        # Calculer les performances
        win_rate = (self.profitable_trades / self.positions_closed * 100) if self.positions_closed > 0 else 0
        trades_per_hour = self.positions_closed / hours_running if hours_running > 0 else 0
        
        # Calculer le ROI (Return on Investment)
        initial_capital = self.config.INITIAL_CAPITAL
        current_capital = self.position_manager.capital
        roi = ((current_capital - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0
        
        # Créer un résumé
        summary_data = {
            "Temps d'exécution": f"{int(hours_running)}h {int((hours_running % 1) * 60)}m",
            "Positions ouvertes": len(self.position_manager.active_positions),
            "Positions fermées": self.positions_closed,
            "Taux de réussite": f"{win_rate:.2f}%",
            "Trades par heure": f"{trades_per_hour:.2f}",
            "Profit total": f"{self.total_profit:.2f}",
            "ROI": f"{roi:.2f}%",
            "Capital actuel": f"{current_capital:.2f}",
            "Capital maximum": f"{self.peak_capital:.2f}",
            "Drawdown maximum": f"{self.max_drawdown:.2f}%",
            "Trades depuis dernier résumé": self.trades_since_last_summary,
            "Profit depuis dernier résumé": f"{self.profit_since_last_summary:.2f}"
        }
        
        # Afficher le résumé et réinitialiser les compteurs périodiques
        log_summary(self.logger, summary_data, "RÉSUMÉ PÉRIODIQUE")
        
        self.last_summary_time = current_time
        self.trades_since_last_summary = 0
        self.profit_since_last_summary = 0.0
    
    async def start_auto_summary_task(self, interval_seconds=3600):
        """
        Démarre une tâche qui affiche périodiquement un résumé des performances.
        
        Args:
            interval_seconds: Intervalle entre les résumés en secondes (défaut: 1 heure)
        """
        self.summary_interval = interval_seconds
        
        while True:
            await asyncio.sleep(interval_seconds)
            # Afficher le résumé des positions actives puis le résumé global
            self.display_active_positions()
            self.display_periodic_summary()
    
    def display_system_status(self):
        """
        Affiche l'état actuel du système (connexions, mémoire, etc.)
        """
        log_separator(self.logger, "ÉTAT DU SYSTÈME")
        
        # Informations diverses sur l'état du système
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        uptime = time.time() - self.start_time
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        self.logger.info(f"Date et heure: {current_time}")
        self.logger.info(f"Temps d'exécution: {int(hours)}h {int(minutes)}m {int(seconds)}s")
        self.logger.info(f"Mode d'exécution: {'Test' if self.config.ORDER_EXECUTION_MODE == 0 else 'Réel'}")
        self.logger.info(f"Monnaie de référence: {self.config.REFERENCE_CURRENCY}")
        self.logger.info(f"Capital initial: {self.config.INITIAL_CAPITAL:.2f}")
        self.logger.info(f"Capital actuel: {self.position_manager.capital:.2f}")
        
        # Ajout de l'état de prise de positions
        if hasattr(self, 'trader') and self.trader:
            trading_status = "ACTIVÉE" if self.trader.accepting_new_positions else "DÉSACTIVÉE"
            self.logger.info(f"Prise de positions: {trading_status}")
        
        # Informations sur les paires surveillées
        pairs_count = len(self.price_manager.current_prices)
        self.logger.info(f"Paires surveillées: {pairs_count}")
        
        log_separator(self.logger)
    
    def display_volatility_rankings(self, top_n=10):
        """
        Affiche un classement des paires par volatilité avec précision adaptative pour les prix
        
        Args:
            top_n: Nombre de paires à afficher
        """
        # Récupérer les ratios de volatilité pour toutes les paires
        volatility_data = []
        
        for pair in self.price_manager.current_prices.keys():
            metrics = self.price_manager.get_volatility_metrics(pair)
            current_price = self.price_manager.get_current_price(pair) or 0.0
            volatility_data.append((pair, metrics['volatility_ratio'], metrics['atr'], current_price))
        
        # Trier par ratio de volatilité (du plus élevé au plus faible)
        volatility_data.sort(key=lambda x: x[1], reverse=True)
        
        # Créer un tableau pour l'affichage
        table = ConsoleTable(["Rang", "Paire", "Ratio Volatilité", "ATR", "Prix actuel"], [8, 12, 15, 15, 15])
        
        for i, (pair, ratio, atr, current_price) in enumerate(volatility_data[:top_n]):
            # Déterminer la précision appropriée pour le prix et l'ATR
            price_precision = get_price_precision(current_price)
            atr_precision = get_price_precision(atr)  # Même logique pour l'ATR
            
            table.add_row([
                i + 1,
                pair,
                f"{ratio:.2f}",                       # Toujours 2 décimales pour les ratios
                f"{atr:.{atr_precision}f}",           # Précision adaptative pour ATR
                f"{current_price:.{price_precision}f}" # Précision adaptative pour le prix
            ])
        
        log_separator(self.logger, f"TOP {top_n} PAIRES PAR VOLATILITÉ")
        table.log_table(self.logger)
    
    def display_welcome_message(self):
        """Affiche un message de bienvenue avec informations sur le bot"""
        bot_name = "CryptoTrader"
        version = "2.3"
        
        self.logger.info(f"{Colors.BRIGHT_CYAN}{Colors.BOLD}")
        log_separator(self.logger)
        self.logger.info(f"{bot_name} v{version} - Bot de Trading Crypto".center(80))
        log_separator(self.logger)
        self.logger.info(f"{Colors.RESET}")
        
        # Informations sur la configuration
        self.logger.info(f"Mode d'exécution: {'Test' if self.config.ORDER_EXECUTION_MODE == 0 else 'Réel'}")
        self.logger.info(f"Monnaie de référence: {self.config.REFERENCE_CURRENCY}")
        self.logger.info(f"Capital initial: {self.config.INITIAL_CAPITAL:.2f} {self.config.REFERENCE_CURRENCY}")
        
        if self.config.ENABLE_WARMUP:
            warmup_duration_mins = self.config.ATR_PERIOD * self.config.INTERVAL * self.config.WARMUP_MULTIPLIER / 60
            self.logger.info(f"Période de warm-up: {warmup_duration_mins:.1f} minutes")
        
        # Aide sur les niveaux de verbosité
        self.logger.info(f"\nNiveaux de verbosité disponibles:")
        self.logger.info(f"  - MINIMAL: Uniquement les événements critiques et les positions")
        self.logger.info(f"  - NORMAL: Événements importants (niveau par défaut)")
        self.logger.info(f"  - DETAILED: Informations détaillées sur le trading")
        self.logger.info(f"  - DEBUG: Tous les détails techniques pour le débogage")
        
        self.logger.info(f"\nDémarrage du bot...")

    def toggle_trading(self, enable: Optional[bool] = None) -> None:
        """
        Active ou désactive la prise de nouvelles positions.
        
        Args:
            enable: True pour activer, False pour désactiver, None pour basculer l'état actuel
        """
        # Si CryptoTrader est accessible
        if hasattr(self, 'trader') and self.trader:
            current_state = self.trader.accepting_new_positions
            
            # Si enable est None, on bascule l'état actuel
            new_state = not current_state if enable is None else enable
            
            # Appeler la méthode set_trading_status du trader
            self.trader.set_trading_status(new_state)
            
            status_str = "activée" if new_state else "désactivée"
            self.logger.info(f"Prise de nouvelles positions {status_str}")
        else:
            self.logger.error("Impossible d'accéder au trader pour modifier l'état de trading")

    def process_command(self, command):
        """
        Traite une commande utilisateur entrée dans le terminal
        
        Args:
            command: La commande à traiter (chaîne de caractères)
        
        Returns:
            True si le bot doit continuer, False pour arrêter
        """
        command = command.strip().lower()
        
        if command in ["quit", "exit", "q"]:
            return False
            
        elif command in ["help", "h", "?"]:
            self.logger.info("\nCommandes disponibles:")
            self.logger.info("  help, h, ? - Affiche cette aide")
            self.logger.info("  status, s - Affiche l'état du système")
            self.logger.info("  positions, p - Affiche les positions actives")
            self.logger.info("  summary, sum - Affiche un résumé des performances")
            self.logger.info("  vol - Affiche le classement par volatilité")
            self.logger.info("  stop_trading, st - Arrête la prise de nouvelles positions")
            self.logger.info("  start_trading, sta - Réactive la prise de nouvelles positions")
            self.logger.info("  verbose min - Change la verbosité à minimal")
            self.logger.info("  verbose normal - Change la verbosité à normal")
            self.logger.info("  verbose detailed - Change la verbosité à detailed")
            self.logger.info("  verbose debug - Change la verbosité à debug")
            self.logger.info("  quit, exit, q - Quitte le programme")
            
        elif command in ["status", "s"]:
            self.display_system_status()
            
        elif command in ["positions", "p"]:
            self.display_active_positions()
            
        elif command in ["summary", "sum"]:
            self.display_periodic_summary()
            
        elif command == "vol":
            self.display_volatility_rankings()
        
        # Nouvelles commandes pour contrôler la prise de positions
        elif command in ["stop_trading", "st"]:
            self.toggle_trading(False)
            
        elif command in ["start_trading", "sta"]:
            self.toggle_trading(True)
            
        elif command.startswith("verbose "):
            level = command.split(" ")[1]
            if level == "min":
                self.set_verbosity(VerbosityLevel.MINIMAL)
            elif level == "normal":
                self.set_verbosity(VerbosityLevel.NORMAL)
            elif level == "detailed":
                self.set_verbosity(VerbosityLevel.DETAILED)
            elif level == "debug":
                self.set_verbosity(VerbosityLevel.DEBUG)
            else:
                self.logger.info(f"Niveau de verbosité non reconnu: {level}")
        
        return True