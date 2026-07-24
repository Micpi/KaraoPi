#!/usr/bin/env python3
"""Fullscreen GTK progress display that survives KaraoPi/Chromium restarts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def read_status(path):
    try:
        with open(path, "r", encoding="utf-8") as status_file:
            return json.load(status_file)
    except (OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--logo")
    args = parser.parse_args()

    yad = shutil.which("yad")
    if not yad:
        return 0

    command = [
        yad,
        "--progress",
        "--fullscreen",
        "--undecorated",
        "--on-top",
        "--skip-taskbar",
        "--no-buttons",
        "--auto-close",
        "--percentage=0",
        "--title=KaraoPi Update",
        "--text=Preparing the update…",
        "--text-align=center",
    ]
    if args.logo and os.path.isfile(args.logo):
        command.extend([f"--image={args.logo}", "--image-on-top"])

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    error_since = None
    last_payload = None
    try:
        while process.poll() is None:
            status = read_status(args.status_file)
            if status:
                payload = (status.get("progress"), status.get("message"), status.get("state"))
                if payload != last_payload and process.stdin:
                    message = str(status.get("message") or "Updating KaraoPi").replace("\n", " ")
                    process.stdin.write(f"#{message}\n{int(status.get('progress', 0))}\n")
                    process.stdin.flush()
                    last_payload = payload
                if status.get("state") == "complete":
                    break
                if status.get("state") == "error":
                    error_since = error_since or time.monotonic()
                    if time.monotonic() - error_since >= 20:
                        break
            time.sleep(0.35)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        status = read_status(args.status_file)
        if status and status.get("state") == "complete":
            try:
                os.remove(args.status_file)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
