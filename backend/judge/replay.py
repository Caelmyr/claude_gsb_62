"""赛后复盘：由原始提交分片重建比赛过程。

只读 data/submissions/{contest_id}/ 下的提交分片，按「评测完成时刻」重放，
为前端时间线/排名快照提供紧凑事件流：

  - first_solves：每道题首次被做对的人与时刻（无人 AC 的题目为 None）；
  - events：每条已判定的提交（时刻、题目、用户、结果、得分）；
  - participants / stats：参赛者名单与汇总统计（用于空状态展示）。

复盘的排名由前端基于 events 逐步重放计算，rank_rows() 提供与榜单一致
口径的排序规则（ACM：解题数降序、罚时升序；IOI：总分降序、用时升序）。

本模块为纯只读计算，不触碰 scores/ 榜单数据，不影响实时排行榜与成绩。
"""
import os

from backend import config
from backend.storage import read_json, list_files
from backend.utils import parse_time

# 已判定、可参与复盘的状态（PENDING/JUDGING 等未完成状态不计入）
_JUDGED = ("AC", "WA", "TLE", "MLE", "RE", "CE", "OLE", "SE")


def _elapsed_seconds(contest, time_str):
    """将存储时间串换算为「距比赛开始的秒数」，不在比赛时段内返回 None。"""
    ts = parse_time(time_str)
    start = parse_time(contest.get("start_time"))
    end = parse_time(contest.get("end_time"))
    if ts is None or start is None:
        return None
    elapsed = int(ts - start)
    if elapsed < 0:
        return None
    if end is not None and elapsed > int(end - start):
        return None
    return elapsed


def _load_events(contest):
    """扫描该竞赛的提交分片，产出按时刻升序的紧凑事件列表。"""
    cdir = os.path.join(config.SUBMISSIONS_DIR, contest["id"])
    events = []
    for uid in list_files(cdir):
        shard = read_json(os.path.join(cdir, uid + ".json"))
        if not shard:
            continue
        for s in shard.get("submissions", []):
            if s.get("status") not in _JUDGED:
                continue
            # 优先使用评测完成时刻，缺失时退化为提交时刻
            t = _elapsed_seconds(contest, s.get("judged_at") or s.get("created_at"))
            if t is None:
                continue
            events.append({
                "t": t,
                "pid": s.get("problem_id"),
                "uid": s.get("user_id"),
                "username": s.get("username", ""),
                "nickname": s.get("nickname") or s.get("username", ""),
                "status": s.get("status"),
                "score": s.get("score", 0) or 0,
                "time_ms": s.get("time_ms", 0) or 0,
            })
    events.sort(key=lambda e: e["t"])
    return events


def rank_rows(state, mode):
    """对 {uid: row} 状态排序并赋名次，返回榜单行列表（与实时榜单同口径）。"""
    rows = list(state.values())
    if mode == "acm":
        rows.sort(key=lambda r: (-r["solved"], r["penalty"], r["user_id"]))
    else:
        rows.sort(key=lambda r: (-r["score"], r["total_time_ms"], r["user_id"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def build_replay(contest):
    """构建某场已结束竞赛的复盘数据（调用方负责校验比赛状态）。"""
    mode = contest.get("mode", "acm")
    start = parse_time(contest.get("start_time"))
    end = parse_time(contest.get("end_time"))
    duration = int(end - start) if (start is not None and end is not None) else 0

    # 题目元信息（含标题，供前端展示）
    problems = []
    for p in contest.get("problems", []):
        pid = p.get("problem_id")
        meta = read_json(os.path.join(config.PROBLEMS_DIR, f"{pid}.json")) or {}
        problems.append({
            "problem_id": pid,
            "title": meta.get("title", ""),
            "order": p.get("order"),
        })

    events = _load_events(contest)

    # 每题首次 AC（事件已按时刻升序，先出现者即首杀）
    first_solves = {}
    for e in events:
        if e["status"] == "AC" and e["pid"] not in first_solves:
            first_solves[e["pid"]] = {
                "problem_id": e["pid"],
                "user_id": e["uid"],
                "username": e["username"],
                "nickname": e["nickname"],
                "t": e["t"],
            }

    # 参赛者（按首次提交时刻排序）与每题统计
    participants = {}
    stats = {"submissions": len(events), "accepted": 0,
             "participants": 0, "solved_problems": 0}
    per_problem = {p["problem_id"]: {"attempts": 0, "accepted": 0} for p in problems}
    for e in events:
        if e["uid"] not in participants:
            participants[e["uid"]] = {
                "user_id": e["uid"],
                "username": e["username"],
                "nickname": e["nickname"],
                "first_t": e["t"],
            }
        pp = per_problem.get(e["pid"])
        if pp is not None:
            pp["attempts"] += 1
            if e["status"] == "AC":
                pp["accepted"] += 1
        if e["status"] == "AC":
            stats["accepted"] += 1
    stats["participants"] = len(participants)
    stats["solved_problems"] = sum(1 for p in problems
                                   if p["problem_id"] in first_solves)

    return {
        "contest_id": contest["id"],
        "contest_title": contest.get("title", ""),
        "mode": mode,
        "start_time": contest.get("start_time"),
        "end_time": contest.get("end_time"),
        "duration": duration,
        "penalty_seconds": int(config.DEFAULT_SETTINGS["ranking"]["penalty_seconds"]),
        "problems": problems,
        "first_solves": first_solves,
        "events": events,
        "participants": sorted(participants.values(), key=lambda u: u["first_t"]),
        "per_problem": per_problem,
        "stats": stats,
    }
