"""Client decisions and open assumptions, shown to planners so they can be confirmed."""


def settings_items(cfg: dict) -> list[dict]:
    rows = [
        ("Buying window", f"Monthly, cutoff day {cfg['buying_window']['cutoff_day']}",
         "Client decision (third week); cutoff day is our reading"),
        ("Capacity source", "Rolling ledger from our assignments", "Client decision"),
        ("Weeks used", "All 100", "Client decision"),
        ("DTC", "One customer", "Client decision"),
        ("Last-chance conflicts", "Warn, don't block", "Client decision"),
        ("Backup factory", f"{cfg['backup_source']}-level", "Assumption: confirm"),
        ("15-day grouping", cfg["grouping"]["mode"], "Assumption: confirm (anchor = from earliest RDD)"),
        ("Primary and backup both over 85%", "Less-loaded factory plus warning", "Assumption: confirm"),
        ("Lot below MOQ/MPQ", "Waits for the next run if it can still start on time", "Assumption: confirm"),
        ("MOQ fix after a hold", "Same market only (spec 3.3)", "Assumption: spec example says another market"),
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
        "piggyback_tolerance_pct": cfg["piggyback"]["tolerance_pct"],
        "grouping_window_days": cfg["grouping"]["window_days"],
    }
