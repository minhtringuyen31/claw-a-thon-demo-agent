---
# fetch_data_node settings.
#
# sample_size : how many rows to keep per slice (pom_acr + trans_log).
#               Trade-off: bigger sample → more context for hypothesis,
#               but bigger state + bigger prompt.
sample_size: 20
---

# Pattern-finding strategy

> This body is forwarded to `hypothesis_node` via `state["fetch_strategy_body"]`.
> Use it to tell the hypothesis model HOW to mine the targeted slices that
> fetch_data retrieves. Edit freely — code does not parse this section.

## Reasoning steps

(Replace with your own rules. Example placeholder below.)

1. For each `investigation_slice`, compare the `pom_acr` rows (confirmed
   fraud matching the filter) against the `trans_log` rows (universe
   matching the same filter).
2. Identify columns where the fraud sample's distribution diverges
   sharply from the universe — those are signal columns.
3. Propose ONE pattern per iteration, combining at most three signal
   columns. Tighten thresholds first, widen on retry to recover recall.

## Signal selection priorities

- Prefer columns that appear in the evidence `filters` (already flagged
  by anomaly_check as anomalous).
- Then check `bankType`, `bankCode`, `integratedChannel`, `pmcID`,
  `userChargeAmount`, hour-of-day.
- Avoid columns with low cardinality in the slice (e.g. only one value).

## Threshold guidance

- For numeric columns (`userChargeAmount`): use a quantile of the fraud
  sample (p25 / p50 / p95) rather than a hand-picked number.
- For categorical columns: prefer equality on a single high-loss value
  before widening to a set.
