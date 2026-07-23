"""Admin routes for system control and authentication."""

import datetime
import os
import subprocess
import sys
import threading
import psutil
import time

import flask_babel
from flask import flash, jsonify, make_response, redirect, request, url_for
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from pikaraoke import VERSION
from pikaraoke.karaoke import Karaoke
from pikaraoke.lib.current_app import (
    broadcast_event,
    get_admin_password,
    get_karaoke_instance,
    is_admin,
)
from pikaraoke.lib.get_platform import get_platform
from pikaraoke.lib.karaopi_release import AppUpdateError, start_background_update
from pikaraoke.lib.youtube_dl import get_youtubedl_version, upgrade_youtubedl

_ = flask_babel.gettext

admin_bp = Blueprint("admin", __name__)


class AuthForm(Schema):
    admin_password = fields.String(load_default="", metadata={"description": "Admin password"})
    next = fields.String(
        load_default="/", metadata={"description": "URL to redirect to after login"}
    )


def delayed_halt(cmd: int, k: Karaoke):
    time.sleep(1.5)
    k.queue_manager.queue_clear()
    k.stop()
    if cmd == 0:
        sys.exit()
    if cmd == 1:
        os.system("shutdown now")
    if cmd == 2:
        os.system("reboot")
    if cmd == 3:
        process = subprocess.Popen(["raspi-config", "--expand-rootfs"])
        process.wait()
        os.system("reboot")


@admin_bp.route("/update_ytdl")
def update_ytdl():
    """Update yt-dlp to the latest version."""
    k = get_karaoke_instance()

    def update_youtube_dl():
        time.sleep(3)
        k.youtubedl_version = upgrade_youtubedl()

    if is_admin():
        flash(
            # MSG: Message shown after starting the yt-dlp update.
            _("Updating yt-dlp! Should take a minute or two... "),
            "is-warning",
        )
        th = threading.Thread(target=update_youtube_dl)
        th.start()
    else:
        # MSG: Message shown after trying to update yt-dlp without admin permissions.
        flash(_("You don't have permission to update yt-dlp"), "is-danger")
    return redirect(url_for("info.info"))


@admin_bp.route("/update_app")
def update_app():
    """Update KaraoPi from the latest published GitHub release."""
    k = get_karaoke_instance()
    if not is_admin():
        # MSG: Message shown after trying to update KaraoPi without admin permissions.
        flash(_("You don't have permission to update KaraoPi"), "is-danger")
        return redirect(url_for("info.info"))

    app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    relaunch_command = [sys.executable, "-m", "pikaraoke.app"] + sys.argv[1:]
    try:
        update_status = start_background_update(
            app_root=app_root,
            current_version=VERSION,
            relaunch_command=relaunch_command,
        )
    except AppUpdateError as exc:
        flash(str(exc), "is-warning")
        return redirect(url_for("info.info"))
    except Exception as exc:
        flash(f"Unable to start KaraoPi update: {exc}", "is-danger")
        return redirect(url_for("info.info"))

    msg = _("Updating KaraoPi to %(tag)s. The application will stop now and restart automatically.") % {
        "tag": update_status["latest_tag"]
    }
    flash(msg, "is-warning")
    k.send_notification(msg, "warning")
    th = threading.Thread(target=delayed_halt, args=[0, k])
    th.start()
    return redirect(url_for("home.home"))


@admin_bp.route("/reload_splash")
def reload_splash():
    """Force any connected splash screen(s) to reload, so appearance changes
    (theme colors, logo, QR code) that don't apply live take effect immediately."""
    if not is_admin():
        # MSG: Message shown after trying to reload the splash screen without admin permissions.
        flash(_("You don't have permission to reload the splash screen"), "is-danger")
        return redirect(url_for("info.info"))

    broadcast_event("force_reload_splash")
    # MSG: Message shown after requesting a splash screen reload.
    flash(_("Reloading the splash screen..."), "is-success")
    return redirect(url_for("info.info"))


@admin_bp.route("/library_stats")
def library_stats():
    """Return song count for the admin dashboard."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    k = get_karaoke_instance()
    return jsonify({"song_count": len(k.song_manager.songs)})


@admin_bp.route("/sync_library")
def sync_library():
    """Trigger a background library scan."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    k = get_karaoke_instance()
    started = k.sync_library()
    if started:
        return jsonify({"status": "started"})
    return jsonify({"status": "already_syncing"})


@admin_bp.route("/cover_art/status")
def cover_art_status():
    """Return cover synchronization progress and index totals."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(get_karaoke_instance().cover_art_manager.status())


@admin_bp.route("/cover_art/sync", methods=["POST"])
def sync_cover_art():
    """Start background artwork matching for the complete song library."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    k = get_karaoke_instance()

    def finished(status):
        if k.socketio:
            k.socketio.emit("cover_art_sync_finished", status, namespace="/")

    started = k.cover_art_manager.start_sync(
        force=request.form.get("force") == "true", on_finished=finished
    )
    if started:
        if k.socketio:
            k.socketio.emit("cover_art_sync_started", namespace="/")
        return jsonify({"status": "started"})
    return jsonify({"status": "already_syncing"})


@admin_bp.route("/quit")
def quit():
    """Exit the PiKaraoke application."""
    k = get_karaoke_instance()
    if is_admin():
        # MSG: Message shown after quitting pikaraoke.
        msg = _("Exiting pikaraoke now!")
        flash(msg, "is-danger")
        k.send_notification(msg, "danger")
        th = threading.Thread(target=delayed_halt, args=[0, k])
        th.start()
    else:
        # MSG: Message shown after trying to quit pikaraoke without admin permissions.
        flash(_("You don't have permission to quit"), "is-danger")
    return redirect(url_for("home.home"))


@admin_bp.route("/shutdown")
def shutdown():
    """Shut down the host system."""
    k = get_karaoke_instance()
    if is_admin():
        # MSG: Message shown after shutting down the system.
        msg = _("Shutting down system now!")
        flash(msg, "is-danger")
        k.send_notification(msg, "danger")
        th = threading.Thread(target=delayed_halt, args=[1, k])
        th.start()
    else:
        # MSG: Message shown after trying to shut down the system without admin permissions.
        flash(_("You don't have permission to shut down"), "is-danger")
    return redirect(url_for("home.home"))


@admin_bp.route("/reboot")
def reboot():
    """Reboot the host system."""
    k = get_karaoke_instance()
    if is_admin():
        # MSG: Message shown after rebooting the system.
        msg = _("Rebooting system now!")
        flash(msg, "is-danger")
        k.send_notification(msg, "danger")
        th = threading.Thread(target=delayed_halt, args=[2, k])
        th.start()
    else:
        # MSG: Message shown after trying to reboot the system without admin permissions.
        flash(_("You don't have permission to Reboot"), "is-danger")
    return redirect(url_for("home.home"))


@admin_bp.route("/expand_fs")
def expand_fs():
    """Expand filesystem on Raspberry Pi."""
    k = get_karaoke_instance()
    if is_admin() and k.is_raspberry_pi:
        # MSG: Message shown after expanding the filesystem.
        flash(_("Expanding filesystem and rebooting system now!"), "is-danger")
        th = threading.Thread(target=delayed_halt, args=[3, k])
        th.start()
    elif not k.is_raspberry_pi:
        # MSG: Message shown after trying to expand the filesystem on a non-raspberry pi device.
        flash(_("Cannot expand fs on non-raspberry pi devices!"), "is-danger")
    else:
        # MSG: Message shown after trying to expand the filesystem without admin permissions
        flash(_("You don't have permission to resize the filesystem"), "is-danger")
    return redirect(url_for("home.home"))


@admin_bp.route("/auth", methods=["POST"])
@admin_bp.arguments(AuthForm, location="form")
def auth(form):
    """Authenticate as admin."""
    admin_password = get_admin_password()
    p = form["admin_password"]
    next_url = form["next"]

    # Validate next_url to prevent open redirect vulnerabilities
    if not next_url.startswith("/"):
        next_url = "/"

    if p == admin_password:
        resp = make_response(redirect(next_url))
        expire_date = datetime.datetime.now()
        expire_date = expire_date + datetime.timedelta(days=90)
        resp.set_cookie("admin", admin_password, expires=expire_date)
        # MSG: Message shown after logging in as admin successfully
        flash(_("Admin mode granted!"), "is-success")
    else:
        resp = make_response(redirect(next_url))
        # MSG: Message shown after failing to login as admin
        flash(_("Incorrect admin password!"), "is-danger")
    return resp


@admin_bp.route("/logout")
def logout():
    """Log out of admin mode."""
    resp = make_response(redirect(url_for("info.info")))
    resp.set_cookie("admin", "")
    # MSG: Message shown after logging out as admin successfully
    flash(_("Logged out of admin mode!"), "is-success")
    return resp


@admin_bp.route("/usb_paths")
def get_usb_paths():
    """
    Detects and returns a list of potential USB drive paths.
    """
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    usb_paths = []
    platform = get_platform()

    if platform == "windows":
        # On Windows, iterate through drive letters and check if they are removable.
        # This is a heuristic; a more robust solution might involve pywin32 or shelling out to powershell.
        import string
        for drive_letter in string.ascii_uppercase:
            drive_path = f"{drive_letter}:\\"
            if os.path.exists(drive_path):
                # psutil.disk_partitions() can give more info, but identifying "removable" is tricky
                # without platform-specific APIs. For simplicity, we list existing drives.
                usb_paths.append({"path": drive_path, "label": drive_path})
    else: # Linux, macOS, etc.
        partitions = psutil.disk_partitions()
        for p in partitions:
            # Heuristic: check for common USB mount points or 'removable' option
            if "removable" in p.opts or p.mountpoint.startswith("/media/") or p.mountpoint.startswith("/mnt/"):
                label = p.mountpoint # Use mountpoint as label for now
                usb_paths.append({"path": p.mountpoint, "label": label})

    return jsonify(usb_paths)
