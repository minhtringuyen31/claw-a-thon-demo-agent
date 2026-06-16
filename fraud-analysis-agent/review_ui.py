"""Minimal Streamlit viewer for the Risk Analysis Agent.

Read-only — no approve/reject flow. The agent runs end-to-end without a
human gate; this UI just lets a strategist inspect the final
`investigation_report` and `rule_json` policy suggestion.

Run (from the fraud-analysis-agent directory, with the service running):

    AGENT_URL=http://localhost:8000 uv run streamlit run review_ui.py
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Risk Agent Report",
    page_icon=":mag:",
    layout="wide",
)
st.title("Risk Analysis Agent — Report Viewer")
st.caption(f"Connected to: `{AGENT_URL}`")


def _list_runs() -> list[str]:
    try:
        r = httpx.get(f"{AGENT_URL}/runs", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Could not list runs: {e}")
        return []


def _get_run(run_id: str) -> dict | None:
    try:
        r = httpx.get(f"{AGENT_URL}/runs/{run_id}", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Could not load run {run_id}: {e}")
        return None


with st.sidebar:
    st.header("Runs")
    if st.button("Refresh", use_container_width=True):
        st.rerun()
    run_ids = _list_runs()
    if not run_ids:
        st.info("No runs yet. POST to /runs or /triggers/email to start one.")
        selected = None
    else:
        selected = st.radio("Select a run", run_ids, index=len(run_ids) - 1)

    st.divider()
    st.subheader("Trigger a test run")
    sample_body = st.text_area(
        "Email body",
        value=(
            "3 confirmed CF cases this week on international card. "
            "Please profile and propose a detection rule."
        ),
        height=120,
    )
    if st.button("POST /triggers/email", use_container_width=True):
        try:
            r = httpx.post(
                f"{AGENT_URL}/triggers/email",
                json={
                    "subject": "Suspicious CF spike",
                    "sender": "fraud-ops@company.vn",
                    "body": sample_body,
                },
                timeout=15,
            )
            r.raise_for_status()
            st.success(f"Started run {r.json()['run_id']}")
            st.rerun()
        except Exception as e:
            st.error(f"Trigger failed: {e}")


if not selected:
    st.stop()

run = _get_run(selected)
if not run:
    st.stop()

status = run["status"]
badge = {
    "running":   ":hourglass_flowing_sand: running",
    "completed": ":white_check_mark: completed",
    "failed":    ":x: failed",
}.get(status, status)

c1, c2 = st.columns(2)
c1.metric("Status", badge)
report = run.get("investigation_report") or {}
c2.metric("Iterations", report.get("iteration_count", "—"))

# ----- Anomaly check ------------------------------------------------------

decision = run.get("anomaly_decision") or {}
if decision:
    st.subheader("Anomaly check")
    a, b = st.columns(2)
    a.metric(
        "Anomalous",
        ":white_check_mark: yes" if decision.get("is_anomalous") else ":no_entry_sign: no",
    )
    b.metric("Confidence", f"{decision.get('confidence', 0):.2f}")
    if decision.get("reasoning"):
        st.write(decision["reasoning"])
    evidence = decision.get("evidence") or []
    if evidence:
        st.markdown("**Evidence**")
        st.json(evidence)

# ----- No-action branch ---------------------------------------------------

no_action = run.get("no_action_report")
if no_action:
    st.subheader("No-action report")
    st.info(no_action.get("recommendation", ""))
    with st.expander("Full no-action payload"):
        st.json(no_action)

# ----- Investigation report ----------------------------------------------

if report:
    st.subheader("Investigation report")
    a, b, c = st.columns(3)
    a.metric("Stop reason", report.get("stop_reason", "—"))
    a.metric(
        "Patterns attempted",
        len(report.get("patterns_attempted") or []),
    )

    final = report.get("final_pattern")
    if final:
        st.markdown("### Final pattern")
        st.write(final.get("description", ""))
        m = final.get("metrics") or {}
        a, b, c, d = st.columns(4)
        a.metric("Precision", f"{m.get('precision', 0):.3f}")
        b.metric("Recall", f"{m.get('recall', 0):.3f}")
        c.metric("F1", f"{m.get('f1', 0):.3f}")
        d.metric("Action", final.get("recommended_action", "—"))
        if final.get("sql_predicate"):
            st.code(final["sql_predicate"], language="sql")
        if final.get("rationale"):
            st.info(final["rationale"])

    if report.get("recommendation"):
        st.success(report["recommendation"])

    st.markdown("### All attempts")
    for p in report.get("patterns_attempted") or []:
        m = p.get("metrics") or {}
        status_label = p.get("status", "candidate")
        with st.expander(
            f"#{p.get('iteration', '?')} · {status_label.upper()} · {p.get('description', '(no description)')}"
        ):
            cols = st.columns(4)
            cols[0].metric("Precision", f"{m.get('precision', 0):.3f}" if m else "—")
            cols[1].metric("Recall", f"{m.get('recall', 0):.3f}" if m else "—")
            cols[2].metric("F1", f"{m.get('f1', 0):.3f}" if m else "—")
            cols[3].metric("Action", p.get("recommended_action", "—"))
            if p.get("sql_predicate"):
                st.code(p["sql_predicate"], language="sql")
            if p.get("rationale"):
                st.write("**Rationale:**", p["rationale"])
            if p.get("notes"):
                st.write("**Notes:**", p["notes"])

    st.markdown("### ReAct trace")
    for step in report.get("investigation_log") or []:
        with st.expander(
            f"Iter {step.get('iteration', '?')} · {step.get('tool', '—')}"
        ):
            if step.get("plan_thought"):
                st.write("**Plan:**", step["plan_thought"])
            if step.get("hypothesis_being_tested"):
                st.write(
                    "**Hypothesis:**", step["hypothesis_being_tested"]
                )
            st.write("**Args:**")
            st.json(step.get("args") or {})
            st.write("**Observation:**")
            st.json(step.get("observation") or {})
            if step.get("next_thought"):
                st.write("**Next thought:**", step["next_thought"])

# ----- Policy suggestion --------------------------------------------------

if run.get("rule_json"):
    st.subheader("Policy suggestion (RuleJSON)")
    st.json(run["rule_json"])
