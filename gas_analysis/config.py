"""Shared paths and constants for the gas fleet heat-rate pipeline."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("GAS_DATA_DIR", ROOT / "data"))   # raw downloads + extracted
RAW = DATA / "raw"
X = DATA / "x"
CACHE = DATA / "cache"
OUT = Path(os.environ.get("GAS_OUT_DIR", ROOT / "outputs"))
FUEL_COST_CSV = Path(os.environ.get("GAS_FUEL_COST_CSV", ROOT / "inputs" / "eia923_page5_gas_fuel_cost_2019_2025.csv"))

YEARS = list(range(2019, 2026))
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

GAS_FUELS = {"NG", "OG", "PG", "BFG", "LFG", "OBG", "SGC", "SGP"}

# EIA-923 prime mover -> class
PM_CLASS = {"CA": "CC", "CT": "CC", "CS": "CC", "GT": "GT", "ST": "ST", "IC": "IC"}
CLASS_NAME = {"CC": "Combined Cycle", "GT": "Gas Turbine", "ST": "Gas Steam", "IC": "Gas Recip"}
# EIA-860 Technology -> class (gas technologies only)
TECH_CLASS = {
    "Natural Gas Fired Combined Cycle": "CC",
    "Natural Gas Fired Combustion Turbine": "GT",
    "Natural Gas Steam Turbine": "ST",
    "Natural Gas Internal Combustion Engine": "IC",
}

for p in (CACHE, OUT):
    p.mkdir(parents=True, exist_ok=True)
