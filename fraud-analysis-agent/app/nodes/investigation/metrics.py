"""Precision / recall / F1 against pom_acr (truth) within the time window.

Ground truth source selected by GROUND_TRUTH_SOURCE:
  - pom_acr  : transID rows from pom_acr (default)
  - column   : legacy `is_fraud` column on the `transactions` table
"""
from __future__ import annotations

import os

from app.shared.warehouse import warehouse_query


def _ground_truth_source() -> str:
    return os.environ.get("GROUND_TRUTH_SOURCE", "pom_acr").lower()


def _load_ground_truth(
    window: dict | None,
    fraud_types: list[str] | None,
) -> set[str]:
    src = _ground_truth_source()

    if src == "pom_acr":
        clauses = ["1=1"]
        if window:
            clauses.append(
                f"reqDate >= '{window['start']}' AND "
                f"reqDate <= '{window['end']} 23:59:59'"
            )
        if fraud_types:
            types_csv = ", ".join(f"'{t}'" for t in fraud_types)
            clauses.append(f"fraud_type IN ({types_csv})")
        sql = f"SELECT transID FROM pom_acr WHERE {' AND '.join(clauses)}"
        df = warehouse_query(sql)
        return set(df["transID"])

    if src == "column":
        df = warehouse_query(
            "SELECT txn_id FROM transactions WHERE is_fraud = 1"
        )
        return set(df["txn_id"])

    raise ValueError(f"Unknown GROUND_TRUTH_SOURCE={src!r}")


def compute_metrics(
    matched_case_ids: list[str],
    window: dict | None = None,
    fraud_types: list[str] | None = None,
) -> dict:
    truth = _load_ground_truth(window, fraud_types)
    flagged = set(matched_case_ids)

    tp = len(flagged & truth)
    fp = len(flagged - truth)
    fn = len(truth - flagged)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "hit_count": tp,
        "total_fraud": len(truth),
        "total_flagged": len(flagged),
    }
