"""Schema introspection for MySQL warehouse tables."""
from __future__ import annotations

from app.shared.warehouse import warehouse_query


def get_schema(tables: list[str]) -> dict[str, list[dict]]:
    """Return {table: [{column, dtype, nullable}, ...]} via MySQL DESCRIBE.

    DESCRIBE returns: Field, Type, Null, Key, Default, Extra
    """
    out: dict[str, list[dict]] = {}
    for t in tables:
        df = warehouse_query(f"DESCRIBE {t}")
        out[t] = [
            {
                "column": row["Field"],
                "dtype": row["Type"],
                "nullable": str(row["Null"]).upper() == "YES",
            }
            for _, row in df.iterrows()
        ]
    return out
