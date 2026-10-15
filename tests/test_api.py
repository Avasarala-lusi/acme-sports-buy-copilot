"""API contract used by the web front end."""
import pytest

from tests.conftest import needs_data

pytestmark = needs_data
RUN = "MRP-WK020"


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
    assert len(runs) == 100 and sum(r["is_buying_run"] for r in runs) == 23
    assert len(client.get("/factories").json()) == 6
    settings = client.get("/settings").json()
    assert settings["thresholds"]["moq_per_market"] == 300 and settings["items"]
    assert any("backup" in i for i in client.get("/data-issues").json())
    assert not any(client.get("/features").json().values())


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
    assert plan["buying_run_id"] == "MRP-WK025" and plan["lots"]
    r = client.put(f"/overrides/MRP-WK021/lots/{plan['lots'][0]['lot_id']}", json={"decision": "No-Go", "factory": None, "note": ""})
    assert r.status_code == 400 and "draft" in r.json()["detail"]
    assert client.post("/overrides/MRP-WK021/holds", json={"customer_id": "DTC"}).status_code == 400


def test_requisition_lists(client):
    plan = client.get(f"/plan/{RUN}").json()
    for status in ["unresolved", "future", "waiting"]:
        rows = client.get(f"/runs/{RUN}/requisitions?status={status}").json()
        assert len(rows) == plan["counts"][status]
    assert client.get(f"/runs/{RUN}/requisitions?status=bad").status_code == 422


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
    assert len(trend) == 23 and any(t["run_id"] == RUN for t in trend)
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
