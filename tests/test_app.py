"""Headless check that the Streamlit app runs for sample weeks and every scenario."""
import pytest

from tests.conftest import needs_data

pytestmark = needs_data
APP = "app/streamlit_app.py"


@pytest.fixture(scope="module")
def app():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    assert not at.exception, at.exception
    return at


@pytest.mark.parametrize("week_index", [0, 19, 50, 99])
def test_week_renders(app, week_index):
    app.sidebar.selectbox[0].select_index(week_index).run()
    assert not app.exception, app.exception
    assert app.metric[0].label == "Lots to buy"


@pytest.mark.parametrize("scenario", ["Hold a customer", "Delay production", "Switch factories"])
def test_scenarios_render(app, scenario):
    app.sidebar.selectbox[0].select_index(19).run()
    app.radio[0].set_value(scenario).run()
    assert not app.exception, app.exception


def test_switch_to_uncertified_factory_shows_error(app):
    app.sidebar.selectbox[0].select_index(19).run()
    app.radio[0].set_value("Switch factories").run()
    target = next(s for s in app.selectbox if s.label.startswith("Move from"))
    bad = next(i for i, o in enumerate(target.options) if "not certified" in o)
    target.select_index(bad).run()
    assert any("not certified" in e.value for e in app.error)
