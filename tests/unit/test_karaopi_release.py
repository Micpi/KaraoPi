"""Tests for the Raspberry Pi self-update workflow."""

from unittest.mock import patch

import pytest

from pikaraoke.lib import karaopi_release


def test_install_requirements_uses_uv_when_available(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='karaopi'\n", encoding="utf-8")

    with (
        patch.object(karaopi_release.shutil, "which", return_value="/usr/bin/uv"),
        patch.object(karaopi_release.subprocess, "check_call") as check_call,
    ):
        karaopi_release.install_requirements(str(tmp_path))

    check_call.assert_called_once_with(["/usr/bin/uv", "sync"], cwd=str(tmp_path))


def test_failed_pending_update_keeps_marker_for_diagnostics_and_retry(tmp_path):
    karaopi_release.write_pending_update_marker(
        str(tmp_path), "Micpi/KaraoPi", "v9.9.9", "https://example.invalid/release.zip"
    )

    with patch.object(
        karaopi_release, "download_release_archive", side_effect=RuntimeError("download failed")
    ):
        with pytest.raises(RuntimeError, match="download failed"):
            karaopi_release.apply_pending_update(str(tmp_path))

    assert karaopi_release.read_pending_update_marker(str(tmp_path))["tag"] == "v9.9.9"
