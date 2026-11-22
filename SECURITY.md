# Sécurité

Seule la dernière version publiée reçoit des correctifs.

Pour signaler une faille (fuite de la session GeoRide, de positions GPS, exécution de code…), **n'ouvre pas
d'issue publique** : utilise *Security → Report a vulnerability* sur ce dépôt
([lien direct](https://github.com/bartolije/georide-ha/security/advisories/new)). Réponse sous quelques jours.

L'intégration ne conserve que la session GeoRide (pas de mot de passe), dans le stockage de Home Assistant.
Les diagnostics masquent la session, l'e-mail et les positions.
