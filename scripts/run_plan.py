"""Plan every MRP run and write the deliverable tables to outputs/.

Usage: python scripts/run_plan.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.accounting import accounting_report  # noqa: E402
from engine.metrics import comparison_table  # noqa: E402
from engine.output import get_planner, write_outputs  # noqa: E402

t = time.time()
planner = get_planner()
out = write_outputs(planner)
print(f"Planned {planner.processed + 1} runs in {time.time() - t:.0f}s -> {out}")
report = accounting_report(planner)
print("Accounting check:", "PASSED" if report["passed"] else "FAILED", json.dumps(report["checks"]))
print(comparison_table(planner).to_string(index=False))
