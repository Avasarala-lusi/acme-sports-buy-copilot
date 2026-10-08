# Worked examples: MRP-WK020 (14 Dec 2025)

Each example takes a real lot from the plan and shows the calculation step by step, so it can be checked by hand or in Excel. Values come from the supplied data and `config/thresholds.yaml`. The script that writes this page re-checks every result against the engine.


## 1. Rule 1: purchase window

Requisition **PR-4A93DA5C98** (AP-19602-C, CO, 855 units).

| Step | Value |
|---|---|
| Requested delivery date (RDD) | 09 Apr 2026 |
| Manufacturing lead time at primary ACME-CN04 | 45 days |
| Transport lead time | 65 days |
| Release date = RDD − 45 − 65 | **20 Dec 2025** |
| Run date | 14 Dec 2025 |
| Current buying window (cutoff day 21) | WIN-2025-12 |
| Next buying window | WIN-2026-01 (21 Jan 2026) |
| Release date before next window? | Yes → **Buy now** |

## 2. Rule 2: 15-day grouping

Lot **MRP-WK020-L008** groups 2 requisition(s) of AP-19602-C for CO:

| Requisition | Size | Units | RDD |
|---|---|---|---|
| PR-4A93DA5C98 | L | 855 | 09 Apr 2026 |
| PR-FC7D9CFDF8 | S | 152 | 22 Apr 2026 |

Latest RDD − earliest RDD = 13 days ≤ 15 → same lot.

## 3. Rule 3: minimum quantities, and capacity routing

| Check | Calculation | Result |
|---|---|---|
| MOQ (per market) | 855 + 152 = 1,007 ≥ 300 | Met |
| MPQ (apparel, per factory) | AP-19602-C at ACME-IN06 this run = 2,654 ≥ 1,200 | Met |
| Capacity | Primary ACME-CN04 at 114% ≥ 85% | Route to backup |
| Backup | ACME-IN06 at 32% < 85%, certified | Assigned |
| Cost change | 1,007 × $97.97 × (0.88 − 1.15) | **−$26,637.06** |

## 4. Rule 4: piggyback (pull-forward to reach a minimum)

Lot **MRP-WK020-L005** (TK-36685-C, US).

| Step | Value |
|---|---|
| Quantity before | ACME-TR05 total 1197 |
| Threshold | MPQ 1200 |
| Tolerance check | 1,197 ≥ 1,200 × (1 − 5%) = 1,140 → auto-trigger |
| Pulled forward (into an existing market lot) | 156 units from WIN-2026-01 |
| Final lot quantity | 1,353 |

## 5. Rule 5: wholesale forecast exclusion

| Field | Value |
|---|---|
| Requisition | PR-C5C5A9B8AB (HD-83519-A, PE, 111 units) |
| Channel | 01 (wholesale) |
| Confirmed sales order? | No |
| Early Buy article? | No |
| Result | Moved to **Future** (not bought) |

## 6. What-if: hold customer CUST-0012

NSV at risk = sum of CUST-0012's sales orders in this week's lots = **$323,551.09**.

| Lot | Before | Removed | After = before − removed | MOQ check | Suggested fix |
|---|---|---|---|---|---|
| MRP-WK020-L003 | 390 | 390 | 390 − 390 = **0** | lot fully held | Lot fully held: no units left to buy |
| MRP-WK020-L013 | 2,228 | 474 | 2,228 − 474 = **1,754** | ≥ 300, OK | — |
| MRP-WK020-L031 | 576 | 289 | 576 − 289 = **287** | < 300, alert | Pull 289 units forward from 1 future CL requisition(s) of FW-44522-C |

## 7. What-if: ACME-TR05 production delayed 14 days

Lot **MRP-WK020-L001**: expected arrival 26 Feb 2026 + 14 days = **12 Mar 2026**; RDD 26 Feb 2026 → late.

Across ACME-TR05's 9 lots this week: 9 would be late, $1,166,458.64 of sales value at risk.

## 8. What-if: switch lot MRP-WK020-L001 from ACME-TR05 to ACME-CN04

| Step | Value |
|---|---|
| Certified for HD-17100-C? | Yes (ACME-CN04, ACME-ID03, ACME-TR05) |
| Cost change | 1,012 × $73.95 × (1.15 − 1.05) = **$7,483.74** |
| Lead-time change | +43 days |
| New arrival | 06 Apr 2026 vs RDD 26 Feb 2026 → late |
| MOQ still met | Yes (1,012 units, unchanged) |

Switching to **ACME-VN01** is rejected: it is not certified for HD-17100-C in the certification matrix.

## 9. Complete accounting (all 100 runs)

| Outcome | Units |
|---|---|
| BOUGHT | 11,815,627 |
| FUTURE_FORECAST | 4,326,491 |
| OPEN | 580,803 |
| UNRESOLVED_MOQ | 160,737 |
| UNRESOLVED_MPQ | 291,793 |
| **Total** | **17,175,451** = all 24,962 requisitions (17,175,451 units) |
