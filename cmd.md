## Commandes d'execution

### --execution-mode [0-2] : Mode d'exécution des ordres
0 : Tests sur testnet (validation seulement)
1 : Ordres réels sur testnet (avec fonds virtuels)
2 : Ordres réels sur mainnet (fonds réels)


### --reference-currency [symbole] : 
Monnaie de référence (USDT, USDC, BUSD, etc.)

### --verbosity [niveau] : Niveau de verbosité des logs
minimal : Uniquement les erreurs et les événements critiques
normal : Événements importants (valeur par défaut)
detailed : Informations détaillées sur les trades
debug : Tous les détails techniques


## Commandes disponibles pendant l'exécution.
help, h, ? : Affiche l'aide des commandes
status, s : Affiche l'état du système
positions, p : Affiche les positions actives
summary, sum : Affiche un résumé des performances
vol : Affiche le classement des paires par volatilité
verbose min : Change la verbosité à minimal
verbose normal : Change la verbosité à normal
verbose detailed : Change la verbosité à detailed
verbose debug : Change la verbosité à debug
quit, exit, q : Quitte le programme


## Code couleur
🟢 Vert : Positions ouvertes, profits
🔴 Rouge : Erreurs, pertes
🟡 Jaune : Avertissements, informations importantes
🔵 Bleu : Informations système, messages de debug
⚪ Blanc : Informations standard

## Astuces d'utilisation

Pendant la phase de warm-up : Utilisez la commande status pour vérifier la progression.
Pour une surveillance continue : Utilisez le niveau de verbosité normal qui donne une bonne vision des événements importants sans surcharger l'affichage.
Pour l'analyse de performance : Utilisez la commande summary régulièrement pour suivre l'évolution des performances.
Pour le débogage : Passez temporairement en mode verbose debug pour voir tous les détails techniques.
Pour une surveillance discrète : Utilisez le niveau minimal qui n'affiche que les ouvertures/fermetures de positions et les erreurs.
Consultez les logs : Tous les détails sont toujours enregistrés dans les fichiers de log, même si vous avez choisi un mode d'affichage minimal.