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


def get_remote_tag_commit(remote_name, tag_name):
    output = run_command(["git", "ls-remote", "--tags", remote_name, tag_name]).stdout.strip()
    if not output:
        return None
    # Prefer the dereferenced (^{}) entry which points at the commit for annotated tags.
    lines = output.splitlines()
    for line in lines:
        if line.endswith(f"refs/tags/{tag_name}^{{}}"):
            return line.split()[0]
    return lines[0].split()[0]


def ensure_tag_ready(tag_name, remote_name):
    """Create and push the tag if missing. Returns True if the tag already existed on the remote."""
    local_head = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
    remote_commit = get_remote_tag_commit(remote_name, tag_name)

    if remote_commit is None:
        local_tag = run_command(["git", "tag", "--list", tag_name]).stdout.strip()
        if local_tag:
            raise ReleaseError(f"Tag '{tag_name}' already exists locally but not on remote '{remote_name}'.")
        run_command(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"])
        try:
            run_command(["git", "push", remote_name, tag_name])
        except ReleaseError:
            run_command(["git", "tag", "-d", tag_name], check=False)
            raise
        return False

    commit_matches = remote_commit == local_head or run_command(
        ["git", "rev-parse", f"{remote_commit}^{{commit}}"], check=False
    ).stdout.strip() == local_head
    if not commit_matches:
        raise ReleaseError(
            f"Tag '{tag_name}' already exists on remote '{remote_name}' but points at a different commit "
            f"({remote_commit}) than HEAD ({local_head}). Bump VERSION in constants.py before releasing again."
        )
    return True


def get_github_token():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise ReleaseError(
            "No GitHub token found. Set the GITHUB_TOKEN (or GH_TOKEN) environment variable with a token "
            "that has 'repo' scope before publishing a release."
        )
    return token


def api_request(method, url, token, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {token}",
            "User-Agent": "KaraoPi-Release-Script",
            "Content-Type": "application/json",
        },
    )
    return urlopen(request, timeout=20)


def get_existing_release(repository, tag_name, token):
    try:
        with api_request("GET", f"https://api.github.com/repos/{repository}/releases/tags/{tag_name}", token) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise ReleaseError(f"Unable to check existing GitHub release: {exc}")
    except URLError as exc:
        raise ReleaseError(f"Unable to check existing GitHub release: {exc}")


def create_github_release(repository, tag_name, token):
    payload = {
        "tag_name": tag_name,
        "name": tag_name,
        "generate_release_notes": True,
        "make_latest": "true",
    }
    try:
        with api_request("POST", f"https://api.github.com/repos/{repository}/releases", token, payload) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", "ignore")
        raise ReleaseError(f"Unable to create GitHub release: {exc}\n{error_body}")
    except URLError as exc:
        raise ReleaseError(f"Unable to create GitHub release: {exc}")


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

    token = get_github_token()
    existing_release = get_existing_release(repository, tag_name, token)
    if existing_release:
        print(f"Release checks passed for {repository} {tag_name} on branch {branch}.")
        print(f"GitHub release already published: {existing_release.get('html_url')}")
        return 0

    print(f"Release checks passed for {repository} {tag_name} on branch {branch}.")
    if args.dry_run:
        print("Dry run enabled, no tag or release was created.")
        return 0

    tag_already_existed = ensure_tag_ready(tag_name, args.remote)
    if tag_already_existed:
        print(f"Tag '{tag_name}' already published on remote '{args.remote}', reusing it.")
    else:
        print(f"Tag '{tag_name}' created and pushed to remote '{args.remote}'.")

    release = create_github_release(repository, tag_name, token)
    print(f"GitHub release published automatically: {release.get('html_url')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReleaseError as exc:
        print(f"Release failed: {exc}", file=sys.stderr)
        sys.exit(1)