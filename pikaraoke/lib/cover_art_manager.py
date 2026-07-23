"""Local cover-art indexing and multi-provider synchronization."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Callable

import requests

from pikaraoke.lib.get_platform import get_data_directory
from pikaraoke.lib.karaoke_database import KaraokeDatabase

DEEZER_SEARCH_URL = "https://api.deezer.com/search"
MUSICBRAINZ_RECORDING_URL = "https://musicbrainz.org/ws/2/recording"
CAA_RELEASE_GROUP_URL = "https://coverartarchive.org/release-group/{mbid}/front-500"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_MATCH_SCORE = 0.78
USER_AGENT = "KaraoPi/1.0 (https://github.com/Micpi/KaraoPi)"


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _match_score(artist: str, title: str, candidate_artist: str, candidate_title: str) -> float:
    artist_score = SequenceMatcher(None, _normalize(artist), _normalize(candidate_artist)).ratio()
    title_score = SequenceMatcher(None, _normalize(title), _normalize(candidate_title)).ratio()
    return artist_score * 0.45 + title_score * 0.55


def parse_song_identity(display_name: str) -> tuple[str, str] | None:
    """Parse the conventional 'artist - title' karaoke filename."""
    parts = re.split(r"\s+[-–—]\s+", display_name, maxsplit=1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return None
    return parts[0].strip(), parts[1].strip()


class CoverArtManager:
    """Downloads artwork into a dedicated directory and indexes it in SQLite."""

    def __init__(
        self,
        db: KaraokeDatabase,
        songs_provider: Callable[[], list[str]],
        display_name_provider: Callable[[str], str],
        data_directory: str | None = None,
    ) -> None:
        self._db = db
        self._songs_provider = songs_provider
        self._display_name_provider = display_name_provider
        self.directory = os.path.join(data_directory or get_data_directory(), "cover_art")
        os.makedirs(self.directory, exist_ok=True)
        self._lock = threading.Lock()
        self._syncing = False
        self._progress = {"current": 0, "total": 0, "found": 0, "missing": 0, "errors": 0}
        self._last_musicbrainz_request = 0.0

    def get_cover_key(self, song_path: str) -> str | None:
        record = self._db.get_cover_art(song_path)
        if not record or record["status"] != "found" or not record["cover_key"]:
            return None
        path = os.path.join(self.directory, record["cover_key"])
        return record["cover_key"] if os.path.isfile(path) else None

    def get_cover_path(self, cover_key: str) -> str | None:
        if not re.fullmatch(r"[a-f0-9]{24}\.(?:jpg|png|webp)", cover_key):
            return None
        path = os.path.abspath(os.path.join(self.directory, cover_key))
        if os.path.commonpath([path, os.path.abspath(self.directory)]) != os.path.abspath(
            self.directory
        ):
            return None
        return path if os.path.isfile(path) else None

    def status(self) -> dict:
        indexed = self._db.get_cover_art_stats()
        return {
            **self._progress,
            "indexed_total": indexed.get("total", 0),
            "indexed_found": indexed.get("found", 0),
            "indexed_missing": indexed.get("missing", 0),
            "indexed_unresolved": indexed.get("unresolved", 0),
            "syncing": self._syncing,
        }

    def start_sync(self, force: bool = False, on_finished: Callable[[dict], None] | None = None) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self._syncing = True
        thread = threading.Thread(
            target=self._sync_worker, args=(force, on_finished), daemon=True, name="cover-art-sync"
        )
        thread.start()
        return True

    def _sync_worker(self, force: bool, on_finished: Callable[[dict], None] | None) -> None:
        try:
            songs = list(self._songs_provider())
            self._progress = {
                "current": 0,
                "total": len(songs),
                "found": 0,
                "missing": 0,
                "errors": 0,
            }
            for index, song_path in enumerate(songs, start=1):
                self._progress["current"] = index
                existing = self._db.get_cover_art(song_path)
                if not force and existing and existing["status"] == "found":
                    self._progress["found"] += 1
                    continue
                try:
                    self._sync_song(song_path)
                except Exception:
                    logging.exception("Cover art sync failed for %s", song_path)
                    self._progress["errors"] += 1
            if on_finished:
                on_finished(self.status())
        finally:
            self._syncing = False
            self._lock.release()

    def _song_identity(self, song_path: str) -> tuple[str, str] | None:
        artist, title = self._db.get_song_identity(song_path)
        if artist and title:
            return artist, title
        return parse_song_identity(self._display_name_provider(song_path))

    def _sync_song(self, song_path: str) -> None:
        identity = self._song_identity(song_path)
        if not identity:
            display_name = self._display_name_provider(song_path)
            self._db.upsert_cover_art(song_path, "", display_name, "unresolved")
            self._progress["missing"] += 1
            return

        artist, title = identity
        candidates = self._deezer_candidates(artist, title)
        candidates.extend(self._musicbrainz_candidates(artist, title))
        candidates.sort(key=lambda item: item["score"], reverse=True)
        for candidate in (item for item in candidates if item["score"] >= MIN_MATCH_SCORE):
            try:
                content, extension = self._download_image(candidate["url"])
                digest = hashlib.sha256(
                    f"{_normalize(artist)}|{_normalize(title)}".encode()
                ).hexdigest()[:24]
                cover_key = digest + extension
                destination = os.path.join(self.directory, cover_key)
                temporary = destination + ".tmp"
                with open(temporary, "wb") as output:
                    output.write(content)
                os.replace(temporary, destination)
                self._db.upsert_cover_art(
                    song_path,
                    artist,
                    title,
                    "found",
                    cover_key=cover_key,
                    source=candidate["source"],
                    source_url=candidate["url"],
                )
                self._progress["found"] += 1
                return
            except (requests.RequestException, ValueError, OSError):
                logging.info(
                    "Cover candidate unavailable from %s for %s - %s",
                    candidate["source"],
                    artist,
                    title,
                )

        self._db.upsert_cover_art(song_path, artist, title, "missing")
        self._progress["missing"] += 1

    def _deezer_candidates(self, artist: str, title: str) -> list[dict]:
        try:
            response = requests.get(
                DEEZER_SEARCH_URL,
                params={"q": f'artist:"{artist}" track:"{title}"', "limit": 5},
                headers={"User-Agent": USER_AGENT},
                timeout=12,
            )
            response.raise_for_status()
            results = []
            for item in response.json().get("data", []):
                album = item.get("album") or {}
                url = album.get("cover_xl") or album.get("cover_big")
                if url:
                    results.append(
                        {
                            "source": "deezer",
                            "url": url,
                            "score": _match_score(
                                artist,
                                title,
                                (item.get("artist") or {}).get("name", ""),
                                item.get("title_short") or item.get("title", ""),
                            ),
                        }
                    )
            return results
        except (requests.RequestException, ValueError):
            logging.warning("Deezer cover lookup failed for %s - %s", artist, title)
            return []

    def _musicbrainz_candidates(self, artist: str, title: str) -> list[dict]:
        elapsed = time.monotonic() - self._last_musicbrainz_request
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        try:
            response = requests.get(
                MUSICBRAINZ_RECORDING_URL,
                params={
                    "query": f'recording:"{title}" AND artist:"{artist}"',
                    "fmt": "json",
                    "limit": 5,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=12,
            )
            self._last_musicbrainz_request = time.monotonic()
            response.raise_for_status()
            results = []
            for recording in response.json().get("recordings", []):
                credit = recording.get("artist-credit") or []
                candidate_artist = "".join(
                    part.get("name", "") + part.get("joinphrase", "") for part in credit
                )
                score = _match_score(artist, title, candidate_artist, recording.get("title", ""))
                seen_groups = set()
                for release in recording.get("releases") or []:
                    group = release.get("release-group") or {}
                    mbid = group.get("id")
                    if mbid and mbid not in seen_groups:
                        seen_groups.add(mbid)
                        results.append(
                            {
                                "source": "coverartarchive",
                                "url": CAA_RELEASE_GROUP_URL.format(mbid=mbid),
                                "score": score,
                            }
                        )
            return results
        except (requests.RequestException, ValueError):
            logging.warning("MusicBrainz cover lookup failed for %s - %s", artist, title)
            return []

    def _download_image(self, url: str) -> tuple[bytes, str]:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=20, stream=True, allow_redirects=True
        )
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(64 * 1024):
            content.extend(chunk)
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError("Cover image exceeds size limit")
        raw = bytes(content)
        if raw.startswith(b"\xff\xd8\xff"):
            extension = ".jpg"
        elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = ".png"
        elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            extension = ".webp"
        else:
            raise ValueError("Unsupported cover image format")
        return raw, extension
