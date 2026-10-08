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
    assert len(client.get("/runs").json()) == 100
    assert len(client.get("/factories").json()) == 6
    settings = client.get("/settings").json()
    assert settings["thresholds"]["moq_per_market"] == 300 and settings["items"]
    assert len(client.get("/data-issues").json()) >= 5
    assert not any(client.get("/features").json().values())


def test_plan_shape(client):
    plan = client.get(f"/plan/{RUN}").json()
    lot = plan["lots"][0]
    for key in ["lot_id", "reason", "warnings", "decision", "decision_type", "certified_factories", "suggested_rdd"]:
        assert key in lot
    assert plan["kpis"] == plan["kpis_automatic"] and plan["manual_changes"] == 0
    assert set(plan["counts"]) == {"unresolved", "future", "waiting"}


def test_requisition_lists(client):
    plan = client.get(f"/plan/{RUN}").json()
    for status in ["unresolved", "future", "waiting"]:
        rows = client.get(f"/runs/{RUN}/requisitions?status={status}").json()
        assert len(rows) == plan["counts"][status]
    assert client.get(f"/runs/{RUN}/requisitions?status=bad").status_code == 422


def test_decision_round_trip(client):
    lot = client.get(f"/plan/{RUN}").json()["lots"][0]
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
