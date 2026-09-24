"""Load EIA-923 Page 1 Generation and Fuel Data, 2019-2025, to a long monthly table."""
import glob
import pandas as pd
from config import X, CACHE, YEARS, MONTHS

SHEET = "Page 1 Generation and Fuel Data"


def _find_header(path, sheet):
    raw = pd.read_excel(path, sheet_name=sheet, header=None, nrows=10)
    for i, row in raw.iterrows():
        if any(str(v).strip() == "Plant Id" for v in row.values):
            return i
    raise ValueError(f"no 'Plant Id' header in first 10 rows of {path}")


def _file(year):
    hits = sorted(glob.glob(str(X / f"f923_{year}" / "EIA923_Schedules_2_3_4_5_M_12_*.xlsx")))
    if not hits:
        raise FileNotFoundError(f"EIA-923 {year} not found under {X}")
    return hits[0]


def load_year(year):
    path = _file(year)
    hdr = _find_header(path, SHEET)
    df = pd.read_excel(path, sheet_name=SHEET, header=hdr)
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    df = df.rename(columns={"Plant Id": "plant_id", "Reported Prime Mover": "pm",
                            "Reported Fuel Type Code": "fuel", "Plant Name": "plant_name",
                            "Plant State": "state", "NERC Region": "nerc",
                            "Balancing Authority Code": "ba", "Operator Name": "operator",
                            "Operator Id": "operator_id",
                            "Combined Heat And Power Plant": "chp",
                            "Respondent Frequency": "resp_freq"})
    df = df[pd.to_numeric(df["plant_id"], errors="coerce").notna()]
    df["plant_id"] = df["plant_id"].astype(int)
    ids = ["plant_id", "plant_name", "operator", "operator_id", "state", "nerc", "ba", "chp", "resp_freq", "pm", "fuel"]
    parts = []
    for mi, m in enumerate(MONTHS, 1):
        cols = {f"Quantity {m}": "quantity", f"Elec_Quantity {m}": "elec_quantity",
                f"Tot_MMBtu {m}": "tot_mmbtu", f"Elec_MMBtu {m}": "elec_mmbtu", f"Netgen {m}": "netgen"}
        p = df[ids + list(cols)].rename(columns=cols)
        p["month"] = mi
        parts.append(p)
    out = pd.concat(parts, ignore_index=True)
    out["year"] = year
    for c in ["quantity", "elec_quantity", "tot_mmbtu", "elec_mmbtu", "netgen"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")   # '.' = not reported
    for c in ["plant_name", "operator", "operator_id", "state", "nerc", "ba", "chp", "resp_freq", "pm", "fuel"]:
        out[c] = out[c].astype(str).str.strip()
    return out


def load_all(force=False):
    f = CACHE / "eia923_page1_long.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    df = pd.concat([load_year(y) for y in YEARS], ignore_index=True)
    df.to_parquet(f, index=False)
    return df


if __name__ == "__main__":
    d = load_all(force=True)
    print(d.shape)
    print(d.groupby("year").netgen.sum() / 1e6)
