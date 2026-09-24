"""赛后复盘（只读）：依据提交分片回放比赛全程。

提供：
  - 每道题首次 AC（First Blood）的选手与准确时刻；
  - 比赛窗口内的全部有效提交事件，供前端在任意时刻重建完整榜单；
  - 参与人数 / 提交数等汇总信息。

本模块只读取 data/submissions/<contest_id>/ 下的提交记录，
不读取也不写入 scores / ranking，对原有排行榜与成绩零影响。
复盘只对已结束的比赛开放（由 API 层校验状态）。
"""
import os

from backend import config
from backend.storage import read_json, list_files
from backend.utils import parse_time

# 已出最终裁决的状态；PENDING / JUDGING 尚未形成有效记录，不参与回放
FINAL_STATUSES = {"AC", "WA", "TLE", "MLE", "OLE", "RE", "CE", "SE"}


def _problem_meta(contest):
    """竞赛题目清单（补充题目标题等展示信息）。"""
    metas = []
    for p in contest.get("problems", []) or []:
        pid = p.get("problem_id")
        if not pid:
            continue
        detail = read_json(os.path.join(config.PROBLEMS_DIR, f"{pid}.json")) or {}
        metas.append({
            "problem_id": pid,
            "title": detail.get("title", pid),
            "order": p.get("order", len(metas) + 1),
            "points": p.get("points", detail.get("points", 0)),
        })
    metas.sort(key=lambda m: (m["order"], m["problem_id"]))
    return metas


def collect_events(contest):
    """扫描竞赛提交分片，返回比赛窗口内的有效提交事件。

    事件按 (elapsed_sec, id) 升序；时刻统一用 parse_time 解析，
    因此相对开赛的偏移量不受服务器时区影响。
    窗口外（开赛前/结束后）以及尚未裁决完的提交一律剔除。
    """
    cid = contest.get("id")
    start = parse_time(contest.get("start_time"))
    end = parse_time(contest.get("end_time"))
    if not cid or start is None:
        return [], start, end

    cdir = os.path.join(config.SUBMISSIONS_DIR, cid)
    events = []
    for uid in list_files(cdir):
        shard = read_json(os.path.join(cdir, uid + ".json"))
        if not shard:
            continue
        for s in shard.get("submissions", []) or []:
            if s.get("status") not in FINAL_STATUSES:
                continue
            ts = parse_time(s.get("created_at"))
            if ts is None or ts < start:
                continue
            if end is not None and ts > end:
                continue
            events.append({
                "id": s.get("id"),
                "at": s.get("created_at"),
                "elapsed_sec": int(ts - start),
                "problem_id": s.get("problem_id"),
                "user_id": s.get("user_id"),
                "username": s.get("username", "") or uid,
                "nickname": s.get("nickname") or s.get("username", "") or uid,
                "status": s.get("status"),
                "score": int(s.get("score") or 0),
            })
    events.sort(key=lambda e: (e["elapsed_sec"], e["id"] or ""))
    return events, start, end


def build_replay(contest, penalty_seconds):
    """汇总一次比赛的复盘数据。"""
    problems = _problem_meta(contest)
    events, start, end = collect_events(contest)

    if start is not None and end is not None and end >= start:
        duration = int(end - start)
    else:
        duration = 0

    # 每道题的首次 AC：按事件时间顺序，第一次遇到即首杀
    first_solves = {p["problem_id"]: None for p in problems}
    participant_ids = set()

    for e in events:
        participant_ids.add(e["user_id"])
        if e["status"] == "AC" and first_solves.get(e["problem_id"]) is None:
            first_solves[e["problem_id"]] = {
                "problem_id": e["problem_id"],
                "user_id": e["user_id"],
                "username": e["username"],
                "nickname": e["nickname"],
                "at": e["at"],
                "elapsed_sec": e["elapsed_sec"],
            }

    # 首杀尝试次数：该选手在首杀时刻（含）之前对这道题的全部提交数。
    # 单独统计而非边遍历边计数，保证同一秒内的多次提交计数确定、不受并列顺序影响。
    for fs in first_solves.values():
        if not fs:
            continue
        fs["attempts"] = sum(
            1 for e in events
            if e["user_id"] == fs["user_id"]
            and e["problem_id"] == fs["problem_id"]
            and e["elapsed_sec"] <= fs["elapsed_sec"]
        )

    return {
        "contest_id": contest.get("id"),
        "contest_title": contest.get("title", ""),
        "mode": contest.get("mode", "acm"),
        "start_time": contest.get("start_time"),
        "end_time": contest.get("end_time"),
        "duration_sec": duration,
        "penalty_seconds": int(penalty_seconds),
        "problems": problems,
        # 与题目顺序一一对应；无人通过的题对应 null（前端展示空状态）
        "first_solves": [first_solves.get(p["problem_id"]) for p in problems],
        "events": events,
        "stats": {
            "submissions": len(events),
            "accepted": sum(1 for e in events if e["status"] == "AC"),
            "participants": len(participant_ids),
            "solved_problems": sum(1 for v in first_solves.values() if v),
        },
    }
