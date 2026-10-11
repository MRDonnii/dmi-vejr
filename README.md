# DMI Vejr

Home Assistant-integration med alt fra DMI's open data, plus en færdig vejrside.

| Del | Hvor |
| --- | --- |
| Integrationen `dmi_vejr` | `custom_components/dmi_vejr` (dette repo), installeres via HACS |
| Vejrkortet `custom:ha-weather-card` | [MRDonnii/ha-smart-home-cards](https://github.com/MRDonnii/ha-smart-home-cards) (`src/cards/ha-weather-card`), installeres via HACS |
| Visningens opsætning | `dashboard/vejret.json` (kopi af `views[2]` i `energi-overblik`) |

## Installation

1. HACS → Integrationer → menuen ⋮ → *Brugerdefinerede repositories*: tilføj
   `https://github.com/MRDonnii/dmi-vejr` som *Integration*.
2. Hent **DMI Vejr** og genstart Home Assistant.
3. Indstillinger → Enheder og tjenester → *Tilføj integration* → **DMI Vejr**.

## Opsætning: adresse eller sted på kortet

- **Adresse**: skriv en dansk adresse (fx `Torvegade 1, Randers`); den slås op i OpenStreetMap.
- **Placering på kortet**: uden adresse bruges nålen på kortet (som standard Hjem).
- **Kommune** (DMI's klimadata) og **varslingsregion** (DMI's varsler) findes automatisk ud fra
  stedet, men kan vælges i listerne.

Stedet kan ændres senere: Indstillinger → Enheder og tjenester → DMI Vejr → **Konfigurer**.
Integrationen genindlæses med det nye sted. Steder uden for Danmark afvises, fordi DMI's data kun
dækker Danmark.

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

## Test

```sh
pip install pytest-homeassistant-custom-component h5py freezegun
python -m pytest tests
```

En ny version udgives ved at hæve `version` i `manifest.json`; workflowet laver så en release, som HACS henter.

## Visningen

`dashboard/vejret.json` er en færdig visning. Radaren følger det sted, integrationen er sat op til.
Under vejrkortet ligger otte grafer (`apexcharts-card` i `layout-card`): temperatur med
usikkerhedsbånd, vandstand med stormflodsprognose og tidevand, vind, nedbør, skyer og sol,
skybase/nulgradsgrænse/tordenenergi, lufttryk og luftfugtighed (7 dage) og døgntemperaturer (30 dage). Den kan sættes ind igen som en visning i
`energi-overblik` (eller et andet dashboard) med HA's rå konfigurationseditor.

Tests og eksempler bruger Randers centrum (56.4607, 10.0364) som position.
