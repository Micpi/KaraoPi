"""Home page route."""

import flask_babel
from flask import jsonify, render_template, request, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance, get_site_name, is_admin

_ = flask_babel.gettext


home_bp = Blueprint("home", __name__)


@home_bp.route("/manifest.webmanifest")
def webmanifest():
    """Describe KaraoPi as an installable iOS and Android web app."""
    site_name = get_site_name()
    scope = request.script_root.rstrip("/") + "/"
    response = jsonify(
        {
            "name": site_name,
            "short_name": "KaraoPi",
            "description": "Karaoke queue and remote control",
            "start_url": url_for("home.home"),
            "scope": scope,
            "display": "standalone",
            "background_color": "#111111",
            "theme_color": "#111111",
            "icons": [
                {
                    "src": url_for(
                        "static", filename="images/karaopi-logo-boot.png"
                    ),
                    "sizes": "any",
                    "type": "image/png",
                    "purpose": "any",
                }
            ],
        }
    )
    response.mimetype = "application/manifest+json"
    return response


@home_bp.route("/")
def home():
    """Home page with now playing info and controls."""
    k = get_karaoke_instance()
    site_name = get_site_name()
    return render_template(
        "home.html",
        site_title=site_name,
        title="Home",
        transpose_value=k.playback_controller.now_playing_transpose,
        admin=is_admin(),
        is_transpose_enabled=k.is_transpose_enabled,
        volume=k.volume,
        mic_available=k.sound_manager.available,
    )
