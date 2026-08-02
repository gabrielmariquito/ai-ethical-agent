import pytest

from ethical_agent.gui_choices import ENGINE_LABELS, STAGE_LABELS, engine_value, stage_value
from webui_support import RunningServer


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path)
    yield running
    running.close()


def test_choices_engines_match_gui_choices_module(server):
    status, body, _ = server.get("/api/choices")
    assert status == 200
    expected = [{"label": label, "value": engine_value(label)} for label in ENGINE_LABELS]
    assert body["engines"] == expected


def test_choices_stages_match_gui_choices_module(server):
    status, body, _ = server.get("/api/choices")
    assert status == 200
    expected = [{"label": label, "value": stage_value(label)} for label in STAGE_LABELS]
    assert body["stages"] == expected


def test_choices_defaults_reflect_initial_config(server):
    status, body, _ = server.get("/api/choices")
    assert status == 200
    assert body["defaults"] == server.initial_config
