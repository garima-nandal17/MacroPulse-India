"""
brief_facts.py — MacroPulse India, Day 10 (AI Briefing: facts layer, enriched)

Deterministic payload for the briefing. Now decomposes each sector's implied response
into per-factor CONTRIBUTIONS and SHARES, attaches significance + an evidence tier,
flags outsized macro inputs, orders sectors by EVIDENCE then magnitude, and builds a
factual headline. Pure data — the renderer narrates it and invents no numbers.
"""
from __future__ import annotations

import pandas as pd

from fetch_daily import get_connection
from impact_panel import ImpactPanel, SECTOR_LABELS
from whatif_simulator import WhatIfSimulator, SCENARIOS


def _query_df(conn, sql):
    cur = conn.cursor(); cur.execute(sql)
    cols = [c[0] for c in cur.description]; rows = cur.fetchall(); cur.close()
    return pd.DataFrame(rows, columns=cols)


def _stars(p):
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else "~"


def _evidence(min_p):
    if min_p < 0.01:
        return "Strong", 3
    if min_p < 0.05:
        return "Moderate", 2
    return "Weak", 1


def _regime(ms):
    cpi, iip = ms.get("CPI_chg", 0.0), ms.get("IIP_chg", 0.0)
    if cpi > 0 and iip < 0:
        return "contractionary with rising inflation"
    if cpi < 0 and iip > 0:
        return "disinflationary recovery"
    if iip > 0:
        return "expansionary"
    if iip < 0:
        return "contractionary"
    return "mixed"


def _decompose(engine, macro_state, freq, alpha):
    b = engine.betas
    active, no_exposure = [], []
    for asset, sector in SECTOR_LABELS.items():
        sb = b[(b["freq"] == freq) & (b["asset"] == asset)
               & (b["factor"].isin(macro_state)) & (b["pvalue"] <= alpha)].copy()
        if sb.empty:
            no_exposure.append(sector); continue
        sb["contribution"] = sb.apply(lambda r: r["beta"] * macro_state[r["factor"]], axis=1)
        total = float(sb["contribution"].sum())
        if total == 0:
            no_exposure.append(sector); continue
        sb = sb.sort_values("contribution", key=lambda s: s.abs(), ascending=False)
        drivers = [{"factor": r["factor"], "beta": float(r["beta"]), "pvalue": float(r["pvalue"]),
                    "contribution_pct": float(r["contribution"]) * 100.0,
                    "share": float(r["contribution"]) / total, "stars": _stars(float(r["pvalue"]))}
                   for _, r in sb.iterrows()]
        label, rank = _evidence(drivers[0]["pvalue"])  # dominant driver carries the evidence
        active.append({"sector": sector, "implied_pct": total * 100.0,
                       "direction": "up" if total > 0 else "down",
                       "evidence": label, "_rank": rank, "drivers": drivers})
    active.sort(key=lambda s: (-s["_rank"], -abs(s["implied_pct"])))
    return active, no_exposure


def _outsized(conn, macro_state):
    try:
        adf = _query_df(conn, "SELECT * FROM analysis_daily")
    except Exception:
        return []
    flags = []
    for f, v in macro_state.items():
        if f in adf.columns:
            s = pd.to_numeric(adf[f], errors="coerce").dropna()
            if len(s) > 10 and s.std() > 0 and abs(v) > 2 * s.std():
                flags.append({"factor": f, "value": v, "z": v / float(s.std())})
    return flags


def assemble(scenario_name=None, freq="daily", alpha=0.10, conn=None):
    own = conn is None
    conn = conn or get_connection()
    try:
        panel_obj = ImpactPanel(conn=conn)
        macro_state, asof = panel_obj.current_state()
        engine = panel_obj.engine

        active, no_exposure = _decompose(engine, macro_state, freq, alpha)
        outsized = _outsized(conn, macro_state)

        cpi = macro_state.get("CPI_chg", 0.0)
        iip = macro_state.get("IIP_chg", 0.0)
        ur = macro_state.get("Unemployment_chg", 0.0)
        lead = (f"strongest-evidence reading is {active[0]['sector']} {active[0]['direction']} "
                f"[{active[0]['evidence']}]") if active else "no sector shows significant exposure"
        headline = (f"Macro is {_regime(macro_state)}: CPI {cpi:+.2%} MoM, IIP {iip:+.2%} MoM, "
                    f"unemployment {ur:+.2f}pp — {lead}.")

        b = engine.betas
        sig = b[(b["freq"] == freq) & (b["pvalue"] <= alpha) & (b["asset"].isin(SECTOR_LABELS))].copy()
        if not sig.empty:
            sig["sector"] = sig["asset"].map(SECTOR_LABELS)
            sig["stars"] = sig["pvalue"].map(_stars)
            sig = sig.sort_values("pvalue")[["sector", "factor", "beta", "pvalue", "stars"]].head(10)

        scenario = None
        if scenario_name:
            shocks = SCENARIOS[scenario_name]
            res = WhatIfSimulator(engine=engine, conn=conn).simulate(shocks, freq=freq, alpha=alpha)
            scenario = {"name": scenario_name, "shocks": shocks, "results": res.to_dict("records")}

        caveats = [
            "Readings are implied daily returns — directional/ordinal, not point forecasts.",
            "Limited sample (~261 daily / ~13 monthly obs); sectors are ordered by evidence, then magnitude.",
            "A sector under 'no significant exposure' has no beta clearing the significance threshold "
            "to the current factors — all sectors are ingested, so absence is never missing data.",
            "Projection is linear (beta x shock); non-linear macro responses are not captured.",
        ]
        return {
            "asof": str(asof), "freq": freq, "headline": headline,
            "macro_state": macro_state, "outsized_factors": outsized,
            "active_sectors": active, "no_exposure_sectors": no_exposure,
            "significant_sensitivities": sig.to_dict("records") if not sig.empty else [],
            "scenario": scenario,
            "coverage": {"sectors_total": len(SECTOR_LABELS), "active": len(active)},
            "caveats": caveats,
        }
    finally:
        if own and conn is not None:
            conn.close()