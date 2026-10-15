# Worked examples: MRP-WK020 (14 Dec 2025)

Each example takes a real lot from the plan and shows the calculation step by step, so it can be checked by hand or in Excel. Values come from the supplied data and `config/thresholds.yaml`. The script that writes this page re-checks every result against the engine.


## 0. Monthly buying window

The buying window is the PO day of the third week of each month (days 15-21). MRP-WK020's PO date, 17 Dec 2025, is in the third week, so MRP-WK020 is a **buying run**: its purchases are committed.

The weekly runs before it (MRP-WK017, MRP-WK018, MRP-WK019) showed **drafts** of this window: what it would buy with the demand known that week. Drafts change nothing; the next window is WIN-2026-01 (21 Jan 2026).

## 1. Rule 1: purchase window

Requisition **PR-CC0049143D** (FW-87110-C, PE, 1,525 units).

| Step | Value |
|---|---|
| Requested delivery date (RDD) | 14 Apr 2026 |
| Manufacturing lead time at primary ACME-VN01 | 55 days |
| Transport lead time | 68 days |
| Release date = RDD − 55 − 68 | **12 Dec 2025** |
| This buying window | WIN-2025-12 (17 Dec 2025) |
| Next buying window | WIN-2026-01 (21 Jan 2026) |
| Release date before next window? | Yes → **Buy in this window** |

## 2. Rule 2: 15-day grouping

Lot **MRP-WK020-L117** groups 1 requisition(s) of FW-87110-C for PE:

| Requisition | Size | Units | RDD |
|---|---|---|---|
| PR-CC0049143D | US8 | 1,525 | 14 Apr 2026 |

Latest RDD − earliest RDD = 0 days ≤ 15 → same lot.

## 3. Rule 3: minimum quantities, and capacity routing

| Check | Calculation | Result |
|---|---|---|
| MOQ (per market) | 1,525 = 1,525 ≥ 300 | Met |
| MPQ (footwear, per factory) | FW-87110-C at ACME-ID03 this window = 10,544 ≥ 2,400 | Met |
| Capacity | Primary ACME-VN01 busiest production week **with this lot**: 86% ≥ 85% | Route to backup |
| Backup | ACME-ID03 with this lot: 70.5% → 72.1% < 85%, certified | Assigned |
| Cost change | 1,525 × $154.61 × (0.95 − 1.1) | **−$35,367.04** |

## 4. Rule 4: piggyback (pull-forward to reach a minimum)

Lot **MRP-WK020-L080** (BT-37869-C, CL).

| Step | Value |
|---|---|
| Quantity before | ACME-CN04 total 2302 |
| Threshold | MPQ 2400 |
| Tolerance check | 2,302 ≥ 2,400 × (1 − 5%) = 2,280 → auto-trigger |
| Pulled forward (into an existing market lot) | 78 units from WIN-2026-01 |
| Final lot quantity | 962 |

## 5. Rule 5: wholesale forecast exclusion

| Field | Value |
|---|---|
| Requisition | PR-C8BFADFFEF (FW-44522-C, MX, 216 units) |
| Channel | 01 (wholesale) |
| Confirmed sales order? | No |
| Early Buy article? | No |
| Result | Moved to **Future** (not bought) |

## 5b. Capacity: a lot that needs planner review

Lot **MRP-WK020-L097** (AP-87992-A, US, 1,556 units).

Engine note: Needs planner review: no certified factory has room (ACME-CN04 100.9% with this lot, limit 100%); not bought automatically

Every certified option would pass the 100% limit with this lot, so it is **not bought** and its requisitions are marked for planner review. A planner can approve it, move it, or reject it. This window has 78 such lot(s).

## 6. What-if: credit hold on customer CUST-0001 (rating C)

NSV at risk = sum of CUST-0001's sales orders in this week's lots = **$3,303,079.14**.

| Lot | Before | Removed | After = before − removed | MOQ check | Suggested fix | After fix: MOQ / MPQ |
|---|---|---|---|---|---|---|
| MRP-WK020-L014 | 551 | 307 | 551 − 307 = **244** | < 300, alert | Pull 176 units forward from 1 future MX requisition(s) of HD-82845-C, none from CUST-0001 | OK / OK |
| MRP-WK020-L049 | 1,865 | 1,497 | 1,865 − 1,497 = **368** | ≥ 300, OK | — | OK / OK |
| MRP-WK020-L052 | 2,066 | 2,066 | 2,066 − 2,066 = **0** | lot fully held | Lot fully held: no units left to buy | OK / OK |
| MRP-WK020-L102 | 3,459 | 1,812 | 3,459 − 1,812 = **1,647** | ≥ 300, OK | — | OK / OK |
| MRP-WK020-L130 | 502 | 286 | 502 − 286 = **216** | < 300, alert | Pull 789 units forward from 1 future MX requisition(s) of BT-15695-C, none from CUST-0001 | OK / OK |
| MRP-WK020-L154 | 4,449 | 1,249 | 4,449 − 1,249 = **3,200** | ≥ 300, OK | — | OK / OK |
| MRP-WK020-L193 | 2,005 | 697 | 2,005 − 697 = **1,308** | ≥ 300, OK | — | OK / OK |
| MRP-WK020-L211 | 4,120 | 275 | 4,120 − 275 = **3,845** | ≥ 300, OK | — | OK / OK |
| MRP-WK020-L219 | 2,207 | 2,207 | 2,207 − 2,207 = **0** | lot fully held | Lot fully held: no units left to buy | OK / OK |
| MRP-WK020-L226 | 2,852 | 2,703 | 2,852 − 2,703 = **149** | < 300, alert | No eligible same-market future demand to pull; hold for next window or accept below MOQ | below / OK |
| MRP-WK020-L227 | 1,339 | 1,339 | 1,339 − 1,339 = **0** | lot fully held | Lot fully held: no units left to buy | OK / OK |
| MRP-WK020-L303 | 316 | 316 | 316 − 316 = **0** | lot fully held | Lot fully held: no units left to buy | OK / OK |
| MRP-WK020-L372 | 5,581 | 3,013 | 5,581 − 3,013 = **2,568** | ≥ 300, OK | — | OK / OK |

A fix only uses future demand from other customers (never CUST-0001), each requisition at most once, and MOQ, MPQ and factory load are re-checked after it.

## 7. What-if: ACME-TR05 production delayed 14 days

Lot **MRP-WK020-L001**: expected arrival 22 Feb 2026 + 14 days = **08 Mar 2026**; RDD 05 Feb 2026 → late.

Across ACME-TR05's 40 lots this week: 40 would be late, $7,620,260.59 of sales value at risk.

## 8. What-if: switch lot MRP-WK020-L001 from ACME-TR05 to ACME-CN04

| Step | Value |
|---|---|
| Certified for HD-17100-C? | Yes (ACME-CN04, ACME-ID03, ACME-TR05) |
| Cost change | 2,676 × $73.95 × (1.15 − 1.05) = **$19,789.02** |
| Lead-time change | +48 days |
| New arrival | 11 Apr 2026 vs RDD 05 Feb 2026 → late |
| MOQ still met | Yes (2,676 units, unchanged) |
| ACME-TR05 load (lot removed) | 70.3% → 66.7% |
| ACME-CN04 load (lot added) | 106.1% → **108.0%** (above the threshold) (over capacity) |
| MPQ 1,200 after the move | ACME-TR05 10,960, ACME-CN04 2,676 units |

Switching to **ACME-VN01** is rejected: it is not certified for HD-17100-C in the certification matrix.

## 8b. Pull-forward

Window load uses the same weeks above and below the line: ACME-VN01 in WIN-2025-12 = 88,063 units ÷ (18,000 × 5 weeks) = 97.8% on average; its busiest week is 103.1%. A window is flagged on its busiest week.

542 article-market groups were reviewed in overloaded windows; 4 can move. Each move is tested on one shared copy of the ledger that already holds the earlier moves.

Example: 10,256 units of HD-17100-C for BR at ACME-TR05: Pull forward to WIN-2025-12: busiest week there 70.3% → 83.9%; WIN-2026-02 98.8% → 90.9%.

## 9. Complete accounting (all 100 runs, 23 buying windows)

| Outcome | Units |
|---|---|
| BOUGHT | 7,111,422 |
| FUTURE_FORECAST | 4,336,027 |
| OPEN | 999,030 |
| PLANNER_REVIEW | 4,554,483 |
| UNRESOLVED_MOQ | 192,066 |
| UNRESOLVED_MPQ | 361,615 |
| **Total** | **17,554,643** = all 25,141 requisitions (17,554,643 units) |
