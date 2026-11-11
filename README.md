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
- 🔒 un **verrou** à distance (GeoRide 1 ; le GeoRide 3 se verrouille
  seul avec le badge ou le téléphone)
- 🚨 des **événements HA** quand l'alarme se déclenche (vibration,
  mouvement…), avec environ 1 min de délai
- 🔋 sa **batterie en %**, son **compteur kilométrique** et son **dernier
  trajet** (distance, durée, vitesses, angle max à gauche et à droite)
- 🛠️ un **capteur par entretien** configuré dans l'appli GeoRide
  (vidange, chaîne, pneus…)
- 🏷️ tes **badges Bluetooth**, comme appareils séparés avec leur
  batterie

L'intégration utilise l'API v2 de GeoRide (`api-v2.georide.com`), celle
de l'appli depuis sa version 5.5, interrogée toutes les 60 s.

---

## Installation

[![Ouvrir Home Assistant et ajouter ce dépôt à HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bartolije&repository=georide-ha&category=integration)

[![Ouvrir Home Assistant et ajouter l'intégration GeoRide.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=georide)

1. Le premier badge ajoute ce dépôt à HACS (ou *HACS → Intégrations →
   ⋮ → Dépôts personnalisés →* `https://github.com/bartolije/georide-ha`).
2. Installe **GeoRide** depuis HACS, puis redémarre Home Assistant.
3. Le second badge ouvre l'ajout de l'intégration (ou *Paramètres →
   Appareils et services → Ajouter une intégration → GeoRide*).

Home Assistant 2026.8 ou plus récent est requis.

### Installation manuelle (sans HACS)

Copie `custom_components/georide/` dans le dossier
`config/custom_components/` de Home Assistant, redémarre, puis ajoute
l'intégration depuis *Paramètres → Appareils et services*.

L'interface est traduite en **français, anglais, allemand, espagnol,
italien et néerlandais**. Les traductions DE / ES / IT / NL sont
perfectibles : les contributions natives sont bienvenues.

## Connexion et session

Comme l'appli GeoRide, l'intégration se connecte **sans mot de passe** :
tu saisis l'e-mail de ton compte, GeoRide t'envoie un code à usage
unique par e-mail, tu le tapes. Seule la session qui en résulte est
conservée.

**Une session GeoRide dure 90 jours.** Quand elle expire, GeoRide
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
| `lock` | (nom de la moto) | Verrou manuel, traceurs GeoRide 1 seulement. Le GeoRide 3 se verrouille seul (badge, téléphone) : pas d'entité. |
| `switch` | Mode éco | Mode « moto sans batterie » de l'appli. Appliqué à la prochaine connexion du traceur, ce qui peut prendre des heures quand il est en veille. |
| `sensor` | Compteur kilométrique | Kilomètres parcourus. |
| `sensor` | Vitesse | Indisponible : l'API v2 ne donne plus la vitesse instantanée. |
| `sensor` | Batterie | Batterie de la moto en %, calculée depuis la tension. |
| `sensor` | Dernière position | Horodatage du dernier point GPS. |
| `sensor` | Dernier trajet : fin, distance, durée, vitesse moyenne, vitesse max | Le trajet le plus récent (rafraîchi toutes les 5 min). Il reste affiché jusqu'au suivant, même après l'hivernage ou un redémarrage (jusqu'à un an). |
| `sensor` | Angle d'inclinaison max du dernier trajet | Désactivé par défaut. Degrés depuis la verticale ; attributs `max_left`, `max_right` et `side`. |
| `sensor` | Altitude | Diagnostic, désactivé par défaut. Indisponible avec l'API v2. |
| `sensor` | Tension batterie externe / interne | Diagnostic. La tension interne est indisponible avec l'API v2 (elle donne un pourcentage). |
| `sensor` | Fin de l'abonnement | Diagnostic, désactivé par défaut. |
| `sensor` | (un par entretien) | Un capteur diagnostic par entretien configuré dans l'appli, en km ou en jours restants (négatif = en retard). |
| `binary_sensor` | En mouvement | Déduit de l'âge du dernier point GPS (moins de 5 min). |
| `binary_sensor` | Volée / Chute détectée | Inconnus avec l'API v2, qui ne donne plus ces informations. |
| `binary_sensor` | Badge associé | Diagnostic, désactivé par défaut. |

Les traceurs et badges retirés du compte GeoRide disparaissent de Home
Assistant au redémarrage suivant ; les nouveaux apparaissent en une
minute environ.

### Badges

Chaque badge Bluetooth associé à un traceur apparaît comme un appareil
rattaché à sa moto.

| Plateforme | Entité | Contenu |
|---|---|---|
| `sensor` | Batterie | Batterie du badge en %. |
| `sensor` | Dernière remontée batterie | Indisponible avec l'API v2. |
| `binary_sensor` | Mise à jour du firmware disponible | Inconnue avec l'API v2. |

Le modèle du badge s'affiche sur la fiche de l'appareil, et son adresse
MAC y est rattachée.

## Rafraîchissement des données

L'intégration interroge `api-v2.georide.com` toutes les 60 s (véhicule,
traceur, batterie, mode, abonnement et derniers événements du
traceur). Les trajets sont rafraîchis toutes les 5 min, les entretiens
et les badges toutes les 15 min. L'API v2 n'a pas de canal temps réel
(l'appli n'ouvre plus l'ancien flux socket.io) : les alarmes arrivent
dans Home Assistant en une minute environ.

## Service `georide.trip_summary`

Récupère les trajets d'une période et renvoie des statistiques. La
réponse d'un service se récupère dans un script ou une automatisation
avec `response_variable:`.

```yaml
script:
  georide_30_derniers_jours:
    sequence:
      - service: georide.trip_summary
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

## Événements

L'intégration déclenche des événements Home Assistant, utiles pour les
automatisations.

| Événement | Données (`event_data`) | Déclenché quand |
|---|---|---|
| `georide_lock_event` | `device_id`, `tracker_id`, `tracker_name`, `is_locked` | le verrou change d'état. |
| `georide_moving_event` | `device_id`, `tracker_id`, `tracker_name`, `moving` | la moto se met en mouvement ou s'arrête. |
| `georide_alarm_event` | `device_id`, `tracker_id`, `tracker_name`, `type`, `occurred_at`, `source` | à chaque nouvel événement du traceur. `type` est le type GeoRide sans le préfixe `event/` : `vibration/detected`, `movement/detected`, `displacement/detected`, `power/restored`… (types changés avec l'API v2). |

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
      event_type: georide_alarm_event
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
regroupe la carte, le verrou, la batterie, la vitesse, le compteur, la
dernière position et le dernier trajet dans un seul bloc par moto, avec
une photo de la moto en bandeau si tu veux.

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
- **Pas de vitesse instantanée, d'altitude, ni d'indicateur vol ou
  chute** avec l'API v2.
- **Alarmes avec environ 1 min de délai** : il n'y a plus de temps
  réel.
- **Intégration personnalisée** : elle n'est pas dans Home Assistant de
  base, les mises à jour passent par HACS.

## Dépannage

Pour voir ce que l'intégration récupère, active les journaux de
débogage :

```yaml
logger:
  default: info
  logs:
    custom_components.georide: debug
```

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
3. La session reste valable chez GeoRide jusqu'à son expiration
   (90 jours).

## Qualité

L'intégration déclare l'[échelle de qualité des intégrations Home Assistant](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
dans [`custom_components/georide/quality_scale.yaml`](custom_components/georide/quality_scale.yaml) :

- 🥉 Bronze : **18 / 18** règles
- 🥈 Argent : **10 / 10** règles
- 🥇 Or : **19 / 21** règles, les 2 autres exemptées (découverte sur le
  réseau local, sans objet pour un service cloud)
- 🏆 Platine : **2 / 3** règles, la 3e exemptée (aucune dépendance
  externe : le client de l'API est dans l'intégration)

Le tout vérifié à chaque push par la CI : mypy `--strict` et 255 tests
(97 % de couverture) contre la dernière version de Home Assistant, plus
les validations officielles `hassfest` et HACS (aussi lancées chaque
semaine pour repérer une version de HA qui casserait l'intégration). C'est une auto-évaluation : Home
Assistant n'audite l'échelle de qualité que pour les intégrations
officielles.

## Licence

[MIT](LICENSE)
