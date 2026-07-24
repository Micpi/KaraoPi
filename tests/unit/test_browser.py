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


def test_pi_display_is_painted_black_when_xsetroot_is_available():
    karaoke = MagicMock()
    karaoke.url = "http://127.0.0.1:5555"
    karaoke.is_raspberry_pi = True
    browser = Browser(karaoke)

    with (
        patch("pikaraoke.lib.browser.is_linux", return_value=True),
        patch("pikaraoke.lib.browser.shutil.which", return_value="/usr/bin/xsetroot"),
        patch("pikaraoke.lib.browser.subprocess.run") as run,
    ):
        browser._prepare_pi_display()

    run.assert_called_once_with(
        ["/usr/bin/xsetroot", "-solid", "black"],
        stdout=-3,
        stderr=-3,
        timeout=3,
        check=False,
    )


def test_pi_chromium_flags_keep_gpu_acceleration_and_bound_cache():
    flags = Browser._pi_chromium_flags()

    assert "--enable-gpu-rasterization" in flags
    assert "--enable-zero-copy" in flags
    assert "--disk-cache-size=67108864" in flags
    assert "--media-cache-size=134217728" in flags
    assert "--disable-gpu" not in flags
    assert "--disable-software-rasterizer" not in flags
