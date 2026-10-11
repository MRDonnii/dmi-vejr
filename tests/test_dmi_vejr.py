"""Tests for DMI Vejr against a real Home Assistant core.

Fixtures are real data from 2026-10-08 ~20:00: the DMI radar composite at
17:55Z showed rain over the example location, Randers town centre (about 0.9 mm/h), while the DMI HARMONIE
model said clear sky (WMO 0) and no precipitation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.dmi_vejr.const import DOMAIN, EDR_INTERVAL, EDR_RETRY_INTERVAL, FORECAST_URL
from custom_components.dmi_vejr.radar import parse_composite, read_window, stereographic
from custom_components.dmi_vejr.radar_map import RadarFrame, render_frames

FIXTURES = Path(__file__).parent / "fixtures"
RADAR_H5 = (FIXTURES / "rain_sample.h5").read_bytes()
FORECAST = json.loads((FIXTURES / "forecast.json").read_text())
LAT, LON = 56.4607, 10.0364  # Randers town centre (example location)
RADAR_HREF = "https://opendataapi.dmi.dk/v1/radardata/download/dk.com.202610081755.500_max.h5"
LISTING = {"features": [{"id": "dk.com.202610081755.500_max.h5", "asset": {"data": {"href": RADAR_HREF}}}]}
NOW = datetime(2026, 10, 8, 18, 10, tzinfo=timezone.utc)  # 15 min after the scan


def _station(sid, name, lon, lat, value, observed="2026-10-08T18:00:00Z", param="temp_dry"):
    return {"geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"stationId": sid, "name": name, "value": value, "observed": observed,
                           "parameterId": param}}


def _every_parameter(features: list) -> dict:
    """The same readings for every metObs parameter (one combined DMI request)."""
    from custom_components.dmi_vejr.const import OBS_PARAMETERS, OBS_SLOW_PARAMETERS

    params = [*OBS_PARAMETERS, *OBS_SLOW_PARAMETERS]
    return {"features": [
        {**f, "properties": {**f["properties"], "parameterId": p}} for p in params for f in features
    ]}


# Hald Vest 11.6 km, Oedum 18.4 km, Skagen far outside the search radius.
OBSERVATIONS = _every_parameter([
    _station("06072", "Ødum", 10.1272, 56.3027, 7.6),
    _station("06049", "Hald Vest", 10.0929, 56.5604, 9.3),
    _station("06049", "Hald Vest", 10.0929, 56.5604, 8.9, "2026-10-08T17:50:00Z"),
    _station("06041", "Skagen", 10.6, 57.7, 1.0),
])
STATIONS = {"features": [
    {"properties": {"stationId": "06049", "name": "Hald Vest"}},
    {"properties": {"stationId": "06072", "name": "Ødum"}},
]}
# One strike about 12 km north-east, one far away (Copenhagen).
LIGHTNING = {"features": [
    {"geometry": {"type": "Point", "coordinates": [10.16, 56.54]},
     "properties": {"observed": "2026-10-08T18:02:00Z", "type": 0, "amp": -12.0}},
    {"geometry": {"type": "Point", "coordinates": [12.57, 55.68]},
     "properties": {"observed": "2026-10-08T18:05:00Z", "type": 0, "amp": -5.0}},
]}


# UV comes from a second Open-Meteo call without the DMI model (HARMONIE has no UV).
UV_URL = re.compile(re.escape(FORECAST_URL) + r"\?(?!.*models=).*")
UV = {
    "current": {"uv_index": 0.0},
    "hourly": {"time": FORECAST["hourly"]["time"], "uv_index": [1.5] * len(FORECAST["hourly"]["time"])},
    "daily": {"time": FORECAST["daily"]["time"], "uv_index_max": [2.2, 2.35, 2.5, 2.0, 1.9, 2.1, 2.4]},
}


def _climate_day(day: str, values: dict) -> list:
    return [
        {"properties": {"parameterId": k, "value": v, "from": f"{day}T00:00:00.001000+02:00",
                        "to": "x", "municipalityId": "0730"}}
        for k, v in values.items()
    ]


# Real shapes from DMI climateData (Randers Kommune), today's value is "so far".
CLIMATE = {"features": (
    _climate_day("2026-10-08", {"acc_precip": 4.6, "acc_heating_degree_days_17": 5.7, "mean_temp": 11.3,
                                "leaf_moisture": 1380.0, "no_frost_days": 0.0})
    + _climate_day("2026-10-07", {"acc_precip": 1.3, "acc_heating_degree_days_17": 6.1, "mean_temp": 9.7,
                                  "no_frost_days": 1.0})
    + _climate_day("2026-10-01", {"acc_heating_degree_days_17": 4.0})
    + _climate_day("2026-09-30", {"acc_heating_degree_days_17": 9.9})  # previous month
)}
OCEAN_STATIONS = {"features": [
    {"properties": {"stationId": "22058", "name": "Randers Havn I"}},
    {"properties": {"stationId": "22059", "name": "Randers Havn II"}},
]}
OCEAN_OBS = {"features": [
    _station("22058", "Randers Havn I", 10.04, 56.457, 12.0),
]}
TIDE_STATIONS = {"features": [
    {"geometry": {"type": "Point", "coordinates": [10.04, 56.457]},
     "properties": {"stationId": "22058", "name": "Randers"}},
    {"geometry": {"type": "Point", "coordinates": [10.21, 56.15]},
     "properties": {"stationId": "22331", "name": "Århus"}},
]}
# A tide wave: low 18:40Z (-10 cm), high 21:00Z (+14 cm).
_TIDE = [(-6, "18:10"), (-9, "18:20"), (-10, "18:40"), (-7, "19:00"), (0, "19:40"),
         (8, "20:20"), (13, "20:50"), (14, "21:00"), (12, "21:20"), (5, "22:00")]
TIDE = {"features": [
    {"properties": {"predictionTime": f"2026-10-08T{t}:00Z", "value": v, "stationId": "22058"}}
    for v, t in _TIDE
]}


def _cap(level: str, area: str, desc: str, onset: str, expires: str, ident: str, event="Moderate Regn"):
    return {"alert": {"identifier": ident, "msgType": "Alert", "info": [{
        "language": "da-DK", "event": event, "headline": f"DMI varsel {desc}",
        "description": desc, "onset": onset, "expires": expires,
        "parameter": [{"valueName": "awareness_level", "value": level}],
        "area": [{"areaDesc": desc, "geocode": [{"valueName": "EMMA_ID", "value": area}]}],
    }]}}


WARNINGS = {"warnings": [
    _cap("1; green; Minor", "DK004", "Ingen varsler", "2026-10-08T08:00:00+02:00",
         "2026-10-13T01:59:00+02:00", "none"),
    _cap("2; yellow; Moderate", "DK004", "Østjylland", "2026-10-08T19:00:00+02:00",
         "2026-10-09T06:00:00+02:00", "rain-east"),
    _cap("3; orange; Severe", "DK007", "Vest- og Sydsjælland", "2026-10-08T19:00:00+02:00",
         "2026-10-09T06:00:00+02:00", "fog-zealand", "Severe Tåge"),
    _cap("2; yellow; Moderate", "DK004", "Østjylland", "2026-10-07T10:00:00+02:00",
         "2026-10-07T18:00:00+02:00", "expired"),
    _cap("2; yellow; Moderate", "DK004", "Østjylland", "2026-10-08T18:00:00+02:00",
         "2026-10-09T06:00:00+02:00", "rain-east-v1"),
]}
WARNINGS["warnings"][1]["alert"]["references"] = "vagtchef@dmi.dk,rain-east-v1,2026-10-08T17:00:00+02:00"


def _coverage(values: dict) -> dict:
    times = [f"2026-10-08T{h:02d}:00:00Z" for h in range(17, 24)] + [
        f"2026-10-09T{h:02d}:00:00Z" for h in range(0, 22)
    ]
    return {"type": "Coverage", "domain": {"axes": {"t": {"values": times}}},
            "ranges": {k: {"values": (v * len(times))[: len(times)]} for k, v in values.items()}}


EDR_EPS = _coverage({
    "temperature-2m-below-273k-probability": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 15, 40, 55, 30],
    "total-precipitation-above-10mm-in-3hours-probability": [5],
    "total-precipitation-above-30mm-in-3hours-probability": [0],
    "gust-wind-speed-10m-above-25ms-within-1hour-probability": [0],
})
EDR_EPS["ranges"]["visibility-above-100m-probability"] = {"values": [0, 0, 30] + [0] * 26}
EDR_SF = _coverage({
    "probability-of-lightning": [2.0, 12.0, 0.0], "precipitation-type": [1],
    "temperature-2m": [282.15], "cloud-base": [850.0], "low-cloud-cover": [90.0],
    "medium-cloud-cover": [20.0], "high-cloud-cover": [5.0],
    "convective-available-potential-energy": [10.0, 250.0, 40.0], "0-degrees-c-isothermal-level": [1200.0],
    "downward-short-wave-radiation-flux-instant": [100.0], "visibility": [12000.0],
    "snow-depth-water-equivalent": [0.0],
})
# Ensemble percentiles; temperature in kelvin like DMI sends it.
EDR_PCT = _coverage({
    "temperature-2m-10percentile": [276.15, 275.15, 277.15], "temperature-2m-50percentile": [279.15],
    "temperature-2m-90percentile": [282.15, 284.15, 283.15],
    "gust-wind-speed-10m-1h-10percentile": [5.0], "gust-wind-speed-10m-1h-50percentile": [8.0],
    "gust-wind-speed-10m-1h-90percentile": [12.0, 15.5, 11.0],
    "wind-speed-10m-10percentile": [2.0], "wind-speed-10m-50percentile": [4.0, 6.5],
    "wind-speed-10m-90percentile": [7.0],
    "total-precipitation-1h-10percentile": [0.0], "total-precipitation-1h-50percentile": [0.1],
    "total-precipitation-1h-90percentile": [0.5],
    "time-integral-of-total-solid-precipitation-flux-1h-10percentile": [0.0],
    "time-integral-of-total-solid-precipitation-flux-1h-50percentile": [0.0],
    "time-integral-of-total-solid-precipitation-flux-1h-90percentile": [0.0],
})
# DKSS storm surge forecast in metres, rising to 0.62 m.
DKSS = _coverage({"sea-mean-deviation": [0.10, 0.20, 0.35, 0.50, 0.62, 0.40, 0.20, 0.05]})


def _mock_apis(aioclient_mock, radar=RADAR_H5, forecast=FORECAST, observations=OBSERVATIONS, edr_status=200):
    aioclient_mock.get(UV_URL, json=UV)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/climateData/.*"), json=CLIMATE)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/oceanObs/collections/station/.*"), json=OCEAN_STATIONS)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/oceanObs/collections/observation/.*"), json=OCEAN_OBS)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/oceanObs/collections/tidewaterstation/.*"), json=TIDE_STATIONS)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/oceanObs/collections/tidewater/.*"), json=TIDE)
    aioclient_mock.get(re.compile(r"https://feeds\.meteoalarm\.org/.*"), json=WARNINGS)
    if edr_status != 200:
        aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/forecastedr/.*"), status=edr_status)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/forecastedr/collections/harmonie_dini_eps_probabilities/.*"), json=EDR_EPS)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/forecastedr/collections/harmonie_dini_sf/.*"), json=EDR_SF)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/forecastedr/collections/harmonie_dini_eps_percentiles/.*"), json=EDR_PCT)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/forecastedr/collections/dkss_idw/.*"), json=DKSS)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/radardata/collections/.*"), json=LISTING)
    aioclient_mock.get(RADAR_HREF, content=radar)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/metObs/collections/station/.*"), json=STATIONS)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/metObs/collections/observation/.*"), json=observations)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/lightningdata/.*"), json=LIGHTNING)
    aioclient_mock.get(re.compile(re.escape(FORECAST_URL) + ".*"), json=forecast)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    entry = MockConfigEntry(domain=DOMAIN, data={"latitude": LAT, "longitude": LON})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_projection_matches_proj_reference_points() -> None:
    # Values from pyproj '+proj=stere +ellps=WGS84 +lat_0=56 +lon_0=10.5666 +lat_ts=56'.
    forward = stereographic(56, 10.5666)
    x, y = forward(10.0364, 56.4607)
    assert abs(x - -32687.148) < 0.01 and abs(y - 51423.486) < 0.01


def test_parse_composite_finds_rain_at_location() -> None:
    sample = parse_composite(RADAR_H5, LAT, LON, nearby_km=5, search_km=30, min_dbz=7, nearest_rain_mm_h=0.5)
    assert sample.covered
    assert sample.time == datetime(2026, 10, 8, 17, 55, 1, tzinfo=timezone.utc)
    assert 0.5 < sample.rate_mm_h < 1.5
    assert sample.dbz == 23.0
    assert sample.max_nearby_mm_h > sample.rate_mm_h
    assert sample.nearest_rain_km == 0.0


def test_parse_composite_outside_grid() -> None:
    sample = parse_composite(RADAR_H5, 70.0, 40.0, nearby_km=5, search_km=30, min_dbz=7, nearest_rain_mm_h=0.5)
    assert not sample.covered and sample.rate_mm_h is None


async def test_radar_overrides_clear_model(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock)
    await _setup(hass)

    weather = hass.states.get("weather.dmi_vejr")
    assert weather.state == "rainy"  # model says WMO 0 / clear-night
    assert float(hass.states.get("sensor.dmi_vejr_nedbor_lige_nu").state) > 0.5
    assert hass.states.get("binary_sensor.dmi_vejr_regner_nu").state == "on"
    assert float(hass.states.get("sensor.dmi_vejr_afstand_til_naermeste_regn").state) == 0.0
    # Measured at the nearest station (Hald Vest, latest reading) instead of the model.
    assert weather.attributes["temperature"] == 9.3
    temp = hass.states.get("sensor.dmi_vejr_temperatur")
    assert float(temp.state) == 9.3
    assert temp.attributes["station"] == "Hald Vest"
    assert temp.attributes["afstand_km"] < 20
    assert hass.states.get("sensor.dmi_vejr_vindhastighed").attributes["unit_of_measurement"] == "m/s"

    hourly = await hass.services.async_call(
        "weather", "get_forecasts", {"entity_id": "weather.dmi_vejr", "type": "hourly"},
        blocking=True, return_response=True,
    )
    first = hourly["weather.dmi_vejr"]["forecast"][0]
    assert first["condition"] == "rainy"
    assert first["precipitation"] >= 0.5
    assert len(hourly["weather.dmi_vejr"]["forecast"]) == 48
    assert all("precipitation_probability" in f for f in hourly["weather.dmi_vejr"]["forecast"])

    daily = await hass.services.async_call(
        "weather", "get_forecasts", {"entity_id": "weather.dmi_vejr", "type": "daily"},
        blocking=True, return_response=True,
    )
    assert len(daily["weather.dmi_vejr"]["forecast"]) == 7


async def test_uv_and_daily_humidity(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock)
    await _setup(hass)

    weather = hass.states.get("weather.dmi_vejr")
    assert weather.attributes["uv_index"] == 0.0
    assert weather.attributes["dew_point"] == 9.3  # measured; the model says 6.3
    daily = await hass.services.async_call(
        "weather", "get_forecasts", {"entity_id": "weather.dmi_vejr", "type": "daily"},
        blocking=True, return_response=True,
    )
    today = daily["weather.dmi_vejr"]["forecast"][0]
    assert today["humidity"] == 91 and today["uv_index"] == 2.2
    hourly = await hass.services.async_call(
        "weather", "get_forecasts", {"entity_id": "weather.dmi_vejr", "type": "hourly"},
        blocking=True, return_response=True,
    )
    assert hourly["weather.dmi_vejr"]["forecast"][0]["uv_index"] == 1.5


async def test_uv_outage_keeps_forecast(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(UV_URL, status=503)
    _mock_apis(aioclient_mock)
    await _setup(hass)

    weather = hass.states.get("weather.dmi_vejr")
    assert weather.state == "rainy"
    assert "uv_index" not in weather.attributes


async def test_dry_radar_removes_model_rain(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    forecast = json.loads(json.dumps(FORECAST))
    forecast["current"]["weather_code"] = 61  # model: rain
    # Same file, but sampled where the radar is dry (Copenhagen is 5.6 km from rain).
    _mock_apis(aioclient_mock, forecast=forecast)
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    entry = MockConfigEntry(domain=DOMAIN, data={"latitude": 55.68, "longitude": 12.57})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.dmi_vejr_regner_nu").state == "off"
    assert hass.states.get("weather.dmi_vejr").state == "cloudy"


async def test_stale_radar_falls_back_to_model(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(datetime(2026, 10, 8, 19, 0, tzinfo=timezone.utc))  # 65 min after scan
    _mock_apis(aioclient_mock)
    await _setup(hass)
    assert hass.states.get("sensor.dmi_vejr_nedbor_lige_nu").state == "unavailable"
    assert hass.states.get("binary_sensor.dmi_vejr_regner_nu").state == "unavailable"
    assert hass.states.get("weather.dmi_vejr").state == "clear-night"
    assert hass.states.get("sensor.dmi_vejr_radartidspunkt").state != "unavailable"


async def test_radar_outage_does_not_block_setup_forever(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/.*"), status=503)
    aioclient_mock.get(re.compile(r"https://feeds\.meteoalarm\.org/.*"), status=503)
    aioclient_mock.get(re.compile(re.escape(FORECAST_URL) + ".*"), json=FORECAST)
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    entry = MockConfigEntry(domain=DOMAIN, data={"latitude": LAT, "longitude": LON})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state.name == "SETUP_RETRY"


NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"


async def test_config_flow_defaults_to_home(hass: HomeAssistant, aioclient_mock) -> None:
    hass.config.latitude, hass.config.longitude = LAT, LON
    aioclient_mock.get(NOMINATIM_REVERSE, json={"address": {"municipality": "Randers Kommune"}})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location": {"latitude": LAT, "longitude": LON}, "municipality": "auto", "warning_area": "auto"},
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "DMI Vejr"
    assert result["data"] == {
        "latitude": LAT, "longitude": LON, "municipality": "0730", "warning_area": "DK004", "address": None,
    }


async def test_config_flow_finds_an_address(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(NOMINATIM_SEARCH, json=[{
        "lat": "55.39591", "lon": "10.38831", "display_name": "Flakhaven 2, Odense",
        "address": {"municipality": "Odense Kommune"},
    }])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"address": "Flakhaven 2, Odense", "location": {"latitude": LAT, "longitude": LON},
         "municipality": "auto", "warning_area": "auto"},
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Flakhaven 2, Odense"
    assert result["data"] == {
        "latitude": 55.39591, "longitude": 10.38831, "municipality": "0461", "warning_area": "DK006",
        "address": "Flakhaven 2, Odense",
    }


async def test_config_flow_address_not_found(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(NOMINATIM_SEARCH, json=[])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"address": "Findes ikke 99", "location": {"latitude": LAT, "longitude": LON},
         "municipality": "auto", "warning_area": "auto"},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"address": "address_not_found"}


async def test_config_flow_rejects_places_outside_denmark(hass: HomeAssistant, aioclient_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location": {"latitude": 52.52, "longitude": 13.40}, "municipality": "auto", "warning_area": "auto"},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "outside_denmark"}


async def test_config_flow_without_openstreetmap_uses_nearest_municipality(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(NOMINATIM_REVERSE, status=503)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location": {"latitude": 57.05, "longitude": 9.92}, "municipality": "auto", "warning_area": "DK002"},
    )
    assert result["type"] == "create_entry"
    assert result["data"]["municipality"] == "0851"  # Aalborg
    assert result["data"]["warning_area"] == "DK002"  # chosen by hand


async def test_options_move_the_integration(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock)
    entry = await _setup(hass)
    aioclient_mock.get(NOMINATIM_SEARCH, json=[{
        "lat": "55.67590", "lon": "12.56840", "address": {"municipality": "Københavns Kommune"},
    }])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"address": "Rådhuspladsen 1, København", "location": {"latitude": LAT, "longitude": LON},
         "municipality": "auto", "warning_area": "auto"},
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.title == "Rådhuspladsen 1, København"
    assert entry.options["municipality"] == "0101"
    assert entry.options["warning_area"] == "DK008"
    assert entry.state.name == "LOADED"
    assert entry.runtime_data.climate.municipality == "0101"
    assert entry.runtime_data.warnings.area == "DK008"


async def test_radar_map_is_an_animated_gif(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory, hass_client) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock)
    await _setup(hass)
    state = hass.states.get("image.dmi_vejr_radarkort")
    assert state is not None and state.state != "unavailable"
    client = await hass_client()
    token = state.attributes["access_token"]
    resp = await client.get(f"/api/image_proxy/image.dmi_vejr_radarkort?token={token}")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/gif"
    body = await resp.read()
    assert body[:6] == b"GIF89a" and len(body) > 5000


async def test_lightning_counts_only_nearby_strikes(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock)
    await _setup(hass)
    assert hass.states.get("sensor.dmi_vejr_lyn_sidste_30_min").state == "1"
    distance = float(hass.states.get("sensor.dmi_vejr_lyn_naermeste_afstand").state)
    assert 9 < distance < 15
    bearing = float(hass.states.get("sensor.dmi_vejr_lyn_retning").state)
    assert 20 < bearing < 70


async def test_stale_station_values_fall_back_to_model(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    old = _every_parameter([_station("06049", "Hald Vest", 10.0929, 56.5604, 9.3, "2026-10-08T16:00:00Z")])
    _mock_apis(aioclient_mock, observations=old)
    await _setup(hass)
    assert hass.states.get("sensor.dmi_vejr_temperatur").state == "unavailable"
    assert hass.states.get("weather.dmi_vejr").attributes["temperature"] == FORECAST["current"]["temperature_2m"]


async def test_station_outage_does_not_block_setup(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/radardata/collections/.*"), json=LISTING)
    aioclient_mock.get(RADAR_HREF, content=RADAR_H5)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v2/.*"), status=503)
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/forecastedr/.*"), status=429)
    aioclient_mock.get(re.compile(r"https://feeds\.meteoalarm\.org/.*"), status=503)
    aioclient_mock.get(re.compile(re.escape(FORECAST_URL) + ".*"), json=FORECAST)
    entry = await _setup(hass)
    assert entry.state.name == "LOADED"
    assert hass.states.get("sensor.dmi_vejr_temperatur").state == "unavailable"
    assert hass.states.get("weather.dmi_vejr").state == "rainy"


def _pixel(gif: bytes, x: int, y: int) -> tuple[int, int, int]:
    import io
    from PIL import Image

    return Image.open(io.BytesIO(gif)).convert("RGB").getpixel((x, y))


def test_radar_map_draws_lightning() -> None:
    rw = read_window(RADAR_H5, LAT, LON, half_km=65, min_dbz=7)
    frames = [RadarFrame(rw.time, rw.rate)]
    row, col = rw.project(56.54, 10.16)  # a strike 12 km north-east of the location
    x, y = int((col - rw.window.c0 + 0.5) * 3), int((row - rw.window.r0 + 0.5) * 3)
    plain = render_frames(frames, rw.window, rw.project)
    # The Copenhagen strike is off the map and must not break anything.
    gif = render_frames(
        frames, rw.window, rw.project,
        strikes=[(56.54, 10.16, 3.0), (55.68, 12.57, 3.0)],
    )
    red, green, blue = _pixel(gif, x, y)
    assert red > 200 and green > 180 and blue < 90  # yellow bolt
    assert _pixel(plain, x, y) != (red, green, blue)


async def test_all_extra_dmi_data(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)  # 20:10 local, 8 October
    _mock_apis(aioclient_mock)
    await _setup(hass)

    def state(entity_id):
        st = hass.states.get(entity_id)
        assert st is not None, entity_id
        return st

    # More station values (nearest station measuring each).
    assert float(state("sensor.dmi_vejr_dugpunkt").state) == 9.3
    assert float(state("sensor.dmi_vejr_hojeste_temperatur_sidste_12_timer").state) == 9.3
    assert state("sensor.dmi_vejr_graestemperatur").attributes["station"] == "Hald Vest"
    assert state("sensor.dmi_vejr_observeret_vejr").state == "Ingen væsentligt vejr"
    assert state("weather.dmi_vejr").attributes["dew_point"] == 9.3
    # Climate data: today so far, yesterday, this month.
    precip = state("sensor.dmi_vejr_nedbor_i_dag")
    assert float(precip.state) == 4.6 and precip.attributes["i_går"] == 1.3
    assert float(state("sensor.dmi_vejr_graddage_denne_maned").state) == 15.8  # 5.7 + 6.1 + 4.0
    assert state("sensor.dmi_vejr_torkeindeks").state == "unavailable"  # not in this data
    # Harbour and tide.
    level = state("sensor.dmi_vejr_vandstand_havn")
    assert float(level.state) == 12.0 and level.attributes["station"] == "Randers Havn I"
    high = state("sensor.dmi_vejr_naeste_hojvande")
    assert high.state == "2026-10-08T21:00:00+00:00" and high.attributes["niveau_cm"] == 14
    assert state("sensor.dmi_vejr_naeste_lavvande").state == "2026-10-08T18:40:00+00:00"
    # Warnings: only the yellow East Jutland one; green, other areas and expired are ignored.
    warnings = state("sensor.dmi_vejr_varsler")
    assert warnings.state == "1"
    assert warnings.attributes["varsler"][0]["farve"] == "Gul"
    assert warnings.attributes["varsler"][0]["type"] == "Regn"
    assert state("binary_sensor.dmi_vejr_varsel_aktivt").state == "on"
    # DMI forecast API: ensemble probabilities and lightning.
    frost = state("sensor.dmi_vejr_frostrisiko_naeste_dogn")
    assert float(frost.state) == 55 and frost.attributes["næste_6_timer"] == 0
    assert float(state("sensor.dmi_vejr_lynrisiko_naeste_dogn").state) == 12.0
    assert state("sensor.dmi_vejr_nedborstype_prognose").state == "Regn"


async def test_busy_dmi_forecast_api_does_not_break_setup(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock, edr_status=429)
    entry = await _setup(hass)
    assert entry.state.name == "LOADED"
    assert hass.states.get("sensor.dmi_vejr_frostrisiko_naeste_dogn").state == "unavailable"
    assert hass.states.get("weather.dmi_vejr").state == "rainy"


async def test_busy_forecast_api_retries_soon_until_first_data(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock, edr_status=429)
    entry = await _setup(hass)
    edr = entry.runtime_data.edr
    assert edr.update_interval == EDR_RETRY_INTERVAL
    # DMI answers again: the risks appear and the normal hourly pace returns.
    aioclient_mock.clear_requests()
    _mock_apis(aioclient_mock)
    await edr.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.dmi_vejr_lynrisiko_naeste_dogn").state) == 12.0
    assert edr.update_interval == EDR_INTERVAL


async def test_missing_ensemble_half_retries_soon(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    # Only the ensemble endpoint is busy; lightning arrives.
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/v1/forecastedr/collections/harmonie_dini_eps_probabilities/.*"), status=429)
    _mock_apis(aioclient_mock)
    entry = await _setup(hass)
    edr = entry.runtime_data.edr
    assert float(hass.states.get("sensor.dmi_vejr_lynrisiko_naeste_dogn").state) == 12.0
    assert hass.states.get("sensor.dmi_vejr_frostrisiko_naeste_dogn").state == "unavailable"
    assert edr.update_interval == EDR_RETRY_INTERVAL
    aioclient_mock.clear_requests()
    _mock_apis(aioclient_mock)
    await edr.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.dmi_vejr_frostrisiko_naeste_dogn").state) == 55
    assert edr.update_interval == EDR_INTERVAL


def test_weather_codes() -> None:
    from custom_components.dmi_vejr.extras import weather_text

    assert weather_text(161) == "Let regn"
    assert weather_text(195) == "Kraftig torden med byger"
    assert weather_text(102) == "Ingen væsentligt vejr"
    assert weather_text(None) is None


async def test_one_station_request_and_last_values_kept(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock)
    entry = await _setup(hass)
    station_calls = [c for c in aioclient_mock.mock_calls if "metObs/collections/observation" in str(c[1])]
    # One combined request plus the four slow ones, not one per parameter.
    assert len(station_calls) == 5
    # DMI busy: the last values stay (they age out by themselves).
    aioclient_mock.clear_requests()
    aioclient_mock.get(re.compile(r"https://opendataapi\.dmi\.dk/.*"), status=429)
    aioclient_mock.get(re.compile(r"https://feeds\.meteoalarm\.org/.*"), status=429)
    aioclient_mock.get(re.compile(r"https://api\.open-meteo\.com/.*"), status=429)
    await entry.runtime_data.observations.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.dmi_vejr_temperatur").state) == 9.3


async def test_measured_sky_and_fog_override_the_model(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    # Copenhagen: the radar is dry there; a DMI station nearby reports overcast.
    obs = _every_parameter([_station("06180", "Lufthavn", 12.65, 55.61, 100.0)])
    _mock_apis(aioclient_mock, observations=obs)
    await hass.config.async_set_time_zone("Europe/Copenhagen")
    entry = MockConfigEntry(domain=DOMAIN, data={"latitude": 55.68, "longitude": 12.57})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    weather = hass.states.get("weather.dmi_vejr")
    assert weather.state == "cloudy"  # model: clear night (WMO 0)
    assert weather.attributes["cloud_coverage"] == 100


def test_newest_station_wins_over_a_stale_nearer_one() -> None:
    from custom_components.dmi_vejr.observations import nearest_observation

    features = [
        _station("06049", "Hald Vest", 10.0929, 56.5604, 14.0, "2026-10-08T09:00:00Z", "temp_max_past12h"),
        _station("06072", "Ødum", 10.1272, 56.3027, 13.5, "2026-10-08T18:00:00Z", "temp_max_past12h"),
    ]
    obs = nearest_observation(features, LAT, LON, {}, 45)
    assert obs.station_id == "06072" and obs.value == 13.5


def test_satellite_geometry_and_times():
    from datetime import datetime, timezone

    from custom_components.dmi_vejr import satellite as sat

    caps = '<Layer><Dimension name="time" default="x" units="ISO8601">2024-09-23T00:00:00.000Z/2026-10-10T17:00:00.000Z/PT10M</Dimension></Layer>'
    latest = sat.latest_time(caps)
    assert latest == datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc)
    times = sat.frame_times(latest, 12)
    assert len(times) == 12 and times[0] == datetime(2026, 10, 10, 15, 10, tzinfo=timezone.utc) and times[-1] == latest
    assert sat.latest_time("<nothing/>") is None
    view = sat.SatView(56.4607, 10.0364, 300, 783)
    cx, cy = view.pixel(56.4607, 10.0364)
    assert abs(cx - 391.5) < 0.5 and abs(cy - 391.5) < 0.5
    # Copenhagen lies about 165 km east and 80 km south of the middle.
    kx, ky = view.pixel(55.6761, 12.5683)
    assert 590 < kx < 625 and 480 < ky < 510
    params = view.params(sat.LAYER, "image/jpeg", latest)
    assert params["crs"] == "EPSG:3857" and params["time"] == "2026-10-10T17:00:00Z" and "transparent" not in params


def test_satellite_render_is_animated_webp():
    import io
    from datetime import datetime

    from PIL import Image

    from custom_components.dmi_vejr import satellite as sat

    def jpeg(colour):
        out = io.BytesIO()
        Image.new("RGB", (64, 64), colour).save(out, format="JPEG")
        return out.getvalue()

    view = sat.SatView(56.4607, 10.0364, 300, 200)
    frames = [(datetime(2026, 10, 10, 18, m), jpeg((m * 4, 80, 120))) for m in (0, 10, 20)]
    data = sat.render_frames(frames, None, view)
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "WEBP" and img.n_frames == 3 and img.size == (200, 200)


async def test_everything_else_dmi_offers(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    _mock_apis(aioclient_mock)
    await _setup(hass)

    def state(entity_id):
        st = hass.states.get(entity_id)
        assert st is not None, entity_id
        return st

    # Every other station value DMI reports comes from the same request.
    assert float(state("sensor.dmi_vejr_middeltemperatur_sidste_time").state) == 9.3
    assert float(state("sensor.dmi_vejr_laveste_vind_sidste_time").state) == 9.3
    assert state("sensor.dmi_vejr_snedaekke").state == "9.3"
    # Climate data: more day values and the month so far.
    assert float(state("sensor.dmi_vejr_nedbor_denne_maned").state) == 5.9
    assert float(state("sensor.dmi_vejr_middeltemperatur_denne_maned").state) == 10.5
    assert float(state("sensor.dmi_vejr_frostdage_denne_maned").state) == 1
    assert float(state("sensor.dmi_vejr_bladfugt_seneste_dogn").state) == 23  # 1380 min shown in hours
    # Ensemble probabilities, fog among them.
    assert float(state("sensor.dmi_vejr_tagerisiko_naeste_dogn").state) == 30
    assert state("sensor.dmi_vejr_risiko_for_orkanstod_naeste_dogn").state == "unavailable"  # not in this data
    # Ensemble percentiles: the spread of the next day, temperature in °C.
    low = state("sensor.dmi_vejr_laveste_temperatur_naeste_dogn_ensemble_10")
    assert float(low.state) == 2.0 and low.attributes["median"] == 6.0
    assert low.attributes["timer"][0] == {"t": "2026-10-08T18:00:00+00:00", "p10": 2.0, "p50": 6.0, "p90": 11.0}
    assert float(state("sensor.dmi_vejr_hojeste_temperatur_naeste_dogn_ensemble_90").state) == 11.0
    assert float(state("sensor.dmi_vejr_kraftigste_vindstod_naeste_dogn_ensemble_90").state) == 15.5
    rain = state("sensor.dmi_vejr_nedbor_naeste_dogn_ensemble_median")
    assert float(rain.state) == 2.5 and rain.attributes["op_til_90_procent"] == 12.5  # 25 hours
    # HARMONIE DINI series: cloud base, freezing level, thunder energy, sun.
    assert float(state("sensor.dmi_vejr_skybase_prognose").state) == 850
    assert float(state("sensor.dmi_vejr_nulgradsgraense_hojde").state) == 1200
    cape = state("sensor.dmi_vejr_tordenenergi_cape")
    assert cape.attributes["højeste_næste_døgn"] == 250
    assert float(state("sensor.dmi_vejr_solenergi_naeste_dogn").state) == 2.5
    # DKSS storm surge: the water level ahead at the harbour, with the tide table beside it.
    surge = state("sensor.dmi_vejr_vandstand_prognose")
    assert float(surge.state) == 20  # 18:00Z, the hour containing now
    assert surge.attributes["højeste_næste_48_timer"] == 62.0
    assert surge.attributes["timer"][0] == {"t": "2026-10-08T18:00:00+00:00", "cm": 20, "tidevand": -6}
