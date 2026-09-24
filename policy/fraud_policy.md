# Fraud Policy (v1.0)

> Copied verbatim from the dataset README's "Fraud Policy" section, for
> loading into TigerGraph's vector store as GraphRAG context. This is the
> ground-truth text `policy_engine.py`'s rule functions implement — if the
> two ever disagree, this file (and the README) wins; fix the code.

## 1. Actions

| Action | What it does | Customer impact |
|---|---|---|
| `ALLOW_TRANSACTION` | Let the flagged transaction stand | None |
| `DECLINE_TRANSACTION` | Decline the flagged authorization only. Card stays active | Low |
| `MONITOR_CARD` | Card stays active; raise monitoring sensitivity for 72 hours | None |
| `MONITOR_CONNECTED_CARDS` | Put other cards linked to the same device profile, region cluster, or ring under monitoring | None |
| `WARN_CUSTOMER` | Send an informational message | None |
| `VERIFY_WITH_CUSTOMER` | Ask the cardholder whether they made the transaction. Card stays active pending reply | Low |
| `STEP_UP_AUTH` | Require a one-time passcode or app confirmation before further activity | Low |
| `BLOCK_CARD` | Block this card and reissue | High |
| `BLOCK_ALL_CARDS` | Block every card the customer holds | Very high |
| `GENERATE_REPORT` | Write up the investigation for the internal record, without opening a case | None |
| `CREATE_CASE` | Open an internal fraud case with the evidence attached, and write it to the graph | None |
| `FILE_REPORT` | File a suspicious activity report with the regulator | None |
| `ESCALATE_TO_ANALYST` | Hand the case to a human analyst with the evidence | None |
| `CLOSE_NO_FRAUD` | Close the alert as legitimate | None |

An agent may recommend several actions for one case, ordered by what happens first.

## 2. Approval routing

| Route | Applies to |
|---|---|
| `auto` | `ALLOW_TRANSACTION`, `MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `GENERATE_REPORT`, `CREATE_CASE`, `ESCALATE_TO_ANALYST`, `CLOSE_NO_FRAUD` |
| `L1` (team lead) | `DECLINE_TRANSACTION`; `BLOCK_CARD` when exposure ≤ $2,500 |
| `L2` (fraud manager) | `BLOCK_CARD` when exposure > $2,500; `BLOCK_ALL_CARDS` always; `FILE_REPORT` always |

Only `auto` actions may be executed by the agent. `L1`/`L2` actions are recommended, with the route stated, and wait for a human.

## 3. Rules

- **R1.** Verify before you block on a weak signal. Single-signal case with probability < 0.70 → `VERIFY_WITH_CUSTOMER` or `STEP_UP_AUTH` before any block.
- **R2.** Customer denies the transaction → `BLOCK_CARD`, `CREATE_CASE`. Add `FILE_REPORT` if exposure > $1,000 or shared device/other-card fraud.
- **R3.** Customer confirms the transaction → `CLOSE_NO_FRAUD`.
- **R4.** No reply within 24 hours → `MONITOR_CARD`, `DECLINE_TRANSACTION` for pending auths. Escalate if exposure > $500.
- **R5.** Card testing (3+ small online auths in 1h, then a larger purchase) → `DECLINE_TRANSACTION`, `STEP_UP_AUTH`. If a >$100 purchase already cleared, add `BLOCK_CARD`.
- **R6.** Shared origin (device/region/email across cards) → name the shared element, `CREATE_CASE`, `FILE_REPORT`, `MONITOR_CONNECTED_CARDS` for every sharing card.
- **R7.** Disputed but matches the customer's own recurring pattern → `CREATE_CASE`, `VERIFY_WITH_CUSTOMER`, `WARN_CUSTOMER`. Never block.
- **R8.** Uncertain verdict with exposure > $500, or conflicting evidence → `ESCALATE_TO_ANALYST`.
- **R9.** Undocumented pattern with coordinated/repeated abuse → `CREATE_CASE`, `FILE_REPORT`, `ESCALATE_TO_ANALYST`; describe the pattern in your own words.
- **R10.** Never `BLOCK_ALL_CARDS` unless 2+ confirmed-fraud cards, or credentials confirmed compromised.

## 3a. A case is not a report

A **case** is internal; open one whenever fraud probability reaches 0.30, whenever evidence is requested, or whenever a customer disputes a charge. A **suspicious activity report** is external/regulatory; file one when fraud is confirmed or strongly suspected AND at least one of: exposure > $1,000; shared device/region/email cluster; coordinated/undocumented pattern (R9). A report always has a case behind it.

## 3b. The next best action can change

Recommend what the evidence supports now, request more evidence if the policy calls for it, then recommend again. Record both `initial` and `final`, and what changed.

## 4. Exposure

Sum of absolute amounts of every transaction identified as part of the fraud episode, including the flagged one.

## 5. Gathering more evidence

The agent may, without approval, ask the customer to validate a transaction, request step-up authentication, or request analyst information. Responses are simulated; state the assumption in `evidence_requests`.

## 6. Stopping

Stop when: fraud probability ≥0.85 or ≤0.15, supported by 2+ independent evidence pieces; OR a verification response settles the question; OR further steps are unlikely to change the decision (say why in `stop_reason`).

## 7. Explaining

Every recommendation states the evidence used, why more evidence was requested (if it was), and cites the rule number behind the chosen actions.
