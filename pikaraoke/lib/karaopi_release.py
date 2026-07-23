"""KaraoPi self-update helper: checks and installs releases published on GitHub.

This module is specific to the Micpi/KaraoPi fork and is not part of upstream
PiKaraoke. It lets a git-clone based Raspberry Pi install update itself from a
published GitHub Release without requiring PyPI/uv tool distribution.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import requests

DEFAULT_REPOSITORY = "Micpi/KaraoPi"
GITHUB_API_BASE = "https://api.github.com/repos"
UPDATE_LOG_FILE = "karaopi-update.log"
UPDATE_TIMEOUT_SECONDS = 10


class AppUpdateError(RuntimeError):
    pass


def normalize_release_version(version):
    return str(version or "").strip().lstrip("vV")


def version_key(version):
    parts = re.findall(r"\d+|[A-Za-z]+", normalize_release_version(version))
    key = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.lower()))
    return key


def get_latest_release_info(repository=DEFAULT_REPOSITORY, timeout=UPDATE_TIMEOUT_SECONDS):
    try:
        response = requests.get(
            f"{GITHUB_API_BASE}/{repository}/releases/latest",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "KaraoPi-Updater",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AppUpdateError(f"Unable to fetch latest GitHub release: {exc}")

    if response.status_code == 404:
        raise AppUpdateError(f"No published GitHub release is available yet for {repository}.")
    if not response.ok:
        raise AppUpdateError(f"Unable to fetch latest GitHub release: HTTP {response.status_code}")

    release = response.json()
    tag_name = release.get("tag_name")
    zipball_url = release.get("zipball_url")
    if not tag_name or not zipball_url:
        raise AppUpdateError("Latest GitHub release is missing a tag or source archive URL.")
    return {
        "name": release.get("name") or tag_name,
        "tag_name": tag_name,
        "version": normalize_release_version(tag_name),
        "html_url": release.get("html_url"),
        "zipball_url": zipball_url,
        "published_at": release.get("published_at"),
    }


def get_release_update_status(current_version, repository=DEFAULT_REPOSITORY):
    latest_release = get_latest_release_info(repository=repository)
    current_key = version_key(current_version)
    latest_key = version_key(latest_release["version"])
    update_available = latest_key > current_key
    return {
        "repository": repository,
        "current_version": normalize_release_version(current_version),
        "latest_version": latest_release["version"],
        "latest_tag": latest_release["tag_name"],
        "latest_name": latest_release["name"],
        "latest_url": latest_release["html_url"],
        "published_at": latest_release["published_at"],
        "zipball_url": latest_release["zipball_url"],
        "update_available": update_available,
    }


def get_pending_update_marker_path(app_root):
    return os.path.join(app_root, ".karaopi_update_pending.json")


def write_pending_update_marker(app_root, repository, tag, zip_url):
    marker = {"repository": repository, "tag": tag, "zip_url": zip_url}
    with open(get_pending_update_marker_path(app_root), "w", encoding="utf-8") as marker_file:
        json.dump(marker, marker_file)


def read_pending_update_marker(app_root):
    marker_path = get_pending_update_marker_path(app_root)
    if not os.path.isfile(marker_path):
        return None
    with open(marker_path, "r", encoding="utf-8") as marker_file:
        return json.load(marker_file)


def clear_pending_update_marker(app_root):
    marker_path = get_pending_update_marker_path(app_root)
    if os.path.isfile(marker_path):
        os.remove(marker_path)


def apply_pending_update(app_root):
    """Apply a pending update marker synchronously, if one exists.

    Intended to be called by scripts/karaopi_launch.sh right after the app
    process exits and before relaunching it, so the update is fully applied
    before the next launch instead of racing with the launcher's own restart
    loop (which would otherwise instantly relaunch the OLD version).

    Returns True if an update was applied, False if none was pending.
    """
    marker = read_pending_update_marker(app_root)
    if marker is None:
        return False

    configure_logging(app_root)
    logging.info("Applying pending KaraoPi update to %s", marker["tag"])
    with tempfile.TemporaryDirectory(prefix="karaopi-update-") as temp_dir:
        archive_path = download_release_archive(marker["zip_url"], temp_dir)
        release_root = extract_release_archive(archive_path, temp_dir)
        sync_release_to_app_root(release_root, app_root)
    install_requirements(app_root)
    clear_pending_update_marker(app_root)
    logging.info("KaraoPi update to %s applied successfully.", marker["tag"])
    return True


def start_background_update(app_root, current_version, relaunch_command, repository=DEFAULT_REPOSITORY):
    update_status = get_release_update_status(current_version, repository=repository)
    if not update_status["update_available"]:
        raise AppUpdateError("KaraoPi is already running the latest release.")

    if os.environ.get("KARAOPI_LAUNCHER"):
        # Running under scripts/karaopi_launch.sh: just record the pending update.
        # Its restart loop will apply it synchronously right after this process
        # exits and before relaunching, instead of racing a detached updater
        # against the loop's own instant restart (which would relaunch the OLD
        # version before the update finished downloading/installing).
        write_pending_update_marker(
            app_root, repository, update_status["latest_tag"], update_status["zipball_url"]
        )
        logging.info(
            "Recorded pending KaraoPi update to %s for the kiosk launcher to apply",
            update_status["latest_tag"],
        )
        return update_status

    updater_command = [
        sys.executable,
        os.path.abspath(__file__),
        "--app-root",
        app_root,
        "--repository",
        repository,
        "--tag",
        update_status["latest_tag"],
        "--zip-url",
        update_status["zipball_url"],
        "--wait-for-pid",
        str(os.getpid()),
        "--relaunch-command",
    ]
    updater_command.extend(relaunch_command)

    logging.info("Starting KaraoPi self-update process for release %s", update_status["latest_tag"])
    subprocess.Popen(
        updater_command,
        cwd=app_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return update_status


def process_exists(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        process = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in process.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_process_exit(pid, timeout=120):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not process_exists(pid):
            return
        time.sleep(1)
    raise AppUpdateError(f"Timed out while waiting for process {pid} to exit.")


def download_release_archive(zip_url, destination_dir):
    archive_path = os.path.join(destination_dir, "release.zip")
    try:
        with requests.get(
            zip_url,
            headers={"Accept": "application/octet-stream", "User-Agent": "KaraoPi-Updater"},
            timeout=UPDATE_TIMEOUT_SECONDS,
            stream=True,
        ) as response:
            if not response.ok:
                raise AppUpdateError(f"Unable to download release archive: HTTP {response.status_code}")
            with open(archive_path, "wb") as archive_file:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        archive_file.write(chunk)
    except requests.RequestException as exc:
        raise AppUpdateError(f"Unable to download release archive: {exc}")
    return archive_path


def extract_release_archive(archive_path, destination_dir):
    with zipfile.ZipFile(archive_path, "r") as archive:
        archive.extractall(destination_dir)

    extracted_entries = [
        os.path.join(destination_dir, name)
        for name in os.listdir(destination_dir)
        if name != os.path.basename(archive_path)
    ]
    extracted_dirs = [path for path in extracted_entries if os.path.isdir(path)]
    if len(extracted_dirs) != 1:
        raise AppUpdateError("Unable to locate the extracted KaraoPi release contents.")
    return extracted_dirs[0]


def sync_release_to_app_root(release_root, app_root):
    excluded_names = {".git", ".venv", "__pycache__", UPDATE_LOG_FILE}

    for entry_name in os.listdir(release_root):
        if entry_name in excluded_names:
            continue
        source_path = os.path.join(release_root, entry_name)
        target_path = os.path.join(app_root, entry_name)

        if os.path.isdir(source_path):
            shutil.copytree(
                source_path,
                target_path,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        else:
            os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
            shutil.copy2(source_path, target_path)


def install_requirements(app_root):
    pyproject_path = os.path.join(app_root, "pyproject.toml")
    if not os.path.isfile(pyproject_path):
        logging.info("No pyproject.toml found after update, skipping dependency install.")
        return

    uv_executable = shutil.which("uv")
    if uv_executable:
        # Kiosk installations are created with `uv sync`. Their virtual
        # environment intentionally may not contain pip, so `python -m pip`
        # is not a reliable update path.
        install_command = [uv_executable, "sync"]
        logging.info("Installing KaraoPi dependencies: %s", " ".join(install_command))
        subprocess.check_call(install_command, cwd=app_root)
        return

    if os.name == "nt":
        venv_python = os.path.join(app_root, ".venv", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(app_root, ".venv", "bin", "python")

    python_executable = venv_python if os.path.isfile(venv_python) else sys.executable
    install_command = [python_executable, "-m", "pip", "install", "-e", "."]

    logging.info("Installing KaraoPi dependencies: %s", " ".join(install_command))
    subprocess.check_call(install_command, cwd=app_root)


def relaunch_application(relaunch_command, app_root):
    if not relaunch_command:
        if os.name == "nt":
            venv_python = os.path.join(app_root, ".venv", "Scripts", "python.exe")
        else:
            venv_python = os.path.join(app_root, ".venv", "bin", "python")
        python_executable = venv_python if os.path.isfile(venv_python) else sys.executable
        relaunch_command = [python_executable, "-m", "pikaraoke.app"]
    logging.info("Relaunching KaraoPi: %s", " ".join(relaunch_command))
    subprocess.Popen(
        relaunch_command,
        cwd=app_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def configure_logging(app_root):
    log_path = os.path.join(app_root, UPDATE_LOG_FILE)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def run_update(app_root, repository, tag, zip_url, wait_for_pid, relaunch_command):
    log_path = configure_logging(app_root)
    logging.info("Preparing KaraoPi update from repository %s to release %s", repository, tag)
    logging.info("Update log: %s", log_path)

    wait_for_process_exit(wait_for_pid)
    logging.info("Application process %s exited, downloading release archive", wait_for_pid)

    with tempfile.TemporaryDirectory(prefix="karaopi-update-") as temp_dir:
        archive_path = download_release_archive(zip_url, temp_dir)
        release_root = extract_release_archive(archive_path, temp_dir)
        sync_release_to_app_root(release_root, app_root)

    install_requirements(app_root)
    relaunch_application(relaunch_command, app_root)
    logging.info("KaraoPi update finished successfully.")


def parse_args(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="KaraoPi GitHub release updater")
    parser.add_argument("--app-root", required=True)
    parser.add_argument(
        "--apply-pending",
        action="store_true",
        help="Apply a pending update marker synchronously and exit (used by the kiosk launcher)",
    )
    parser.add_argument("--repository")
    parser.add_argument("--tag")
    parser.add_argument("--zip-url")
    parser.add_argument("--wait-for-pid", type=int)
    parser.add_argument("--relaunch-command", nargs=argparse.REMAINDER, default=[])
    return parser.parse_args(argv)


def main(argv=None):
    parsed_args = parse_args(argv)
    app_root = os.path.abspath(parsed_args.app_root)

    if parsed_args.apply_pending:
        try:
            apply_pending_update(app_root)
        except Exception as exc:
            configure_logging(app_root)
            logging.exception("Failed to apply pending KaraoPi update: %s", exc)
            return 1
        return 0

    missing = [
        name
        for name, value in (
            ("--repository", parsed_args.repository),
            ("--tag", parsed_args.tag),
            ("--zip-url", parsed_args.zip_url),
            ("--wait-for-pid", parsed_args.wait_for_pid),
        )
        if value is None
    ]
    if missing:
        print(f"Missing required arguments: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        run_update(
            app_root=app_root,
            repository=parsed_args.repository,
            tag=parsed_args.tag,
            zip_url=parsed_args.zip_url,
            wait_for_pid=parsed_args.wait_for_pid,
            relaunch_command=parsed_args.relaunch_command,
        )
    except Exception as exc:
        try:
            configure_logging(app_root)
        except Exception:
            pass
        logging.exception("KaraoPi update failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
