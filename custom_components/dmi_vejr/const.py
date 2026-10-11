"""Constants for DMI Vejr."""

from datetime import timedelta

DOMAIN = "dmi_vejr"
NAME = "DMI Vejr"

CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_MUNICIPALITY = "municipality"
CONF_WARNING_AREA = "warning_area"
DEFAULT_MUNICIPALITY = "0730"  # Randers Kommune (DMI climateData municipalityId)
DEFAULT_WARNING_AREA = "DK004"  # Østjylland (MeteoAlarm EMMA_ID used by DMI)

# DMI open data, no API key: radar composite (500 m grid, every 5 minutes).
RADAR_LIST_URL = (
    "https://opendataapi.dmi.dk/v1/radardata/collections/composite/items"
    "?limit=1&sortorder=datetime,DESC"
)
# DMI HARMONIE DINI (2 km) as packaged by Open-Meteo; ECMWF beyond ~2.5 days.
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_MODEL = "dmi_seamless"

RADAR_FRAMES_URL = (
    "https://opendataapi.dmi.dk/v1/radardata/collections/composite/items"
    "?limit={n}&sortorder=datetime,DESC"
)
# Measured values from DMI stations (metObs) and DMI lightning detection.
OBS_URL = "https://opendataapi.dmi.dk/v2/metObs/collections/observation/items"
STATION_URL = "https://opendataapi.dmi.dk/v2/metObs/collections/station/items"
LIGHTNING_URL = "https://opendataapi.dmi.dk/v2/lightningdata/collections/observation/items"

# metObs parameter -> key used by the integration. Each key takes the nearest
# station that measures it (not every station measures everything).
OBS_PARAMETERS = {
    "temp_dry": "temperature",
    "humidity": "humidity",
    "wind_speed": "wind_speed",
    "wind_dir": "wind_bearing",
    "wind_max": "wind_gust",
    "pressure_at_sea": "pressure",
    "precip_past10min": "precip_10min",
    "precip_past1h": "precip_1h",
    "temp_dew": "dew_point",
    "temp_grass": "temp_grass",
    "temp_soil": "temp_soil",
    "radia_glob": "radiation",
    "sun_last1h_glob": "sunshine_1h",
    "visibility": "visibility",
    "cloud_cover": "cloud_cover",
    "weather": "weather_code",
    "precip_dur_past1h": "precip_duration_1h",
    "wind_gust_always_past1h": "wind_gust_1h",
}
OBS_SEARCH_KM = 45.0
OBS_LOOKBACK = timedelta(minutes=90)
OBS_MAX_AGE = timedelta(minutes=80)
OBS_12H_MAX_AGE = timedelta(hours=13)
OBS_DAILY_MAX_AGE = timedelta(hours=30)
# Reported less often, fetched one by one with a longer look-back:
# 12-hour extremes at 06 and 18 UTC, manual snow depth daily at 06 UTC.
OBS_SLOW_PARAMETERS = {
    "temp_max_past12h": ("temp_max_12h", OBS_12H_MAX_AGE),
    "temp_min_past12h": ("temp_min_12h", OBS_12H_MAX_AGE),
    "snow_depth_man": ("snow_depth", OBS_DAILY_MAX_AGE),
}
OBS_INTERVAL = timedelta(minutes=10)

# DMI climate data: day values for the municipality (computed after the day).
CLIMATE_URL = "https://opendataapi.dmi.dk/v2/climateData/collections/municipalityValue/items"
CLIMATE_PARAMETERS = (
    "mean_temp", "max_temp_w_date", "min_temp", "acc_precip", "bright_sunshine",
    "acc_heating_degree_days_17", "mean_wind_speed", "max_wind_speed_3sec",
    "mean_relative_hum", "drought_index", "pot_evaporation_makkink",
    "no_lightning_strikes", "temp_soil_30", "temp_grass", "snow_depth",
)
CLIMATE_INTERVAL = timedelta(hours=2)

# DMI ocean observations and tide predictions (nearest harbour).
OCEAN_OBS_URL = "https://opendataapi.dmi.dk/v2/oceanObs/collections/observation/items"
OCEAN_STATION_URL = "https://opendataapi.dmi.dk/v2/oceanObs/collections/station/items"
TIDE_URL = "https://opendataapi.dmi.dk/v2/oceanObs/collections/tidewater/items"
TIDE_STATION_URL = "https://opendataapi.dmi.dk/v2/oceanObs/collections/tidewaterstation/items"
OCEAN_PARAMETERS = {"sealev_dvr": "water_level", "tw": "water_temperature"}
OCEAN_SEARCH_KM = 30.0
OCEAN_INTERVAL = timedelta(minutes=10)
TIDE_HOURS = 36

# DMI weather warnings, published by DMI through MeteoAlarm (CAP).
WARNINGS_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-denmark"
WARNINGS_INTERVAL = timedelta(minutes=10)

# DMI's own forecast API (EDR): HARMONIE DINI and its ensemble (EPS).
EDR_URL = "https://opendataapi.dmi.dk/v1/forecastedr/collections/{collection}/position"
EDR_PROBABILITIES = {
    "temperature-2m-below-273k-probability": "frost",
    "total-precipitation-above-10mm-in-3hours-probability": "heavy_rain",
    "total-precipitation-above-30mm-in-3hours-probability": "cloudburst",
    "gust-wind-speed-10m-above-25ms-within-1hour-probability": "storm_gust",
}
EDR_SF = {"probability-of-lightning": "lightning", "precipitation-type": "precip_type"}
EDR_HOURS = 24
EDR_INTERVAL = timedelta(minutes=60)
# Until the first forecast arrives, don't wait a full hour after a busy API.
EDR_RETRY_INTERVAL = timedelta(minutes=10)

LIGHTNING_RADIUS_KM = 100.0
LIGHTNING_WINDOW = timedelta(minutes=30)
LIGHTNING_INTERVAL = timedelta(minutes=5)

MAP_HALF_KM = 65.0
MAP_FRAMES = 12  # one hour at 5-minute steps

# Satellite map (EUMETSAT MTG GeoColour, a new picture every 10 minutes, published
# ~30 minutes after the scan): two hours, 600 x 600 km around the home.
SAT_INTERVAL = timedelta(minutes=10)
SAT_FRAMES = 12
SAT_HALF_KM = 300.0
SAT_SIZE = 783

RADAR_INTERVAL = timedelta(minutes=5)
FORECAST_INTERVAL = timedelta(minutes=30)
# Radar is published 10-15 minutes after scan time; older than this is stale.
RADAR_MAX_AGE = timedelta(minutes=35)

# Below ~7 dBZ (0.1 mm/h) the composite is mostly noise.
MIN_DBZ = 7.0
RAIN_NOW_MM_H = 0.2
POURING_MM_H = 4.0
NEARBY_RADIUS_KM = 5.0
SEARCH_RADIUS_KM = 30.0
NEAREST_RAIN_MM_H = 0.5
HOURLY_FORECAST_HOURS = 48

ATTRIBUTION = "Data: DMI (radar, stationer, lyn, klima, hav, varsler, HARMONIE); UV: Open-Meteo"
SAT_ATTRIBUTION = "Satellit: EUMETSAT (MTG GeoColour); kyster: Natural Earth"
