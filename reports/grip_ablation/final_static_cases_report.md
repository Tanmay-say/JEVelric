# Final static submission case report

This report describes the current `cases/HHG-001.json` through `HHG-020.json` answer files. They were generated through the normal static submission path; the GRIP-only provider monkey patch is in a separate runner. The live TigerGraph answer validator passed all 20 files after the action-language validation was added.

| Case | Status | Verdict | Probability | Pattern | Final actions | SAR |
|---|---|---|---:|---|---|---|
| HHG-001 | closed_legitimate | legitimate | 0.15 | none | VERIFY_WITH_CUSTOMER | no file |
| HHG-002 | open | uncertain | 0.62 | card_not_present_fraud | DECLINE_TRANSACTION, MONITOR_CARD | no file |
| HHG-003 | closed_legitimate | legitimate | 0.1 | none | VERIFY_WITH_CUSTOMER | no file |
| HHG-004 | open | uncertain | 0.68 | card_not_present_new_device | BLOCK_CARD, CREATE_CASE | no file |
| HHG-005 | closed_fraud | fraud | 0.75 | card_not_present_new_device | BLOCK_CARD, MONITOR_CONNECTED_CARDS, CREATE_CASE, FILE_REPORT | file |
| HHG-006 | escalated | fraud | 0.74 | card_not_present_new_device | ESCALATE_TO_ANALYST, FILE_REPORT | file |
| HHG-007 | escalated | uncertain | 0.25 | none | DECLINE_TRANSACTION, MONITOR_CARD, ESCALATE_TO_ANALYST | no file |
| HHG-008 | escalated | uncertain | 0.5 | card_not_present_fraud | DECLINE_TRANSACTION, MONITOR_CARD, ESCALATE_TO_ANALYST | no file |
| HHG-009 | closed_legitimate | legitimate | 0.15 | none | DECLINE_TRANSACTION, MONITOR_CARD | no file |
| HHG-010 | escalated | fraud | 0.74 | card_not_present_new_device | BLOCK_CARD, CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST | file |
| HHG-011 | closed_fraud | fraud | 0.9 | card_testing | DECLINE_TRANSACTION, STEP_UP_AUTH, MONITOR_CONNECTED_CARDS, CREATE_CASE, FILE_REPORT | file |
| HHG-012 | closed_legitimate | legitimate | 0.1 | none | VERIFY_WITH_CUSTOMER | no file |
| HHG-013 | escalated | uncertain | 0.6 | account_takeover | DECLINE_TRANSACTION, MONITOR_CARD, ESCALATE_TO_ANALYST | no file |
| HHG-014 | closed_fraud | fraud | 0.74 | account_takeover | BLOCK_CARD, CREATE_CASE | no file |
| HHG-015 | escalated | fraud | 0.82 | card_not_present_new_device | MONITOR_CONNECTED_CARDS, CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST | file |
| HHG-016 | open | uncertain | 0.68 | card_not_present_new_device | BLOCK_CARD, CREATE_CASE | no file |
| HHG-017 | open | uncertain | 0.2 | none | DECLINE_TRANSACTION, VERIFY_WITH_CUSTOMER, MONITOR_CARD, WARN_CUSTOMER, CREATE_CASE | no file |
| HHG-018 | escalated | uncertain | 0.3 | none | DECLINE_TRANSACTION, MONITOR_CARD, ESCALATE_TO_ANALYST | no file |
| HHG-019 | closed_fraud | fraud | 0.8 | card_not_present_new_device | MONITOR_CONNECTED_CARDS, CREATE_CASE, FILE_REPORT | file |
| HHG-020 | escalated | fraud | 0.7 | account_takeover | ESCALATE_TO_ANALYST | no file |

## HHG-001

- **Finding:** closed_legitimate / legitimate / none / probability 0.15 / exposure $0.00
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **What changed:** nothing
- **Evidence items:** 2
  - graph `query:card_window(card_id=C12382-K1)`: Card C12382-K1 has 15 transaction(s) within ±48h of 3514030 totaling $1167.96. (IDs: 3510115, 3510225, 3510464, 3510612, 3511596, 3512936, 3513814, 3514030, 3514461, 3515241, 3517969, 3519088, 3519140, 3519301, 3519548)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-1066, CC-2964, CC-1673, CC-3587)
- **SAR:** file=False; reason=3a: not filed — verdict is legitimate; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=8092; latency=20.23s
- **Summary:** Verdict: legitimate. The 15 transactions on card C12382-K1 (2016-12-03 to 2016-12-06, total exposure $1,167.96) are all in-person purchases of product W in regions (e.g., 203, 204, 433, 444, 485, 498) that all appear in the cardholder's 284-transaction history, with amounts consistent with the historical mean of $123.11. No known fraud pattern fits: no card-testing sequence, no online/new-device activity, no out-of-region use, and no device or email cluster links (shared flags all false). The heuristic estimate is low (fraud_probability 0.28, single signal only), and the only elevated transaction (txn 3514030, $77.07, risk_score 0.61) is an isolated in-person purchase in a familiar region. Recommended action: CLOSE_NO_FRAUD, with no card restrictions.

## HHG-002

- **Finding:** open / uncertain / card_not_present_fraud / probability 0.62 / exposure $292.36
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** DECLINE_TRANSACTION [L1] — R4: no reply within 24 hours, pending authorization; MONITOR_CARD [auto] — R4: no reply within 24 hours
- **What changed:** no reply response added ['DECLINE_TRANSACTION', 'MONITOR_CARD'] and removed ['VERIFY_WITH_CUSTOMER']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C11891-K1)`: Card C11891-K1 has 1 transaction(s) within ±48h of 3478782 totaling $292.36. (IDs: 3478782)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-4160)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=6182; latency=36.38s
- **Summary:** Verdict: uncertain. A single online transaction (txn 3478782) on card C11891-K1 for $292.36 on 2016-11-22 is flagged as possible card-not-present fraud — the amount is well above the customer's historical mean of $43.99, and the customer has a prior confirmed fraud case (CC-4160) on the same card. However, the evidence is a single signal (fraud probability 0.58, below the 0.70 threshold), with no device, region, or shared-email anomalies, so the pattern is not confirmed. Recommended action per R1: VERIFY_WITH_CUSTOMER (or STEP_UP_AUTH) before any block, with MONITOR_CARD on C11891-K1 in the interim.

## HHG-003

- **Finding:** closed_legitimate / legitimate / none / probability 0.1 / exposure $0.00
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **What changed:** nothing
- **Evidence items:** 2
  - graph `query:card_window(card_id=C08623-K2)`: Card C08623-K2 has 26 transaction(s) within ±48h of 3530164 totaling $5517.92. (IDs: 3524629, 3524740, 3525595, 3527130, 3527215, 3527397, 3527532, 3528392, 3528902, 3529041, 3529981, 3530056, 3530164, 3531019, 3531833, 3532138, 3532333, 3532926, 3533469, 3533601, 3533775, 3533776, 3533819, 3534946, 3535845, 3535867)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-2935, CC-4957, CC-3327, CC-3682, CC-2817)
- **SAR:** file=False; reason=3a: not filed — verdict is legitimate; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=11408; latency=23.44s
- **Summary:** Verdict: legitimate (CLOSE_NO_FRAUD). The 26 in-person transactions on card C08623-K2 from 2016-12-08 to 2016-12-12 (total exposure $5,517.92) all occurred in billing regions well within the cardholder's 715-transaction history (e.g., 204, 330, 264, 251), with amounts consistent with the historical mean of $134.28 and no device, email, or region-sharing anomalies. No known fraud pattern fits: activity is card-present, in-region, and consistent with the cardholder's profile; the heuristic hint reports fraud probability 0.28, single-signal-only, pattern 'none'. Prior confirmed-fraud cases (CC-2935, CC-4957, CC-3327, CC-3682, CC-2817) involved out-of-region or account-takeover activity not present here. Recommended action: CLOSE_NO_FRAUD, with no card blocking or customer disruption required.

## HHG-004

- **Finding:** open / uncertain / card_not_present_new_device / probability 0.68 / exposure $384.43
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** BLOCK_CARD [L1] — R2: customer denied the transaction; CREATE_CASE [auto] — R2: customer denied the transaction
- **What changed:** denied response added ['BLOCK_CARD', 'CREATE_CASE'] and removed ['VERIFY_WITH_CUSTOMER']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C08106-K1)`: Card C08106-K1 has 8 transaction(s) within ±48h of 3583227 totaling $384.43. (IDs: 3580804, 3583227, 3583499, 3583503, 3584017, 3585446, 3585726, 3587858)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-3778, CC-2121, CC-1736, CC-0696)
  - customer `evidence_request:1`: Customer states they did not make these purchases and still has the card. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=7163; latency=22.91s
- **Summary:** Case HHG-004 on card C08106-K1 (customer C08106) was triggered by customer_report: Customer C08106 message: 'I never made this $128.33 purchase. Please check my card.' Refers to 3583227. Flagged transaction 3583227. Graph evidence supports pattern card_not_present_new_device with fraud probability 0.68 and exposure $384.43. Working verdict is uncertain. Recommended actions: BLOCK_CARD, CREATE_CASE.

## HHG-005

- **Finding:** closed_fraud / fraud / card_not_present_new_device / probability 0.75 / exposure $100.07
- **Initial actions:** MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R6: shared device profile across cards; FILE_REPORT [L2] — R6: shared device profile across cards
- **Final actions:** BLOCK_CARD [L1] — R2: customer denied the transaction; MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R2: customer denied the transaction; FILE_REPORT [L2] — R2: exposure exceeds $1,000 or activity connects to a shared origin
- **What changed:** denied response added ['BLOCK_CARD']
- **Evidence items:** 4
  - graph `query:card_window(card_id=C02923-K1)`: Card C02923-K1 has 1 transaction(s) within ±48h of 3523199 totaling $100.07. (IDs: 3523199)
  - graph `query:device_neighbors(txn_id=3523199)`: Device profile shared with other cards in the review window. (IDs: C08299-K1, C11496-K2, C11539-K2, C12267-K2)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-2400, CC-2717, CC-2857)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=True; reason=3a: fraud confirmed/strongly suspected and activity connects to a shared origin; amount=$100.07; dates=['2016-12-07', '2016-12-07']
- **Run:** tool_calls=7; tokens=10277; latency=160.47s
- **Summary:** Verdict: fraud (account takeover), consistent with the heuristic's 0.86 probability. The flagged transaction 3523199 on card C02923-K1 (customer C02923) is a $100.07 online purchase on 2016-12-07 from a device marked New (iOS Device#08b637c722), which is shared with four other cards (C08299-K1, C11496-K2, C11539-K2, C12267-K2) — a device/match-flag anomaly pattern pointing to stolen credentials. This matches three prior confirmed account-takeover cases on the same card (CC-2400, CC-2717, CC-2857), each closed as confirmed fraud with mixed-channel activity inconsistent with the cardholder. Recommended actions: BLOCK_CARD (exposure $100.07 ≤ $2,500, route L1), MONITOR_CONNECTED_CARDS for the shared-device cards, and CREATE_CASE with the evidence attached.

## HHG-006

- **Finding:** escalated / fraud / card_not_present_new_device / probability 0.74 / exposure $2508.06
- **Initial actions:** ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500; FILE_REPORT [L2] — 3a: fraud confirmed/strongly suspected and exposure exceeds $1,000
- **Final actions:** ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500; FILE_REPORT [L2] — 3a: fraud confirmed/strongly suspected and exposure exceeds $1,000
- **What changed:** nothing
- **Evidence items:** 1
  - graph `query:card_window(card_id=C07297-K1)`: Card C07297-K1 has 8 transaction(s) within ±48h of 3476682 totaling $2508.06. (IDs: 3473012, 3474057, 3476602, 3476633, 3476665, 3476682, 3477578, 3478191)
- **SAR:** file=True; reason=3a: fraud confirmed/strongly suspected and exposure exceeds $1,000; amount=$2508.06; dates=['2016-11-20', '2016-11-22']
- **Run:** tool_calls=7; tokens=9364; latency=50.23s
- **Summary:** Verdict: fraud (account takeover pattern, probability 0.74). Card C07297-K1 (customer C07297) shows a burst of four online purchases on 2016-11-21 within 30 minutes — txns 3476602 ($478.95), 3476633 ($456.96), 3476665 ($488.04), and 3476682 ($482.12) — all on devices marked `New` (Trident/7.0#1c429b2df5 and iOS Device#0c46cadac9), far above the customer's historical mean of $116.43, while normal in-person activity continued, indicating stolen credentials rather than a stolen card number. Total exposure is $2,508.06. Recommended actions: CREATE_CASE and ESCALATE_TO_ANALYST (auto), plus BLOCK_CARD routed to L2 since exposure exceeds $2,500.

## HHG-007

- **Finding:** escalated / uncertain / none / probability 0.25 / exposure $14099.73
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70; ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **Final actions:** DECLINE_TRANSACTION [L1] — R4: no reply within 24 hours, pending authorization; MONITOR_CARD [auto] — R4: no reply within 24 hours; ESCALATE_TO_ANALYST [auto] — R4: no reply and exposure exceeds $500
- **What changed:** no reply response added ['DECLINE_TRANSACTION', 'MONITOR_CARD'] and removed ['VERIFY_WITH_CUSTOMER']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C09933-K2)`: Card C09933-K2 has 50 transaction(s) within ±48h of 3514948 totaling $14099.73. (IDs: 3509151, 3509355, 3509392, 3509466, 3510700, 3511523, 3511607, 3511937, 3512302, 3512690, 3512716, 3513073, 3513079, 3513351, 3513366, 3513495, 3513664, 3514092, 3514137, 3514145, 3514278, 3514335, 3514573, 3514948, 3515001, 3515045, 3515193, 3515709, 3515752, 3515777, 3515982, 3516208, 3516823, 3516828, 3516867, 3517307, 3517314, 3517460, 3517968, 3518078, 3518432, 3518784, 3519222, 3519385, 3519461, 3520279, 3520325, 3520344, 3520430, 3520501)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-1524, CC-0104, CC-3821, CC-4196, CC-5092)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=25051; latency=94.45s
- **Summary:** Verdict: uncertain. Card C09933-K2 (customer C09933) shows 50 in-person transactions in region 264 from 2016-12-03 to 2016-12-06 totaling $14,099.73 in exposure, but the activity is consistent with the cardholder's established history (region 264 is among their 27 known regions, mean amount $126.02, product W, in-person channel), and no known fraud pattern fits — the heuristic reports pattern "none" with fraud probability 0.28 and a single weak signal. The only anomalies are two small online purchases from new devices (txn 3515777, $30.01, and txn 3516867, $99.94), which alone are ambiguous, plus a prior confirmed account-takeover case (CC-1524) on this same card. Given the weak signal and prior compromise history, recommend VERIFY_WITH_CUSTOMER and MONITOR_CARD (auto actions) before any block, per policy R1.

## HHG-008

- **Finding:** escalated / uncertain / card_not_present_fraud / probability 0.5 / exposure $816.09
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70; ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **Final actions:** DECLINE_TRANSACTION [L1] — R4: no reply within 24 hours, pending authorization; MONITOR_CARD [auto] — R4: no reply within 24 hours; ESCALATE_TO_ANALYST [auto] — R4: no reply and exposure exceeds $500
- **What changed:** no reply response added ['DECLINE_TRANSACTION', 'MONITOR_CARD'] and removed ['VERIFY_WITH_CUSTOMER']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C13171-K2)`: Card C13171-K2 has 17 transaction(s) within ±48h of 3558054 totaling $816.09. (IDs: 3553223, 3553269, 3553275, 3553281, 3554288, 3554589, 3554683, 3555638, 3555768, 3556719, 3557118, 3557979, 3557987, 3558054, 3558907, 3561532, 3561904)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-1715, CC-3422, CC-3566, CC-0056, CC-5010)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=13455; latency=33.56s
- **Summary:** Verdict: uncertain. Card C13171-K2 (customer C13171) shows 17 online transactions totaling $816.09 between 2016-12-18 and 2016-12-21, with several small authorizations (e.g., txn 3553275 at $9.51, 3554589 at $11.91, 3555638 at $11.85, 3556719 at $8.33) followed by larger purchases (e.g., 3561532 at $126.47), and multiple transactions flagged with device id_15='New' — a possible card-not-present/new-device pattern, though the heuristic gives only 0.28 fraud probability with a single signal. The card has three prior confirmed-fraud cases (CC-1715, CC-3422, CC-3566, CC-0056, CC-5010), which raises concern but does not confirm this window. Recommended action: VERIFY_WITH_CUSTOMER and MONITOR_CARD per R1, escalating to an analyst if the customer denies the activity.

## HHG-009

- **Finding:** closed_legitimate / legitimate / none / probability 0.15 / exposure $0.00
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** DECLINE_TRANSACTION [L1] — R4: no reply within 24 hours, pending authorization; MONITOR_CARD [auto] — R4: no reply within 24 hours
- **What changed:** no reply response added ['DECLINE_TRANSACTION', 'MONITOR_CARD'] and removed ['VERIFY_WITH_CUSTOMER']
- **Evidence items:** 2
  - graph `query:card_window(card_id=C08299-K1)`: Card C08299-K1 has 1 transaction(s) within ±48h of 3581141 totaling $30.02. (IDs: 3581141)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — verdict is legitimate; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=6416; latency=19.83s
- **Summary:** Verdict: legitimate. The single flagged transaction, txn 3581141 on card C08299-K1 (customer C08299, $30.02, online, 2016-12-28), fits no known fraud pattern — it is a one-off online purchase of product S within the customer's normal history (31 prior transactions, mean $52.22, same product and channel mix, region 203 among their usual regions). Risk score is low (0.28), id_15 is 'Found', and no shared device, region, or email anomalies were flagged. Recommended action: CLOSE_NO_FRAUD.

## HHG-010

- **Finding:** escalated / fraud / card_not_present_new_device / probability 0.74 / exposure $1000.03
- **Initial actions:** ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **Final actions:** BLOCK_CARD [L1] — R2: customer denied the transaction; CREATE_CASE [auto] — R2: customer denied the transaction; FILE_REPORT [L2] — R2: exposure exceeds $1,000 or activity connects to a shared origin; ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **What changed:** denied response added ['BLOCK_CARD', 'CREATE_CASE', 'FILE_REPORT']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C10434-K1)`: Card C10434-K1 has 1 transaction(s) within ±48h of 3506725 totaling $1000.03. (IDs: 3506725)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-0873)
  - customer `evidence_request:1`: Customer states they did not make these purchases and still has the card. (IDs: none)
- **SAR:** file=True; reason=3a: fraud confirmed/strongly suspected and exposure exceeds $1,000; amount=$1000.03; dates=['2016-12-02', '2016-12-02']
- **Run:** tool_calls=7; tokens=7536; latency=27.95s
- **Summary:** Case HHG-010 on card C10434-K1 (customer C10434) was triggered by risk_score: Real-time model scored transaction 3506725 ($1,000.03, online) at 0.90. Review and decide. Flagged transaction 3506725. Graph evidence supports pattern card_not_present_new_device with fraud probability 0.74 and exposure $1000.03. Working verdict is fraud. Recommended actions: BLOCK_CARD, CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST.

## HHG-011

- **Finding:** closed_fraud / fraud / card_testing / probability 0.9 / exposure $3984.80
- **Initial actions:** DECLINE_TRANSACTION [L1] — R5: card testing sequence observed; STEP_UP_AUTH [auto] — R5: card testing sequence observed; MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R6: shared device profile across cards; FILE_REPORT [L2] — R6: shared device profile across cards
- **Final actions:** DECLINE_TRANSACTION [L1] — R5: card testing sequence observed; STEP_UP_AUTH [auto] — R5: card testing sequence observed; MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R6: shared device profile across cards; FILE_REPORT [L2] — R6: shared device profile across cards
- **What changed:** nothing
- **Evidence items:** 3
  - graph `query:card_window(card_id=C11923-K2)`: Card C11923-K2 has 84 transaction(s) within ±48h of 3583368 totaling $3984.80. (IDs: 3578405, 3578451, 3578471, 3578475, 3578483, 3578486, 3578491, 3578496, 3578506, 3578817, 3578995, 3578997, 3579400, 3579407, 3579576, 3579597, 3580137, 3580202, 3580219, 3580232, 3580348, 3580380, 3580403, 3580417, 3580427, 3580478, 3580544, 3580712, 3580765, 3580776, 3580815, 3580821, 3580907, 3580933, 3580951, 3580992, 3581048, 3581345, 3582082, 3582107, 3582142, 3582175, 3582178, 3582327, 3582338, 3582375, 3582413, 3582602, 3582624, 3582671, 3582738, 3582868, 3582897, 3583101, 3583140, 3583199, 3583229, 3583348, 3583368, 3583406, 3583411, 3583415, 3583417, 3583435, 3583494, 3583644, 3583670, 3583866, 3583914, 3583968, 3584003, 3584153, 3584155, 3584401, 3584460, 3584516, 3584693, 3584706, 3584859, 3584962, 3584985, 3585055, 3585064, 3585345)
  - graph `query:device_neighbors(txn_id=3583368)`: Device profile shared with other cards in the review window. (IDs: C03938-K1, C05595-K1, C05678-K1)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-3039, CC-3905, CC-2799, CC-0290, CC-2673)
- **SAR:** file=True; reason=3a: fraud confirmed/strongly suspected and exposure exceeds $1,000; activity connects to a shared origin; amount=$3984.80; dates=['2016-12-27', '2016-12-29']
- **Run:** tool_calls=7; tokens=37187; latency=82.79s
- **Summary:** Verdict: fraud (probability 0.94), consistent with card testing on card C11923-K2 (customer C11923). The window shows 84 online transactions totaling $3,984.80 in exposure across 2016-12-27 to 2016-12-29, including a run of small sub-$5 authorizations (e.g., txn 3578491 for $5.13, 3578496 for $4.96, 3578997 for $4.88, 3582142 for $4.15, 3582175 for $4.01, 3583866 for $2.51, 3584962 for $2.76) followed by larger purchases (e.g., 3583670 for $227.32, 3584401 for $264.18, 3584460 for $264.03), with many transactions flagged id_15 'New' from devices not previously seen on this account. The pattern is corroborated by five prior confirmed-fraud cases on the same card (CC-0290, CC-2673 card testing; CC-2799, CC-3039, CC-3905 card-not-present new device), and the device profile SM-G610F Build/NRD90M#bfff8f74f5 is shared with cards C03938-K1, C05595-K1, and C05678-K1. Recommended actions: CREATE_CASE, then BLOCK_CARD (exposure $3,984.80 > $2,500, so route L2) and FILE_REPORT (L2), with MONITOR_CONNECTED_CARDS for the shared-device cards.

## HHG-012

- **Finding:** closed_legitimate / legitimate / none / probability 0.1 / exposure $0.00
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **What changed:** nothing
- **Evidence items:** 2
  - graph `query:card_window(card_id=C05876-K2)`: Card C05876-K2 has 24 transaction(s) within ±48h of 3553342 totaling $1113.17. (IDs: 3547831, 3548770, 3549201, 3549583, 3550012, 3550013, 3550293, 3550470, 3551245, 3552000, 3552020, 3553253, 3553342, 3554541, 3556479, 3557084, 3557091, 3557158, 3557340, 3557368, 3557731, 3557749, 3558647, 3558915)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-2370, CC-0003)
- **SAR:** file=False; reason=3a: not filed — verdict is legitimate; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=10014; latency=17.59s
- **Summary:** Verdict: legitimate. Card C05876-K2 (customer C05876) shows 24 in-person purchases totaling $1,113.17 between 2016-12-16 and 2016-12-20, all in regions (e.g., 264, 272, 330, 494) and products consistent with the cardholder's 688-transaction history, with low risk scores (mostly under 0.3) and no device, region, or email sharing flags. The activity fits no known fraud pattern — it is routine card-present spending, not card testing, card-not-present fraud, or account takeover; the prior confirmed fraud (case CC-2370) involved online transactions, unlike this window. Recommended action: CLOSE_NO_FRAUD.

## HHG-013

- **Finding:** escalated / uncertain / account_takeover / probability 0.6 / exposure $3058.09
- **Initial actions:** ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **Final actions:** DECLINE_TRANSACTION [L1] — R4: no reply within 24 hours, pending authorization; MONITOR_CARD [auto] — R4: no reply within 24 hours; ESCALATE_TO_ANALYST [auto] — R4: no reply and exposure exceeds $500
- **What changed:** no reply response added ['DECLINE_TRANSACTION', 'MONITOR_CARD']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C07671-K2)`: Card C07671-K2 has 34 transaction(s) within ±48h of 3526826 totaling $3058.09. (IDs: 3521713, 3521799, 3521839, 3521874, 3522133, 3523372, 3523953, 3524194, 3524237, 3524600, 3524626, 3524788, 3525205, 3525559, 3525584, 3525753, 3525762, 3525902, 3526234, 3526249, 3526265, 3526538, 3526677, 3526747, 3526826, 3526999, 3527288, 3527851, 3528696, 3529131, 3529473, 3529623, 3531359, 3532154)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-4294, CC-3216, CC-1475, CC-3761)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=18324; latency=26.24s
- **Summary:** Verdict: uncertain — the evidence is suggestive but not conclusive. The flagged activity is a single online transaction (txn 3526826, $35.66, product C, risk score 0.76, device marked New) embedded in an otherwise normal in-person spending pattern on card C07671-K2, consistent with possible card-not-present fraud from a new device (pattern 3) or the account-takeover pattern suggested by the heuristic (probability 0.74), but one anomalous online purchase amid heavy habitual in-person activity is ambiguous. Key evidence: the New-device online transaction against 1130 prior transactions across in_person and online channels, plus a history of three confirmed fraud cases on this same card (CC-4294, CC-3216, CC-1475). Recommended action: VERIFY_WITH_CUSTOMER (or STEP_UP_AUTH) per R1 before any block, with MONITOR_CARD on C07671-K2; escalate to an analyst if the customer denies the transaction.

## HHG-014

- **Finding:** closed_fraud / fraud / account_takeover / probability 0.74 / exposure $142.00
- **Initial actions:** (empty)
- **Final actions:** BLOCK_CARD [L1] — R2: customer denied the transaction; CREATE_CASE [auto] — R2: customer denied the transaction
- **What changed:** denied response added ['CREATE_CASE', 'BLOCK_CARD']
- **Evidence items:** 2
  - graph `query:card_window(card_id=C13487-K1)`: Card C13487-K1 has 3 transaction(s) within ±48h of 3478561 totaling $142.00. (IDs: 3477218, 3478561, 3478886)
  - customer `evidence_request:1`: Analyst confirms the related activity flagged in the trigger is part of the same episode. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=5540; latency=25.89s
- **Summary:** Case HHG-014 on card C13487-K1 (customer C13487) was triggered by analyst_request: Analyst request: several cards this month show purchases from the same unusual device profile. Review transaction 3478561 on card C13487-K1 and look for related activity. Flagged transaction 3478561. Graph evidence supports pattern account_takeover with fraud probability 0.74 and exposure $142.00. Working verdict is fraud. Recommended actions: BLOCK_CARD, CREATE_CASE.

## HHG-015

- **Finding:** escalated / fraud / card_not_present_new_device / probability 0.82 / exposure $2452.98
- **Initial actions:** MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R6: shared device profile across cards; FILE_REPORT [L2] — R6: shared device profile across cards; ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **Final actions:** MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R6: shared device profile across cards; FILE_REPORT [L2] — R6: shared device profile across cards; ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **What changed:** nothing
- **Evidence items:** 3
  - graph `query:card_window(card_id=C03042-K1)`: Card C03042-K1 has 5 transaction(s) within ±48h of 3464869 totaling $2452.98. (IDs: 3462385, 3462387, 3462404, 3464869, 3468946)
  - graph `query:device_neighbors(txn_id=3464869)`: Device profile shared with other cards in the review window. (IDs: C05704-K2)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-3886, CC-0615, CC-1313)
- **SAR:** file=True; reason=3a: fraud confirmed/strongly suspected and exposure exceeds $1,000; activity connects to a shared origin; amount=$2452.98; dates=['2016-11-16', '2016-11-18']
- **Run:** tool_calls=7; tokens=9098; latency=31.83s
- **Summary:** Verdict: fraud (account takeover / card-not-present from a new device). Card C03042-K1 shows a burst of in-person purchases on 2016-11-16 (txns 3462385, 3462387, 3462404, totaling ~$1,541) followed by an online purchase of $599.94 (txn 3464869) on 2016-11-17 from a device marked New (Trident/7.0#347e7400), which is also shared with card C05704-K2 — mixed-channel activity inconsistent with the cardholder's history, with prior confirmed fraud on the same card (cases CC-3886 and CC-0615). Total exposure is $2,452.98. Recommended actions: BLOCK_CARD (route L2, exposure > $2,500 threshold applies to L1 only), plus MONITOR_CONNECTED_CARDS for C05704-K2 and CREATE_CASE with the evidence attached.

## HHG-016

- **Finding:** open / uncertain / card_not_present_new_device / probability 0.68 / exposure $59.67
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** BLOCK_CARD [L1] — R2: customer denied the transaction; CREATE_CASE [auto] — R2: customer denied the transaction
- **What changed:** denied response added ['BLOCK_CARD', 'CREATE_CASE'] and removed ['VERIFY_WITH_CUSTOMER']
- **Evidence items:** 2
  - graph `query:card_window(card_id=C09988-K1)`: Card C09988-K1 has 1 transaction(s) within ±48h of 3534820 totaling $59.67. (IDs: 3534820)
  - customer `evidence_request:1`: Customer states they did not make these purchases and still has the card. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=6372; latency=11.85s
- **Summary:** The investigation into transaction 3534820 for customer C09988 yields an uncertain verdict, as the fraud probability of 0.68 falls below the 0.70 threshold required for definitive action. The activity aligns with the card-not-present fraud from a new device pattern, evidenced by the $59.67 online purchase on card C09988-K1 using a device marked as New. However, the single-signal nature of the evidence and the customer's consistent history of online product C purchases limit the strength of the fraud indication. Consequently, the recommended actions are to CREATE_CASE to document the investigation and BLOCK_CARD to secure the account, with the latter requiring L1 approval due to the exposure being under $2,500.

## HHG-017

- **Finding:** open / uncertain / none / probability 0.2 / exposure $300.14
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70
- **Final actions:** DECLINE_TRANSACTION [L1] — R4: no reply within 24 hours, pending authorization; VERIFY_WITH_CUSTOMER [auto] — R7: dispute matches customer's own recurring pattern; MONITOR_CARD [auto] — R4: no reply within 24 hours; WARN_CUSTOMER [auto] — R7: dispute matches customer's own recurring pattern; CREATE_CASE [auto] — R7: dispute matches customer's own recurring pattern
- **What changed:** no reply response added ['MONITOR_CARD', 'DECLINE_TRANSACTION', 'CREATE_CASE', 'WARN_CUSTOMER']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C04570-K1)`: Card C04570-K1 has 3 transaction(s) within ±48h of 3450629 totaling $300.14. (IDs: 3450436, 3450503, 3450629)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-1383)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=7530; latency=22.21s
- **Summary:** Verdict: uncertain — the evidence does not support a confirmed fraud pattern. Card C04570-K1 (customer C04570) made three online purchases on 2016-11-11 (txns 3450436, 3450503, 3450629, totaling $300.14 in exposure) for ~$100 each, but these amounts and the online channel fit the customer's history (mean $246.40, prior online purchases of product R), and the heuristic hint flags this as a single-signal case with fraud probability 0.28 and no matching known pattern. The shared email (anonymous.com) and region (204) clusters are large but not flagged as shared signals, and similar case CC-1383 was cleared after customer verification. Recommended action: VERIFY_WITH_CUSTOMER (or STEP_UP_AUTH) per R1 before any block, with MONITOR_CARD as a follow-up; escalate to an analyst only if the customer cannot confirm the transactions.

## HHG-018

- **Finding:** escalated / uncertain / none / probability 0.3 / exposure $20746.23
- **Initial actions:** VERIFY_WITH_CUSTOMER [auto] — R1: single weak signal, probability below 0.70; ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **Final actions:** DECLINE_TRANSACTION [L1] — R4: no reply within 24 hours, pending authorization; MONITOR_CARD [auto] — R4: no reply within 24 hours; ESCALATE_TO_ANALYST [auto] — R4: no reply and exposure exceeds $500
- **What changed:** no reply response added ['DECLINE_TRANSACTION', 'MONITOR_CARD'] and removed ['VERIFY_WITH_CUSTOMER']
- **Evidence items:** 3
  - graph `query:card_window(card_id=C02354-K2)`: Card C02354-K2 has 158 transaction(s) within ±48h of 3491361 totaling $20746.23. (IDs: 3486046, 3486080, 3486178, 3486190, 3486192, 3486266, 3486341, 3486462, 3486507, 3486559, 3486744, 3486755, 3486949, 3486963, 3486966, 3487032, 3487364, 3487401, 3487425, 3487444, 3487493, 3487509, 3487549, 3487557, 3487573, 3487604, 3487632, 3487659, 3487685, 3487694, 3487810, 3487905, 3487973, 3487985, 3487994, 3488000, 3488006, 3488015, 3488023, 3488044, 3488056, 3488061, 3488103, 3488116, 3488325, 3488371, 3488433, 3488476, 3488490, 3488502, 3488570, 3488601, 3488661, 3488749, 3488755, 3488852, 3488866, 3488893, 3488922, 3488954, 3488967, 3488986, 3489157, 3489290, 3489383, 3489428, 3489497, 3489509, 3489515, 3489676, 3489691, 3489703, 3489721, 3489767, 3489772, 3489813, 3489904, 3490019, 3490069, 3490114, 3490180, 3490239, 3490305, 3490411, 3490444, 3490511, 3490585, 3490630, 3490655, 3490727, 3490961, 3490982, 3491104, 3491265, 3491361, 3491379, 3491469, 3491537, 3491586, 3491624, 3491753, 3491759, 3491774, 3491794, 3491856, 3491872, 3492018, 3492105, 3492168, 3492221, 3492278, 3492300, 3492405, 3492558, 3492783, 3492968, 3492992, 3493114, 3493118, 3493254, 3493258, 3493295, 3493301, 3493420, 3493673, 3493830, 3493835, 3493982, 3494040, 3494297, 3494313, 3494500, 3494569, 3494681, 3495111, 3495116, 3495181, 3495232, 3495325, 3495379, 3495392, 3495400, 3495684, 3495731, 3495754, 3495821, 3495904, 3495908, 3495952, 3495996, 3495998, 3496129, 3496239, 3496257, 3496291, 3496335, 3496796, 3496867)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-0454, CC-3537, CC-1450, CC-4942, CC-0255)
  - customer `evidence_request:1`: Step-up authentication fails, consistent with the account being compromised. (IDs: none)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=61959; latency=65.05s
- **Summary:** Verdict: uncertain — the evidence does not support a confirmed fraud determination at this time. The heuristic flags no known pattern (pattern=none, fraud probability 0.28, single signal only), and the activity on card C02354-K2 (customer C02354) is dominated by in-person purchases consistent with the cardholder's broad history across 35 regions and all five products, though the window shows an unusually high volume (168 transactions, $20,746.23 exposure, 2016-11-25 to 2016-11-29) and several online purchases from devices marked New (e.g., txn 3487659, 3489428, 3493830, 3494313, 3495379), which alone would fit pattern 3 only weakly. The customer's prior confirmed cases (CC-0454, CC-1450, CC-0255 account takeover; CC-3537, CC-4942 out-of-region) raise prior risk but do not confirm this window. Recommended action: VERIFY_WITH_CUSTOMER on the flagged online/New-device transactions, MONITOR_CARD for 72 hours, and ESCALATE_TO_ANALYST given the exposure and history; no block should be issued on this weak signal per R1.

## HHG-019

- **Finding:** closed_fraud / fraud / card_not_present_new_device / probability 0.8 / exposure $360.74
- **Initial actions:** MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R6: shared device profile across cards; FILE_REPORT [L2] — R6: shared device profile across cards
- **Final actions:** MONITOR_CONNECTED_CARDS [auto] — R6: shared device profile across cards; CREATE_CASE [auto] — R6: shared device profile across cards; FILE_REPORT [L2] — R6: shared device profile across cards
- **What changed:** nothing
- **Evidence items:** 3
  - graph `query:card_window(card_id=C07987-K2)`: Card C07987-K2 has 4 transaction(s) within ±48h of 3503878 totaling $360.74. (IDs: 3499109, 3503878, 3507926, 3508124)
  - graph `query:device_neighbors(txn_id=3503878)`: Device profile shared with other cards in the review window. (IDs: C01104-K2, C01983-K1, C06224-K2, C11309-K1)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-5026, CC-2860, CC-2011, CC-2087)
- **SAR:** file=True; reason=3a: fraud confirmed/strongly suspected and activity connects to a shared origin; amount=$360.74; dates=['2016-11-30', '2016-12-02']
- **Run:** tool_calls=7; tokens=9062; latency=34.23s
- **Summary:** Verdict: fraud (probability 0.86), consistent with account takeover. Card C07987-K2 (customer C07987) shows mixed-channel activity: normal in-person use (txn 3499109, 3507926, 3508124) alongside online txn 3503878 ($99.92, 2016-12-01) from a device marked New (Windows#d8d6f92018) with risk score 0.90 — a device shared with four other cards (C01104-K2, C01983-K1, C06224-K2, C11309-K1). The customer has three prior confirmed-fraud cases on this same card (CC-5026, CC-2860, CC-2011), and total exposure is $360.74. Recommended: CREATE_CASE, then BLOCK_CARD (route L1, exposure ≤ $2,500) and MONITOR_CONNECTED_CARDS for the cards sharing the device profile.

## HHG-020

- **Finding:** escalated / fraud / account_takeover / probability 0.7 / exposure $508.79
- **Initial actions:** ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **Final actions:** ESCALATE_TO_ANALYST [auto] — R8: uncertain verdict with exposure over $500
- **What changed:** nothing
- **Evidence items:** 2
  - graph `query:card_window(card_id=C12265-K2)`: Card C12265-K2 has 5 transaction(s) within ±48h of 3509359 totaling $508.79. (IDs: 3509359, 3510096, 3510577, 3511725, 3514532)
  - graph `query:closed_case_similarity`: Similar closed investigations were retrieved from case history. (IDs: CC-2447, CC-2277)
- **SAR:** file=False; reason=3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present; amount=$0.00; dates=[]
- **Run:** tool_calls=7; tokens=5584; latency=18.87s
- **Summary:** Verdict: fraud, consistent with account takeover on card C12265-K2 (customer C12265). The pattern matches prior confirmed cases CC-2447 and CC-2277 on the same card: mixed-channel activity inconsistent with the cardholder, with an online transaction (txn 3509359, $125.08, 2016-12-03) flagged with a New device (id_15='New', device profile 'Trident/7.0#be7f40add6', risk score 0.52) alongside otherwise normal in-person purchases in region 264. Total exposure is $508.79 across five transactions on 2016-12-03 and 2016-12-04. Recommended actions: BLOCK_CARD (route L1, exposure ≤ $2,500), preceded by STEP_UP_AUTH and CREATE_CASE, with ESCALATE_TO_ANALYST for review.
