"""Score history and participant rankings."""

from collections import OrderedDict

import flask_babel
from flask import render_template
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance, get_site_name

_ = flask_babel.gettext

scores_bp = Blueprint("scores", __name__)


@scores_bp.route("/scores")
def scores():
    """Show performances grouped and ranked by KaraoPi startup session."""
    k = get_karaoke_instance()
    grouped: OrderedDict[int, dict] = OrderedDict()

    for performance in k.db.get_score_history():
        session_id = performance["session_id"]
        session = grouped.setdefault(
            session_id,
            {
                "id": session_id,
                "started_at": performance["started_at"],
                "performances": [],
                "participants": {},
            },
        )
        session["performances"].append(performance)
        participant = session["participants"].setdefault(
            performance["participant"],
            {"name": performance["participant"], "scores": [], "best": 0},
        )
        participant["scores"].append(performance["score"])
        participant["best"] = max(participant["best"], performance["score"])

    sessions = []
    for session in grouped.values():
        ranking = []
        for participant in session["participants"].values():
            scores_list = participant.pop("scores")
            participant["songs"] = len(scores_list)
            participant["average"] = round(sum(scores_list) / len(scores_list), 1)
            ranking.append(participant)
        session["ranking"] = sorted(
            ranking,
            key=lambda item: (-item["average"], -item["best"], item["name"].casefold()),
        )
        sessions.append(session)

    return render_template(
        "scores.html",
        site_title=get_site_name(),
        title=_("Scores"),
        sessions=sessions,
    )
