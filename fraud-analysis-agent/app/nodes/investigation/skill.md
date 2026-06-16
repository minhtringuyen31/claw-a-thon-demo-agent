# Investigation Skill — How to Run the ReAct Loop

> Procedural rules + priorities + meta-principles + a worked example.
> Pair this with `investigation_kb.md` (catalogs, thresholds, templates).
> Edit freely — code does not parse this body.

---

## 1. Master thinking flow (13 steps)

Always start at step 1 and only progress when the previous step did not
yield a passing rule. **Do NOT combine multiple data sources before a
simple translog-only rule has been scored.**

| Step | What to do |
|---|---|
| 1 | Identify exact fraud scope from anomaly evidence |
| 2 | Pull fraud transID list inside that scope |
| 3 | Join fraud transID with `trans_log` to get full transaction detail |
| 4 | Build base population (same filter, wider window — default D-30) |
| 5 | From translog only, look for simple patterns (velocity, amount, count, fail, interval, device, IP, card, BIN, merchant) |
| 6 | Generate candidate rule(s) from translog |
| 7 | Score precision / recall / fraud amount recall / business impact on base population |
| 8 | If translog-only rule misses, join `user_profile` for identity / KYC patterns |
| 9 | Generate combined translog + profile rule |
| 10 | If still not enough, join `user_journey` for events before transaction |
| 11 | Generate combined velocity + profile + journey rule |
| 12 | Choose best rule(s) and recommend an action |
| 13 | If nothing passes → declare "not enough pattern", do **not** force a weak rule |

---

## 2. Step 1 — Fraud scope discipline

- **Filter first, breakdown second.** Do not query all-system fraud when
  the anomaly is limited to a slice.
- Dispatch table:

| Anomaly dimension | Filter on it → then breakdown |
|---|---|
| `appID` | pmcID, source of fund, BIN, issuer bank, amount band, user segment |
| pmcID / payment method | appID, merchant, BIN, source of fund, userID, device, IP |
| BIN | appID, merchant, pmcID, issuer bank, userID, device, IP |
| merchant/appID + source of fund | already 2-dim; treat as the scope |

- Output the scope explicitly: filter condition, time range, fraud transID
  count, fraud amount, fraud user count.

---

## 3. Step 2 picking time windows (Section 6.2)

| Need | Default window |
|---|---|
| Monthly impact analysis | D-30 |
| Fraud spiked fast — short-term analysis | D-7 |
| D-30 sample too small | D-60 / D-90 |

---

## 4. Step 3 — translog interrogation checklist

After joining fraud transID with translog, ask:

- Which appID / merchant / SOF dominates?
- Domestic card vs international vs wallet balance?
- Which BIN / issuer bank concentrates?
- Which amount band? Which hour-of-day band?
- New users vs. returning users?
- Many fails before successes?
- Many txns in short interval?
- Multiple users sharing device / IP / card / BIN?
- Has any existing rule already hit?

---

## 5. Rule selection priority (Section 10.3)

When choosing between candidate rules:

1. Precision high enough to avoid hurting good users.
2. Fraud amount recall is good.
3. Business impact is low.
4. Rule is simple and easy to implement.
5. Rule is easy to explain.
6. Rule can apply at the right checkpoint.
7. Threshold can be tuned after monitoring.

**Tie-breakers** between rules of similar quality:
- Fewer conditions wins.
- Lower good-user impact wins.
- Higher fraud-amount recall wins.

---

## 6. When translog-only is not enough (Step 7)

Diagnose by checking:
- Fraud too dispersed.
- Velocity is not distinct vs. good users.
- Fraud amount / count not distinct from good users.
- Fraud + good users share merchant / SOF.
- Need identity (profile) or behavior-before (journey) to separate.

Then escalate to user_profile.

---

## 7. user_profile join procedure (Step 8)

- Join base population (both fraud AND good users) with `user_profile`.
  Comparing only fraud users is meaningless; you need the good baseline.
- Refer to KB §6 for metric families + rule templates.
- Acceptance: KB §6.3.

---

## 8. Journey escalation triggers (Step 9)

Escalate to `user_journey` when any of:
- Fraud relates to account takeover.
- Fraud occurs right after: change phone, reset PIN, add card / map bank,
  eKYC / NFC, login new device, register.
- Fraud has no strong velocity but suspicious journey events appear
  before the transaction.

---

## 9. Look-ahead bias safeguard (Step 10)

**Critical safety rule.** When joining `user_journey`:
- Only use events whose timestamp is **strictly before** transaction time.
- Compute `time_since_<event>` rather than raw event flag.
- Never reference events that occurred after the transaction — that
  pollutes evaluation with future knowledge.

---

## 10. When to declare "no pattern" (Step 13 / §17.5)

If after exhausting translog → profile → journey, no rule passes the KB
acceptance criteria, the agent must NOT propose a weak rule. Conclude:

- "Chưa đủ pattern để tạo hard rule. Các rule đã test không đạt
  precision/recall yêu cầu."

And recommend:
- Monitor 3-7 days.
- Tag cases to collect more labels.
- Use challenge instead of reject if some control is still needed.
- Add data: device / IP / card fingerprint / journey if currently missing.
- Escalate to human review if fraud amount keeps rising.

---

## 11. Hard meta-principles (Section 18)

These are **non-negotiable**:

1. Always go **simple → complex** — do not combine many conditions if a
   simple rule is already good enough.
2. Never look only at the fraud sample — always compare against base
   population.
3. Never judge a rule by recall alone — always compute precision and
   good-user impact.
4. Prefer rules that are easy to explain and implement.
5. Distinguish: **rule gap** vs. challenge gap vs. checkpoint gap vs.
   bypass/whitelist gap vs. data gap.
6. Always check whether fraud is currently being approved / challenged /
   rejected.
7. **Avoid look-ahead bias** with user_journey (use events before trans).
8. State the time window of every metric.
9. State the threshold of every rule.
10. State the recommended action per rule.
11. State why a rule was chosen or dropped.

---

## 12. Worked example (Section 19)

A reference reasoning chain showing how steps 1-13 play out on one case.

**Phase 1 detected:**
- Fraud at AppID X +45% vs W-1, fraud amount +180M VND.
- Concentrated on `source_of_fund = international card`.
- 70% of the increment came from 3 BINs.

**Step 1 — scope.** Filter:
`appID = X AND source_of_fund = international card AND BIN IN (b1, b2, b3)`,
time range = anomalous week.

**Step 2 — sample.** Join transID with translog, compute fraud sample
(count / amount / users / cards / devices / IPs).

**Step 3 — base population.** Same filter, D-30 window. Includes fraud +
non-fraud.

**Step 4 — test translog-only rules.** Best rule:
```
total_amount_user_24h >= 10M AND source_of_fund = international card
→ precision 68%, recall 42%, fraud amount recall 55%, good user impact 4%
```
Conclusion: recall good, precision too low. Escalate to user_profile.

**Step 5 — join user_profile.** Finding: 80% of fraud users have
`account_age <= 7d`; good users at same condition only 8%. Test rule:
```
total_amount_user_24h >= 10M AND account_age <= 7d AND SOF = international
→ precision 91%, recall 28%, fraud amount recall 43%, good user impact 0.7%
```
Conclusion: meets challenge / conditional-reject criteria.

**Step 6 — join user_journey for further refinement.** Finding: 60% of
fraud users have `mapcard_age <= 24h`. Test rule:
```
total_amount_user_24h >= 10M AND account_age <= 7d AND mapcard_age <= 24h
→ precision 96%, recall 18%, fraud amount recall 35%, good user impact 0.2%
```
Conclusion: very high precision but recall < 20% — use as targeted reject.

**Final recommendation:**

| Rule | Action | Reason |
|---|---|---|
| `SOF = intl card AND amount_24h >= 10M AND account_age <= 7d` | Challenge | P=91%, R=28%, good-user impact 0.7% |
| `SOF = intl card AND amount_24h >= 10M AND account_age <= 7d AND mapcard_age <= 24h` | Reject | P=96%, fraud amount recall 35%, good-user impact 0.2% |

**Next step:** apply at payment-authorization checkpoint. Monitor fraud
amount, challenge pass rate, false positive, TPV impact over 7 days. If
fraud shifts to a different BIN, broaden by `SOF + account_age` instead of
fixed BINs.

---

## 13. ReAct loop discipline (this codebase)

- **Tool-selection priority:** `aggregate` for shape questions →
  `query_with_filters` for inspecting raw rows → `compute_metrics` for
  scoring a candidate → `raw_sql` only when the structured tools cannot
  express the query.
- Record a `PatternAttempt` **only** after `compute_metrics`. Earlier
  iterations are exploration — keep `new_pattern_attempt = null`.
- Output discipline: strict JSON for plan / observation, args reference
  real columns in `data_schema`, Vietnamese OK in `plan_thought` /
  `next_thought` / `notes`, keep them 2-4 sentences.

## 14. HARD escalation rules (non-negotiable)

These are enforced by the router — if you ignore them the loop keeps
running anyway, so it is faster to follow them.

1. **Escalation order is mandatory.** Per KB §1:
   `translog` → `user_profile` → `user_journey`.
   - If your best `translog`-only rule has precision < the requested
     `min_precision` target, you **MUST** attempt at least one rule that
     joins `user_profile` (e.g. with `account_age`, `nfc_status`,
     `cccd_hash` multi-account) before stopping.
   - If your best `translog + user_profile` rule still has precision <
     `min_precision`, you **MUST** attempt at least one rule that joins
     `user_journey` (events `map_card`, `login_new_device`, `reset_pin`,
     `change_phone`, etc. with `TIMESTAMPDIFF(HOUR, ...) <= 24` style
     conditions).

2. **`stop = true` is allowed ONLY if at least one of:**
   - You already have a pattern whose actual `precision ≥ 0.95` (very
     strong rule — even a translog-only one qualifies). OR
   - You have scored at least one rule using `user_profile` AND one rule
     using `user_journey`. OR
   - You explicitly conclude "no pattern available" after exhausting all
     three data sources.

3. **Threshold target lives in `threshold_target` in the user message.**
   Do not mark your own attempt `status="passed"` — the router uses the
   actual metrics. Be honest in `rationale`/`notes`.

4. **Action mapping is per KB §8.** A rule with `precision < 0.9` is
   *not* a Reject rule. A rule with `recall < 0.2` is not a Challenge
   rule either — it is a *targeted* rule and only qualifies when
   `precision ≥ 0.95`.

5. **Build SQL incrementally.** Start from translog-only `sql_predicate`
   then add a `JOIN user_profile up USING(userID)` and a
   `DATEDIFF(t.reqDate, up.account_created_date) <= 7`-style condition,
   then add an `EXISTS (SELECT 1 FROM user_journey j WHERE
   j.userID = t.userID AND j.event_type = 'map_card' AND j.event_time <
   t.reqDate AND TIMESTAMPDIFF(HOUR, j.event_time, t.reqDate) <= 24)`.
   See `TOOL_REGISTRY_SPEC` for the exact JOIN snippets.
