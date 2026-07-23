"""Tests for splash browser launch behavior."""

from unittest.mock import MagicMock, patch

from pikaraoke.lib.browser import Browser


def test_pi_launch_url_requests_one_time_boot_reload():
    karaoke = MagicMock()
    karaoke.url = "http://127.0.0.1:5555"
    karaoke.is_raspberry_pi = True

    browser = Browser(karaoke)
    with patch("pikaraoke.lib.browser.time.time", return_value=1234.567):
        assert browser._get_launch_url() == "http://127.0.0.1:5555/splash?kiosk_boot=1234567"


def test_desktop_launch_url_is_unchanged():
    karaoke = MagicMock()
    karaoke.url = "http://127.0.0.1:5555"
    karaoke.is_raspberry_pi = False

    assert Browser(karaoke)._get_launch_url() == "http://127.0.0.1:5555/splash"
