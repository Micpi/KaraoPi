import argparse
import ast
import json
import os
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONSTANTS_FILE = os.path.join(REPO_ROOT, "constants.py")
DEFAULT_BRANCH = "main"
DEFAULT_REMOTE = "origin"


class ReleaseError(RuntimeError):
    pass


def run_command(command, cwd=REPO_ROOT, check=True):
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise ReleaseError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed


def load_release_metadata():
    with open(CONSTANTS_FILE, "r", encoding="utf-8") as constants_file:
        module = ast.parse(constants_file.read(), filename=CONSTANTS_FILE)

    metadata = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"VERSION", "GITHUB_REPOSITORY"}:
                metadata[name] = ast.literal_eval(node.value)

    missing = {"VERSION", "GITHUB_REPOSITORY"} - metadata.keys()
    if missing:
        raise ReleaseError(f"Missing required release metadata in constants.py: {', '.join(sorted(missing))}")
    return metadata


def get_current_branch():
    return run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def ensure_clean_worktree():
    status = run_command(["git", "status", "--short"]).stdout.strip()
    if status:
        raise ReleaseError(
            "Working tree is not clean. Commit or stash your changes before publishing a release.\n" + status
        )


def ensure_branch(branch, expected_branch):
    if branch != expected_branch:
        raise ReleaseError(f"Current branch is '{branch}', expected '{expected_branch}' before publishing a release.")


def ensure_remote_exists(remote_name):
    remotes = run_command(["git", "remote"]).stdout.splitlines()
    if remote_name not in remotes:
        raise ReleaseError(f"Remote '{remote_name}' is not configured.")


def ensure_origin_matches_repository(remote_name, repository):
    remote_url = run_command(["git", "remote", "get-url", remote_name]).stdout.strip()
    expected_suffixes = [
        f"github.com/{repository}.git",
        f"github.com:{repository}.git",
        f"github.com/{repository}",
        f"github.com:{repository}",
    ]
    if not any(remote_url.endswith(suffix) for suffix in expected_suffixes):
        raise ReleaseError(
            f"Remote '{remote_name}' points to '{remote_url}', but release target expects repository '{repository}'."
        )


def ensure_remote_branch_up_to_date(remote_name, branch):
    run_command(["git", "fetch", remote_name, branch])
    local_head = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote_head = run_command(["git", "rev-parse", f"{remote_name}/{branch}"]).stdout.strip()
    if local_head != remote_head:
        raise ReleaseError(
            f"Local HEAD ({local_head}) does not match {remote_name}/{branch} ({remote_head}). Push or pull changes first."
        )


def ensure_tag_absent(tag_name, remote_name):
    local_tag = run_command(["git", "tag", "--list", tag_name]).stdout.strip()
    if local_tag:
        raise ReleaseError(f"Tag '{tag_name}' already exists locally.")

    remote_tags = run_command(["git", "ls-remote", "--tags", remote_name, tag_name]).stdout.strip()
    if remote_tags:
        raise ReleaseError(f"Tag '{tag_name}' already exists on remote '{remote_name}'.")


def ensure_release_absent(repository, tag_name):
    request = Request(
        f"https://api.github.com/repos/{repository}/releases/tags/{tag_name}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "KaraoPi-Release-Script",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return
        raise ReleaseError(f"Unable to check existing GitHub release: {exc}")
    except URLError as exc:
        raise ReleaseError(f"Unable to check existing GitHub release: {exc}")

    release_url = payload.get("html_url", "GitHub")
    raise ReleaseError(f"A GitHub release already exists for tag '{tag_name}': {release_url}")


def create_and_push_tag(tag_name, remote_name):
    run_command(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"])
    try:
        run_command(["git", "push", remote_name, tag_name])
    except ReleaseError:
        run_command(["git", "tag", "-d", tag_name], check=False)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify and publish a KaraoPi GitHub release tag")
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    metadata = load_release_metadata()
    version = str(metadata["VERSION"]).strip()
    repository = str(metadata["GITHUB_REPOSITORY"]).strip()
    tag_name = f"v{version}"
    branch = get_current_branch()

    ensure_clean_worktree()
    ensure_branch(branch, args.branch)
    ensure_remote_exists(args.remote)
    ensure_origin_matches_repository(args.remote, repository)
    ensure_remote_branch_up_to_date(args.remote, args.branch)
    ensure_tag_absent(tag_name, args.remote)
    ensure_release_absent(repository, tag_name)

    print(f"Release checks passed for {repository} {tag_name} on branch {branch}.")
    if args.dry_run:
        print("Dry run enabled, tag was not created.")
        return 0

    create_and_push_tag(tag_name, args.remote)
    print(
        "Tag pushed successfully. GitHub Actions will now publish the GitHub release automatically from this tag."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReleaseError as exc:
        print(f"Release failed: {exc}", file=sys.stderr)
        sys.exit(1)