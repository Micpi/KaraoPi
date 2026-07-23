import argparse
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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
    request = Request(
        f"{GITHUB_API_BASE}/{repository}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "KaraoPi-Updater",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            release = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise AppUpdateError(f"No published GitHub release is available yet for {repository}.")
        raise AppUpdateError(f"Unable to fetch latest GitHub release: {exc}")
    except URLError as exc:
        raise AppUpdateError(f"Unable to fetch latest GitHub release: {exc}")
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


def start_background_update(app_root, current_version, relaunch_command, repository=DEFAULT_REPOSITORY):
    update_status = get_release_update_status(current_version, repository=repository)
    if not update_status["update_available"]:
        raise AppUpdateError("KaraoPi is already running the latest release.")

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


def wait_for_process_exit(pid, timeout=120):
    start_time = time.time()
    while time.time() - start_time < timeout:
        if not process_exists(pid):
            return
        time.sleep(1)
    raise AppUpdateError(f"Timed out while waiting for process {pid} to exit.")


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


def download_release_archive(zip_url, destination_dir):
    archive_path = os.path.join(destination_dir, "release.zip")
    request = Request(
        zip_url,
        headers={"Accept": "application/octet-stream", "User-Agent": "KaraoPi-Updater"},
    )
    try:
        with urlopen(request, timeout=UPDATE_TIMEOUT_SECONDS) as response:
            with open(archive_path, "wb") as archive_file:
                while True:
                    chunk = response.read(1024 * 64)
                    if not chunk:
                        break
                    archive_file.write(chunk)
    except (HTTPError, URLError) as exc:
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
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)


def install_requirements(app_root):
    requirements_path = os.path.join(app_root, "requirements.txt")
    if not os.path.isfile(requirements_path):
        logging.info("No requirements.txt found after update, skipping dependency install.")
        return

    if os.name == "nt":
        venv_pip = os.path.join(app_root, ".venv", "Scripts", "pip.exe")
    else:
        venv_pip = os.path.join(app_root, ".venv", "bin", "pip")

    if os.path.isfile(venv_pip):
        install_command = [venv_pip, "install", "-r", requirements_path]
    else:
        install_command = [sys.executable, "-m", "pip", "install", "-r", requirements_path]

    logging.info("Installing KaraoPi dependencies: %s", " ".join(install_command))
    subprocess.check_call(install_command, cwd=app_root)


def relaunch_application(relaunch_command, app_root):
    if not relaunch_command:
        relaunch_command = [sys.executable, os.path.join(app_root, "app.py")]
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
    parser = argparse.ArgumentParser(description="KaraoPi GitHub release updater")
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--zip-url", required=True)
    parser.add_argument("--wait-for-pid", type=int, required=True)
    parser.add_argument("--relaunch-command", nargs=argparse.REMAINDER, default=[])
    return parser.parse_args(argv)


def main(argv=None):
    parsed_args = parse_args(argv)
    try:
        run_update(
            app_root=os.path.abspath(parsed_args.app_root),
            repository=parsed_args.repository,
            tag=parsed_args.tag,
            zip_url=parsed_args.zip_url,
            wait_for_pid=parsed_args.wait_for_pid,
            relaunch_command=parsed_args.relaunch_command,
        )
    except Exception as exc:
        try:
            configure_logging(os.path.abspath(parsed_args.app_root))
        except Exception:
            pass
        logging.exception("KaraoPi update failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())