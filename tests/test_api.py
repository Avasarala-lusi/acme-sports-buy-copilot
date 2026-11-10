"""API contract used by the web front end."""
import pytest

from tests.conftest import needs_data

pytestmark = needs_data
RUN = "MRP-WK019"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient

    import api.main as main
    from engine.overrides import OverrideStore

    path = tmp_path_factory.mktemp("overrides") / "overrides.json"
    main.store = lambda: OverrideStore(path)  # keep test decisions out of the real file
    return TestClient(main.app)


def test_reference_endpoints(client):
    assert client.get("/health").json()["runs"] == 100
    runs = client.get("/runs").json()
    assert len(runs) == 100 and sum(r["is_buying_run"] for r in runs) == 46
    assert len(client.get("/factories").json()) == 6
    settings = client.get("/settings").json()
    assert settings["thresholds"]["moq_per_market"] == 300 and settings["items"]
    assert any("backup" in i for i in client.get("/data-issues").json())
    assert client.get("/features").json()["forecast"] is True


def test_plan_shape(client):
    plan = client.get(f"/plan/{RUN}").json()
    lot = plan["lots"][0]
    for key in ["lot_id", "reason", "warnings", "decision", "decision_type", "certified_factories", "suggested_rdd"]:
        assert key in lot
    assert plan["kpis"] == plan["kpis_automatic"] and plan["manual_changes"] == 0
    assert set(plan["counts"]) == {"unresolved", "future", "review", "waiting"}
    assert plan["is_buying_run"] and plan["plan_status"] == "Committed" and plan["buying_run_id"] == RUN


def test_draft_week(client):
    plan = client.get("/plan/MRP-WK021").json()
    assert not plan["is_buying_run"] and plan["plan_status"] == "Draft"
    assert plan["buying_run_id"] == "MRP-WK022" and plan["lots"]
    r = client.put(f"/overrides/MRP-WK021/lots/{plan['lots'][0]['lot_id']}", json={"decision": "No-Go", "factory": None, "note": ""})
    assert r.status_code == 400 and "draft" in r.json()["detail"]
    assert client.post("/overrides/MRP-WK021/holds", json={"customer_id": "DTC"}).status_code == 400


def test_requisition_lists(client):
    plan = client.get(f"/plan/{RUN}").json()
    for status in ["unresolved", "future", "waiting"]:
        rows = client.get(f"/runs/{RUN}/requisitions?status={status}").json()
        assert len(rows) == plan["counts"][status]
    assert client.get(f"/runs/{RUN}/requisitions?status=bad").status_code == 422


def test_overdue_pr_remains_in_current_review_rows(client):
    pr_id = "PR-4EE6B9E79A"
    for run in ("MRP-WK019", "MRP-WK020", "MRP-WK022"):
        plan = client.get(f"/plan/{run}").json()
        matches = [lot for lot in plan["lots"] if pr_id in lot["pr_ids"].split(",")]
        assert len(matches) == 1
        lot = matches[0]
        assert lot["decision"] == "Review"
        detail = client.get(f"/lots/{run}/{lot['lot_id']}/requisitions").json()
        assert any(row["pr_id"] == pr_id and row["requested_qty"] == 411 for row in detail)


def test_decision_round_trip(client):
    lot = next(l for l in client.get(f"/plan/{RUN}").json()["lots"] if l["auto_decision"] == "Buy")
    client.put(f"/overrides/{RUN}/lots/{lot['lot_id']}", json={"decision": "No-Go", "factory": None, "note": "test"})
    plan = client.get(f"/plan/{RUN}").json()
    changed = next(l for l in plan["lots"] if l["lot_id"] == lot["lot_id"])
    assert changed["decision"] == "No-Go" and changed["decision_type"] == "manual"
    assert plan["manual_changes"] == 1 and plan["kpis"]["lots"] == plan["kpis_automatic"]["lots"] - 1
    client.delete(f"/overrides/{RUN}")
    assert client.get(f"/plan/{RUN}").json()["manual_changes"] == 0


def test_uncertified_switch_rejected(client):
    lot = client.get(f"/plan/{RUN}").json()["lots"][0]
    factories = [f["factory_id"] for f in client.get("/factories").json()]
    bad = next(f for f in factories if f not in lot["certified_factories"])
    r = client.put(f"/overrides/{RUN}/lots/{lot['lot_id']}", json={"decision": "Buy", "factory": bad, "note": ""})
    assert r.status_code == 400


def test_exports(client):
    csv = client.get(f"/export/{RUN}?format=csv")
    assert csv.status_code == 200 and csv.text.startswith("suggestion_id,run_id")
    xlsx = client.get(f"/export/{RUN}?format=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_unknown_run_is_404(client):
    assert client.get("/plan/MRP-WK999").status_code == 404


def test_trend_and_units(client):
    trend = client.get("/trend").json()
    assert len(trend) == 46 and any(t["run_id"] == RUN for t in trend)
    plan = client.get(f"/plan/{RUN}").json()
    point = next(t for t in trend if t["run_id"] == RUN)
    assert point["lots"] == plan["kpis_automatic"]["lots"]
    assert plan["units"]["bought"] == plan["kpis"]["units_bought"] and plan["units"]["waiting"] > 0


def test_network_routes_add_up(client):
    net = client.get(f"/network/{RUN}").json()
    plan = client.get(f"/plan/{RUN}").json()
    assert len(net["factories"]) == 6 and net["routes"]
    assert abs(sum(r["bought_units"] for r in net["routes"]) - plan["kpis"]["units_bought"]) < 1e-6
    assert abs(sum(r["review_units"] for r in net["routes"]) - plan["kpis"]["review_units"]) < 1e-6


def test_checks_include_baseline_evaluation(client):
    baseline = client.get("/checks").json()["baseline"]
    assert any(r["metric"].startswith("Backup-triggered") for r in baseline)


def test_forecast_endpoint(client):
    f = client.get(f"/forecast/{RUN}").json()
    assert f["intake"] and f["load"] and f["windows"] and f["origin_week"] == int(RUN[-3:])
    assert all(row["actual"] is None for row in f["intake"])
    assert client.get(f"/forecast/{RUN}?model=invented").status_code == 400


def test_waiting_demand_does_not_double_count_review_or_unresolved(client):
    plan = client.get("/plan/MRP-WK022").json()
    review = {p for row in plan["lots"] if row["decision"] == "Review" for p in row["pr_ids"].split(",") if p}
    waiting = client.get("/runs/MRP-WK022/requisitions?status=waiting").json()
    unresolved = client.get("/runs/MRP-WK022/requisitions?status=unresolved").json()
    assert review.isdisjoint(row["pr_id"] for row in waiting)
    assert plan["units"]["waiting"] == sum(row["requested_qty"] for row in waiting)
    assert plan["units"]["unresolved"] == sum(row["requested_qty"] for row in unresolved)
    assert plan["counts"]["waiting"] == len(waiting)


def test_impact_endpoint(client):
    r = client.get("/impact?price=21").json()
    assert r["price_per_unit_usd"] == 21 and r["by_market"] and r["top_customers"]


def test_extension_endpoints(client):
    f = client.get("/features").json()
    assert not any(f[k] for k in ["risk", "drill", "data_health", "ask"])
    assert f["optimizer"] and f["benchmark"]
    assert f["forecast"]
    for path in ["/risk", "/data-health"]:
        assert client.get(path).status_code == 409


def test_released_network_endpoint_does_not_enable_other_prototypes(client, monkeypatch):
    from api import main
    monkeypatch.setattr(main, "_network_results", lambda: {"complete": True, "service_basis": "Planned on-time units"})
    r = client.get("/network-plans")
    assert r.status_code == 200 and r.json()["complete"]
    assert client.get("/risk").status_code == 409
