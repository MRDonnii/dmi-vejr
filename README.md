# DMI Vejr

Hele vejrsiden i Home Assistant (`energi-overblik/vejret`):

| Del | Hvor |
| --- | --- |
| Integrationen `dmi_vejr` (v0.4.0) | `custom_components/dmi_vejr` (dette repo) |
| Vejrkortet `custom:ha-weather-card` | [MRDonnii/ha-smart-home-cards](https://github.com/MRDonnii/ha-smart-home-cards) (`src/cards/ha-weather-card`), installeres via HACS |
| Visningens opsætning | `dashboard/vejret.json` (kopi af `views[2]` i `energi-overblik`) |

## Integrationen

Alt fra DMI's open data:

- radar (regn nu, nærmeste regn, animeret radarkort med lyn) og lyndetektion;
- alle 43 parametre fra metObs-stationerne (nærmeste station pr. parameter, én forespørgsel);
- klimadata for kommunen: alle dagsværdier, i dag og i går, plus måneden indtil nu;
- havn: vandstand, vandtemperatur, tidevandstabel og DMI's stormflodsmodel DKSS (48 timer frem);
- varsler (DMI via MeteoAlarm);
- DMI's prognose-API (EDR): alle 17 ensemble-sandsynligheder (frost, tåge, sne, regn, skybrud,
  storm, orkan), ensemble-percentiler som usikkerhedsbånd (temperatur, vind, vindstød, regn, sne)
  og HARMONIE DINI (skybase, skylag, nulgradsgrænse, tordenenergi, sol, sigtbarhed, sne);
- 7-dagesprognosen (HARMONIE via Open-Meteo `dmi_seamless`).

Ikke med: 10 km-klimafeltet (kommer ca. to dage forsinket), WAM-bølgemodellen (havet),
rå radarfiler og lynsensordata. DMI har ingen pollen eller UV. Satellitkortet kommer fra EUMETSAT
(MTG GeoColour), da DMI ikke har satellitbilleder i open data.

Hold antallet af DMI-kald nede: koordinatoren har en begrænser på 2 samtidige kald (DMI svarer 429).
Prognose-API'et kaldes 3 gange i timen (sandsynligheder, percentiler, DINI) og DKSS én gang i timen.

## Test og deploy

```sh
/tmp/roe-test-venv/bin/python -m pytest tests
~/.local/bin/bt-guard-deploy   # kopierer filerne til HA; genstart derefter HA
```

## Visningen

`dashboard/vejret.json` er visningen som den ser ud i HA. Radaren følger Home Assistants hjemposition.
Under vejrkortet ligger otte grafer (`apexcharts-card` i `layout-card`): temperatur med
usikkerhedsbånd, vandstand med stormflodsprognose og tidevand, vind, nedbør, skyer og sol,
skybase/nulgradsgrænse/tordenenergi, lufttryk og luftfugtighed (7 dage) og døgntemperaturer (30 dage). Den kan sættes ind igen som en visning i
`energi-overblik` (eller et andet dashboard) med HA's rå konfigurationseditor.

Tests og eksempler bruger Randers centrum (56.4607, 10.0364) som position. Integrationen bruger selv Home Assistants hjemposition.
