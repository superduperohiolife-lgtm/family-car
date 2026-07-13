# -*- coding: utf-8 -*-
"""距離・新しさ・価格を min-max 正規化し、重み付き平均で総合スコアを算出。
新しさ = 年式スコア（新しいほど高）と走行距離スコア（少ないほど高）の平均。
"""
import config

def _nrm(v, lo, hi, higher_better=True):
    if hi == lo:
        return 100.0
    s = 100 * (v - lo) / (hi - lo)
    return s if higher_better else 100 - s

def score(rows):
    if not rows:
        return rows
    ys = [r["year"] for r in rows]; ms = [r["mil"] for r in rows]
    ps = [r["price"] for r in rows]; ds = [r["dist"] for r in rows]
    ylo, yhi = min(ys), max(ys); mlo, mhi = min(ms), max(ms)
    plo, phi = min(ps), max(ps); dlo, dhi = min(ds), max(ds)
    w = config.WEIGHTS; wsum = w["distance"] + w["newness"] + w["price"]
    for r in rows:
        ysc = _nrm(r["year"], ylo, yhi, True)
        msc = _nrm(r["mil"], mlo, mhi, False)
        r["new"] = (ysc + msc) / 2
        r["dsc"] = _nrm(r["dist"], dlo, dhi, False)
        r["psc"] = _nrm(r["price"], plo, phi, False)
        r["total"] = (w["distance"]*r["dsc"] + w["newness"]*r["new"] + w["price"]*r["psc"]) / wsum
    rows.sort(key=lambda x: -x["total"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows
