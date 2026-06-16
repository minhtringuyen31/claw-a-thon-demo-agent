"""ingest_node — parse raw report (email / post-mortem) into FraudContext.

The report carries a TABLE of reported fraud cases whose schema matches
`pom_acr` (appID, userID, transID, reqDate, userChargeAmount,
integratedChannel, bankCode, bankType, fraud_type, appName, reportCat, ...).
We extract those rows verbatim — keys mirror the source columns — plus the
surrounding context (severity, time_hint, raw_summary).

Prompt is built from four sections to keep behavior debuggable:

    ROLE      who the model is and what it returns
    SCHEMA    the exact JSON shape (mirrors FraudContext)
    RULES     do/don't list — how to extract the case table, when to default
    EXAMPLES  two few-shot pairs (email + post-mortem) to lock the format
"""
from __future__ import annotations

from app.llm import get_llm
from app.state import AgentState, FraudContext


_ROLE = (
    "You are a senior fraud-report parser at a Vietnamese fintech. "
    "Reports arrive either as an internal email or as a post-mortem record. "
    "Each report contains a TABLE of reported fraud cases whose columns "
    "match the production `pom_acr` schema. Extract that table verbatim "
    "plus the surrounding context."
)


_SCHEMA = (
    "Return ONLY a JSON object with this exact shape:\n"
    "{\n"
    '  "reported_cases": [ { ...case fields... }, ... ]   # one dict per row\n'
    '  "severity":       "low" | "medium" | "high" | "critical"\n'
    '  "time_hint":      string | null   # natural-language window, e.g. "last 90 days"\n'
    '  "raw_summary":    string          # one Vietnamese sentence summarising the report\n'
    "}"
)


_RULES = (
    "Rules:\n"
    "1. reported_cases mirrors the data table in the report. ONE dict per "
    "row. Use the EXACT column / field names from the source as keys "
    "(camelCase or snake_case — copy verbatim). Do NOT rename columns and "
    "do NOT invent fields. If the report has no table, return an empty list.\n"
    "2. Copy values verbatim. Numbers stay numeric, dates stay as written "
    "in the source. null when the cell is empty / missing.\n"
    "3. fraud_type belongs INSIDE each row (it is a column of pom_acr). "
    "Do NOT lift it to the top level.\n"
    "4. severity is judged from stated impact: critical = losses > 100M VND "
    "or > 10 cases; high = repeat incident or named cases > 3; medium = "
    "isolated suspicious activity; low = FYI / monitoring request.\n"
    "5. time_hint: copy the analyst's wording (\"last 90 days\", \"Q1 2026\", "
    "\"từ tháng 3\"). null when not specified.\n"
    "6. raw_summary: ONE Vietnamese sentence. Mention the fraud mechanism "
    "(based on fraud_type code + channel/bankType) and the targeted asset.\n"
    "7. Reports may be in Vietnamese, English, or mixed. Parse both. The "
    "summary itself stays Vietnamese.\n"
    "8. Output strict JSON only — no markdown fences, no commentary."
)


_EXAMPLE_EMAIL_IN = (
    "Source: email\n\n"
    "Raw report:\n"
    "From: fraud-ops@company.vn\n"
    "Subject: [URGENT] Chargeback spike — please profile\n\n"
    "Team, please analyse the following 3 confirmed CF cases in the last "
    "90 days and propose a detection rule.\n\n"
    "| appID | pmcID | transType | transID | reqDate | userChargeAmount | integratedChannel | bankCode | bankType | fraud_type | appName | reportCat |\n"
    "|-------|-------|-----------|---------|---------|------------------|-------------------|----------|----------|------------|---------|-----------|\n"
    "| 149 | 36 | 15 | 250103000921213 | 2026-01-03 12:28:47 | 10000000 | CREDIT CARD | ZPCC | international | CF | Mobile Payment | Game |\n"
    "| 356 | 39 | 15 | 250106000523652 | 2026-01-06 09:45:47 | 6000000 | domestic_napas | ZPVCB | domestic_napas | CF | TIKI.VN.GW | Marketplace |\n"
    "| 3677 | 36 | 15 | 250110000470409 | 2026-01-10 09:09:15 | 5299000 | CREDIT CARD | ZPCC | international | CF | Roblox | Game |"
)

_EXAMPLE_EMAIL_OUT = (
    "{\n"
    '  "reported_cases": [\n'
    '    {"appID": 149, "pmcID": 36, "transType": 15, "transID": "250103000921213", '
    '"reqDate": "2026-01-03 12:28:47", "userChargeAmount": 10000000, '
    '"integratedChannel": "CREDIT CARD", "bankCode": "ZPCC", '
    '"bankType": "international", "fraud_type": "CF", '
    '"appName": "Mobile Payment", "reportCat": "Game"},\n'
    '    {"appID": 356, "pmcID": 39, "transType": 15, "transID": "250106000523652", '
    '"reqDate": "2026-01-06 09:45:47", "userChargeAmount": 6000000, '
    '"integratedChannel": "domestic_napas", "bankCode": "ZPVCB", '
    '"bankType": "domestic_napas", "fraud_type": "CF", '
    '"appName": "TIKI.VN.GW", "reportCat": "Marketplace"},\n'
    '    {"appID": 3677, "pmcID": 36, "transType": 15, "transID": "250110000470409", '
    '"reqDate": "2026-01-10 09:09:15", "userChargeAmount": 5299000, '
    '"integratedChannel": "CREDIT CARD", "bankCode": "ZPCC", '
    '"bankType": "international", "fraud_type": "CF", '
    '"appName": "Roblox", "reportCat": "Game"}\n'
    "  ],\n"
    '  "severity": "high",\n'
    '  "time_hint": "last 90 days",\n'
    '  "raw_summary": "Chargeback fraud diện rộng trên cả thẻ quốc tế và domestic-napas, '
    'liên quan nhiều app game/marketplace."\n'
    "}"
)

_EXAMPLE_POSTMORTEM_IN = (
    "Source: postmortem\n\n"
    "Raw report:\n"
    "Incident: INC-2026-0042\n"
    "Summary: SIM swap dẫn tới rút tiền không phép qua ví điện tử\n"
    "Record:\n"
    "{\n"
    '  "incident_id": "INC-2026-0042",\n'
    '  "window": "tháng 5/2026",\n'
    '  "cases": [\n'
    '    {"appID": 5210, "pmcID": 39, "transType": 15, "transID": "260504001200055", '
    '"reqDate": "2026-05-04 02:14:00", "userChargeAmount": 22000000, '
    '"integratedChannel": "EWALLET", "bankCode": "ZPMB", '
    '"bankType": "domestic_napas", "fraud_type": "SS", '
    '"appName": "Zalo Pay", "reportCat": "Finance"},\n'
    '    {"appID": 5210, "pmcID": 39, "transType": 15, "transID": "260509001750102", '
    '"reqDate": "2026-05-09 03:48:31", "userChargeAmount": 18000000, '
    '"integratedChannel": "EWALLET", "bankCode": "ZPMB", '
    '"bankType": "domestic_napas", "fraud_type": "SS", '
    '"appName": "Zalo Pay", "reportCat": "Finance"}\n'
    "  ]\n"
    "}"
)

_EXAMPLE_POSTMORTEM_OUT = (
    "{\n"
    '  "reported_cases": [\n'
    '    {"appID": 5210, "pmcID": 39, "transType": 15, "transID": "260504001200055", '
    '"reqDate": "2026-05-04 02:14:00", "userChargeAmount": 22000000, '
    '"integratedChannel": "EWALLET", "bankCode": "ZPMB", '
    '"bankType": "domestic_napas", "fraud_type": "SS", '
    '"appName": "Zalo Pay", "reportCat": "Finance"},\n'
    '    {"appID": 5210, "pmcID": 39, "transType": 15, "transID": "260509001750102", '
    '"reqDate": "2026-05-09 03:48:31", "userChargeAmount": 18000000, '
    '"integratedChannel": "EWALLET", "bankCode": "ZPMB", '
    '"bankType": "domestic_napas", "fraud_type": "SS", '
    '"appName": "Zalo Pay", "reportCat": "Finance"}\n'
    "  ],\n"
    '  "severity": "critical",\n'
    '  "time_hint": "tháng 5/2026",\n'
    '  "raw_summary": "SIM swap chiếm OTP, đối tượng rút tiền qua ví điện tử '
    'với hai giao dịch đêm tổng 40M VND."\n'
    "}"
)

_EXAMPLES = (
    "Examples:\n\n"
    "INPUT:\n" + _EXAMPLE_EMAIL_IN + "\n\nOUTPUT:\n" + _EXAMPLE_EMAIL_OUT
    + "\n\n---\n\n"
    "INPUT:\n" + _EXAMPLE_POSTMORTEM_IN + "\n\nOUTPUT:\n"
    + _EXAMPLE_POSTMORTEM_OUT
)


SYSTEM = "\n\n".join([_ROLE, _SCHEMA, _RULES, _EXAMPLES])


def ingest_node(state: AgentState) -> dict:
    llm = get_llm(role="ingest")
    user = (
        f"Source: {state['source_type']}\n\n"
        f"Raw report:\n{state['raw_input']}"
    )
    ctx = FraudContext(**llm.complete_json(SYSTEM, user))
    return {
        "fraud_context": ctx.model_dump(mode="json"),
        "iteration_count": 0,
        "hypotheses": [],
    }
