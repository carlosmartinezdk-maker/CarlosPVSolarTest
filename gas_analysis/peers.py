"""M7 Peer Relative Index: median HR_corr of >=8 matched healthy peers / own HR_corr."""
import numpy as np
import pandas as pd

SIZE_BANDS = {   # unit (frame) size bands, MW per unit
    "CC": [0, 50, 100, 200, 300, 1e9],
    "GT": [0, 25, 50, 100, 200, 1e9],
    "ST": [0, 50, 150, 300, 600, 1e9],
    "IC": [0, 2, 5, 10, 20, 1e9],
}
VINTAGE_TOL_YR = 5
REGION_KM = 500
LF_TOL = 0.10
MIN_PEERS = 8
PEER_HEALTH_HRI = 0.90
# Relaxation ladder when the strict (spec) match yields < MIN_PEERS: tier 1 = spec; 2 = drop region; 3 = vintage +-10 yr
PEER_TIERS = [
    {"tier": 1, "region": True, "vintage": VINTAGE_TOL_YR},
    {"tier": 2, "region": False, "vintage": VINTAGE_TOL_YR},
    {"tier": 3, "region": False, "vintage": 10},
]


def size_band(df):
    out = pd.Series(np.nan, index=df.index)
    for cls, edges in SIZE_BANDS.items():
        m = df["cls"] == cls
        out[m] = pd.cut(df.loc[m, "unit_size_mw"], edges, labels=False, include_lowest=True)
    return out


def _km(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    a = np.sin((la[:, None] - la[None, :]) / 2) ** 2 + \
        np.cos(la[:, None]) * np.cos(la[None, :]) * np.sin((lo[:, None] - lo[None, :]) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def add_pri(p):
    p["size_band"] = size_band(p)
    p["pri"] = np.nan
    p["n_peers"] = 0
    p["peer_hr_median"] = np.nan
    p["peer_tier"] = np.nan
    elig = p["scoreable"] & p["size_band"].notna() & p["cod_year"].notna() & p["lat"].notna()
    for (cls, y, m), d in p[elig].groupby(["cls", "year", "month"]):
        idx = d.index.values
        sb, cod, lf = (d[c].to_numpy(dtype=float) for c in ["size_band", "cod_year", "lf"])
        nerc = d["nerc"].astype(str).to_numpy(dtype=object)
        hr = d["hr_corr"].to_numpy(dtype=float)
        healthy = (d["hri"].to_numpy(dtype=float) >= PEER_HEALTH_HRI) & ~d["chp_cohort"].to_numpy(dtype=bool)
        km = _km(d["lat"].to_numpy(dtype=float), d["lon"].to_numpy(dtype=float))
        same_region = (nerc[:, None] == nerc[None, :]) | (km <= REGION_KM)
        base = (sb[:, None] == sb[None, :]) & (np.abs(lf[:, None] - lf[None, :]) <= LF_TOL) & healthy[None, :]
        np.fill_diagonal(base, False)
        done = np.zeros(len(d), bool)
        for t in PEER_TIERS:
            mask = base & (np.abs(cod[:, None] - cod[None, :]) <= t["vintage"])
            if t["region"]:
                mask &= same_region
            n = mask.sum(1)
            ok = (n >= MIN_PEERS) & ~done
            if not ok.any():
                continue
            mat = np.where(mask[ok], hr[None, :], np.nan)
            med = np.nanmedian(mat, axis=1)
            p.loc[idx[ok], "n_peers"] = n[ok]
            p.loc[idx[ok], "peer_tier"] = t["tier"]
            p.loc[idx[ok], "peer_hr_median"] = med
            p.loc[idx[ok], "pri"] = med / hr[ok]
            done |= ok
    return p


if __name__ == "__main__":
    p = pd.read_parquet("data/cache/_scratch_scored.parquet")
    p = add_pri(p)
    s = p[p.scoreable & ~p.chp_cohort]
    print("PRI coverage of scoreable non-CHP:", s.groupby("cls").pri.apply(lambda x: x.notna().mean()).round(3).to_dict())
    print(s.groupby(["cls"]).peer_tier.value_counts(dropna=False).unstack().fillna(0).astype(int))
    print(s.groupby("cls").pri.describe(percentiles=[.1, .5, .9]).round(3))
    p.to_parquet("data/cache/_scratch_scored.parquet")
