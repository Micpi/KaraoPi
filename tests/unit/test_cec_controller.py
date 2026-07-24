"""Tests for optional HDMI-CEC media controls."""

from unittest.mock import Mock

from pikaraoke.lib.cec_controller import CecController


def test_parse_supported_cec_keys():
    assert CecController.parse_action("DEBUG: key pressed: play (44)") == "play"
    assert CecController.parse_action("DEBUG: key pressed: pause (46)") == "pause"
    assert CecController.parse_action("DEBUG: key pressed: pause/play (61)") == "play_pause"
    assert CecController.parse_action("DEBUG: key pressed: stop (45)") == "stop"
    assert CecController.parse_action("DEBUG: key pressed: forward (4b)") == "next"
    assert CecController.parse_action("DEBUG: key pressed: backward (4c)") == "previous"


def test_parse_ignores_non_key_log_lines():
    assert CecController.parse_action("DEBUG: user control pressed (44)") is None
    assert CecController.parse_action("DEBUG: key released: play (44)") is None
    assert CecController.parse_action("TRAFFIC: << 10:44:41") is None


def test_start_is_optional_when_cec_client_is_missing():
    controller = CecController(Mock(), executable="")
    assert controller.start() is False


def test_dispatch_debounces_duplicate_press_events(monkeypatch):
    callback = Mock()
    controller = CecController(callback, executable="cec-client", debounce_seconds=0.5)
    times = iter([10.0, 10.1, 11.0])
    monkeypatch.setattr("pikaraoke.lib.cec_controller.time.monotonic", lambda: next(times))

    controller._dispatch("play_pause")
    controller._dispatch("play_pause")
    controller._dispatch("play_pause")

    assert callback.call_count == 2
