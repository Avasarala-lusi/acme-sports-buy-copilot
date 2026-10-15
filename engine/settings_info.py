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
