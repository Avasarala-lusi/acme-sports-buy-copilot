"""Client decisions and open assumptions, shown to planners so they can be confirmed."""


def settings_items(cfg: dict) -> list[dict]:
    bw, cap = cfg["buying_window"], cfg["capacity"]
    week = bw["week_of_month"]
    rows = [
        ("Buying window", f"Monthly, week {week} (days {7 * (week - 1) + 1}-{7 * week}); purchases committed only then",
         "Client decision (third week); exact days are our reading"),
        ("Weeks between windows", "Draft of the next window; nothing committed" if bw.get("weekly_drafts", True)
         else "No plan shown", "Assumption: confirm"),
        ("Capacity source", "Rolling ledger from our assignments", "Client decision"),
        ("Capacity check", f"Load including the new lot; route to backup at {cap['backup_threshold_pct']}%",
         "Spec 3.2"),
        ("Factory limit", f"{cap['hard_limit_pct']}% of weekly capacity", "Assumption: confirm (overtime?)"),
        ("No certified factory has room", "Planner review, not bought" if cap["when_no_capacity"] == "planner_review"
         else "Bought with a warning", "Assumption: confirm"),
        ("Weeks used", "All 100", "Client decision"),
        ("DTC customers", "One customer" if cfg["data"]["dtc_as_single_customer"] else "Named accounts (data v5)",
         "Client decision (DTC as one customer) superseded by data v5: confirm"),
        ("Last-chance conflicts", "Warn, don't block (shown as over capacity)", "Client decision"),
        ("Backup factory", {"factory_chain": "Factory chain: backup, its backup, ... to CN04",
                            "factory": "Factory-level backup (one step)",
                            "article": "Article-level backup"}[cfg["backup_source"]],
         "Assumption: data v5 follows the factory chain; confirm"),
        ("15-day grouping", cfg["grouping"]["mode"], "Assumption: confirm (anchor = from earliest RDD)"),
        ("Lot below MOQ/MPQ", "Waits for the next window if it can still start on time, else unresolved",
         "Assumption: confirm"),
        ("MOQ fix after a hold", "Same market only, never the held customer (spec 3.3)",
         "Assumption: spec example says another market"),
        ("Lead time at another factory", "Midpoint of the factory's range", "Assumption"),
        ("Capacity use over time", "Spread over manufacturing weeks", "Assumption"),
    ]
    replacements = {
        "Buying window": ("MID/EOM; latest PO weekday on/before 15th and last PO weekday of month",
                          "Four client PO-date examples verified; remaining calendar formula is a team default"),
        "Factory limit": (f"{cap['hard_limit_pct']}% including manual approvals and last-chance", "Client confirmed"),
        "No certified factory has room": ("Keep visible for planner review; no assumed overtime", "Client confirmed"),
        "Last-chance conflicts": ("Priority first, but never bypass capacity or confirmation conflicts", "Client guidance; user review policy"),
        "Backup factory": ("Factory chain with certification checked at every step", "Client confirmed"),
        "Lead time at another factory": ("Arithmetic midpoint; supplied/estimated source shown", "Client confirmed fallback"),
        "Capacity use over time": ("Business-day-proportional weights in [start, completion); calendar duration",
                                   "Client proportional rule; endpoints/holidays are assumptions"),
        "DTC customers": ("Separate named customer accounts", "Client confirmed"),
        "15-day grouping": ("Earliest-to-latest original RDD, including MPQ and moves", "Client confirmed"),
        "MOQ fix after a hold": ("Same article/market/date span; proposal until accepted", "Client market-separation rule"),
    }
    rows=[(t,*replacements[t]) if t in replacements else (t,s,st) for t,s,st in rows]
    rows.extend([
        ("Priority ties","Earliest RDD, then highest NSV, then order-backed" if cfg.get("priority",{}).get("tie_break","rdd_then_revenue")=="rdd_then_revenue" else "Order-backed, then NSV, then RDD","Client decision (Oct 29)"),
        ("MPQ", "Same article, factory, buying window and 15-day RDD span; category chooses threshold", "Client confirmed"),
        ("Suggested RDD", "PO + manufacture + transit; signed exposure vs original RDD", "User adopted"),
        ("Hold / Delay", "One-window scope; outstanding demand returns later; No-Go cancels", "Assumption: reversible saved decisions"),
        ("Pull-forward source", "Original future scheduled buying run_id, not intake run", "Client field definition; team mapping"),
        ("Forecast", f"{cfg.get('forecast', {}).get('model', 'stage_seasonal')}; 17-week intake horizon, four-window load view", "Team method; historical evaluation required"),
        ("Forecast warnings", "Saved decisions included; estimates warn but never reserve capacity or block a valid purchase", "User-approved workflow"),
        ("Optimizer and benchmark", "Read-only chronological replay; client priority before cost/planned service; full eligible population", "User-approved release workflow; see validation results"),
        ("Later additions", "On-time simulation, disruption drill, data-health and plain-English tools remain disabled", "User scope decision"),
    ])
    return [{"topic": t, "setting": s, "status": st} for t, s, st in rows]


def thresholds(cfg: dict) -> dict:
    return {
        "moq_per_market": cfg["quantities"]["moq_per_market"],
        "mpq_apparel": cfg["quantities"]["mpq"]["apparel"],
        "mpq_footwear": cfg["quantities"]["mpq"]["footwear"],
        "backup_threshold_pct": cfg["capacity"]["backup_threshold_pct"],
        "hard_limit_pct": cfg["capacity"]["hard_limit_pct"],
        "piggyback_tolerance_pct": cfg["piggyback"]["tolerance_pct"],
        "grouping_window_days": cfg["grouping"]["window_days"],
    }
