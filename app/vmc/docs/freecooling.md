# Free cooling et bypass — VMC DOMEO210

Documentation du fonctionnement thermique de l’échangeur, du bypass et de la logique **free cooling** sur la DOMEO210, telle qu’observée et pilotée dans HomeIot.

## Sondes de température

| Sonde | Signification | Emplacement typique |
|-------|---------------|---------------------|
| **Tout** | Air extérieur brut | Entrée extérieure, avant échangeur |
| **Timp** | Air insufflé (entrée) | Après échangeur côté soufflage |
| **Text** | Air extrait | Bouches d’extraction (cuisine, SdB…) |
| **Tint** | Température intérieure | Sonde dans l’unité (référence globale logement) |

**Timp ≠ Tout** : en mode récupération (bypass fermé), Timp est le résultat de l’échange thermique entre les deux flux. Avec le bypass ouvert, les chemins sont court-circuités et **Timp ≈ Text** (plus de transfert dans l’échangeur).

## Échangeur à plaques (récupération passive)

L’échangeur est **bidirectionnel** au sens thermique : la chaleur va toujours du flux le plus chaud vers le plus froid. Les flux ne se mélangent pas.

### Hiver — Text > Timp (cas classique)

L’air extrait chaud cède ses calories à l’air neuf froid :

```
Text (extraction, chaud)  ──►  chaleur  ──►  Timp (insufflation, froid)
```

- **Timp** monte (air neuf préchauffé par rapport à Tout)
- **Text** baisse
- La récupération de chaleur est **utile**

### Été canicule — Text < Timp (extérieur plus chaud que l’intérieur)

L’air entrant chaud cède un peu de chaleur à l’extraction plus fraîche :

```
Timp / Tout (entrant, chaud)  ──►  chaleur  ──►  Text (extraction, plus frais)
```

- **Timp** reste inférieur à **Tout** grâce à l’échangeur (léger refroidissement de l’air entrant)
- Ce n’est **pas** du free cooling efficace (l’air reste trop chaud)
- Mais c’est **mieux** que l’air extérieur brut

Dans ce cas, **ouvrir le bypass aggrave la situation** : Timp ≈ Tout, donc air insufflé **plus chaud** qu’avec l’échangeur actif.

## Rôle du bypass

Le bypass **court-circuite l’échangeur** : l’air neuf n’est plus réchauffé (ou refroidi) par l’air extrait.

| Mode | Effet |
|------|-------|
| Bypass **fermé** | Récupération active — échange Text ↔ Timp |
| Bypass **ouvert** | Pas de récupération — Timp proche de Text (chemins superposés) |

### Bypass manuel vs auto

- **MANUAL BYPASS** (bobine 9) : force l’ouverture pendant une durée (timer, défaut 8 h). À garder **désactivé** en routine.
- **BYPASS AUTO CONTROL** (bobine 8) : autorise la logique native DOMEO selon les seuils Tint / Text MINI.
- **STATE OF BYPASS** (lecture seule) : état réel du clapet (physique), distinct du réglage manuel.

## Free cooling — quand le bypass a du sens

Le free cooling consiste à insuffler de l’**air extérieur frais** sans le faire réchauffer par l’extraction chaude dans l’échangeur.

### Conditions opérationnelles

Les trois conditions suivantes doivent être réunies :

| # | Condition | Pourquoi |
|---|-----------|----------|
| 1 | **Tint > Tint MINI** (défaut 24 °C) | Intérieur inconfortablement chaud |
| 2 | **Text > Text MINI** (défaut 12 °C) | Extraction assez chaude ; évite le bypass quand Text est très basse (hiver) |
| 3 | **Tout < Text** | Extérieur plus frais que l’extraction — seule situation où la ventilation refroidit |

Conditions complémentaires utiles en observation :

- **Text > Timp** : l’échangeur réchauffe l’air neuf (Timp tiré vers Text) — le bypass évite cette perte de free cooling
- **Tout < Tint** : l’extérieur est plus frais que l’intérieur (sinon aucune ventilation ne refroidit)

### Exemple typique (nuit d’été)

| Sonde | Valeur |
|-------|--------|
| Tout | 18 °C |
| Tint | 26 °C |
| Text | ~26 °C |
| Timp (échangeur actif) | ~22 °C |

- Text > Timp → l’échangeur « mange » 4 °C de free cooling
- Tint > 24 °C → besoin de refroidir
- Tout < Text → l’extérieur est exploitable

→ Le bypass auto **s’ouvre** : Timp descend vers ~18 °C (proche de Tout).

### Cas où le bypass ne doit **pas** s’ouvrir

| Situation | Raison |
|-----------|--------|
| **Hiver** (Tint < 24 °C) | Récupération de chaleur souhaitée |
| **Canicule, intérieur frais** (Text < Timp, Tout > Tint) | L’échangeur refroidit déjà un peu l’air entrant ; le bypass insufflerait un air **plus chaud** |
| **Text < Text MINI** (ex. 11 °C) | Condition DOMEO non remplie — extraction trop froide |

## Seuils bypass auto DOMEO

Registres Modbus (holding) :

| Paramètre | Registre | Plage | Défaut |
|-----------|----------|-------|--------|
| Text MINI | 22 | 11–20 °C | 12 °C |
| Tint MINI | 23 | 21–30 °C | 24 °C |
| BYPASS AUTO CONTROL | bobine 8 | ON/OFF | — |

### Text MINI — plancher sur l’extraction

- **Text < Text MINI** (ex. 11 °C en hiver) → condition 2 **fausse** → pas de bypass
- **Text > Text MINI** (ex. 15 °C) → condition 2 **vraie**, mais le bypass ne s’ouvre que si **Tint > Tint MINI** et **Tout < Text** sont aussi vrais

En hiver typique, même avec Text à 15 °C, **Tint reste sous 24 °C** : le bypass reste fermé. Text MINI protège surtout les cas où l’extraction est très froide ; le verrou principal « saison » reste **Tint MINI**.

### Tint MINI — seuil de confort intérieur

Bypass auto envisagé uniquement si l’intérieur dépasse ce seuil (défaut 24 °C).

## Schéma récapitulatif

```
                    ┌─────────────────────────────────────┐
                    │         BYPASS FERMÉ                │
                    │  Échangeur actif — récupération     │
                    └─────────────────────────────────────┘
                                      │
          Text > Timp                 │                 Text < Timp
          (hiver / free cooling       │                 (canicule, int. frais)
           si Tout < Text)            │                 Garder bypass FERMÉ
                    │                 │                 (échangeur refroidit Timp)
                    ▼                 ▼
              Réchauffe Timp     Légère baisse Timp
              (utile hiver)      vs Tout (mieux que bypass)

                    ┌─────────────────────────────────────┐
                    │    FREE COOLING (bypass ouvert)     │
                    │  Tint > 24  ET  Text > 12           │
                    │  ET  Tout < Text  ET  Text > Timp  │
                    └─────────────────────────────────────┘
```

## Configuration dans HomeIot

- **Dashboard VMC** (`/vmc/`) : cartes Tout, Timp, Text, Tint ; badge **STATE OF BYPASS** ; section bypass auto (Text MINI, Tint MINI)
- **API** :
  - `GET /vmc/change/bypass_auto` — bascule BYPASS AUTO CONTROL
  - `GET /vmc/config/bypass_auto_text_mini?value=…`
  - `GET /vmc/config/bypass_auto_tint_mini?value=…`
- **Historique** : courbe `bypass` = état réel du clapet (`STATE OF BYPASS`)
- **Watchdog** (`app/vmc/watchdog.py`) : ajuste le débit bas (120 / 150 m³/h) selon bypass actif et capteurs X-Sense (SAAS vs Kitchen) — indépendant de la logique free cooling DOMEO

## Recommandations

1. **BYPASS AUTO** : ACTIVED en routine
2. **MANUAL BYPASS** : DESACTIVED sauf test ponctuel
3. Seuils par défaut (Text MINI 12 °C, Tint MINI 24 °C) : adaptés à un usage standard
4. En canicule avec intérieur plus frais que l’extérieur : ne pas forcer le bypass manuel

## Références

- Registres Modbus : `app/vmc/config/domeo210_modbus.yml`
- Forum HACF : [VMC Domeo 210 Modbus](https://forum.hacf.fr/t/vmc-domeo-210-modbus/3947)
