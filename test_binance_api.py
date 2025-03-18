# test_binance_api.py
import asyncio
import os
import json
import logging
from dotenv import load_dotenv
from binance_api_connection import BinanceAPIManager

# Chargement des variables d'environnement depuis le fichier .env
load_dotenv()

# Configuration basique du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_api_connection():
    """
    Test de connexion à l'API Binance
    - Vérifie la connexion de base (ping)
    - Teste l'authentification avec les clés API
    - Récupère et affiche les informations du compte si authentifié
    """
    # Récupération des clés API depuis les variables d'environnement
    api_key = os.environ.get('BINANCE_API_KEY', '')
    api_secret = os.environ.get('BINANCE_API_SECRET', '')
    test_mode = os.environ.get('BINANCE_TEST_MODE', 'True').lower() == 'true'
    
    logger.info(f"Clé API trouvée: {'Oui' if api_key else 'Non'}")
    logger.info(f"Clé secrète trouvée: {'Oui' if api_secret else 'Non'}")
    logger.info(f"Mode test: {test_mode}")
    
    if not api_key or not api_secret:
        logger.error("Clés API Binance non configurées dans le fichier .env")
        return
    
    # Initialisation du gestionnaire API
    api_manager = BinanceAPIManager(api_key, api_secret, test_mode)
    
    try:
        # Initialisation de la session
        await api_manager.init_session()
        logger.info(f"Session initialisée (mode test: {test_mode})")
        
        # Test ping
        logger.info("Test de ping à l'API Binance...")
        await api_manager._make_request("GET", "/api/v3/ping")
        logger.info("✓ Ping réussi")
        
        # Test heure serveur
        logger.info("Récupération de l'heure du serveur...")
        server_time = await api_manager.get_server_time()
        logger.info(f"✓ Heure du serveur récupérée: {server_time}")
        
        # Test d'authentification
        logger.info("Test d'authentification avec les clés API...")
        account_info = await api_manager.get_account_info()
        logger.info("✓ Authentification réussie")
        
        # Affichage des informations du compte
        logger.info("Informations du compte:")
        
        # Récupérer les balances non nulles
        balances = [
            asset for asset in account_info.get('balances', [])
            if float(asset['free']) > 0 or float(asset['locked']) > 0
        ]
        
        # Afficher les balances
        if balances:
            logger.info(f"Nombre d'actifs avec balance: {len(balances)}")
            logger.info("Balances disponibles:")
            for asset in balances:
                logger.info(f"  • {asset['asset']}: {asset['free']} (libre) + {asset['locked']} (bloqué)")
        else:
            logger.info("Aucune balance disponible sur ce compte")
            
        # Test d'un ordre fictif
        logger.info("Test d'ordre fictif...")
        test_result = await api_manager.place_test_order(
            symbol="BTCUSDT",
            side="BUY",
            type="MARKET",
            quantity=0.001
        )
        logger.info("✓ Test d'ordre réussi - Les paramètres d'ordre sont valides")
        
        # Test des règles d'échange
        logger.info("Récupération des règles de l'échange...")
        exchange_info = await api_manager.get_exchange_info()
        
        # Afficher quelques informations sur les règles
        symbols_info = exchange_info.get('symbols', [])
        btc_usdt = next((s for s in symbols_info if s['symbol'] == 'BTCUSDT'), None)
        
        if btc_usdt:
            logger.info("Règles pour BTCUSDT:")
            lot_size = next((f for f in btc_usdt['filters'] if f['filterType'] == 'LOT_SIZE'), {})
            min_notional = next((f for f in btc_usdt['filters'] if f['filterType'] == 'MIN_NOTIONAL'), {})
            
            if lot_size:
                logger.info(f"  • Quantité min: {lot_size.get('minQty')}")
                logger.info(f"  • Quantité max: {lot_size.get('maxQty')}")
                logger.info(f"  • Step size: {lot_size.get('stepSize')}")
                
            if min_notional:
                logger.info(f"  • Valeur minimale d'ordre: {min_notional.get('minNotional')} USDT")
        
        logger.info("✓ Tests API Binance réussis")
        
    except Exception as e:
        logger.error(f"Erreur lors du test API: {e}")
    finally:
        # Fermeture propre de la session
        if api_manager.session and not api_manager.session.closed:
            await api_manager.close_session()
            logger.info("Session fermée")

if __name__ == "__main__":
    # Configuration de la boucle d'événements pour Windows si nécessaire
    import platform
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Exécution du test
    asyncio.run(test_api_connection())