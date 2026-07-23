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


def test_download_archive_uses_github_api_media_type(tmp_path):
    class FakeResponse:
        ok = True
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_content(self, chunk_size):
            assert chunk_size == 1024 * 64
            yield b"zip-content"

    with patch.object(
        karaopi_release.requests, "get", return_value=FakeResponse()
    ) as request_get:
        archive = karaopi_release.download_release_archive(
            "https://api.github.com/repos/Micpi/KaraoPi/zipball/v9.9.9",
            str(tmp_path),
        )

    assert (tmp_path / "release.zip").read_bytes() == b"zip-content"
    assert archive == str(tmp_path / "release.zip")
    assert request_get.call_args.kwargs["headers"]["Accept"] == "application/vnd.github+json"
