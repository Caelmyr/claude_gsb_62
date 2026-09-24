"""赛后复盘 API：仅对已结束的竞赛开放。"""
import os

from flask import Blueprint

from backend import config
from backend.api import ok, err, require_auth, get_current_user
from backend.storage import read_json
from backend.judge.ranking import contest_status
from backend.judge.replay import build_replay

replay_bp = Blueprint("replay", __name__)


@replay_bp.get("/contests/<contest_id>/replay")
@require_auth
def contest_replay(contest_id):
    contest = read_json(os.path.join(config.CONTESTS_DIR, f"{contest_id}.json"))
    if not contest:
        return err("竞赛不存在", 404)
    user = get_current_user()
    if not contest.get("visble", True) and (user is None or user.get("role") != "admin"):
        return err("竞赛不存在", 404)
    # 复盘只针对已结束的比赛：未开始/进行中一律不开放
    status = contest_status(contest)
    if status != "ended":
        label = {"upcoming": "尚未开始", "running": "正在进行中"}.get(status, "")
        return err(f"比赛{label}，复盘将在比赛结束后开放", 400)
    return ok(build_replay(contest))
