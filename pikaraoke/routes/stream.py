"""Video streaming routes for transcoded media playback."""

import os
import time

import flask_babel
from flask import Response, make_response, request, send_file
from flask_smorest import Blueprint

_ = flask_babel.gettext

from pikaraoke.lib.current_app import get_karaoke_instance
from pikaraoke.lib.file_resolver import FileResolver, get_tmp_dir

stream_bp = Blueprint("stream", __name__)


# Serves HLS playlist file - explicit .m3u8 extension
@stream_bp.route("/stream/<id>.m3u8")
def stream_playlist(id):
    """Serve HLS playlist file."""
    file_path = os.path.join(get_tmp_dir(), f"{id}.m3u8")
    k = get_karaoke_instance()

    # Mark song as started when client connects (idempotent)
    # Validate stream ID matches current song to prevent stale requests from setting is_playing
    if not k.playback_controller.is_playing:
        now_playing_url = k.playback_controller.now_playing_url
        if now_playing_url and id in now_playing_url:
            k.playback_controller.start_song()

    # Wait for playlist file to exist
    max_wait = 50  # 5 seconds max
    wait_count = 0
    while not os.path.exists(file_path) and wait_count < max_wait:
        time.sleep(0.1)
        wait_count += 1

    if os.path.exists(file_path):
        # Read file content and return with no-cache headers
        # This is critical for iOS Safari which aggressively caches playlists
        with open(file_path, "r") as f:
            content = f.read()
        response = make_response(content)
        response.headers["Content-Type"] = "application/vnd.apple.mpegurl"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    else:
        return Response("Playlist not found", status=404)


# Serves HLS segment files - .m4s (fragmented MP4) extension
@stream_bp.route("/stream/<filename>.m4s")
def stream_segment_m4s(filename):
    """Serve HLS segment file (fragmented MP4)."""
    # Security: prevent directory traversal
    if ".." in filename or "/" in filename:
        return Response("Invalid segment", status=400)

    segment_path = os.path.join(get_tmp_dir(), f"{filename}.m4s")

    if os.path.exists(segment_path):
        return send_file(segment_path, mimetype="video/mp4")
    else:
        return Response(f"Segment not found: {filename}.m4s", status=404)


# Serves init.mp4 header file for fMP4 (with unique filenames per stream)
@stream_bp.route("/stream/<filename>_init.mp4")
def stream_init(filename):
    """Serve init.mp4 header file for fragmented MP4 streams."""
    # Security: prevent directory traversal
    if ".." in filename or "/" in filename:
        return Response("Invalid init file", status=400)

    init_path = os.path.join(get_tmp_dir(), f"{filename}_init.mp4")
    if os.path.exists(init_path):
        return send_file(init_path, mimetype="video/mp4")
    else:
        return Response("Init file not found", status=404)


# Legacy .ts support for backward compatibility
@stream_bp.route("/stream/<filename>.ts")
def stream_segment(filename):
    """Serve HLS segment file (MPEG-TS)."""
    # Security: prevent directory traversal
    if ".." in filename or "/" in filename:
        return Response("Invalid segment", status=400)

    segment_path = os.path.join(get_tmp_dir(), f"{filename}.ts")

    if os.path.exists(segment_path):
        return send_file(segment_path, mimetype="video/mp2t")
    else:
        return Response(f"Segment not found: {filename}.ts", status=404)


# Main streaming route - serves HLS or progressive MP4 based on file extension
@stream_bp.route("/stream/<id>")
def stream_main(id):
    """Route streaming request to HLS or progressive MP4."""
    # Check if it's an HLS request (.m3u8) or MP4 request (.mp4)
    if request.path.endswith(".m3u8"):
        return stream_playlist(id.replace(".m3u8", ""))
    elif request.path.endswith(".mp4"):
        return stream_progressive_mp4(id.replace(".mp4", ""))
    else:
        # Fallback: try HLS first
        return stream_playlist(id)


# Progressive MP4 streaming with init.mp4 + segments concatenation
# This method works with HLS-generated fMP4 segments but serves them as continuous MP4
# Compatible with Chrome, Firefox and RPi with hardware acceleration
@stream_bp.route("/stream/<id>.mp4")
def stream_progressive_mp4(id):
    """Stream progressive MP4 from HLS-generated segments."""
    file_path = os.path.join(get_tmp_dir(), f"{id}.mp4")
    k = get_karaoke_instance()

    # Mark song as started when client connects (idempotent)
    # Validate stream ID matches current song to prevent stale requests from setting is_playing
    if not k.playback_controller.is_playing:
        now_playing_url = k.playback_controller.now_playing_url
        if now_playing_url and id in now_playing_url:
            k.playback_controller.start_song()

    # Wait for output file to exist
    max_wait = 50  # 5 seconds max
    wait_count = 0
    while not os.path.exists(file_path) and wait_count < max_wait:
        time.sleep(0.1)
        wait_count += 1

    if not os.path.exists(file_path):
        return Response("Stream file not ready", status=404)

    def generate():
        position = 0  # Initialize the position variable
        chunk_size = 10240 * 1000 * 25  # Read file in up to 25MB chunks
        with open(file_path, "rb") as file:
            # Keep yielding file chunks as long as ffmpeg process is transcoding
            while k.playback_controller.ffmpeg_process.poll() is None:
                file.seek(position)  # Move to the last read position
                chunk = file.read(chunk_size)
                if chunk is not None and len(chunk) > 0:
                    yield chunk
                    position += len(chunk)  # Update the position with the size of the chunk
                time.sleep(1)  # Wait a bit before checking the file size again
            chunk = file.read(chunk_size)  # Read the last chunk
            yield chunk
            position += len(chunk)  # Update the position with the size of the chunk

    return Response(generate(), mimetype="video/mp4")


def stream_file_path_full(file_path):
    if not file_path or not os.path.isfile(file_path):
        return Response("File not found.", status=404)
    # Werkzeug handles conditional and byte-range requests without loading the
    # entire video into Python memory.
    return send_file(os.path.abspath(file_path), conditional=True)


@stream_bp.route("/stream/direct/<id>")
def stream_direct(id):
    """Serve the current compatible media file without copying or transcoding."""
    k = get_karaoke_instance()
    controller = k.playback_controller
    now_playing_url = controller.now_playing_url
    if not now_playing_url or id not in now_playing_url:
        return Response("Stream not found.", status=404)
    if not controller.is_playing:
        controller.start_song()
    return stream_file_path_full(controller.now_playing_filename)


# Streams the file in full with proper range headers
# (Safari compatible, but requires the ffmpeg transcoding to be complete to know file size)
@stream_bp.route("/stream/full/<id>")
def stream_full(id):
    """Stream video with range headers (Safari compatible)."""
    k = get_karaoke_instance()

    # Mark song as started when client connects (idempotent)
    # Validate stream ID matches current song to prevent stale requests from setting is_playing
    if not k.playback_controller.is_playing:
        now_playing_url = k.playback_controller.now_playing_url
        if now_playing_url and id in now_playing_url:
            k.playback_controller.start_song()

    file_path = os.path.join(get_tmp_dir(), f"{id}.mp4")
    return stream_file_path_full(file_path)


@stream_bp.route("/stream/bg_video")
def stream_bg_video():
    """Stream the background video file."""
    k = get_karaoke_instance()
    file_path = k.bg_video_path
    if k.bg_video_path is not None:
        return send_file(os.path.abspath(file_path), mimetype="video/mp4")
    else:
        return Response("Background video not found.", status=404)


# subtitle .ass
@stream_bp.route("/subtitle/<id>")
def stream_subtitle(id):
    """Serve subtitle file for the current song."""
    k = get_karaoke_instance()
    try:
        original_file_path = k.playback_controller.now_playing_filename
        now_playing_url = k.playback_controller.now_playing_url
        if original_file_path and now_playing_url and id in now_playing_url:
            fr = FileResolver(original_file_path)
            ass_file_path = fr.ass_file_path
            if ass_file_path and os.path.exists(ass_file_path):
                return send_file(
                    os.path.abspath(ass_file_path),
                    mimetype="text/plain",
                    as_attachment=False,
                    download_name=os.path.basename(ass_file_path),
                )
    except Exception as e:
        k.log_and_send(_("Failed to stream subtitle: ") + str(e), "danger")
        return Response("Subtitle streaming error.", status=500)
    return Response("Subtitle file not found for this stream ID.", status=404)
