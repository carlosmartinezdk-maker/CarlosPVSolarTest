"""Extract plant -> customer group mapping from the fleet production workbook and flag SSI customers.

    python build_customer_map.py <Fleet_Production_by_Technology_2019_2025.xlsx>

Writes (small, committed):
  plant_customer_map.csv   plant_id, sheet, customer, owner, ssi   (latest reporting year per plant x sheet)
  owner_customer_map.csv   owner -> customer (workbook 'Customer Mapping' sheet)
SSI status comes from ssi_customers.txt (the current SSI customer list); the workbook's own SSI column is
cross-checked and differences are printed.
"""
import sys
import pandas as pd
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHEETS = ["Solar", "Wind", "BESS", "Gas Turbine", "Combined Cycle", "Nuclear", "Gas Steam"]


def main(xlsx):
    ssi = {l.strip() for l in (HERE / "ssi_customers.txt").read_text(encoding="utf-8").splitlines() if l.strip()}
    rows = []
    for s in SHEETS:
        d = pd.read_excel(xlsx, s, usecols=["Plant Id", "YEAR", "CUSTOMER", "SSI", "OWNER", "Technology_Detail"])
        d = d.sort_values("YEAR").drop_duplicates("Plant Id", keep="last")
        d["sheet"] = s
        rows.append(d)
    m = pd.concat(rows, ignore_index=True).rename(columns={"Plant Id": "plant_id", "CUSTOMER": "customer",
                                                           "OWNER": "owner", "SSI": "ssi_workbook",
                                                           "Technology_Detail": "tech_detail"})
    m["ssi"] = m["customer"].isin(ssi)
    diff = m[(m["ssi_workbook"] == "SSI customer") != m["ssi"]]
    print(f"{len(m)} plant x sheet rows; SSI plants {int(m['ssi'].sum())}; disagreements with workbook SSI column: {len(diff)}")
    m[["plant_id", "sheet", "customer", "owner", "ssi", "tech_detail"]].to_csv(HERE / "plant_customer_map.csv", index=False)
    cm = pd.read_excel(xlsx, "Customer Mapping", header=3)
    cm.columns = ["owner", "customer", "ssi_workbook", "method", "plants", "max_mw"]
    cm["ssi"] = cm["customer"].isin(ssi)
    cm[["owner", "customer", "ssi", "method"]].to_csv(HERE / "owner_customer_map.csv", index=False)
    listed_in_us = sorted(ssi & set(m["customer"]))
    print(f"SSI list: {len(ssi)} names, {len(listed_in_us)} appear as US customer groups")
    (HERE / "ssi_customers_matched_us.txt").write_text("\n".join(listed_in_us) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
