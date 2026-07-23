"""Tests for cover artwork matching and local indexing."""

from pikaraoke.lib.cover_art_manager import _match_score, parse_song_identity


def test_parse_song_identity():
    assert parse_song_identity("David Bowie - Heroes") == ("David Bowie", "Heroes")


def test_parse_song_identity_requires_separator():
    assert parse_song_identity("Unknown karaoke song") is None


def test_match_score_prefers_exact_identity():
    exact = _match_score("Daft Punk", "Get Lucky", "Daft Punk", "Get Lucky")
    wrong = _match_score("Daft Punk", "Get Lucky", "Other Artist", "Other Song")
    assert exact == 1.0
    assert exact > wrong
