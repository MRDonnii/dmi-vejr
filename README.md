# DMI Vejr

Hele vejrsiden i Home Assistant (`energi-overblik/vejret`):

| Del | Hvor |
| --- | --- |
| Integrationen `dmi_vejr` (v0.3.7) | `custom_components/dmi_vejr` (dette repo) |
| Vejrkortet `custom:ha-weather-card` | [MRDonnii/ha-smart-home-cards](https://github.com/MRDonnii/ha-smart-home-cards) (`src/cards/ha-weather-card`), installeres via HACS |
| Visningens opsætning | `dashboard/vejret.json` (kopi af `views[2]` i `energi-overblik`) |

## Integrationen

Alt fra DMI's open data: radar (regn nu, nærmeste regn, animeret radarkort med lyn), metObs-stationer,
klimadata for kommunen, havnedata (vandstand, vandtemperatur, tidevand), varsler (MeteoAlarm),
HARMONIE-ensemble-risici og prognose (Open-Meteo `dmi_seamless`). Satellitkortet kommer fra EUMETSAT
(MTG GeoColour), da DMI ikke har satellitbilleder i open data.

Hold antallet af DMI-kald nede: koordinatoren har en begrænser på 2 samtidige kald (DMI svarer 429).

## Test og deploy

```sh
/tmp/roe-test-venv/bin/python -m pytest tests
~/.local/bin/bt-guard-deploy   # kopierer filerne til HA; genstart derefter HA
```

## Visningen

`dashboard/vejret.json` er visningen som den ser ud i HA, med radarens position sat til Randers centrum som eksempel. Den kan sættes ind igen som en visning i
`energi-overblik` (eller et andet dashboard) med HA's rå konfigurationseditor.

Tests og eksempler bruger Randers centrum (56.4607, 10.0364) som position. Integrationen bruger selv Home Assistants hjemposition.
