"""Customer group + SSI assignment shared by the gas and BESS pipelines and the infographics.

Priority per site: (1) workbook plant match on the same technology sheet; (2) workbook plant match on any sheet;
(3) EIA owner name via the workbook owner->customer table; (4) operator name via the same table; (5) owner name
as-is (unmapped). SSI = customer group appears in ssi_customers.txt."""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
GAS_SHEET = {"CC": "Combined Cycle", "GT": "Gas Turbine", "ST": "Gas Steam", "IC": "Gas Turbine"}


def ssi_set():
    return {l.strip() for l in (HERE / "ssi_customers.txt").read_text(encoding="utf-8").splitlines() if l.strip()}


def assign(df, sheet, owner_col="owner", operator_col="operator"):
    """df: one row per site with plant_id, owner/operator columns; sheet: series or scalar of workbook sheet names.
    Returns df with customer_group, ssi (bool), ssi_status ('SSI customer'|'prospect'), customer_source."""
    pm = pd.read_csv(HERE / "plant_customer_map.csv")
    om = pd.read_csv(HERE / "owner_customer_map.csv").dropna(subset=["owner"]).drop_duplicates("owner")
    o2c = dict(zip(om["owner"].str.strip().str.lower(), om["customer"]))
    same = {(r.plant_id, r.sheet): r.customer for r in pm.itertuples()}
    anyp = pm.drop_duplicates("plant_id").set_index("plant_id")["customer"].to_dict()
    df = df.copy()
    sh = sheet if isinstance(sheet, pd.Series) else pd.Series(sheet, index=df.index)
    cust, src = [], []
    for pid, s, ow, op in zip(df["plant_id"], sh, df.get(owner_col, pd.Series(index=df.index)),
                              df.get(operator_col, pd.Series(index=df.index))):
        if (pid, s) in same:
            cust.append(same[(pid, s)]); src.append("workbook plant (same technology)")
        elif pid in anyp:
            cust.append(anyp[pid]); src.append("workbook plant (other technology)")
        elif isinstance(ow, str) and ow.strip().lower() in o2c:
            cust.append(o2c[ow.strip().lower()]); src.append("workbook owner map")
        elif isinstance(op, str) and op.strip().lower() in o2c:
            cust.append(o2c[op.strip().lower()]); src.append("workbook owner map (operator)")
        else:
            cust.append(ow if isinstance(ow, str) and ow else (op if isinstance(op, str) else "Unknown"))
            src.append("unmapped (owner as reported)")
    df["customer_group"] = cust
    df["customer_source"] = src
    ssi = ssi_set()
    df["ssi"] = df["customer_group"].isin(ssi)
    df["ssi_status"] = df["ssi"].map({True: "SSI customer", False: "prospect"})
    return df
