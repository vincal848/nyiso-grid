"""Paths and global settings."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("NYISO_ROOT", Path(__file__).resolve().parents[2]))
DATA = ROOT / "data"
RAW = DATA / "raw"
CURATED = DATA / "curated"
REF = DATA / "ref"
DB_PATH = DATA / "nyiso.duckdb"
WEB = ROOT / "web"

MIS_BASE = "http://mis.nyiso.com/public/csv"
TZ = "America/New_York"

DEFAULT_START = "2021-10"  # YYYY-MM, inclusive

# NYISO internal load zones (letter -> MIS name)
ZONES = {
    "A": "WEST", "B": "GENESE", "C": "CENTRL", "D": "NORTH", "E": "MHK VL",
    "F": "CAPITL", "G": "HUD VL", "H": "MILLWD", "I": "DUNWOD", "J": "N.Y.C.", "K": "LONGIL",
}
EXTERNAL_ZONES = ["H Q", "NPX", "O H", "PJM"]

FUELS = ["Nuclear", "Hydro", "Dual Fuel", "Natural Gas", "Wind",
         "Other Renewables", "Other Fossil Fuels"]

# Weather stations (NOAA GHCNh ids, verified). Each NYISO internal zone maps to >= 1 station.
WEATHER_STATIONS = {
    #  code: (GHCNh id,     name,                 lat,     lon,      zones)
    "BUF": ("USW00014733", "Buffalo",            42.9408, -78.7358, ("WEST",)),
    "ROC": ("USW00014768", "Rochester",          43.1172, -77.6753, ("GENESE",)),
    "SYR": ("USW00014771", "Syracuse",           43.1111, -76.1038, ("CENTRL",)),
    "MSS": ("USW00094725", "Massena",            44.9358, -74.8456, ("NORTH",)),
    "ART": ("USW00094790", "Watertown",          43.9886, -76.0261, ("MHK VL",)),
    "ALB": ("USW00014735", "Albany",             42.7431, -73.8092, ("CAPITL",)),
    "POU": ("USW00014757", "Poughkeepsie",       41.6258, -73.8817, ("HUD VL",)),
    "HPN": ("USW00094745", "White Plains",       41.0670, -73.7076, ("MILLWD", "DUNWOD")),
    "LGA": ("USW00014732", "LaGuardia",          40.7794, -73.8803, ("N.Y.C.",)),
    "JFK": ("USW00094789", "JFK",                40.6386, -73.7622, ("N.Y.C.",)),
    "ISP": ("USW00004781", "Islip",              40.7939, -73.1017, ("LONGIL",)),
}

# Information-availability rules (verified 2026-09-27; see dictionary conventions "As-of availability").
DAM_BID_DEADLINE_ET = "05:00"   # bids for day D close 05:00 ET on D-1 (NYISO MST 4.2)
DAM_RESULTS_ET = "11:00"        # DAM results posted by 11:00 ET on D-1
ISOLF_AVAILABLE_ET = "08:30"    # ISOLF file dated F is posted ~07:05-08:20 ET on F (MIS P-7 index)
