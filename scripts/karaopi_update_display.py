#!/usr/bin/env python3
"""Centered console progress display that survives KaraoPi/browser restarts."""

from __future__ import annotations

import argparse
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


def run_tk_display(status_file, logo_path):
    """Render the canonical KaraoPi boot/update card without a browser."""
    try:
        import tkinter as tk
    except ImportError:
        return None

    try:
        root = tk.Tk(className="KaraoPi")
    except tk.TclError:
        return None

    root.configure(bg="#07090f")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.lift()

    card = tk.Frame(
        root,
        width=520,
        height=410,
        bg="#121520",
        highlightbackground="#343744",
        highlightthickness=1,
    )
    card.place(relx=0.5, rely=0.5, anchor="center")
    card.pack_propagate(False)

    logo_image = None
    if logo_path and os.path.isfile(logo_path):
        try:
            logo_image = tk.PhotoImage(file=logo_path)
            scale = max(1, max(logo_image.width(), logo_image.height()) // 104)
            if scale > 1:
                logo_image = logo_image.subsample(scale, scale)
            tk.Label(card, image=logo_image, bg="#121520").pack(pady=(34, 10))
        except tk.TclError:
            logo_image = None

    tk.Label(
        card,
        text="KaraoPi",
        font=("DejaVu Sans", 30, "bold"),
        fg="#ffffff",
        bg="#121520",
    ).pack(pady=(4 if logo_image else 72, 4))

    state_label = tk.Label(
        card,
        text="PREPARING THE KARAOKE EXPERIENCE",
        font=("DejaVu Sans", 10, "bold"),
        fg="#8b5cf6",
        bg="#121520",
    )
    state_label.pack(pady=(2, 12))

    message_label = tk.Label(
        card,
        text="Starting KaraoPi system services",
        font=("DejaVu Sans", 12),
        fg="#aeb4c5",
        bg="#121520",
        wraplength=430,
        justify="center",
    )
    message_label.pack(pady=(0, 20))

    track = tk.Canvas(card, width=360, height=8, bg="#121520", highlightthickness=0)
    track.pack()
    track.create_rectangle(0, 1, 360, 7, fill="#2d3244", outline="")
    progress_bar = track.create_rectangle(0, 1, 1, 7, fill="#8b5cf6", outline="")

    percent_label = tk.Label(
        card,
        text="0%",
        font=("DejaVu Sans", 10, "bold"),
        fg="#e8e9ef",
        bg="#121520",
    )
    percent_label.pack(pady=(10, 0))

    last_payload = None
    error_since = None

    def refresh():
        nonlocal last_payload, error_since
        status = read_status(status_file) or {
            "progress": 0,
            "message": "Preparing the karaoke experience…",
            "state": "awaiting_browser",
        }
        progress = max(0, min(100, int(status.get("progress", 0))))
        state = str(status.get("state") or "updating")
        payload = (progress, status.get("message"), state)
        if payload != last_payload:
            labels = {
                "updating": "KARAOPI UPDATE IN PROGRESS",
                "awaiting_browser": "PREPARING THE KARAOKE EXPERIENCE",
                "complete": "KARAOPI IS READY",
                "error": "UPDATE NEEDS ATTENTION",
            }
            state_label.configure(text=labels.get(state, state.replace("_", " ").upper()))
            message_label.configure(text=str(status.get("message") or "Preparing KaraoPi"))
            track.coords(progress_bar, 0, 1, max(3, int(3.6 * progress)), 7)
            progress_bar_color = "#22d3ee" if progress >= 100 else "#8b5cf6"
            track.itemconfigure(progress_bar, fill=progress_bar_color)
            percent_label.configure(text=f"{progress}%")
            last_payload = payload
        if state == "complete":
            root.after(650, root.destroy)
            return
        if state == "error":
            error_since = error_since or time.monotonic()
            if time.monotonic() - error_since >= 20:
                root.destroy()
                return
        root.lift()
        root.after(250, refresh)

    root.after(0, refresh)
    root.mainloop()
    status = read_status(status_file)
    if status and status.get("state") == "complete":
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

    # Prefer the native, browser-independent implementation of the canonical
    # KaraoPi loading card. It covers the desktop until the splash reports a
    # decoded media frame and survives KaraoPi/browser restarts during updates.
    tk_result = run_tk_display(args.status_file, args.logo)
    if tk_result is not None:
        return tk_result

    # Compatibility fallbacks for minimal desktop installations.
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
        "--text=KARΛOPI\n\nPreparing the system…",
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
                    display_message = "KARΛOPI\n\n" + message
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
