"""Image serving routes for QR code and logo."""
import mimetypes
import os
import uuid

import flask_babel
from flask import flash, jsonify, redirect, request, send_file, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import broadcast_event, get_karaoke_instance, is_admin
from pikaraoke.lib.get_platform import get_data_directory

_ = flask_babel.gettext

images_bp = Blueprint("images", __name__)

ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@images_bp.route("/qrcode")
def qrcode():
    """Get QR code image for the web interface URL."""
    k = get_karaoke_instance()
    return send_file(k.qr_code_path, mimetype="image/png")


@images_bp.route("/logo")
def logo():
    """Get the KaraoPi logo image (custom logo if one was uploaded, otherwise the default)."""
    k = get_karaoke_instance()
    custom_logo_path = k.preferences.get_or_default("custom_logo_path")
    logo_path = custom_logo_path if custom_logo_path and os.path.isfile(custom_logo_path) else k.logo_path
    logo_path = os.path.abspath(logo_path)
    mimetype = mimetypes.guess_type(logo_path)[0] or "image/png"
    return send_file(logo_path, mimetype=mimetype)


@images_bp.route("/logo/upload", methods=["POST"])
def upload_logo():
    """Upload a custom logo, replacing the default KaraoPi logo. Admin only."""
    k = get_karaoke_instance()
    if not is_admin():
        # MSG: Message shown after trying to change the logo without admin permissions.
        flash(_("You don't have permission to change the logo"), "is-danger")
        return redirect(url_for("info.info"))

    uploaded_file = request.files.get("logo_file")
    if not uploaded_file or not uploaded_file.filename:
        # MSG: Message shown when no logo file was selected for upload.
        flash(_("No logo file was selected"), "is-danger")
        return redirect(url_for("info.info"))

    extension = os.path.splitext(uploaded_file.filename)[1].lower()
    if extension not in ALLOWED_LOGO_EXTENSIONS:
        # MSG: Message shown when the uploaded logo file type is not supported.
        flash(_("Unsupported logo file type. Use PNG, JPG, GIF, WEBP, or SVG."), "is-danger")
        return redirect(url_for("info.info"))

    destination = os.path.join(get_data_directory(), f"custom_logo_{uuid.uuid4().hex[:8]}{extension}")
    uploaded_file.save(destination)

    # Remove any previously uploaded custom logo file to avoid accumulating old ones.
    previous_logo_path = k.preferences.get_or_default("custom_logo_path")
    if previous_logo_path and os.path.isfile(previous_logo_path):
        try:
            os.remove(previous_logo_path)
        except OSError:
            pass

    k.preferences.set("custom_logo_path", destination)
    k.generate_qr_code()  # in case the QR code logo is set to reuse the custom logo
    broadcast_event("preferences_update", {"key": "custom_logo_path", "value": destination})
    # MSG: Message shown after successfully uploading a custom logo.
    flash(_("Logo updated successfully"), "is-success")
    return redirect(url_for("info.info"))


@images_bp.route("/logo/reset", methods=["GET"])
def reset_logo():
    """Reset to the default KaraoPi logo. Admin only."""
    k = get_karaoke_instance()
    if not is_admin():
        flash(_("You don't have permission to change the logo"), "is-danger")
        return redirect(url_for("info.info"))

    previous_logo_path = k.preferences.get_or_default("custom_logo_path")
    if previous_logo_path and os.path.isfile(previous_logo_path):
        try:
            os.remove(previous_logo_path)
        except OSError:
            pass

    k.preferences.set("custom_logo_path", "")
    k.generate_qr_code()
    broadcast_event("preferences_update", {"key": "custom_logo_path", "value": ""})
    # MSG: Message shown after resetting to the default logo.
    flash(_("Logo reset to default"), "is-success")
    return redirect(url_for("info.info"))
