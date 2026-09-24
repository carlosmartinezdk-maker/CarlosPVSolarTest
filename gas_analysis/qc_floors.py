"""Physical heat-rate floors/ceilings per class. Below floor = data error (misallocation), never good performance."""
FLOORS = {"CC": 5700, "GT": 7500, "ST": 7500, "IC": 7000}          # Btu/kWh (HHV)
CEILINGS = {"CC": 20000, "GT": 30000, "ST": 25000, "IC": 20000}
MAX_FLOOR_BREACH_SHARE = 0.05       # >5% of a class below floor after re-aggregation -> aggregation is wrong
MAX_LF = 1.10                       # load factor above this -> capacity mismatch


def flag(df):
    """Adds qc_hr: ok | misallocated | above_ceiling | no_gen | no_fuel."""
    f = df["cls"].map(FLOORS)
    c = df["cls"].map(CEILINGS)
    q = (df["hr"] < f).map({True: "misallocated", False: "ok"})
    q = q.where(~(df["hr"] > c), "above_ceiling")
    q = q.where(df["netgen"] > 0, "no_gen")
    q = q.where(~((df["netgen"] > 0) & ~(df["elec_mmbtu"] > 0)), "no_fuel")
    df["qc_hr"] = q
    return df


def breach_table(df):
    s = df[df["netgen"] > 0]
    t = s.groupby("cls")["qc_hr"].value_counts(normalize=True).unstack(fill_value=0)
    return t
