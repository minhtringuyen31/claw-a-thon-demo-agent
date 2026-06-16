"""Seed MySQL with mock warehouse data (4 coherent tables).

Tables created:
  trans_log     (truncated + reseeded)
  pom_acr       (truncated + reseeded)
  user_profile  (truncated + reseeded)
  user_journey  (truncated + reseeded)

Run:
    uv run python -m app.data.seed_mysql

Env (from .env or shell):
    MYSQL_HOST, MYSQL_PORT, MYSQL_DB, MYSQL_USER, MYSQL_PASSWORD
"""
from __future__ import annotations

import os
import sys
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

from app.data.mock_data import generate


# ---------------------- DDL ----------------------

DDL_TRANS_LOG = """
CREATE TABLE IF NOT EXISTS trans_log (
    transID            VARCHAR(48)  NOT NULL,
    appID              INT,
    userID             BIGINT,
    reqDate            DATETIME,
    transStatus        TINYINT,
    userChargeAmount   BIGINT,
    source             VARCHAR(64),
    integratedChannel  VARCHAR(32),
    is_kyc             VARCHAR(8),
    transType          TINYINT,
    map_type           VARCHAR(8),
    bankconnectorcode  VARCHAR(32),
    bankCode           VARCHAR(16),
    pmcID              INT,
    paymentSolution    VARCHAR(32),
    month              VARCHAR(8),
    week               DATE,
    bankType           VARCHAR(32),
    appName            VARCHAR(64),
    reportCat          VARCHAR(32),
    appID_appName      VARCHAR(80),
    PRIMARY KEY (transID),
    INDEX idx_user_time (userID, reqDate),
    INDEX idx_bank_type (bankType),
    INDEX idx_app (appID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_POM_ACR = """
CREATE TABLE IF NOT EXISTS pom_acr (
    transID            VARCHAR(48)  NOT NULL,
    appID              INT,
    userID             BIGINT,
    reqDate            DATETIME,
    transStatus        TINYINT,
    userChargeAmount   BIGINT,
    source             VARCHAR(64),
    integratedChannel  VARCHAR(32),
    is_kyc             VARCHAR(8),
    transType          TINYINT,
    map_type           VARCHAR(8),
    bankconnectorcode  VARCHAR(32),
    bankCode           VARCHAR(16),
    pmcID              INT,
    paymentSolution    VARCHAR(32),
    month              VARCHAR(8),
    week               DATE,
    bankType           VARCHAR(32),
    appName            VARCHAR(64),
    reportCat          VARCHAR(32),
    appID_appName      VARCHAR(80),
    fraud_type         VARCHAR(4),
    report_date        DATE,
    is_loss            TINYINT,
    PRIMARY KEY (transID),
    INDEX idx_fraud_type (fraud_type),
    INDEX idx_req_date (reqDate),
    INDEX idx_user_time (userID, reqDate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_USER_PROFILE = """
CREATE TABLE IF NOT EXISTS user_profile (
    userID                BIGINT PRIMARY KEY,
    account_created_date  DATE,
    ekyc_status           VARCHAR(16),
    ekyc_date             DATE,
    nfc_status            VARCHAR(16),
    nfc_date              DATE,
    dob_year              INT,
    phone                 VARCHAR(16),
    cccd_hash             VARCHAR(32),
    linked_bank           TINYINT,
    linked_card           TINYINT,
    has_credit_limit      TINYINT,
    has_mmf               TINYINT,
    trusted_user          TINYINT,
    whitelist             TINYINT,
    blacklist             TINYINT,
    historical_fraud      TINYINT,
    INDEX idx_account_date (account_created_date),
    INDEX idx_cccd (cccd_hash),
    INDEX idx_ekyc (ekyc_status),
    INDEX idx_nfc (nfc_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

DDL_USER_JOURNEY = """
CREATE TABLE IF NOT EXISTS user_journey (
    event_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
    userID      BIGINT,
    event_type  VARCHAR(32),
    event_time  DATETIME,
    INDEX idx_user_time (userID, event_time),
    INDEX idx_event_type (event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


# ---------------------- engine ----------------------

def _engine():
    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("MYSQL_PORT", "3306")
    db = os.environ.get("MYSQL_DB", "risk_db")
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    dsn = (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?charset=utf8mb4"
    )
    return create_engine(dsn, pool_pre_ping=True)


def _strip_tz(df, col):
    if col in df.columns and hasattr(df[col].dtype, "tz") and df[col].dtype.tz is not None:
        df[col] = df[col].dt.tz_localize(None)


def seed() -> None:
    print("Generating mock data…")
    profile_df, journey_df, trans_df, pom_df = generate()
    _strip_tz(trans_df, "reqDate")
    _strip_tz(pom_df, "reqDate")
    _strip_tz(journey_df, "event_time")

    engine = _engine()

    print("Creating + truncating tables…")
    with engine.begin() as conn:
        conn.execute(text(DDL_TRANS_LOG))
        conn.execute(text(DDL_POM_ACR))
        conn.execute(text(DDL_USER_PROFILE))
        conn.execute(text(DDL_USER_JOURNEY))
        conn.execute(text("TRUNCATE TABLE pom_acr"))
        conn.execute(text("TRUNCATE TABLE trans_log"))
        conn.execute(text("TRUNCATE TABLE user_profile"))
        conn.execute(text("TRUNCATE TABLE user_journey"))

    print(f"Inserting {len(profile_df):,} rows → user_profile")
    profile_df.to_sql("user_profile", engine, if_exists="append", index=False, chunksize=5000)

    print(f"Inserting {len(journey_df):,} events → user_journey")
    journey_df.to_sql("user_journey", engine, if_exists="append", index=False, chunksize=5000)

    print(f"Inserting {len(trans_df):,} rows → trans_log")
    trans_df.to_sql("trans_log", engine, if_exists="append", index=False, chunksize=5000)

    print(f"Inserting {len(pom_df):,} rows → pom_acr")
    pom_df.to_sql("pom_acr", engine, if_exists="append", index=False, chunksize=5000)

    with engine.connect() as conn:
        rows = {
            t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            for t in ("user_profile", "user_journey", "trans_log", "pom_acr")
        }
        cf_count = conn.execute(
            text("SELECT COUNT(*) FROM pom_acr WHERE fraud_type='CF'")
        ).scalar() or 0
        fraud_users = conn.execute(
            text("SELECT COUNT(DISTINCT userID) FROM pom_acr")
        ).scalar() or 0

    print()
    print("Done.")
    for t, n in rows.items():
        print(f"  {t:14s}: {n:,} rows")
    print(f"  pom_acr CF only : {cf_count:,}")
    print(f"  distinct fraud users in pom_acr : {fraud_users}")


if __name__ == "__main__":
    sys.exit(seed())
