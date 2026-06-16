"""Mock fraud-warehouse data generator — 4 coherent tables.

Produces:
  user_profile  : 1 row per userID (identity + KYC/NFC + trust flags)
  user_journey  : append-only event log per user (register/login/eKYC/...)
  trans_log     : all transactions
  pom_acr       : confirmed-fraud subset (trans_log + fraud_type, report_date, is_loss)

`seed_mysql.py` calls `generate()` and bulk-inserts into MySQL.

------------------------------------------------------------------------
PLANTED SCENARIO — "International CF wave on freshly-onboarded accounts"
------------------------------------------------------------------------

50 fraud users (userID 1-50):
  - account_created_date in last 3-21 days (recent onboarding)
  - ekyc_status = passed (same day as account creation)
  - nfc_status  = none (NEVER did NFC)
  - cccd_hash   shared (every 5 fraud users share 1 CCCD → 10 distinct CCCDs)
  - linked_bank = 1, linked_card = 1, trusted_user = 0
  - journey events (BEFORE their first fraud trans):
      register → login → ekyc      (at account creation)
      change_device      1-72h before first fraud trans
      login_new_device   1-24h before
      map_card           1-24h before
      30% have reset_pin 1-24h before
      20% have change_phone within 7 days
  - 5-15 fraud transactions each:
      bankType = international, integratedChannel = CREDIT CARD,
      bankCode = ZPCC, pmcID = 36,
      userChargeAmount in {5M, 8M, 12M, 20M, 30M} ± 5%,
      hour ∈ {0,1,2,3,4,22,23} (mostly night),
      fraud_type = CF, source = "[bank_dispute]", is_loss = 1

950 good users (userID 51-1000):
  - account_created_date spread over last 365 days
  - 70% eKYC passed, 50% NFC passed
  - CCCD mostly unique (~5% shared)
  - varied trust flags
  - normal journey events (logins, occasional map_card / map_bank)
  - 15-30 transactions over last 60 days:
      bankType ~ 50% domestic_napas / 35% domestic_direct / 15% international,
      channel/bank varied,
      amount distribution weighted toward 50K-3M,
      hour uniform 0-23
  - background fraud noise ~0.1%

Discoverable patterns (precision increasing):
  1. bankType=international + userChargeAmount >= 5M
     → moderate precision (some good users also do international high-value)
  2. + account_age <= 7d
     → much higher precision (KB §6 user_profile join)
  3. + mapcard_age <= 24h
     → highest precision (KB §7.5 journey + map_card combine)
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pandas as pd

# ---------------- configuration ----------------

N_FRAUD_USERS = 50
N_GOOD_USERS = 950
TODAY = date(2026, 6, 13)
TRANS_WINDOW_DAYS = 60

APPS = [
    (148, "Payment Direct", "Game"),
    (149, "Mobile Payment", "Game"),
    (356, "TIKI.VN.GW", "Marketplace"),
    (2391, "The giai tri", "Telco"),
    (3677, "Roblox", "Game"),
    (3555, "DEALTODAY", "Entertainment"),
    (4012, "Shopee", "Marketplace"),
    (4118, "Lazada", "Marketplace"),
    (5001, "Grab", "Transportation"),
    (5210, "Zalo Pay", "Finance"),
]

BANKS = [
    ("ZPVCB", "domestic_napas"),
    ("ZPTCB", "domestic_napas"),
    ("ZPACB", "domestic_direct"),
    ("ZPMB", "domestic_napas"),
    ("ZPTPB", "domestic_direct"),
    ("ZPCC", "international"),
]
GOOD_CHANNELS = ["domestic_napas", "CREDIT CARD", "ATM-API", "QR-CODE", "EWALLET"]
GOOD_AMOUNT_BUCKETS = [50_000, 200_000, 500_000, 1_000_000, 3_000_000,
                       6_500_000, 12_000_000, 30_000_000]
GOOD_AMOUNT_WEIGHTS = [8, 8, 6, 5, 4, 3, 2, 1]
FRAUD_AMOUNT_BUCKETS = [5_000_000, 8_000_000, 12_000_000, 20_000_000, 30_000_000]
FRAUD_HOURS = [0, 1, 2, 3, 4, 22, 23]


# ---------------- helpers ----------------

def _phone(uid: int) -> str:
    return f"09{uid:08d}"


def _cccd_fraud(uid: int) -> str:
    return f"CCCD_F_{(uid - 1) // 5:02d}"   # 5 fraud users per CCCD


def _cccd_good(uid: int) -> str:
    return (
        f"CCCD_G_SHARED_{uid % 100:03d}"
        if random.random() < 0.05
        else f"CCCD_G_{uid:05d}"
    )


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _ts(d: date, hour: int | None = None) -> datetime:
    h = hour if hour is not None else random.randint(0, 23)
    return datetime.combine(d, datetime.min.time()) + timedelta(
        hours=h, minutes=random.randint(0, 59), seconds=random.randint(0, 59)
    )


# ---------------- user_profile ----------------

def _generate_user_profile() -> pd.DataFrame:
    rows: list[dict] = []

    # 50 fraud users — recently onboarded, non-NFC, shared CCCDs
    for uid in range(1, N_FRAUD_USERS + 1):
        created = TODAY - timedelta(days=random.randint(3, 21))
        rows.append({
            "userID": uid,
            "account_created_date": created,
            "ekyc_status": "passed",
            "ekyc_date": created,
            "nfc_status": "none",
            "nfc_date": None,
            "dob_year": random.choice([1995, 1996, 1997, 1998, 1999, 2000, 2001]),
            "phone": _phone(uid),
            "cccd_hash": _cccd_fraud(uid),
            "linked_bank": 1,
            "linked_card": 1,
            "has_credit_limit": 0,
            "has_mmf": 0,
            "trusted_user": 0,
            "whitelist": 0,
            "blacklist": 0,
            "historical_fraud": 0,
        })

    # 950 good users — diverse profile
    for uid in range(N_FRAUD_USERS + 1, N_FRAUD_USERS + N_GOOD_USERS + 1):
        created = TODAY - timedelta(days=random.randint(1, 365))
        ekyc_passed = random.random() < 0.70
        nfc_passed = random.random() < 0.50
        rows.append({
            "userID": uid,
            "account_created_date": created,
            "ekyc_status": "passed" if ekyc_passed else random.choice(["pending", "failed"]),
            "ekyc_date": (
                created + timedelta(days=random.randint(0, 30))
                if ekyc_passed else None
            ),
            "nfc_status": "passed" if nfc_passed else random.choice(["pending", "none"]),
            "nfc_date": (
                created + timedelta(days=random.randint(0, 60))
                if nfc_passed else None
            ),
            "dob_year": random.randint(1970, 2005),
            "phone": _phone(uid),
            "cccd_hash": _cccd_good(uid),
            "linked_bank": 1 if random.random() < 0.85 else 0,
            "linked_card": 1 if random.random() < 0.75 else 0,
            "has_credit_limit": 1 if random.random() < 0.25 else 0,
            "has_mmf": 1 if random.random() < 0.05 else 0,
            "trusted_user": 1 if random.random() < 0.30 else 0,
            "whitelist": 1 if random.random() < 0.10 else 0,
            "blacklist": 0,
            "historical_fraud": 1 if random.random() < 0.01 else 0,
        })

    return pd.DataFrame(rows)


# ---------------- user_journey ----------------

def _generate_user_journey(profile_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return (journey_df, first_fraud_trans_day_by_uid).

    The map_card / login_new_device / change_device timestamps are anchored
    to each fraud user's *first fraud transaction day* so the journey-vs-trans
    pattern is exact.
    """
    events: list[dict] = []
    first_fraud_day: dict[int, date] = {}

    for _, u in profile_df.iterrows():
        uid = int(u["userID"])
        is_fraud = uid <= N_FRAUD_USERS
        created: date = u["account_created_date"]

        # baseline events for everyone
        events.append({"userID": uid, "event_type": "register", "event_time": _ts(created)})
        events.append({"userID": uid, "event_type": "login", "event_time": _ts(created)})
        if u["ekyc_status"] == "passed" and u["ekyc_date"] is not None:
            events.append({"userID": uid, "event_type": "ekyc", "event_time": _ts(u["ekyc_date"])})
        if u["nfc_status"] == "passed" and u["nfc_date"] is not None:
            events.append({"userID": uid, "event_type": "nfc", "event_time": _ts(u["nfc_date"])})

        if is_fraud:
            # Anchor: first fraud trans day = account_created + 1..5 days
            anchor = created + timedelta(days=random.randint(1, 5))
            if anchor > TODAY:
                anchor = TODAY - timedelta(days=1)
            first_fraud_day[uid] = anchor
            anchor_dt = datetime.combine(anchor, datetime.min.time())

            events.append({"userID": uid, "event_type": "change_device",
                           "event_time": anchor_dt - timedelta(hours=random.randint(1, 72))})
            events.append({"userID": uid, "event_type": "login_new_device",
                           "event_time": anchor_dt - timedelta(hours=random.randint(1, 24))})
            events.append({"userID": uid, "event_type": "map_card",
                           "event_time": anchor_dt - timedelta(hours=random.randint(1, 24))})
            if random.random() < 0.30:
                events.append({"userID": uid, "event_type": "reset_pin",
                               "event_time": anchor_dt - timedelta(hours=random.randint(1, 24))})
            if random.random() < 0.20:
                events.append({"userID": uid, "event_type": "change_phone",
                               "event_time": anchor_dt - timedelta(days=random.randint(1, 7))})
        else:
            # Good users — sprinkle logins + occasional map events
            for _ in range(random.randint(5, 20)):
                d = TODAY - timedelta(days=random.randint(0, TRANS_WINDOW_DAYS))
                events.append({"userID": uid, "event_type": "login", "event_time": _ts(d)})
            if u["linked_card"]:
                d = created + timedelta(days=random.randint(0, 90))
                events.append({"userID": uid, "event_type": "map_card", "event_time": _ts(d)})
            if u["linked_bank"]:
                d = created + timedelta(days=random.randint(0, 60))
                events.append({"userID": uid, "event_type": "map_bank", "event_time": _ts(d)})
            if random.random() < 0.10:
                d = TODAY - timedelta(days=random.randint(0, TRANS_WINDOW_DAYS))
                events.append({"userID": uid, "event_type": "login_new_device", "event_time": _ts(d)})

    return pd.DataFrame(events), first_fraud_day


# ---------------- trans_log + pom_acr ----------------

def _trans_common(uid: int, app_id: int, app_name: str, report_cat: str,
                  bank_code: str, bank_type: str, channel: str,
                  amount: int, req_dt: datetime, is_fraud: bool,
                  pmc_id: int) -> dict:
    return {
        "appID": app_id,
        "userID": uid,
        "transID": f"{req_dt.strftime('%y%m%d')}{'F' if is_fraud else 'G'}{uid:05d}{random.randint(0, 99999):05d}",
        "reqDate": req_dt,
        "transStatus": 1,
        "userChargeAmount": amount,
        "source": "[bank_dispute]" if is_fraud else "",
        "integratedChannel": channel,
        "is_kyc": "gw",
        "transType": 15,
        "map_type": "gw",
        "bankconnectorcode": "",
        "bankCode": bank_code,
        "pmcID": pmc_id,
        "paymentSolution": "",
        "month": req_dt.strftime("%Y-%m"),
        "week": _week_start(req_dt.date()),
        "bankType": bank_type,
        "appName": app_name,
        "reportCat": report_cat,
        "appID_appName": f"{app_id}_{app_name}",
    }


def _generate_trans(profile_df: pd.DataFrame,
                    first_fraud_day: dict[int, date],
                    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    trans_rows: list[dict] = []
    pom_rows: list[dict] = []

    for _, u in profile_df.iterrows():
        uid = int(u["userID"])
        is_fraud_user = uid <= N_FRAUD_USERS
        created: date = u["account_created_date"]

        if is_fraud_user:
            # 5-15 fraud trans starting from anchor day, all CF
            anchor = first_fraud_day.get(uid, created + timedelta(days=1))
            n = random.randint(5, 15)
            for _ in range(n):
                # spread 0-3 days after anchor
                trans_day = anchor + timedelta(days=random.randint(0, 3))
                if trans_day > TODAY:
                    trans_day = TODAY
                hour = random.choice(FRAUD_HOURS)
                req_dt = _ts(trans_day, hour=hour)
                base = random.choice(FRAUD_AMOUNT_BUCKETS)
                amount = base + random.randint(-int(base * 0.05), int(base * 0.05))
                app_id, app_name, report_cat = random.choice(APPS)
                row = _trans_common(
                    uid, app_id, app_name, report_cat,
                    bank_code="ZPCC", bank_type="international",
                    channel="CREDIT CARD", amount=amount, req_dt=req_dt,
                    is_fraud=True, pmc_id=36,
                )
                trans_rows.append(row)
                pom_rows.append({
                    **row,
                    "fraud_type": "CF",
                    "report_date": (req_dt + timedelta(days=random.randint(3, 30))).date(),
                    "is_loss": 1,
                })
        else:
            # 15-30 normal trans
            window_start = max(TODAY - timedelta(days=TRANS_WINDOW_DAYS), created)
            window_days = (TODAY - window_start).days
            if window_days <= 0:
                continue
            n = random.randint(15, 30)
            for _ in range(n):
                trans_day = window_start + timedelta(days=random.randint(0, window_days))
                req_dt = _ts(trans_day)
                bank_code, bank_type = random.choice(BANKS)
                if bank_type == "international":
                    channel = "CREDIT CARD"
                else:
                    channel = random.choices(GOOD_CHANNELS, weights=[6, 1, 3, 4, 2])[0]
                base = random.choices(GOOD_AMOUNT_BUCKETS, weights=GOOD_AMOUNT_WEIGHTS)[0]
                amount = max(1_000, base + random.randint(-int(base * 0.05), int(base * 0.05)))
                app_id, app_name, report_cat = random.choice(APPS)
                is_bg_fraud = random.random() < 0.001
                row = _trans_common(
                    uid, app_id, app_name, report_cat,
                    bank_code=bank_code, bank_type=bank_type,
                    channel=channel, amount=amount, req_dt=req_dt,
                    is_fraud=is_bg_fraud,
                    pmc_id=36 if bank_type == "international" else 39,
                )
                trans_rows.append(row)
                if is_bg_fraud:
                    pom_rows.append({
                        **row,
                        "fraud_type": random.choice(["CF", "AT", "PH", "SS"]),
                        "report_date": (req_dt + timedelta(days=random.randint(3, 30))).date(),
                        "is_loss": 1,
                    })

    return pd.DataFrame(trans_rows), pd.DataFrame(pom_rows)


# ---------------- public API ----------------

def generate(
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (profile_df, journey_df, trans_df, pom_df) — all 4 coherent."""
    random.seed(seed)
    profile_df = _generate_user_profile()
    journey_df, first_fraud_day = _generate_user_journey(profile_df)
    trans_df, pom_df = _generate_trans(profile_df, first_fraud_day)
    return profile_df, journey_df, trans_df, pom_df


if __name__ == "__main__":
    profile_df, journey_df, trans_df, pom_df = generate()
    print(f"user_profile : {len(profile_df):,} rows  ({N_FRAUD_USERS} fraud + {N_GOOD_USERS} good)")
    print(f"user_journey : {len(journey_df):,} events")
    print(f"trans_log    : {len(trans_df):,} transactions")
    print(f"pom_acr      : {len(pom_df):,} confirmed fraud  ({len(pom_df) / len(trans_df) * 100:.2f}%)")
    print()
    print("pom_acr by fraud_type:")
    print(pom_df["fraud_type"].value_counts().to_string())
    print()
    print("pom_acr by bankType:")
    print(pom_df["bankType"].value_counts().to_string())
    print()
    print("journey events by type:")
    print(journey_df["event_type"].value_counts().to_string())
