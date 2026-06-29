# Contrôles Modbus — VMC DOMEO210

Documentation des commandes Modbus (boost, bypass, standby) et de la **détection d'état** telle qu'implémentée dans HomeIot (`app/vmc/domeo.py`, dashboard `/vmc/`).

Pour la logique thermique du bypass et du free cooling, voir [freecooling.md](freecooling.md).

## Vue d'ensemble

| Fonction | Commande (écriture) | État réel (lecture) |
|----------|---------------------|---------------------|
| **Bypass** | Bobine 9 — `MANUAL BYPASS` | Input 25 — `STATE OF BYPASS` (0/1/2) |
| **Bypass auto** | Bobine 8 — `BYPASS AUTO CONTROL` | — |
| **Boost** | Holding 15 — `AIRFLOW SET` (0=OFF, 1=ON) | **Déduit du débit** (voir ci-dessous) |
| **Standby** | Bobine 7 — `ACTIVATION MODE STANBY/ABSENCE` | Bobine 7 (lecture) |

Le bypass dispose d'un registre d'état physique fiable. **Le boost n'en a pas** sur la DOMEO210 observée en production.

## Boost

### Commande

- **Registre** : holding 15 (`AIRFLOW SET`)
- **Valeurs** : `0` = débit bas, `1` = boost (temporisé ½ h), `2` = haut (version allemande)
- **API** : `GET /vmc/change/boost` — bascule ON/OFF via `toggle_boost()` dans `domeo.py`
- **Réglage débit boost** : holding 10 (`TEMPORISED 1/2H BOOST AIRFLOW SETTING`, 120–210 m³/h) — `GET /vmc/change/boost_setting?value=…`
- **Réglage débit bas** : holding 9 (`LOW AIRFLOW SETTING`, 60–150 m³/h) — `GET /vmc/change/airflow?value=…`

### Temporisation

Le boost cuisine est **temporisé 30 minutes** (comportement DOMEO d'usine). Il peut être coupé avant la fin en renvoyant `AIRFLOW SET = 0`.

### Détection d'état — ce qui ne fonctionne pas

Plusieurs indicateurs Modbus sont **trompeurs** sur notre installation :

| Source | Registre | Comportement observé |
|--------|----------|----------------------|
| `TYPE OF CONTROL` | input 10 | Passe à `5` (SWITCH ON/OFF) au boost mais **reste bloqué à 5** après désactivation |
| Input 15 (`FREE COOLING`) | input 15 | Reste à **0** même boost actif — ne pas utiliser comme état boost |
| `TEMPORIZED BOOST` | input 14 | Reste à **0** même boost actif |
| `AIRFLOW SET` (lecture holding) | holding 15 | Reste à **0** en lecture (registre de commande, pas d'état persistant) |

La configuration Home Assistant du forum HACF lit l'input 15 comme « état boost » (`0`/`1`). **Ce n'est pas fiable** sur notre DOMEO210 : boost à 210 m³/h avec input 15 = 0.

### Détection d'état — logique HomeIot

L'état boost est **déduit du débit actuel** par rapport aux réglages bas et boost :

```
boost_actif = CURRENT_AIRFLOW >= (LOW_AIRFLOW_SETTING + BOOST_AIRFLOW_SETTING) / 2
```

| Métrique Modbus | Registre | Rôle |
|-----------------|----------|------|
| `CURRENT AIRFLOW` | input 16 | Débit instantané (m³/h) |
| `LOW AIRFLOW SETTING` | holding 9 | Consigne débit bas |
| `TEMPORISED 1/2H BOOST AIRFLOW SETTING` | holding 10 | Consigne débit boost |

**Exemple** (mesure live, boost actif) :

| Métrique | Valeur |
|----------|--------|
| LOW AIRFLOW SETTING | 120 m³/h |
| BOOST AIRFLOW SETTING | 210 m³/h |
| Seuil (milieu) | 165 m³/h |
| CURRENT AIRFLOW | 210 m³/h |
| → Boost | **ON** |

**Exemple** (boost coupé, `TYPE OF CONTROL` encore à SWITCH) :

| Métrique | Valeur |
|----------|--------|
| CURRENT AIRFLOW | 120 m³/h |
| → Boost | **OFF** |

Si le réglage boost n'est pas disponible, repli : `CURRENT_AIRFLOW > LOW_AIRFLOW_SETTING + 15`.

### Interface (`/vmc/`)

- Badge **Boost ON/OFF** et bouton BOOST : état via `GET /vmc/status` → `modes.boost.active`
- Carte **Type de contrôle** : indicateur Modbus interne — **ne pas** l'utiliser pour l'état boost
- Historique graphique : courbe `boost` = même logique débit (`build_status_doc` dans `domeo.py`)

### Pièges UI / API

1. Ne pas lier le bouton boost à `TYPE OF CONTROL == 5` : faux positifs après désactivation.
2. Ne pas lier à l'input 15 : toujours 0 sur notre matériel.
3. Après une commande, le débit met quelques secondes à se stabiliser — le dashboard rafraîchit à 0 s, 2 s et 5 s.

## Bypass

### Commande et état

| Rôle | Registre | API |
|------|----------|-----|
| Manuel | Bobine 9 | `GET /vmc/change/bypass` |
| Auto | Bobine 8 | `GET /vmc/change/bypass_auto` |
| État réel | Input 25 (`STATE OF BYPASS`) | Lecture via `/vmc/metrics/latest` ou `/vmc/status` |

Valeurs `STATE OF BYPASS` : `0` = DESACTIVED, `1` = ACTIVED, `2` = ERROR.

Le badge bypass du dashboard et `modes.bypass.active` utilisent **STATE OF BYPASS** (état physique du clapet), pas la bobine manuelle.

### Mode SWITCH (boost) — bypass bloqué

Quand `TYPE OF CONTROL` = `5` (SWITCH ON/OFF), souvent après un boost :

- la bobine **MANUAL BYPASS** peut passer à `1` (commande Modbus OK) ;
- mais **STATE OF BYPASS** reste à `0` — le clapet ne s'ouvre pas.

**Séquence de sortie** (implémentée dans `toggle_manual_bypass()` avant activation) :

1. `AIRFLOW SET` (holding 15) ← `0` — coupe le boost
2. `BYPASS AUTO CONTROL` (bobine 8) ← `0` (ACTIVED) — fait repasser `TYPE OF CONTROL` à `4`
3. pause ~1,5 s
4. bascule **MANUAL BYPASS** (bobine 9)

L'activation manuelle **active donc le bypass auto** si la VMC est bloquée en mode SWITCH. La désactivation ne modifie pas le bypass auto.

### Conditions thermiques (bypass auto)

Le bypass **automatique** ne s'ouvre que si Tint > Tint MINI, Text > Text MINI et Tout < Text (voir [freecooling.md](freecooling.md)). Le bypass **manuel** force la commande ; si `STATE OF BYPASS` reste à `0` après la séquence ci-dessus, vérifier les températures et attendre quelques secondes.

## Standby / absence

- **Bobine 7** — `ACTIVATION MODE STANBY/ABSENCE`
- API : `GET /vmc/change/standby`
- État : lecture bobine 7 (`register == 1` → standby inactif / mode normal selon version)

## Implémentation

```
domeo.py
  is_boost_active()           → lecture Modbus live (toggle)
  is_boost_active_from_metrics() → à partir des métriques Mongo
  toggle_boost()              → holding 15 : 0 ou 1
  build_status_doc()          → modes.boost pour historique et /vmc/status

vmc.py
  GET /vmc/change/boost        → toggle_boost + sauvegarde métriques
  GET /vmc/status              → dernier modes.boost depuis Mongo
```

## Références

- Carte registres : `app/vmc/config/domeo210_modbus.yml`
- Forum HACF (config HA, à prendre avec précaution pour l'état boost) : [VMC Domeo 210 Modbus](https://forum.hacf.fr/t/vmc-domeo-210-modbus/3947)
- Thermique bypass / free cooling : [freecooling.md](freecooling.md)
