user# Investigation Knowledge Base — Fraud Pattern Mining

> Catalog + numeric thresholds + rule templates + action mapping + output
> schema. Pure reference material — the LLM looks up values here. For HOW
> to think, see `investigation_skill.md`.

---

## 1. Data sources

| Source | Use | Priority join order |
|---|---|---|
| `trans_log` / `pom_acr` (translog family) | Transaction-level data — primary source | First |
| `user_profile` | Account identity / KYC / NFC / CCCD / FS ownership / trust profile | Second (only after translog rules underperform) |
| `user_journey` | Pre-transaction events (account takeover, change phone, reset PIN, map card/bank, eKYC/NFC) | Third (only if profile still not enough) |

### translog fields to inspect
`transID`, `userID`, `appID`, `pmcID`, `transtype`, `source of fund`,
`amount`, `transaction status` (success/fail/reject/challenge/approve),
`transaction time`, card info (first6, last4, BIN, card type, issuer bank),
`device ID`, `IP`, `platform`, `product code`, `rule hit`, `fail reason` /
bank return code.

### user_profile fields
`userID`, `account created date`, `KYC level`, `eKYC status`, `eKYC date`,
`NFC status`, `NFC date`, `DOB` / age group, `SĐT`, `CCCD/ID hash`,
ownership flags (linked bank, linked card, MMF, credit limit), trust flags
(trusted, whitelist, blacklist, historical fraud).

### user_journey events
`register`, `login`, `login new device`, `change phone`, `reset PIN`,
`map bank`, `unmap bank`, `eKYC`, `NFC`, `change device`,
`lock account`, `unlock account`.

---

## 2. Sample structures

### 2.1. Fraud sample (required fields)
`fraud_trans_count`, `fraud_amount`, `fraud_user_count`, `fraud_card_count`,
`fraud_device_count`, `fraud_ip_count`, `fraud time range`.

### 2.2. Base population
Same filter as fraud sample but wider time range.
Used for: rule hit (total + fraud + good transaction/amount/user),
precision, recall, business impact.

### 2.3. Good sample
Base population minus fraud sample. Used for FP calculation. If fraud
label is incomplete, mark precision as **estimated** and note that human
review / complaint confirmation is needed.

---

## 3. Metric catalog (translog)

### 3.1. User-level velocity

| Metric template | Candidate thresholds to test |
|---|---|
| `total_amount_user_1h` | >= 3M, 5M, 10M, 20M VND |
| `total_amount_user_24h` | >= 10M, 20M, 50M, 100M VND |
| `total_amount_user_7d` | >= 30M, 50M, 100M, 200M VND |
| `total_amount_user_30d` | >= 60M, 100M, 200M, 500M VND |
| `trans_count_user_1h` | >= 3, 5, 10 |
| `trans_count_user_24h` | >= 5, 10, 20 |
| `trans_count_user_7d` | >= 10, 20, 50 |
| `fail_count_user_1h` | >= 3, 5 |
| `fail_count_user_24h` | >= 5, 10 |
| `unique_card_user_24h` | >= 2, 3, 5 |
| `unique_merchant_user_24h` | >= 3, 5, 10 |
| `success_count_user_{1h/24h/7d/30d}` | — |
| `reject_count_user_{1h/24h/7d/30d}` | — |
| `unique_pmc_user_{24h/7d/30d}` | — |
| `unique_device_user_{24h/7d/30d}` | — |
| `unique_ip_user_{24h/7d/30d}` | — |

### 3.2. Card-level

| Metric template | Candidate thresholds |
|---|---|
| `user_count_per_card_24h` | >= 2, 3, 5 |
| `trans_count_card_1h` | >= 3, 5, 10 |
| `trans_count_card_24h` | >= 5, 10, 20 |
| `fail_count_card_1h` | >= 3, 5 |
| `total_amount_card_24h` | >= 10M, 20M, 50M |
| `same_amount_count_card_24h` | >= 3, 5, 10 |
| `device_count_per_card_{24h/7d/30d}` | — |
| `merchant_count_per_card_{24h/7d/30d}` | — |
| `card_success_after_fail_count` | — |

### 3.3. BIN-level

| Metric template | Candidate thresholds |
|---|---|
| `fraud_amount_bin_24h` | >= 30M, 50M, 100M |
| `fraud_count_bin_24h` | >= 10, 20, 50 |
| `trans_count_bin_1h` | >= 20, 50, 100 |
| `fail_rate_bin_1h` | >= 30%, 50%, 70% |
| `user_count_bin_24h` | >= 10, 20, 50 |
| `merchant_count_bin_24h` | >= 3, 5, 10 |
| `total_amount_bin_{1h/24h/7d}` | — |
| `card_count_bin_{24h/7d}` | — |
| `challenge_pass_rate_bin`, `approve_rate_bin` | — (if available) |

### 3.4. Device-level

| Metric | Candidate thresholds |
|---|---|
| `user_count_device_24h` | >= 3, 5, 10 |
| `user_count_device_7d` | >= 5, 10, 20 |
| `card_count_device_24h` | >= 2, 3, 5 |
| `trans_count_device_1h` | >= 5, 10, 20 |
| `total_amount_device_24h` | >= 10M, 20M, 50M |
| `fraud_user_count_device_7d` | >= 2, 3, 5 |

### 3.5. IP-level

| Metric | Candidate thresholds |
|---|---|
| `user_count_ip_1h` | >= 3, 5, 10 |
| `user_count_ip_24h` | >= 5, 10, 20 |
| `trans_count_ip_1h` | >= 10, 20, 50 |
| `total_amount_ip_24h` | >= 20M, 50M, 100M |
| `fraud_user_count_ip_7d` | >= 2, 3, 5 |

### 3.6. Time interval

| Metric | Candidate thresholds |
|---|---|
| `time_since_last_trans_user` | <= 30s, 60s, 3min |
| `#trans_in_5min_user` | >= 3 |
| `#trans_in_10min_user` | >= 5 |
| `#trans_in_1h_user` | >= 10 |
| `min_interval_user_1h`, `avg_interval_user_1h` | — |
| `time_since_add_card`, `time_since_mapbank`, `time_since_changephone`, `time_since_resetpin`, `time_since_register` | — (require journey) |

### 3.7. Amount pattern

| Metric | Candidate thresholds |
|---|---|
| `same_amount_count_user_24h` | >= 3, 5, 10 |
| `same_amount_count_card_24h` | >= 3, 5, 10 |
| `same_amount_count_device_24h` | >= 5 |
| `amount` near limit | 90%–100% of limit |
| `amount` round-number | 500K, 1M, 2M, 5M, 10M |
| `max_amount_user_24h` | >= 2× median amount user 30d |
| `transaction amount` | >= 3× avg amount user 30d |
| `amount_band`, `avg_amount_user_24h`, `amount_std_user_24h` | — |

---

## 4. Rule templates (translog-only — start here)

### 4.1. Amount velocity
`total_amount_{user/card/device/ip}_{1h/24h/7d/30d} >= X`

### 4.2. Count velocity
`trans_count_{user/card/device/ip}_{1h/24h} >= N`
`fail_count_{user/card}_{1h/24h} >= N`

### 4.3. Entity overlap

| Template | Default threshold |
|---|---|
| `user_count_device_24h >= N` | 3 user |
| `user_count_device_7d >= N` | 5 user |
| `user_count_ip_24h >= N` | 5 user |
| `user_count_card_24h >= N` | 3 user |
| `user_count_bin_24h per merchant >= N` | 10 user |
| `trans_count_bin_24h per merchant >= N` | 20 GD |

### 4.4. Time interval
- user >= 3 GD in 5min / >= 5 in 10min / >= 10 in 1h
- card >= 5 GD in 1h
- device >= 10 GD in 1h
- IP >= 20 GD in 1h

### 4.5. Amount repetition
- `same_amount_count_{user/card}_24h >= 3` / device `>= 5`
- amount near limit (90–100%)
- amount round-number AND repeated
- amount > 3× user 30d avg

---

## 5. Evaluation formulas + acceptance criteria

### 5.1. Formulas

| Metric | Formula |
|---|---|
| TP | fraud transaction hit by rule |
| FP | good transaction hit by rule |
| FN | fraud transaction NOT hit |
| Precision | TP / (TP + FP) |
| Recall | TP / (TP + FN) |
| Fraud amount recall | fraud amount hit / total fraud amount |
| Business transaction impact | total trans hit / total trans in base |
| Business amount impact | total amount hit / total amount in base |
| User impact | users hit / total users in base |
| Good user impact | good users hit / total good users in base |

### 5.2. Acceptance criteria

| Criterion | Reject rule | Challenge rule | Targeted high-precision rule |
|---|---|---|---|
| Precision | >= 90% | >= 70% | >= 95% |
| Recall | >= 20% | >= 20% | >= 5% |
| Fraud amount recall | >= 30% | >= 30% | >= 20% |
| Good transaction impact | <= 1% | <= 2% | — |
| Good user impact | <= 1% | <= 2% | ~0% |
| Business amount impact | <= 3% | <= 5% | — |

**Auto-reject the rule when:** `precision < 70% AND recall < 20%`.
**Demote to challenge / monitor when:** `recall >= 50% AND precision < 70%`.

---

## 6. user_profile catalog + rule templates

### 6.1. Profile metrics + thresholds

| Family | Thresholds to test |
|---|---|
| `account_age_at_trans` | <= 1d, <= 3d, <= 7d, <= 30d, > 30d |
| `eKYC_age_at_trans` | <= 1d, <= 7d, <= 30d (+ KYC level, eKYC pass flag) |
| `NFC_age_at_trans` | <= 1d, <= 7d, <= 30d (+ NFC pass flag) |
| Age group | < 18, 18-22, 23-30, 31-45, > 45, DOB missing |
| CCCD multi-account | >= 2, >= 3 accounts per CCCD |
| Financial service ownership | has/missing: linked bank, linked card, credit limit, MMF, wallet balance activity, historical successful payment |
| Trust profile | trusted / whitelist / blacklist / greylist / historical fraud |

### 6.2. Rule templates (translog + profile combine)

| Pattern | Template |
|---|---|
| Velocity + account age | `total_amount_user_24h >= 10M AND account_age <= 7d` |
| Velocity + non-NFC | `total_amount_user_30d >= 60M AND non-NFC` |
| Velocity + non-eKYC | `total_amount_user_7d >= 50M AND non-eKYC` |
| Velocity + newly eKYC | `total_amount_user_24h >= 10M AND eKYC_age <= 1d` |
| Velocity + CCCD multi-account | `total_amount_user_24h >= 10M AND CCCD linked >= 2 accounts` |
| No-behavior + amount | `no historical successful payment AND amount >= 5M` |
| SOF + account age + velocity | `source_of_fund = card AND account_age <= 7d AND total_amount_user_24h >= 10M` |

### 6.3. Acceptance after profile

Rule is good if:
- Precision >= 90%, Recall >= 20%, Fraud amount recall >= 30%, Good user impact <= 1%
- **OR** precision improved >= 15 pp vs. translog-only rule AND recall did not drop > 50%.

---

## 7. user_journey catalog + rule templates

### 7.1. Time windows to check
5min / 30min / 1h / 6h / 24h / 3d / 7d / 30d **before** transaction.

### 7.2. Journey metrics
For each `event`: `had_<event>_before_trans`, `time_since_<event>`.
Events: register, login, login_new_device, changephone, resetpin, mapcard,
unmapcard, mapbank, unmapbank, eKYC, NFC, lock/unlock.

Aggregates: `journey_event_count_{1h/24h/7d}`,
`sensitive_event_count_{24h/7d}`.

### 7.3. Sensitive events
change phone, reset PIN / forgot PIN, login new device, map card / unmap
card, map bank / unmap bank, eKYC, NFC, unlock account, passkey
remove/setup, biometric change.

### 7.4. Candidate journey thresholds
- Sensitive event in last 1h / 24h before trans
- `sensitive_event_count_24h >= 2` / `_7d >= 3`
- Trans within 24h after: change phone / reset PIN / login new device /
  map card / map bank
- Trans within 7d after: eKYC / NFC

### 7.5. Rule templates (velocity + profile + journey combine)

#### Change phone
```
total_amount_user_24h >= 5M  AND changephone_age <= 24h
total_amount_user_24h >= 10M AND changephone_age <= 7d
trans_count_user_24h  >= 5   AND changephone_age <= 24h
source_of_fund = card AND changephone_age <= 24h AND amount >= 3M
payment_amount >= 5M  AND changephone_age <= 24h AND device_age <= 7d
```

#### Reset PIN
```
amount >= 3M AND resetpin_age <= 1h
amount >= 5M AND resetpin_age <= 24h
total_amount_user_24h >= 10M AND resetpin_age <= 24h
resetpin_age <= 24h AND login_new_device_age <= 24h AND amount >= 3M
```

#### Login new device
```
amount >= 3M AND login_new_device_age <= 1h
amount >= 5M AND login_new_device_age <= 24h
total_amount_user_24h >= 10M AND login_new_device_age <= 24h
login_new_device_age <= 24h AND source_of_fund = card AND amount >= 3M
```

#### Map card / map bank
```
amount >= 3M AND mapcard_age <= 1h
amount >= 5M AND mapcard_age <= 24h
total_amount_user_24h >= 10M AND mapcard_age <= 24h
amount >= 5M AND mapbank_age <= 24h
total_amount_user_24h >= 10M AND newly_mapped_bank_or_card = true
```

#### Register / onboarding
```
account_age <= 1d  AND amount >= 3M
account_age <= 3d  AND total_amount_user_24h >= 5M
account_age <= 7d  AND total_amount_user_24h >= 10M
account_age <= 7d  AND trans_count_user_24h >= 5
account_age <= 30d AND total_amount_user_30d >= 60M
account_age <= 7d  AND source_of_fund = card AND amount >= 3M
```

#### eKYC / NFC
```
non-NFC AND total_amount_user_30d >= 60M
non-NFC AND total_amount_user_24h >= 10M
eKYC_age <= 24h AND amount >= 5M
NFC_age  <= 24h AND amount >= 10M
eKYC_age <= 7d  AND trans_count_user_24h >= 5
non-NFC AND source_of_fund = card AND total_amount_user_7d >= 30M
```

#### Sensitive event cluster
```
sensitive_event_count_24h >= 2 AND amount >= 3M
sensitive_event_count_24h >= 2 AND total_amount_user_24h >= 5M
sensitive_event_count_7d  >= 3 AND total_amount_user_7d  >= 20M
login_new_device_age <= 24h AND resetpin_age <= 24h AND amount >= 3M
changephone_age      <= 24h AND mapbank_age <= 24h  AND amount >= 3M
register_age         <= 7d  AND mapcard_age <= 24h  AND amount >= 3M
```

---

## 8. Action mapping (recommend action per rule)

### 8.1. MONITOR — when
- Precision < 70%, Recall < 20%
- Pattern unclear, fraud amount impact small
- Good user impact > 2%
- Rule not strong enough to challenge / reject

### 8.2. CHALLENGE — when
- Precision 70%–89%, Recall >= 20%, Fraud amount recall >= 30%, Good user impact <= 2%
- Fits: new device, change phone / reset PIN, newly mapped card/bank, non-NFC / non-eKYC
- Recall good but precision not high enough to reject

### 8.3. REJECT — when
- Precision >= 90%, Recall >= 20%, Fraud amount recall >= 30%
- Good transaction impact <= 1%, Good user impact <= 1%
- Pattern clear, FP risk low
- Fits: fraud concentrated on entity (card/device/IP/BIN), 1 device/IP linked to many fraud users, BIN attack / card testing clear

### 8.4. BLACKLIST — when
- Entity confirmed in fraud
- Entity-based rule precision >= 95%, good user impact ~0%
- Entities to blacklist: card fingerprint, device ID, IP / range (only if not shared), bank account, BIN (if scope controlled), userID (if fraud confirmed)

### 8.5. WHITELIST EXCLUSION — when
- >= 30% fraud amount or fraud count currently bypassed by whitelist
- Trusted user with sensitive journey event recently
- Whitelisted user logging in on new device within 24h
- Bypass-3DS but fraud concentration on BIN

---

## 9. Output schema (final report)

### 9.1. Fraud scope
- Filter condition, time range fraud sample, time range base population.
- Number of fraud transactions, fraud amount, number of fraud users.
- Main anomalous dimension.

### 9.2. Pattern finding summary

| Source | Patterns to report |
|---|---|
| translog | Amount velocity, count velocity, fail velocity, time interval, device/IP/card overlap, BIN/merchant/SOF concentration |
| user_profile | Account age, KYC/NFC status, new eKYC/NFC, CCCD linkage, trusted/non-trusted, FS ownership |
| user_journey | Change phone, reset PIN, login new device, map card/bank, eKYC/NFC, sensitive event cluster |

### 9.3. Candidate rules tested
For each: rule condition, TP, FP, FN, Precision, Recall, Fraud amount
recall, Good transaction impact, Good user impact, Business amount impact,
recommended action.

### 9.4. Recommended rule(s) — 1-3 best
For each: rule logic, why chosen, fraud coverage, good user impact, action
recommendation, checkpoint to apply, risk if implemented, monitoring plan.

---

## 10. Default threshold reference

### Precision targets
| Rule type | Precision |
|---|---|
| Reject rule | >= 90% |
| Challenge rule | >= 70% |
| Blacklist / entity rule | >= 95% |

### Recall targets
| Rule type | Recall |
|---|---|
| Main rule | >= 20% |
| Targeted high-precision rule | >= 5% (if fraud amount recall >= 20%) |
| Recall-good rule | >= 30% |

### Fraud amount recall targets
| Level | Threshold |
|---|---|
| Minimum | >= 30% |
| Good | >= 50% |
| Targeted (precision >= 95%) | >= 20% |

### Good-user / business impact
| Rule type | Good user impact | Business amount impact |
|---|---|---|
| Reject | <= 1% | <= 3% |
| Challenge | <= 2% | <= 5% |
| Monitor | may be > 2% (no auto reject) | — |

If business amount impact > 5% → need human approval or refine condition.

### Time windows
| Window | Use |
|---|---|
| 5min, 10min, 1h | Short burst |
| 24h | Daily velocity |
| 7d | Medium-term velocity |
| 30d | Monthly velocity |

### Amount thresholds to test
| Window | Thresholds |
|---|---|
| 1h | 3M, 5M, 10M, 20M |
| 24h | 10M, 20M, 50M, 100M |
| 7d | 30M, 50M, 100M, 200M |
| 30d | 60M, 100M, 200M, 500M |

### Count thresholds to test
| Window | Thresholds |
|---|---|
| 1h | 3, 5, 10 trans |
| 24h | 5, 10, 20 trans |
| 7d | 10, 20, 50 trans |
| Fail 1h | 3, 5, 10 |
| Fail 24h | 5, 10, 20 |

### Journey thresholds
| Condition | Threshold |
|---|---|
| Event before transaction | <= 1h / <= 24h / <= 7d |
| Sensitive event count 24h | >= 2 |
| Sensitive event count 7d | >= 3 |
