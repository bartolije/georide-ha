<p align="center">
  <img src="logo.png" alt="GeoRide" width="380">
</p>

# GeoRide pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![release](https://img.shields.io/github/v/release/bartolije/georide-ha)](https://github.com/bartolije/georide-ha/releases)
[![ci](https://github.com/bartolije/georide-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/bartolije/georide-ha/actions)

Intégration Home Assistant **non officielle** pour les traceurs GPS moto
[GeoRide](https://georide.fr). GeoRide est un traceur antivol français
avec verrouillage, alerte vibration, détection de chute et angle
d'inclinaison. L'intégration branche ton compte GeoRide à Home Assistant
pour que chaque moto y apparaisse comme un appareil avec :

- 📍 sa **position** sur la carte
- 🚨 des **événements HA** quand l'alarme se déclenche (vibration,
  mouvement…), avec environ 1 min de délai
- 🔋 la **batterie de la moto** et celle **du traceur** en %, une alerte
  si le traceur est **débranché**, le **compteur kilométrique** et le
  **dernier trajet** (distance, durée, vitesses, angle max à gauche et
  à droite)
- 🛠️ un **capteur par entretien** configuré dans l'appli GeoRide
  (vidange, chaîne, pneus…)
- 🏷️ tes **badges Bluetooth**, comme appareils séparés avec leur
  batterie

L'intégration utilise l'API v2 de GeoRide (`api-v2.georide.com`), celle
de l'appli depuis sa version 5.5, interrogée toutes les 60 s.

**Traceurs pris en charge** : GeoRide 3 et 3S (vérifiés). Les GeoRide 1
et Mini se connectent, sans leur verrou manuel (voir *Limites
connues*). Les **motos
partagées** avec toi par leur propriétaire apparaissent comme les
tiennes (vérifié avec un compte qui en a deux).

---

## Installation

1. Dans HACS, cherche **GeoRide** et installe celle du dépôt
   `bartolije/georide-ha`, puis redémarre Home Assistant. Tant qu'elle
   n'apparaît pas dans la recherche, ajoute le dépôt à la main avec le
   premier badge ci-dessous (ou *HACS → ⋮ → Dépôts personnalisés →*
   `https://github.com/bartolije/georide-ha`, type *Intégration*).
2. Ajoute l'intégration avec le second badge (ou *Paramètres →
   Appareils et services → Ajouter une intégration → GeoRide*).

[![Ouvrir Home Assistant et ajouter ce dépôt à HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bartolije&repository=georide-ha&category=integration)

[![Ouvrir Home Assistant et ajouter l'intégration GeoRide.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=georide_ha)

Son domaine est `georide_ha` : elle peut cohabiter avec l'autre
intégration GeoRide du catalogue HACS (`ptimatth/GeorideHA`, ancienne
API).

Home Assistant 2026.8 ou plus récent est requis.

### Depuis une version 0.17

La 0.18 change le domaine de l'intégration (`georide` → `georide_ha`)
pour cohabiter avec l'autre intégration GeoRide.

**Avec HACS, rien à faire depuis la 0.17.7** : après la mise à jour et le
redémarrage, la 0.18 reprend ton compte, tes appareils et tes entités
(mêmes identifiants, historique conservé), garde les anciens noms
d'événements (`georide_…_event`) et de service (`georide.trip_summary`)
pour tes automatisations. L'ancien dossier `custom_components/georide`
reste en place, inactif : supprime-le à la main (HACS ne le fait pas).
Si tu passes directement d'une version plus
ancienne à la 0.18, ajoute simplement l'intégration GeoRide (nouveau code
par e-mail) : elle reprend l'ancienne installation de la même façon.

**Avec le Marketplace intégré à Home Assistant** (qui remplace HACS), la
mise à jour est refusée (« bartolije/georide-ha changed its domain from
georide to georide_ha, uninstall it and install it again »). Dans ce cas :

1. *Paramètres → Appareils et services → GeoRide → Supprimer*.
2. Dans le Marketplace, désinstalle GeoRide puis réinstalle-le (0.18),
   et redémarre Home Assistant.
3. Ajoute l'intégration GeoRide (nouveau code par e-mail).

Les entités reviennent normalement avec les mêmes identifiants (`sensor.<moto>_…`) et
leur historique, sauf celles que tu avais renommées. À adapter dans tes
automatisations : celles qui ciblent un appareil (et non une entité),
les événements `georide_…_event` (devenus `georide_ha_…_event`) et le
service `georide.trip_summary` (devenu `georide_ha.trip_summary`).

### Installation manuelle (sans HACS)

Copie `custom_components/georide_ha/` dans le dossier
`config/custom_components/` de Home Assistant, redémarre, puis ajoute
l'intégration depuis *Paramètres → Appareils et services*.

L'interface est traduite en **français, anglais, allemand, espagnol,
italien et néerlandais**. Les traductions DE / ES / IT / NL sont
perfectibles : les contributions natives sont bienvenues.

## Connexion et session

Comme l'appli GeoRide, l'intégration se connecte **sans mot de passe** :
tu saisis l'e-mail de ton compte, GeoRide t'envoie un code à usage
unique par e-mail, tu le tapes. Seule la session qui en résulte est
conservée. Code pas reçu ou expiré : coche *Envoyez-moi un nouveau
code* sur le même écran.

**Une session GeoRide dure 90 jours et se prolonge tant que
l'intégration s'en sert** : en usage normal, pas de nouveau code à
saisir. Si elle expire quand même (HA éteint longtemps), GeoRide
refuse les appels et Home Assistant te demande de **te réauthentifier**
(notification dans *Paramètres*, et sur la carte GeoRide dans
*Appareils et services*). Il suffit de la valider : un
nouveau code arrive par e-mail, tu le tapes et tout repart, sans
recréer l'intégration ni perdre l'historique. En attendant, les
entités GeoRide restent indisponibles.

La même démarche sert :
- après la mise à jour depuis une version qui utilisait l'ancienne API
  (0.16 et avant) : l'ancien jeton est refusé par l'API v2 ;
- à la main, quand tu veux : *Paramètres → Appareils et services →
  GeoRide → ⋮ → Reconfigurer*.

## Entités

Chaque traceur du compte devient un appareil avec les entités
suivantes.

| Plateforme | Entité | Contenu |
|---|---|---|
| `device_tracker` | (nom de la moto) | Position GPS, affichée sur la carte. |
| `switch` | Mode éco | Mode « moto sans batterie » de l'appli, pour les traceurs qui l'ont (pas les GeoRide 1 et Mini). Appliqué à la prochaine connexion du traceur, ce qui peut prendre des heures quand il est en veille : en attendant, l'interrupteur affiche le mode demandé et l'attribut `pending_until` l'heure prévue par GeoRide. |
| `sensor` | Compteur kilométrique | Kilomètres parcourus. |
| `sensor` | Batterie | Batterie de la moto en %, calculée depuis la tension. |
| `sensor` | Batterie du traceur | Diagnostic. Batterie interne du boîtier GeoRide en %. |
| `sensor` | Dernière position | Horodatage du dernier point GPS. |
| `sensor` | Dernier trajet : fin, distance, durée, vitesse moyenne, vitesse max | Le trajet le plus récent (vérifié toutes les 5 min). Il reste affiché jusqu'au suivant, même après l'hivernage ou un redémarrage. |
| `sensor` | Angle d'inclinaison max du dernier trajet | Désactivé par défaut. Degrés depuis la verticale ; attributs `max_left`, `max_right` et `side`. |
| `sensor` | Tension batterie externe | Diagnostic. Tension de la batterie de la moto. |
| `sensor` | Fin de l'abonnement | Diagnostic, désactivé par défaut. |
| `sensor` | (un par entretien) | Un capteur diagnostic par entretien configuré dans l'appli, en km ou en jours restants (négatif = en retard). |
| `binary_sensor` | En mouvement | Déduit de l'âge du dernier point GPS (moins de 5 min). |
| `binary_sensor` | Alimentation branchée | Éteint quand le traceur perd l'alimentation de la moto : câble coupé ou batterie débranchée. |
| `binary_sensor` | Volée | Allumé tant qu'un vol est déclaré à l'assistance GeoRide. |
| `binary_sensor` | Traceur en ligne | Diagnostic. Le traceur est connecté à GeoRide. |
| `binary_sensor` | Mode maintenance | Diagnostic. Mode maintenance (garage, transport) actif. |
| `binary_sensor` | Appel d'urgence / Appel aux proches | Diagnostic, désactivés par défaut. Services d'appel après une chute. |
| `binary_sensor` | Badge associé | Diagnostic, désactivé par défaut. |
| `update` | Firmware / Firmware Bluetooth | Version installée et dernière version. La mise à jour se lance depuis l'appli GeoRide. |
| `number` | Tension de coupure batterie | Réglage. Tension de la batterie moto sous laquelle le traceur cesse de s'alimenter dessus (11 à 16 V). Envoyé au traceur à sa prochaine connexion. |
| `switch` | Détecteur de chute | Réglage. |
| `binary_sensor` | Mode veille | Diagnostic. Mode veille du traceur actif (lecture seule). |
| `sensor` | Sensibilité aux vibrations | Diagnostic. Niveau réglé dans l'appli. |

Une entité n'est créée que si le traceur a la fonction : un GeoRide 1 ou
une moto partagée n'ont pas forcément les réglages ci-dessus.

Restent pour leur historique, **désactivées par défaut et indisponibles**
car l'API v2 ne donne plus ces informations : *Vitesse*, *Altitude*,
*Tension batterie interne* et *Chute détectée*.

Les traceurs et badges retirés du compte GeoRide disparaissent de Home
Assistant au redémarrage suivant ; en attendant, tu peux les supprimer
depuis leur fiche (*⋮ → Supprimer*). Les nouveaux apparaissent en une
minute environ.

### Badges

Chaque badge Bluetooth associé à un traceur apparaît comme un appareil
rattaché à sa moto.

| Plateforme | Entité | Contenu |
|---|---|---|
| `sensor` | Batterie | Batterie du badge en %. |
| `sensor` | Dernière remontée batterie | Désactivé par défaut : indisponible avec l'API v2. |
| `binary_sensor` | Mise à jour du firmware disponible | Désactivé par défaut : indisponible avec l'API v2. |

Le modèle du badge s'affiche sur la fiche de l'appareil, et son adresse
MAC y est rattachée.

## Rafraîchissement des données

L'intégration interroge `api-v2.georide.com` toutes les 60 s (véhicule,
traceur, batterie et derniers événements du traceur). Le dernier trajet
est vérifié toutes les 5 min (un seul appel), le mode, l'abonnement, le
firmware, les réglages, la déclaration de vol, les entretiens et les
badges toutes les 15 min : un changement fait dans l'appli GeoRide peut
donc mettre 15 min à apparaître. L'API v2 n'a pas de canal temps réel
(l'appli n'ouvre plus l'ancien flux socket.io) : les alarmes arrivent
dans Home Assistant en une minute environ.

## Service `georide_ha.trip_summary`

Récupère les trajets d'une période et renvoie des statistiques. La
réponse d'un service se récupère dans un script ou une automatisation
avec `response_variable:`.

```yaml
script:
  georide_30_derniers_jours:
    sequence:
      - service: georide_ha.trip_summary
        data:
          start_date: "{{ (now() - timedelta(days=30)).date() }}"
          end_date: "{{ now().date() }}"
        response_variable: resume
      - service: notify.persistent_notification
        data:
          message: >
            {{ resume.aggregate.trips_count }} trajets,
            {{ resume.aggregate.total_km }} km
            ({{ resume.aggregate.avg_km_per_trip }} km en moyenne).
            Vitesse max : {{ resume.aggregate.max_top_speed }} km/h.
```

Forme de la réponse :

```yaml
range:
  from: "2026-04-14T00:00:00Z"
  to:   "2026-05-14T23:59:59Z"
trackers:
  "12345":
    tracker_name: "Z900"
    summary:
      trips_count: 18
      total_km: 743.2
      avg_km_per_trip: 41.3
      km_per_month: { "2026-04": 312.5, "2026-05": 430.7 }
      avg_top_speed: 138.2        # km/h
      max_top_speed: 184.0        # km/h
      max_lean_angle: 47.3        # degrés depuis la verticale, côté le plus penché
      max_left_lean_angle: 47.3
      max_right_lean_angle: 44.1
aggregate:
  # même forme que `summary`, tous traceurs confondus
```

`tracker_id` limite le calcul à un traceur ; `include_trips: true`
ajoute la liste brute des trajets (pour une carte Lovelace, par
exemple).

## Commandes envoyées au traceur

L'intégration n'envoie au traceur que des commandes confirmées sur un
vrai traceur (GeoRide 3S, micrologiciel 50). GeoRide n'applique une
commande qu'à la prochaine connexion du traceur :

| Commande | Confirmée comment |
|---|---|
| Tension de coupure | Le 24/11/2026 : passée de 12,25 V à 12,30 V puis remise à 12,25 V ; chaque valeur a été relue chez GeoRide après l'envoi. |
| Détecteur de chute | Le 24/11/2026 : désactivé puis réactivé ; chaque état a été relu chez GeoRide après l'envoi. |
| Mode éco | Le 24/11/2026 : activé depuis l'intégration ; le traceur l'a appliqué à sa connexion suivante et le mode a été relu « eco » chez GeoRide. Le retour au mode normal part par la même commande. |

## Événements

L'intégration déclenche des événements Home Assistant, utiles pour les
automatisations.

| Événement | Données (`event_data`) | Déclenché quand |
|---|---|---|
| `georide_ha_moving_event` | `device_id`, `tracker_id`, `tracker_name`, `moving` | la moto se met en mouvement ou s'arrête. |
| `georide_ha_alarm_event` | `device_id`, `tracker_id`, `tracker_name`, `type`, `occurred_at`, `source` | à chaque nouvel événement du traceur. `type` est le type GeoRide sans le préfixe `event/` : `vibration/detected`, `movement/detected`, `displacement/detected`, `power/restored`… (types changés avec l'API v2). |

## Exemples d'automatisations

### Prévenir si la moto bouge en ton absence

```yaml
automation:
  - alias: GeoRide - la moto bouge en mon absence
    trigger:
      platform: state
      entity_id: binary_sensor.z900_en_mouvement
      to: "on"
    condition:
      condition: state
      entity_id: person.moi
      state: not_home
    action:
      service: notify.mobile_app_mon_telephone
      data:
        title: La moto bouge
        message: "Ta moto vient de se mettre en mouvement. Regarde la carte."
```

### Notification à chaque alarme

```yaml
automation:
  - alias: GeoRide - alarme
    trigger:
      platform: event
      event_type: georide_ha_alarm_event
    action:
      service: notify.mobile_app_mon_telephone
      data:
        title: "Alarme GeoRide : {{ trigger.event.data.type }}"
        message: "{{ trigger.event.data.tracker_name }} a déclenché une alerte."
```

### Batterie faible

```yaml
automation:
  - alias: GeoRide - batterie faible
    trigger:
      platform: numeric_state
      entity_id: sensor.z900_batterie
      below: 20
    action:
      service: notify.persistent_notification
      data:
        message: "La batterie de la moto est à {{ states('sensor.z900_batterie') }} %."
```

## Carte Lovelace

Une carte personnalisée tient dans `lovelace/georide-card.js`. Elle
regroupe la carte, la batterie de la moto et celle du
traceur, le compteur, la dernière position et le dernier trajet dans un
seul bloc par moto, avec une photo de la moto en bandeau si tu veux. Une
pastille **DÉBRANCHÉ** s'affiche si le traceur perd l'alimentation de la
moto.

### Installation

1. Copie `lovelace/georide-card.js` dans le dossier `<config>/www/` de
   Home Assistant.
2. *Paramètres → Tableaux de bord → ⋮ → Ressources → Ajouter une
   ressource* : URL `/local/georide-card.js`, type *Module JavaScript*.
3. En mode édition d'un tableau de bord : *Ajouter une carte → GeoRide
   bike*.

```yaml
type: custom:georide-card
device_id: <à choisir dans l'éditeur de la carte>
image: /local/zx10r.jpg   # facultatif : dépose une photo dans /config/www/
```

L'API GeoRide ne fournit pas de photo de la moto : le champ `image:`
permet d'utiliser la tienne. Sans lui, la carte affiche un en-tête
texte.

## Limites connues

- **La batterie en % est une estimation** : courbe linéaire de 11,0 V
  (0 %) à 12,7 V (100 %), alors que la décharge réelle d'une batterie
  au plomb ne l'est pas.
- **Pas de vitesse instantanée, d'altitude, ni d'indicateur de chute**
  avec l'API v2.
- **Pas de verrou manuel (GeoRide 1 et Mini)** ni d'activation du
  **mode veille** : ces commandes ne sont pas proposées tant qu'elles
  n'ont pas été confirmées sur un vrai traceur. Le mode veille est
  affiché en lecture seule.
- **Alarmes avec environ 1 min de délai** : il n'y a plus de temps
  réel.
- **Motos partagées** : si GeoRide refuse à ton compte les données d'une
  moto partagée avec toi, elle est ignorée et le journal de Home
  Assistant l'indique (« Skipping GeoRide vehicle … »). Les autres motos
  du compte fonctionnent normalement.
- **Intégration personnalisée** : elle n'est pas dans Home Assistant de
  base, les mises à jour passent par HACS.

## Dépannage

Pour voir ce que l'intégration récupère, active les journaux de
débogage :

```yaml
logger:
  default: info
  logs:
    custom_components.georide_ha: debug
```

En débogage, le journal contient chaque appel à GeoRide (`GET
/v1/vehicles -> 200 in 235 ms`), sans la session ni le contenu des
réponses. En niveau normal, il signale une fois chaque donnée qui cesse
d'arriver (« fetch failed … keeping previous »), puis son retour.

Pour un instantané complet : *Paramètres → Appareils et services →
GeoRide → ⋮ → Télécharger les diagnostics*. La session, les
coordonnées GPS et l'e-mail y sont masqués.

Si l'intégration apparaît en erreur, c'est le plus souvent une session
expirée : valide la notification de nouvelle authentification (ou
*Reconfigurer*), un nouveau code est envoyé par e-mail.

## Suppression

1. *Paramètres → Appareils et services → GeoRide → ⋮ → Supprimer* :
   appareils, entités et intégration sont retirés.
2. Dans HACS : *GeoRide → ⋮ → Supprimer* pour retirer les fichiers de
   `custom_components`.
3. La session GeoRide de l'intégration est fermée à la suppression (si
   GeoRide est injoignable à ce moment-là, elle expire seule en
   90 jours).

## Qualité

L'intégration déclare l'[échelle de qualité des intégrations Home Assistant](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
dans [`custom_components/georide_ha/quality_scale.yaml`](custom_components/georide_ha/quality_scale.yaml) :

- 🥉 Bronze : **18 / 18** règles
- 🥈 Argent : **10 / 10** règles
- 🥇 Or : **19 / 21** règles, les 2 autres exemptées (découverte sur le
  réseau local, sans objet pour un service cloud)
- 🏆 Platine : **2 / 3** règles, la 3e exemptée (aucune dépendance
  externe : le client de l'API est dans l'intégration)

Le tout vérifié à chaque demande de fusion par la CI : mypy `--strict` et 279 tests
(97 % de couverture) contre la dernière version de Home Assistant, plus
les validations officielles `hassfest` et HACS (aussi lancées chaque
semaine pour repérer une version de HA qui casserait l'intégration). C'est une auto-évaluation : Home
Assistant n'audite l'échelle de qualité que pour les intégrations
officielles.

## Licence

[MIT](LICENSE)
