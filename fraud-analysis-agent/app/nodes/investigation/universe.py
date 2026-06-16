"""Universe profile from trans_log — baseline for discriminative power.

A signal is meaningful only when its distribution in the fraud subset
differs from the overall universe. We expose enough breakdown so
hypothesis_node can see the contrast.

Quantiles are computed in Python (pandas) rather than via warehouse-side
percentile functions — keeps the SQL strictly ANSI / MySQL-compatible.
"""
from __future__ import annotations

from app.shared.warehouse import warehouse_query


TOP_K = 10


def universe_profile(window: dict, top_k: int = TOP_K) -> dict:
    start, end = window["start"], window["end"]
    where = f"reqDate >= '{start}' AND reqDate <= '{end} 23:59:59'"

    # Pull amounts to compute quantiles in pandas (avoids MySQL quirks).
    amts_df = warehouse_query(
        f"SELECT userChargeAmount FROM trans_log WHERE {where}"
    )
    amts = amts_df["userChargeAmount"]
    n = int(len(amts))

    if n:
        quantiles = {
            "p25": int(amts.quantile(0.25)),
            "p50": int(amts.quantile(0.50)),
            "p75": int(amts.quantile(0.75)),
            "p95": int(amts.quantile(0.95)),
            "max": int(amts.max()),
        }
    else:
        quantiles = {"p25": 0, "p50": 0, "p75": 0, "p95": 0, "max": 0}

    return {
        "total_transactions": n,
        "amount_quantiles": quantiles,
        "channel_distribution": _top(where, "integratedChannel", top_k),
        "bank_distribution": _top(where, "bankCode", top_k),
        "bank_type_distribution": _top(where, "bankType", top_k),
        "app_distribution": _top(where, "appName", top_k),
        "category_distribution": _top(where, "reportCat", top_k),
        "hour_distribution": _hour(where),
    }


def _top(where: str, col: str, k: int) -> list[dict]:
    sql = f"""
        SELECT {col} AS value, COUNT(*) AS n
        FROM trans_log WHERE {where}
        GROUP BY {col}
        ORDER BY n DESC LIMIT {k}
    """
    df = warehouse_query(sql)
    return [{col: r["value"], "n": int(r["n"])} for _, r in df.iterrows()]


def _hour(where: str) -> list[dict]:
    sql = f"""
        SELECT EXTRACT(HOUR FROM reqDate) AS hour, COUNT(*) AS n
        FROM trans_log WHERE {where}
        GROUP BY hour ORDER BY hour
    """
    df = warehouse_query(sql)
    return [{"hour": int(r["hour"]), "n": int(r["n"])} for _, r in df.iterrows()]
