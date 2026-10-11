"""Places for DMI Vejr: municipalities, warning regions and towns for the maps.

The municipality numbers and centre points are DMI's own (climateData
municipalityValue). Each municipality is given the DMI warning region
(MeteoAlarm EMMA id) it lies in; it is only a suggestion in the setup, where
the region can be chosen by hand.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

# DMI's warning regions on land (MeteoAlarm EMMA ids).
WARNING_REGIONS = {
    "DK001": "Nordjylland",
    "DK002": "Midt- og Vestjylland",
    "DK003": "Bornholm",
    "DK004": "Østjylland",
    "DK005": "Syd- og Sønderjylland",
    "DK006": "Fyn",
    "DK007": "Vest- og Sydsjælland samt Lolland-Falster",
    "DK008": "København og Nordsjælland",
}

# (municipality number, name, warning region, lat, lon of DMI's centre point)
MUNICIPALITIES = [
    ("0101", "København", "DK008", 55.7041, 12.4939),
    ("0147", "Frederiksberg", "DK008", 55.6794, 12.5237),
    ("0151", "Ballerup", "DK008", 55.7278, 12.3684),
    ("0153", "Brøndby", "DK008", 55.645, 12.4044),
    ("0155", "Dragør", "DK008", 55.5938, 12.6502),
    ("0157", "Gentofte", "DK008", 55.751, 12.5507),
    ("0159", "Gladsaxe", "DK008", 55.7399, 12.4762),
    ("0161", "Glostrup", "DK008", 55.696, 12.4092),
    ("0163", "Herlev", "DK008", 55.7414, 12.4258),
    ("0165", "Albertslund", "DK008", 55.685, 12.3523),
    ("0167", "Hvidovre", "DK008", 55.6314, 12.4685),
    ("0169", "Høje-Taastrup", "DK008", 55.667, 12.2578),
    ("0173", "Lyngby-Taarbæk", "DK008", 55.7832, 12.5113),
    ("0175", "Rødovre", "DK008", 55.6818, 12.4487),
    ("0183", "Ishøj", "DK008", 55.6224, 12.3345),
    ("0185", "Tårnby", "DK008", 55.5951, 12.5513),
    ("0187", "Vallensbæk", "DK008", 55.6385, 12.3657),
    ("0190", "Furesø", "DK008", 55.7854, 12.3712),
    ("0201", "Allerød", "DK008", 55.8519, 12.3152),
    ("0210", "Fredensborg", "DK008", 55.9425, 12.4471),
    ("0217", "Helsingør", "DK008", 56.0491, 12.4817),
    ("0219", "Hillerød", "DK008", 55.9343, 12.2595),
    ("0223", "Hørsholm", "DK008", 55.8888, 12.5115),
    ("0230", "Rudersdal", "DK008", 55.8347, 12.4757),
    ("0240", "Egedal", "DK008", 55.7861, 12.2145),
    ("0250", "Frederikssund", "DK008", 55.7819, 11.9728),
    ("0253", "Greve", "DK008", 55.5855, 12.2457),
    ("0259", "Køge", "DK008", 55.4573, 12.0725),
    ("0260", "Halsnæs", "DK008", 55.9957, 12.0027),
    ("0265", "Roskilde", "DK008", 55.6224, 12.1073),
    ("0269", "Solrød", "DK008", 55.5327, 12.1791),
    ("0270", "Gribskov", "DK008", 56.0644, 12.2864),
    ("0306", "Odsherred", "DK007", 55.8513, 11.6007),
    ("0316", "Holbæk", "DK007", 55.6701, 11.5459),
    ("0320", "Faxe", "DK007", 55.2739, 12.0936),
    ("0326", "Kalundborg", "DK007", 55.6599, 11.229),
    ("0329", "Ringsted", "DK007", 55.4691, 11.8151),
    ("0330", "Slagelse", "DK007", 55.3661, 11.3452),
    ("0336", "Stevns", "DK007", 55.3252, 12.3442),
    ("0340", "Sorø", "DK007", 55.5248, 11.5593),
    ("0350", "Lejre", "DK008", 55.6054, 11.9168),
    ("0360", "Lolland", "DK007", 54.8003, 11.2989),
    ("0370", "Næstved", "DK007", 55.2953, 11.6827),
    ("0376", "Guldborgsund", "DK007", 54.8237, 11.9619),
    ("0390", "Vordingborg", "DK007", 55.0646, 11.9738),
    ("0400", "Bornholm", "DK003", 55.1279, 14.8837),
    ("0410", "Middelfart", "DK006", 55.4575, 9.9079),
    ("0420", "Assens", "DK006", 55.3009, 10.0412),
    ("0430", "Faaborg-Midtfyn", "DK006", 55.2125, 10.366),
    ("0440", "Kerteminde", "DK006", 55.3911, 10.5712),
    ("0450", "Nyborg", "DK006", 55.2768, 10.6782),
    ("0461", "Odense", "DK006", 55.3917, 10.2985),
    ("0479", "Svendborg", "DK006", 55.0962, 10.5233),
    ("0480", "Nordfyns", "DK006", 55.506, 10.1678),
    ("0482", "Langeland", "DK006", 54.8199, 10.7087),
    ("0492", "Ærø", "DK006", 54.8559, 10.3995),
    ("0510", "Haderslev", "DK005", 55.2446, 9.2976),
    ("0530", "Billund", "DK005", 55.6977, 9.0065),
    ("0540", "Sønderborg", "DK005", 54.9426, 9.9483),
    ("0550", "Tønder", "DK005", 55.0444, 8.8568),
    ("0561", "Esbjerg", "DK005", 55.4618, 8.7209),
    ("0563", "Fanø", "DK005", 55.4061, 8.421),
    ("0573", "Varde", "DK005", 55.6869, 8.6062),
    ("0575", "Vejen", "DK005", 55.4929, 9.0502),
    ("0580", "Aabenraa", "DK005", 54.9586, 9.2771),
    ("0607", "Fredericia", "DK005", 55.5644, 9.6552),
    ("0615", "Horsens", "DK004", 55.9069, 9.7992),
    ("0621", "Kolding", "DK005", 55.4263, 9.404),
    ("0630", "Vejle", "DK005", 55.6996, 9.364),
    ("0657", "Herning", "DK002", 56.2156, 8.8942),
    ("0661", "Holstebro", "DK002", 56.43, 8.8285),
    ("0665", "Lemvig", "DK002", 56.4724, 8.2887),
    ("0671", "Struer", "DK002", 56.4553, 8.5761),
    ("0706", "Syddjurs", "DK004", 56.3575, 10.5113),
    ("0707", "Norddjurs", "DK004", 56.4648, 10.7585),
    ("0710", "Favrskov", "DK004", 56.2937, 9.9178),
    ("0727", "Odder", "DK004", 55.9412, 10.146),
    ("0730", "Randers", "DK004", 56.5374, 10.0898),
    ("0740", "Silkeborg", "DK004", 56.209, 9.5606),
    ("0741", "Samsø", "DK004", 55.8031, 10.5861),
    ("0746", "Skanderborg", "DK004", 56.0871, 9.8491),
    ("0751", "Aarhus", "DK004", 56.1551, 10.1036),
    ("0756", "Ikast-Brande", "DK002", 56.1449, 9.2311),
    ("0760", "Ringkøbing-Skjern", "DK002", 56.0224, 8.5407),
    ("0766", "Hedensted", "DK004", 55.7378, 9.8227),
    ("0773", "Morsø", "DK001", 56.7531, 8.7078),
    ("0779", "Skive", "DK002", 56.62, 8.9133),
    ("0787", "Thisted", "DK001", 56.8937, 8.4729),
    ("0791", "Viborg", "DK002", 56.4708, 9.5498),
    ("0810", "Brønderslev", "DK001", 57.1799, 10.2782),
    ("0813", "Frederikshavn", "DK001", 57.3232, 10.4137),
    ("0820", "Vesthimmerlands", "DK001", 56.8154, 9.3837),
    ("0825", "Læsø", "DK001", 57.2661, 11.008),
    ("0840", "Rebild", "DK001", 56.869, 9.7604),
    ("0846", "Mariagerfjord", "DK001", 56.7336, 9.9256),
    ("0849", "Jammerbugt", "DK001", 57.1656, 9.622),
    ("0851", "Aalborg", "DK001", 56.9809, 9.9971),
    ("0860", "Hjørring", "DK001", 57.4684, 10.0779),
]

# Towns drawn on the radar and satellite maps (name, lat, lon, big), most
# important first: a town is left out when a more important one is too close
# to its label. Only the big ones are drawn on the wider satellite map.
TOWNS = [
    ("København", 55.6761, 12.5683, True), ("Aarhus", 56.1567, 10.2108, True),
    ("Odense", 55.4038, 10.4024, True), ("Aalborg", 57.0488, 9.9217, True),
    ("Esbjerg", 55.4765, 8.4594, True), ("Randers", 56.4607, 10.0364, True),
    ("Kolding", 55.4904, 9.4722, True), ("Horsens", 55.8607, 9.8503, True),
    ("Vejle", 55.7093, 9.5357, True), ("Herning", 56.1393, 8.9738, True),
    ("Viborg", 56.4532, 9.4020, True), ("Holstebro", 56.3601, 8.6161, True),
    ("Sønderborg", 54.9138, 9.7922, True), ("Næstved", 55.2299, 11.7609, True),
    ("Frederikshavn", 57.4407, 10.5366, True), ("Rønne", 55.1009, 14.7066, True),
    ("Thisted", 56.9552, 8.6943, True), ("Hjørring", 57.4642, 9.9823, True),
    ("Göteborg", 57.7089, 11.9746, True), ("Malmö", 55.6050, 13.0038, True),
    ("Helsingborg", 56.0465, 12.6945, True), ("Kiel", 54.3233, 10.1228, True),
    ("Flensburg", 54.7937, 9.4469, True), ("Hamburg", 53.5511, 9.9937, True),
    ("Roskilde", 55.6419, 12.0878, False), ("Hillerød", 55.9267, 12.3109, False),
    ("Helsingør", 56.0361, 12.6136, False), ("Køge", 55.4580, 12.1821, False),
    ("Holbæk", 55.7175, 11.7128, False), ("Slagelse", 55.4028, 11.3546, False),
    ("Kalundborg", 55.6795, 11.0886, False), ("Ringsted", 55.4426, 11.7903, False),
    ("Nykøbing F", 54.7691, 11.8743, False), ("Nakskov", 54.8306, 11.1360, False),
    ("Vordingborg", 55.0080, 11.9105, False), ("Svendborg", 55.0598, 10.6068, False),
    ("Nyborg", 55.3127, 10.7896, False), ("Middelfart", 55.5058, 9.7302, False),
    ("Fredericia", 55.5657, 9.7526, False), ("Haderslev", 55.2537, 9.4893, False),
    ("Aabenraa", 55.0443, 9.4174, False), ("Tønder", 54.9331, 8.8667, False),
    ("Ribe", 55.3280, 8.7604, False), ("Varde", 55.6206, 8.4807, False),
    ("Grindsted", 55.7577, 8.9273, False), ("Billund", 55.7310, 9.1153, False),
    ("Silkeborg", 56.1697, 9.5451, False), ("Skanderborg", 56.0346, 9.9306, False),
    ("Ikast", 56.1388, 9.1580, False), ("Ringkøbing", 56.0897, 8.2440, False),
    ("Skjern", 55.9504, 8.4950, False), ("Lemvig", 56.5486, 8.3102, False),
    ("Struer", 56.4919, 8.5938, False), ("Skive", 56.5667, 9.0270, False),
    ("Nykøbing M", 56.7956, 8.8586, False), ("Bjerringbro", 56.3768, 9.6606, False),
    ("Hobro", 56.6431, 9.7903, False), ("Mariager", 56.6496, 10.0003, False),
    ("Hadsten", 56.3277, 10.0496, False), ("Grenaa", 56.4155, 10.8786, False),
    ("Ebeltoft", 56.1944, 10.6821, False), ("Odder", 55.9731, 10.1531, False),
    ("Tranebjerg", 55.8406, 10.5967, False), ("Aars", 56.8030, 9.5174, False),
    ("Støvring", 56.8853, 9.8384, False), ("Brønderslev", 57.2702, 9.9411, False),
    ("Skagen", 57.7209, 10.5839, False), ("Sæby", 57.3311, 10.5214, False),
    ("Fjerritslev", 57.0886, 9.2655, False), ("Løgstør", 56.9669, 9.2569, False),
    ("Byrum", 57.2546, 11.0007, False), ("Bogense", 55.5669, 10.0886, False),
    ("Assens", 55.2699, 9.9007, False), ("Faaborg", 55.0956, 10.2427, False),
    ("Kerteminde", 55.4497, 10.6614, False), ("Rudkøbing", 54.9364, 10.7099, False),
    ("Marstal", 54.8550, 10.5160, False), ("Frederikssund", 55.8396, 12.0689, False),
    ("Faxe", 55.2556, 12.1182, False), ("Haslev", 55.3239, 11.9634, False),
    ("Sorø", 55.4318, 11.5555, False), ("Nexø", 55.0606, 15.1311, False),
]

# Farther than this from every municipality centre is not in Denmark.
MAX_DISTANCE_KM = 40.0


def entry_settings(entry: Any) -> Mapping[str, Any]:
    """The setup of a config entry: its data, overridden by what was changed later."""
    return {**entry.data, **entry.options}


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def municipality_name(code: str) -> str | None:
    return next((name for c, name, *_ in MUNICIPALITIES if c == code), None)


def municipality_by_name(name: str | None) -> str | None:
    """Municipality number for a name such as "Randers Kommune" (OpenStreetMap).

    OpenStreetMap also writes "Københavns Kommune" and "Bornholms Regionskommune".
    """
    if not name:
        return None
    key = name.lower().removesuffix(" kommune").removesuffix(" regionskommune").strip()
    names = {n.lower(): c for c, n, *_ in MUNICIPALITIES}
    return names.get(key) or names.get(key.removesuffix("s"))


def nearest_municipality(lat: float, lon: float) -> tuple[str, float]:
    """Municipality whose centre is nearest, and the distance to it in km."""
    return min(
        ((c, distance_km(lat, lon, la, lo)) for c, _, _, la, lo in MUNICIPALITIES),
        key=lambda item: item[1],
    )


def warning_region(municipality: str) -> str | None:
    return next((r for c, _, r, *_ in MUNICIPALITIES if c == municipality), None)
