#!/usr/bin/env python3
"""Centered console progress display that survives KaraoPi/browser restarts."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
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


def format_console(status):
    progress = max(0, min(100, int(status.get("progress", 0))))
    message = str(status.get("message") or "Updating KaraoPi").replace("\n", " ")
    state = str(status.get("state") or "updating")
    filled = progress // 2
    progress_bar = "█" * filled + "░" * (50 - filled)
    state_label = {
        "updating": "UPDATE IN PROGRESS",
        "awaiting_browser": "STARTING KARAOPI",
        "complete": "UPDATE COMPLETE",
        "error": "UPDATE FAILED",
    }.get(state, state.upper())
    return (
        "\033[2J\033[H"
        "\033[38;5;141m"
        "  ██╗  ██╗ █████╗ ██████╗  █████╗  ██████╗ ██████╗ ██╗\n"
        "  ██║ ██╔╝██╔══██╗██╔══██╗██╔══██╗██╔═══██╗██╔══██╗██║\n"
        "  █████╔╝ ███████║██████╔╝███████║██║   ██║██████╔╝██║\n"
        "  ██╔═██╗ ██╔══██║██╔══██╗██╔══██║██║   ██║██╔═══╝ ██║\n"
        "  ██║  ██╗██║  ██║██║  ██║██║  ██║╚██████╔╝██║     ██║\n"
        "  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝\n"
        "\033[0m\n"
        f"  \033[1m{state_label}\033[0m\n\n"
        f"  [{progress_bar}]  {progress:3d}%\n\n"
        f"  {message}\n\n"
        "  Please keep the Raspberry Pi powered on.\n"
        "  This window will close when the splash screen is ready.\n"
    )


def centered_xterm_geometry():
    """Return an xterm geometry centered on the active display."""
    columns, rows = 92, 22
    estimated_width, estimated_height = 950, 540
    screen_width, screen_height = 1920, 1080
    screen_x, screen_y = 0, 0
    xrandr = shutil.which("xrandr")
    if xrandr:
        try:
            output = subprocess.run(
                [xrandr, "--current"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            ).stdout
            connected = [line for line in output.splitlines() if " connected" in line]
            primary = next((line for line in connected if " primary " in line), None)
            display_line = primary or (connected[0] if connected else "")
            match = re.search(r"(\d+)x(\d+)\+(\d+)\+(\d+)", display_line)
            if match:
                screen_width, screen_height, screen_x, screen_y = map(int, match.groups())
        except (OSError, subprocess.TimeoutExpired):
            pass
    x = screen_x + max(0, (screen_width - estimated_width) // 2)
    y = screen_y + max(0, (screen_height - estimated_height) // 2)
    return f"{columns}x{rows}+{x}+{y}"


def run_console(status_file):
    error_since = None
    last_payload = None
    while True:
        status = read_status(status_file) or {
            "progress": 0,
            "message": "Preparing the update…",
            "state": "updating",
        }
        payload = (status.get("progress"), status.get("message"), status.get("state"))
        if payload != last_payload:
            sys.stdout.write(format_console(status))
            sys.stdout.flush()
            last_payload = payload
        if status.get("state") == "complete":
            time.sleep(1.2)
            break
        if status.get("state") == "error":
            error_since = error_since or time.monotonic()
            if time.monotonic() - error_since >= 20:
                break
        time.sleep(0.3)
    if status.get("state") == "complete":
        try:
            os.remove(status_file)
        except OSError:
            pass
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--logo")
    parser.add_argument("--console", action="store_true")
    args = parser.parse_args()

    if args.console:
        return run_console(args.status_file)

    # Prefer a real terminal: it is more reliable across Raspberry Pi desktop
    # sessions and provides the console-style update screen requested by KaraoPi.
    xterm = shutil.which("xterm")
    yad = shutil.which("yad")
    if xterm and not yad:
        command = [
            xterm,
            "-geometry",
            centered_xterm_geometry(),
            "-fa",
            "Monospace",
            "-fs",
            "16",
            "-bg",
            "#080a0f",
            "-fg",
            "#f4f5f8",
            "-title",
            "KaraoPi",
            "-e",
            sys.executable,
            os.path.abspath(__file__),
            "--console",
            "--status-file",
            args.status_file,
        ]
        return subprocess.call(command, env=os.environ.copy())

    # GTK fallback for systems where xterm is unavailable.
    if not yad:
        return 0

    command = [
        yad,
        "--progress",
        "--center",
        "--width=760",
        "--height=460",
        "--undecorated",
        "--on-top",
        "--skip-taskbar",
        "--no-buttons",
        "--auto-close",
        "--percentage=0",
        "--title=KaraoPi",
        "--text=<span size='x-large' weight='bold'>KaraoPi</span>\n\nPreparing the system…",
        "--text-align=center",
        "--text-use-markup",
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
                    display_message = (
                        "<span size='x-large' weight='bold'>KaraoPi</span>\n\n"
                        + html.escape(message)
                    )
                    process.stdin.write(
                        f"#{display_message}\n{int(status.get('progress', 0))}\n"
                    )
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
