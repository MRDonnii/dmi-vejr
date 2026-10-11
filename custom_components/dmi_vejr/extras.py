"""Pure parsers for DMI climate data, ocean data, warnings and EDR forecasts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

# WMO code table 4680 (present weather from an automatic station). DMI's metObs
# parameter "weather" reports 100 + the code.
_WEATHER_4680 = {
    0: "Ingen væsentligt vejr",
    4: "Dis eller røg", 5: "Dis eller røg, sigt under 1 km",
    10: "Diset", 11: "Diamantstøv", 12: "Lyn i det fjerne", 18: "Byger",
    20: "Tåge inden for den seneste time", 21: "Nedbør inden for den seneste time",
    22: "Støvregn inden for den seneste time", 23: "Regn inden for den seneste time",
    24: "Sne inden for den seneste time", 25: "Isslag inden for den seneste time",
    26: "Torden inden for den seneste time", 27: "Fygning", 28: "Fygning", 29: "Kraftig fygning",
    30: "Tåge", 31: "Tåge i banker", 32: "Tåge, aftagende", 33: "Tåge",
    34: "Tåge, tiltagende", 35: "Tåge med rimdannelse",
    40: "Nedbør", 41: "Let nedbør", 42: "Kraftig nedbør", 43: "Let regn",
    44: "Kraftig regn", 45: "Let sne", 46: "Kraftig sne", 47: "Let isslag", 48: "Kraftigt isslag",
    50: "Støvregn", 51: "Let støvregn", 52: "Støvregn", 53: "Kraftig støvregn",
    54: "Let underafkølet støvregn", 55: "Underafkølet støvregn",
    56: "Kraftig underafkølet støvregn", 57: "Let støvregn og regn", 58: "Støvregn og regn",
    60: "Regn", 61: "Let regn", 62: "Regn", 63: "Kraftig regn", 64: "Let isslag",
    65: "Isslag", 66: "Kraftigt isslag", 67: "Let slud", 68: "Slud",
    70: "Sne", 71: "Let sne", 72: "Sne", 73: "Kraftig sne", 74: "Lette iskorn",
    75: "Iskorn", 76: "Kraftige iskorn", 77: "Snekorn", 78: "Iskrystaller",
    80: "Byger", 81: "Lette regnbyger", 82: "Regnbyger", 83: "Kraftige regnbyger",
    84: "Voldsomme regnbyger", 85: "Lette snebyger", 86: "Snebyger", 87: "Kraftige snebyger",
    89: "Hagl", 90: "Torden", 91: "Torden uden nedbør", 92: "Torden med byger",
    93: "Torden med hagl", 94: "Kraftig torden uden nedbør", 95: "Kraftig torden med byger",
    96: "Kraftig torden med hagl", 99: "Tornado",
}

# precipitation-type in HARMONIE DINI.
PRECIP_TYPES = {
    0: "Støvregn", 1: "Regn", 2: "Slud", 3: "Sne",
    4: "Underafkølet støvregn", 5: "Isslag", 6: "Kornsne", 7: "Hagl",
}

WARNING_LEVELS = {2: "Gul", 3: "Orange", 4: "Rød"}


def weather_text(value: float | None) -> str | None:
    """Danish text for DMI's observed present-weather code."""
    if value is None:
        return None
    code = int(value)
    if code >= 100:
        code -= 100
    if 1 <= code <= 3:
        code = 0  # cloud development only
    return _WEATHER_4680.get(code) or _WEATHER_4680.get(code // 10 * 10)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------- climate data


def parse_climate(features: list[dict[str, Any]], tz: tzinfo) -> dict[date, dict[str, float]]:
    """Day values per local date: {date: {parameterId: value}}."""
    out: dict[date, dict[str, float]] = {}
    for feature in features:
        props = feature.get("properties") or {}
        param, value, start = props.get("parameterId"), props.get("value"), props.get("from")
        if param is None or value is None or not start:
            continue
        day = _parse_time(start).astimezone(tz).date()
        out.setdefault(day, {})[param] = value
    return out


def month_sum(days: dict[date, dict[str, float]], param: str, today: date) -> float | None:
    values = [
        v[param] for d, v in days.items()
        if d.year == today.year and d.month == today.month and d <= today and param in v
    ]
    return round(sum(values), 1) if values else None


# ---------------------------------------------------------------- tide


@dataclass(frozen=True)
class TideExtreme:
    time: datetime
    level_cm: float


@dataclass(frozen=True)
class Tide:
    station_id: str
    station_name: str | None
    next_high: TideExtreme | None
    next_low: TideExtreme | None
    now_cm: float | None


def tide_extremes(
    features: list[dict[str, Any]], now: datetime, station_id: str, station_name: str | None
) -> Tide:
    """Next high and low water from DMI's tide prediction series."""
    series = sorted(
        (_parse_time(f["properties"]["predictionTime"]), f["properties"]["value"])
        for f in features
        if (f.get("properties") or {}).get("value") is not None
    )
    high = low = None
    now_cm = None
    for i, (when, level) in enumerate(series):
        if now_cm is None and when >= now:
            now_cm = level
        if when <= now or i == 0 or i == len(series) - 1:
            continue
        before, after = series[i - 1][1], series[i + 1][1]
        if high is None and level > before and level >= after:
            high = TideExtreme(when, level)
        if low is None and level < before and level <= after:
            low = TideExtreme(when, level)
    return Tide(station_id, station_name, high, low, now_cm)


# ---------------------------------------------------------------- warnings


@dataclass(frozen=True)
class DmiWarning:
    identifier: str
    event: str
    headline: str | None
    description: str | None
    level: int
    colour: str
    onset: datetime
    expires: datetime
    area: str

    @property
    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.event,
            "overskrift": self.headline,
            "beskrivelse": self.description,
            "niveau": self.level,
            "farve": self.colour,
            "start": self.onset.isoformat(),
            "slut": self.expires.isoformat(),
            "område": self.area,
        }


@dataclass(frozen=True)
class Warnings:
    area: str
    items: tuple[DmiWarning, ...] = field(default_factory=tuple)

    def active(self, now: datetime) -> list[DmiWarning]:
        return [w for w in self.items if w.onset <= now < w.expires]

    def highest_level(self, now: datetime | None = None) -> int:
        items = self.active(now) if now else self.items
        return max((w.level for w in items), default=0)


def _awareness(info: dict[str, Any]) -> tuple[int, str]:
    for param in info.get("parameter") or []:
        if param.get("valueName") == "awareness_level":
            parts = [p.strip() for p in str(param.get("value", "")).split(";")]
            try:
                level = int(parts[0])
            except ValueError:
                return 0, ""
            return level, parts[1] if len(parts) > 1 else ""
    return 0, ""


def parse_warnings(feed: dict[str, Any], area: str, now: datetime) -> Warnings:
    """DMI warnings (yellow or higher) for one EMMA area that have not expired.

    DMI also publishes standing "no warnings" messages (green, level 1) tagged
    with every area, so filtering on the area alone is not enough.
    """
    alerts = [entry.get("alert") or {} for entry in feed.get("warnings") or []]
    # An update names the versions it replaces: "sender,identifier,sent ...".
    replaced = {
        ref.split(",")[1]
        for alert in alerts
        for ref in str(alert.get("references") or "").split()
        if ref.count(",") >= 2
    }
    found: dict[str, DmiWarning] = {}
    for alert in alerts:
        if alert.get("msgType") == "Cancel" or alert.get("identifier") in replaced:
            continue
        for info in alert.get("info") or []:
            if not str(info.get("language", "")).startswith("da"):
                continue
            level, colour = _awareness(info)
            if level < 2:
                continue
            areas = [
                a for a in info.get("area") or []
                if any(g.get("value") == area for g in a.get("geocode") or [])
            ]
            if not areas:
                continue
            try:
                onset = _parse_time(info.get("onset") or info.get("effective"))
                expires = _parse_time(info["expires"])
            except (KeyError, TypeError, ValueError):
                continue
            if expires <= now:
                continue
            identifier = alert.get("identifier") or f"{info.get('event')}-{onset.isoformat()}"
            found[identifier] = DmiWarning(
                identifier=identifier,
                event=str(info.get("event", "")).removeprefix("Moderate ").removeprefix("Severe ").removeprefix("Extreme "),
                headline=info.get("headline"),
                description=info.get("description"),
                level=level,
                colour=WARNING_LEVELS.get(level, colour),
                onset=onset,
                expires=expires,
                area=areas[0].get("areaDesc", area),
            )
    return Warnings(area, tuple(sorted(found.values(), key=lambda w: (w.onset, -w.level))))


# ---------------------------------------------------------------- EDR forecast


@dataclass(frozen=True)
class Peak:
    value: float | None
    time: datetime | None


def coverage_series(data: dict[str, Any], param: str) -> list[tuple[datetime, float | None]]:
    """(time, value) pairs from a CoverageJSON point response."""
    try:
        times = data["domain"]["axes"]["t"]["values"]
        values = data["ranges"][param]["values"]
    except (KeyError, TypeError):
        return []
    return [(_parse_time(t), v) for t, v in zip(times, values)]


def as_percent(series: list[tuple[datetime, float | None]]) -> list[tuple[datetime, float | None]]:
    """EPS probabilities come as 0..1 or 0..100; members make nonzero percent >= ~2."""
    values = [v for _, v in series if v is not None]
    factor = 100.0 if values and max(values) <= 1.0 else 1.0
    return [(t, None if v is None else round(v * factor, 1)) for t, v in series]


def peak(
    series: list[tuple[datetime, float | None]], start: datetime, hours: int
) -> Peak:
    end = start + timedelta(hours=hours)
    window = [(t, v) for t, v in series if start - timedelta(hours=1) < t <= end and v is not None]
    if not window:
        return Peak(None, None)
    when, value = max(window, key=lambda tv: tv[1])
    return Peak(value, when)


def current(series: list[tuple[datetime, float | None]], now: datetime) -> float | None:
    """Value for the forecast hour containing now (or the next one)."""
    upcoming = [(t, v) for t, v in series if t > now - timedelta(hours=1)]
    return upcoming[0][1] if upcoming else None
