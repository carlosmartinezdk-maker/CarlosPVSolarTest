"""Shared paths and constants for the BESS fleet pipeline."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BESS_DATA_DIR", ROOT / "data"))   # same raw layout as gas_analysis/data
RAW = DATA / "raw"
X = DATA / "x"
CACHE = DATA / "cache"
OUT = Path(os.environ.get("BESS_OUT_DIR", ROOT / "outputs"))
YEARS = list(range(2019, 2026))
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
SUMMER = {6, 7, 8, 9}
SHOULDER = {3, 4, 5, 10, 11}

for p in (CACHE, OUT):
    p.mkdir(parents=True, exist_ok=True)
