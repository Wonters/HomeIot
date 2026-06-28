# Réseau domestique — box et relais Huawei WS8100

Documentation de l'architecture réseau utilisée pour HomeIot : box principale, relais Wi‑Fi en sous-réseau séparé, routage et compartimentation.

## Topologie

```
[Box / routeur principal]
  Réseau : 192.168.1.0/24
  Passerelle : 192.168.1.1
        |
        |  (Ethernet ou Wi‑Fi côté « WAN » du relais)
        |
  [Relais Huawei WS8100]
  IP côté box : 192.168.1.x  (ex. 192.168.1.42 — DHCP réservé recommandé)
        |
  Réseau Wi‑Fi relais : 192.168.3.0/24
  Passerelle : 192.168.3.1
        |
  Appareils IoT, ELFIN EW11, serveur Docker, etc.
  Ex. ELFIN : 192.168.3.11 (port Modbus TCP 8899)
```

| Segment | Plage | Rôle |
|---------|-------|------|
| Box | `192.168.1.*` | Réseau principal (PC, box, imprimantes…) |
| Relais WS8100 | `192.168.3.*` | Sous-réseau Wi‑Fi dédié (IoT, capteurs, VMC) |

Le relais crée un **second sous-réseau** (mode relais / répéteur avec NAT), et non un simple pont sur `192.168.1.*`.

## Comportement observé : asymétrie du trafic

### 3.* → 1.* — fonctionne

Exemple : SSH depuis une machine `192.168.3.x` vers `192.168.1.x`.

1. Le paquet part vers la passerelle `192.168.3.1` (relais).
2. Le relais applique du **NAT** : le trafic sort côté box avec l'IP du relais (`192.168.1.x`).
3. La box route normalement vers le réseau `192.168.1.*`.
4. Les réponses reviennent au relais, qui les renvoie à la machine `192.168.3.x` via sa table de connexions.

### 1.* → 3.* — ne fonctionne pas (sans route statique)

Exemple : ping ou SSH depuis `192.168.1.x` vers `192.168.3.x`.

1. La box reçoit une destination `192.168.3.x`.
2. Elle **ne connaît pas** le réseau `192.168.3.0/24` — ce sous-réseau n'existe que **derrière** le relais.
3. Sans route explicite, le paquet est abandonné ou envoyé vers la passerelle par défaut sans aboutir.

Ce n'est en général **pas** un pare-feu sur les machines `3.*`, mais un **problème de routage** entre deux sous-réseaux.

## Solution retenue : route statique sur la box

Objectif : garder la **compartimentation** (deux subnets distincts) tout en permettant l'accès **volontaire** depuis `1.*` vers `3.*`.

### Configuration sur la box

| Paramètre | Valeur |
|-----------|--------|
| Réseau de destination | `192.168.3.0/24` |
| Masque | `255.255.255.0` |
| Passerelle (next hop) | IP du relais côté box, ex. `192.168.1.42` |

### Prérequis

- **IP fixe ou DHCP réservé** pour le WS8100 côté box (`192.168.1.42` ou autre). Si cette IP change, la route statique cesse de fonctionner.
- Vérifier que la box FAI accepte les **routes statiques LAN → LAN** (toutes ne le permettent pas).

### Test

Depuis une machine `192.168.1.x` :

```shell
ping 192.168.3.11
ssh user@192.168.3.x
nmap -p 8899 192.168.3.11   # ELFIN Modbus TCP
```

## Compartimentation réseau

Deux subnets **≠** isolation sécuritaire forte.

| Aspect | Sans firewall | Avec route statique |
|--------|---------------|---------------------|
| `3.* → 1.*` | Déjà possible (NAT sortant du relais) | Inchangé |
| `1.* → 3.*` | Impossible | Possible (toute la plage `192.168.3.0/24`) |
| Découverte locale (mDNS, Bonjour) | Ne traverse pas les subnets | Idem — accès par IP ou DNS local |
| Logs côté box | Trafic `3.*` sortant vu comme `192.168.1.x` (IP du relais) | Idem |

Pour une vraie compartimentation (IoT isolé du LAN principal), ajouter des **règles firewall** sur la box ou le relais :

- autoriser seulement les ports nécessaires (SSH, HTTP, Modbus 8899, etc.) ;
- éventuellement restreindre `3.* → 1.*` aux seules cibles autorisées.

Le **mode pont / AP** sur le WS8100 (tout le monde en `192.168.1.*`) n'est **pas** retenu ici : il supprime la frontière entre segments.

## Limitations connues

- **Double NAT** côté `3.*` : les machines derrière le relais sortent masquées derrière l'IP du WS8100 côté box.
- **Pas de découverte automatique** entre `1.*` et `3.*` (Chromecast, imprimantes réseau, etc.) — utiliser des IP fixes ou un DNS local.
- **Dashboard / services HomeIot** : configurer l'IP du serveur FastAPI dans les dashboards pour correspondre à l'IP réelle sur `192.168.3.*` (voir README).

## Références projet

- ELFIN EW11 (Modbus VMC) : `192.168.3.11:8899` — voir [README](../../README.md)
- VMC / free cooling : [app/vmc/docs/freecooling.md](../../app/vmc/docs/freecooling.md)
