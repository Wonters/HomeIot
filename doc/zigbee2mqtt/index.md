# Zigbee2MQTT — configuration

Zigbee2MQTT tourne dans Docker via le service `zigbee2mqtt` du [`docker-compose.yml`](../../docker-compose.yml). La configuration persistante se trouve dans [`config/zigbee2mqtt/`](../../config/zigbee2mqtt/).

| Élément | Valeur |
|---------|--------|
| Image | `koenkk/zigbee2mqtt:latest` |
| Interface web | `http://<ip-serveur>:8001` (port 8080 du conteneur) |
| Broker MQTT | `core-mosquitto:1883` (réseau Docker) |
| Préfixe topics | `zigbee2mqtt/` (consommé par HomeIot) |

## Matériel : Sonoff ZBDongle-E

Coordinateur utilisé : **Sonoff Zigbee 3.0 USB Dongle Plus (ZBDongle-E)** — puce EFR32MG21.

Le firmware flashé sur le dongle détermine l'adaptateur à indiquer dans `configuration.yaml` :

| Firmware | `serial.adapter` | Remarque |
|----------|------------------|----------|
| EZSP (NCp UART) | `ezsp` | Configuration actuelle du projet |
| Ember (Silabs NCP) | `ember` | Firmware récent recommandé par la communauté |

Références firmware : [`firmwares/firmwares.txt`](../../../firmwares/firmwares.txt) (dépôt parent).

Pour identifier le port série sur la VM qui porte le dongle :

```shell
ls -l /dev/serial/by-id/usb-ITead*
# ou
ls /dev/ttyACM* /dev/ttyUSB*
```

Préférer le chemin stable `/dev/serial/by-id/...` plutôt que `/dev/ttyACM0` (l'index peut changer au reboot).

---

## Deux topologies possibles

Le point critique est l'**emplacement physique du dongle USB** par rapport à la VM qui exécute le conteneur Zigbee2MQTT.

```
┌─────────────────────────────────────────────────────────────────┐
│  Cas A — dongle sur une AUTRE VM                                │
│                                                                 │
│  [VM dongle]                         [VM HomeIot / Docker]      │
│  Sonoff USB ──► socat :8485  ──TCP──►  zigbee2mqtt              │
│                                         serial.port: tcp://…    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Cas B — dongle sur la MÊME VM que zigbee2mqtt                  │
│                                                                 │
│  [VM HomeIot / Docker]                                          │
│  Sonoff USB ──► /dev/ttyACM0 ──pass-through──► zigbee2mqtt      │
│                                         serial.port: /dev/…     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Cas A — Dongle sur une autre VM (socat TCP)

**Configuration actuelle du projet** : le dongle est branché sur une VM dédiée (`192.168.3.7`), exposé en TCP sur le port `8485`, et Zigbee2MQTT (dans Docker sur la VM HomeIot) s'y connecte à distance.

### 1. Sur la VM qui porte le dongle USB

Installer `socat` et créer un service systemd qui relaie le port série vers TCP.

```shell
sudo apt-get install socat
```

Remplacer `DEVICE` par le chemin réel du dongle (résultat de `ls /dev/serial/by-id/...`) :

```ini
# /etc/systemd/system/zigbee-dongle-socat.service
[Unit]
Description=Sonoff ZBDongle-E — exposition série vers TCP
After=network-online.target

[Service]
ExecStart=/usr/bin/socat -d -d \
  TCP-LISTEN:8485,reuseaddr,keepalive,nodelay,keepidle=1,keepintvl=1,keepcnt=5,fork \
  FILE:/dev/serial/by-id/usb-ITead_Sonoff_Zigbee_3.0_USB_Dongle_Plus_XXXXX-if00,b115200,raw,echo=0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```shell
sudo systemctl daemon-reload
sudo systemctl enable --now zigbee-dongle-socat
sudo systemctl status zigbee-dongle-socat
```

Vérifier que le port écoute :

```shell
ss -tlnp | grep 8485
```

### 2. Réseau

La VM HomeIot doit pouvoir joindre `IP_DONGLE:8485`. Si les deux VMs sont sur des sous-réseaux différents (`192.168.1.*` ↔ `192.168.3.*`), une route statique peut être nécessaire — voir [Réseau domestique](../network/reseau-domestique.md).

Test depuis la VM HomeIot :

```shell
nc -zv 192.168.3.7 8485
```

### 3. `configuration.yaml` (côté Zigbee2MQTT)

Fichier : [`config/zigbee2mqtt/configuration.yaml`](../../config/zigbee2mqtt/configuration.yaml)

```yaml
socat:
  enabled: false          # socat tourne sur la VM dongle, pas dans le conteneur

serial:
  port: tcp://192.168.3.7:8485   # IP de la VM dongle
  adapter: ezsp                  # ou ember selon le firmware flashé

mqtt:
  server: mqtt://core-mosquitto:1883
  user: mqtt-user
  password: mqtt

frontend:
  enabled: true
```

Le bloc `socat` intégré à Zigbee2MQTT (`enabled: true`) sert à exposer un coordinateur **local** en TCP depuis le conteneur lui-même — il ne remplace pas le socat installé sur la VM distante.

### 4. `docker-compose.yml`

Aucun passage de périphérique USB n'est nécessaire sur la VM HomeIot :

```yaml
  zigbee2mqtt:
    image: koenkk/zigbee2mqtt:latest
    container_name: zigbee2mqtt
    restart: unless-stopped
    depends_on:
      - core-mosquitto
    ports:
      - "8001:8080"
    volumes:
      - ./config/zigbee2mqtt:/app/data
    environment:
      - TZ=Europe/Paris
```

Redémarrer après modification de la config :

```shell
docker compose restart zigbee2mqtt
```

---

## Cas B — Dongle sur la même VM que zigbee2mqtt

Le dongle USB est branché directement sur la machine qui exécute Docker. Zigbee2MQTT accède au port série en local, **sans socat TCP**.

### 1. Passer le périphérique USB au conteneur

Ajouter le mapping `devices` dans [`docker-compose.yml`](../../docker-compose.yml). Utiliser le chemin `/dev/serial/by-id/...` pour qu'il reste stable :

```yaml
  zigbee2mqtt:
    image: koenkk/zigbee2mqtt:latest
    container_name: zigbee2mqtt
    restart: unless-stopped
    depends_on:
      - core-mosquitto
    ports:
      - "8001:8080"
    volumes:
      - ./config/zigbee2mqtt:/app/data
    devices:
      - /dev/serial/by-id/usb-ITead_Sonoff_Zigbee_3.0_USB_Dongle_Plus_XXXXX-if00:/dev/ttyZigbee
    environment:
      - TZ=Europe/Paris
```

Le chemin cible (`/dev/ttyZigbee`) est arbitraire mais doit correspondre à `serial.port` dans la configuration.

### 2. `configuration.yaml`

```yaml
socat:
  enabled: false          # pas de relais TCP nécessaire

serial:
  port: /dev/ttyZigbee    # chemin **dans le conteneur** (cf. mapping devices)
  adapter: ezsp           # ou ember selon le firmware flashé

mqtt:
  server: mqtt://core-mosquitto:1883
  user: mqtt-user
  password: mqtt

frontend:
  enabled: true
```

Ne pas utiliser `tcp://127.0.0.1:8485` dans ce cas : le conteneur n'a pas besoin de socat si le dongle lui est passé directement.

### 3. Alternative : socat intégré Zigbee2MQTT (moins courant)

Si le dongle est sur la même VM mais **ne peut pas** être passé au conteneur (contrainte hyperviseur, USB non forwardé, etc.), on peut activer le socat interne de Zigbee2MQTT :

```yaml
socat:
  enabled: true
  master: pty,raw,echo=0,link=/tmp/ttyZ2M,mode=777
  slave: tcp-listen:8485,keepalive,nodelay,reuseaddr,keepidle=1,keepintvl=1,keepcnt=5

serial:
  port: /tmp/ttyZ2M
  adapter: ezsp
```

Cette option suppose que le conteneur voit quand même le périphérique USB (via `devices`). Elle crée un pseudo-TTY local ; utile surtout si un autre processus doit aussi accéder au coordinateur en TCP sur la même machine.

---

## Récapitulatif des différences

| | Cas A — dongle distant | Cas B — dongle local |
|--|------------------------|----------------------|
| socat sur VM dongle | **Oui** (systemd) | Non |
| `socat.enabled` dans Z2M | `false` | `false` (sauf cas particulier) |
| `serial.port` | `tcp://IP:8485` | `/dev/ttyZigbee` (ou `/dev/ttyACM0`) |
| `devices` dans compose | Non | **Oui** |
| Port firewall | Ouvrir `8485/tcp` sur VM dongle | Non |

---

## MQTT et intégration HomeIot

Zigbee2MQTT publie sur le broker Mosquitto du stack Docker :

- Topics : `zigbee2mqtt/<friendly_name>` et `zigbee2mqtt/bridge/#`
- L'application HomeIot (`server`) s'abonne via `MQTT_HOST=core-mosquitto`
- Dashboard capteurs : menu **Capteurs** → section Zigbee

Les identifiants MQTT sont définis dans [`mosquitto/config/passwd`](../../mosquitto/config/passwd) et doivent correspondre à la section `mqtt:` de `configuration.yaml`.

## Convertisseurs externes

Le projet charge des convertisseurs maison depuis `config/zigbee2mqtt/external_converters/` (ex. `linky.js`, `relay.js`, `temperature.js`). Ils sont référencés dans :

```yaml
advanced:
  external_converters:
    - linky.js
    - relay.js
    # ...
```

## Dépannage

| Symptôme | Piste |
|----------|-------|
| `Error: Error while opening socket` | socat non démarré sur la VM dongle, ou IP/port incorrect |
| `SRSP - SYS - failed` / timeout série | Mauvais `adapter` (ezsp vs ember), ou mauvais baudrate |
| Dongle introuvable dans le conteneur | Vérifier `devices:` dans compose et le chemin by-id |
| Pas de messages MQTT | Vérifier user/password Mosquitto, `docker compose logs zigbee2mqtt` |
| Appairage impossible | Frontend Z2M → activer le permit join ; vérifier que le coordinateur n'est pas utilisé ailleurs |

Logs :

```shell
docker compose logs -f zigbee2mqtt
```

## Références

- [Zigbee2MQTT — configuration](https://www.zigbee2mqtt.io/guide/configuration/)
- [Zigbee2MQTT — adapters](https://www.zigbee2mqtt.io/guide/adapters/)
- [Réseau domestique (routes, sous-réseaux)](../network/reseau-domestique.md)
- Firmware ZBDongle-E : [`firmwares/firmwares.txt`](../../../firmwares/firmwares.txt)
