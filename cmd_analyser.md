### example :
python trading_session_analyzer.py --currency USDC --days 1 --mode 0
python trading_session_analyzer.py --currency USDC --hours 2 --mode 1
python trading_session_analyzer.py --currency USDC --hours 2 --reconcile --save-snapshots --mode 1 # --detailed


### Options disponibles :

--currency : Monnaie de référence (USDC, USDT, etc.)
--days : Nombre de jours à analyser en arrière
--mode : Mode d'exécution (0=test sur testnet, 1=réel sur testnet, 2=réel sur mainnet)
--output : Répertoire de sortie pour le rapport et les graphiques

--reconcile: Active la réconciliation des soldes
--save-snapshots: Sauvegarde les snapshots du compte
--detailed: Génère un rapport plus détaillé avec analyses supplémentaires

example : python trading_session_analyzer.py --hours 2 --detailed --save-snapshots

## Option --reconcile
Ce qu'elle fait :
Cette option active la réconciliation des soldes, ce qui signifie que votre script va :

- Comparer les soldes initial et final capturés
- Calculer l'écart entre la variation réelle du solde et le P/L calculé par l'analyse des trades
- Tenter d'expliquer les causes possibles de cet écart
- Afficher ces informations dans une section dédiée du rapport

Si elle n'est pas utilisée :

- La méthode reconcile_account_changes() n'est pas appelée explicitement dans le traitement principal
- La section "RÉCONCILIATION DES SOLDES" n'apparaît pas dans votre rapport
- Aucune analyse des écarts entre P/L calculé et variation réelle du solde n'est effectuée
- Le script ne tente pas d'expliquer les incohérences potentielles entre les trades enregistrés et les variations de solde

En résumé, sans cette option, vous perdez les informations de diagnostic qui pourraient vous aider à comprendre pourquoi vos soldes et vos calculs de P/L ne correspondent pas.

## Option --save-snapshots
Ce qu'elle fait :

- Crée un sous-répertoire "snapshots" dans votre répertoire de sortie
- Capture explicitement un snapshot du compte au tout début du processus
- Sauvegarde ce snapshot initial dans un fichier JSON
- Bien que non explicitement codé dans votre extrait, elle devrait idéalement aussi sauvegarder le snapshot final après toutes les analyses

Mais le plus important : elle définit les moments précis auxquels les snapshots sont pris - le snapshot initial est capturé au tout début du traitement, avant même de générer le rapport.
Si elle n'est pas utilisée :

- Les snapshots ne sont pas sauvegardés dans des fichiers JSON
- Point crucial : Sans cette option, les snapshots sont capturés à l'intérieur de la méthode generate_full_report(), probablement avec un intervalle très court entre eux
- Comme les deux snapshots sont pris presque en même temps, ils affichent les mêmes valeurs
La réconciliation devient moins précise puisqu'elle compare deux états pratiquement identiques du compte