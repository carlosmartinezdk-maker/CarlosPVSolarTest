"""M4 utilisation vs matched peers. Peers: same balancing authority, same duration band, age +-3 years; healthy
(RTE >= 0.75 and non-zero throughput that month). Ladder if < MIN_PEERS: tier 2 drop age; tier 3 national same band."""
import numpy as np
import pandas as pd

AGE_TOL = 3.0
PEER_MIN_RTE = 0.75
MIN_PEERS = 3


def add_uti(p):
    p = p.copy()
    p["peer_efc_median"] = np.nan
    p["peer_tier"] = np.nan
    p["n_peers"] = 0
    ok = p["efc"].notna() & p["e_rated_mwh"].gt(0)
    healthy = (p["rte"] >= PEER_MIN_RTE) & (p["discharge"] > 0) & ~p["hybrid"]
    for (y, m), d in p[ok].groupby(["year", "month"]):
        idx = d.index.to_numpy()
        ba = d["ba"].astype(str).to_numpy(dtype=object)
        band = d["dur_band"].astype(str).to_numpy(dtype=object)
        age = d["age_yr"].to_numpy(float)
        efc = d["efc"].to_numpy(float)
        h = healthy.loc[idx].to_numpy(bool)
        same_band = (band[:, None] == band[None, :]) & h[None, :]
        np.fill_diagonal(same_band, False)
        same_ba = ba[:, None] == ba[None, :]
        near_age = np.abs(age[:, None] - age[None, :]) <= AGE_TOL
        done = np.zeros(len(d), bool)
        for tier, mask in [(1, same_band & same_ba & near_age), (2, same_band & same_ba), (3, same_band)]:
            n = mask.sum(1)
            sel = (n >= MIN_PEERS) & ~done
            if not sel.any():
                continue
            med = np.nanmedian(np.where(mask[sel], efc[None, :], np.nan), axis=1)
            p.loc[idx[sel], "peer_efc_median"] = med
            p.loc[idx[sel], "peer_tier"] = tier
            p.loc[idx[sel], "n_peers"] = n[sel]
            done |= sel
    p["uti"] = p["efc"] / p["peer_efc_median"].where(p["peer_efc_median"] > 0)
    return p
