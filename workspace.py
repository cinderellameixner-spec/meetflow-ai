"""Local meeting history, editable tasks and in-app reminders."""
import calendar
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
import analysis_cache

from meetflow import AnalysisError, MAX_CHARS, validate, InvalidOutput

DB = Path(__file__).parent / "private" / "workspace.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_cache(fingerprint TEXT PRIMARY KEY, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meetings(
 id TEXT PRIMARY KEY, day TEXT NOT NULL, fingerprint TEXT NOT NULL, source TEXT NOT NULL,
 summary TEXT NOT NULL, warning TEXT NOT NULL, UNIQUE(day,fingerprint));
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, meeting TEXT NOT NULL REFERENCES meetings(id), original TEXT NOT NULL,
 action TEXT NOT NULL, owner TEXT NOT NULL, due TEXT NOT NULL, deadline TEXT NOT NULL,
 reminder TEXT NOT NULL, seen TEXT NOT NULL DEFAULT '', completed TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY, aliases TEXT NOT NULL);
"""
FIELDS = ("action","owner","due","deadline","reminder")
MONTHS = {s.lower(): i for i in range(1,13) for s in (calendar.month_abbr[i],calendar.month_name[i])}


def fail(msg):
    raise AnalysisError(msg, "workspace")


def value(v, limit=1500):
    if not isinstance(v, str) or len(v)>limit:
        fail("字段内容过长或格式错误。")
    return v.strip()


def iso_day(s):
    try:
        return date.fromisoformat(s).isoformat()
    except (ValueError, TypeError):
        fail("请选择有效日期。")


def calendar_day(raw, meeting):
    """Resolve a single unambiguous date relative to the meeting."""
    if not raw:
        return ""
    base = date.fromisoformat(meeting)
    s = re.sub(r"^(?:(?:on or )?by\s+|截止到?|最迟到?)|(?:以?前|之前|截止)$", "", raw.strip(), flags=re.I).strip()
    # Strip a time of day only after retaining its date.
    s = re.sub(r"(?:上午|下午|晚上|早上|中午|\s+at\s+|\s+\d{1,2}:).*", "", s, flags=re.I).strip()
    if s in ("今天","明天","后天","today","tomorrow"):
        return (base+timedelta(days={"今天":0,"明天":1,"后天":2,"today":0,"tomorrow":1}[s])).isoformat()
    weekday = re.fullmatch(r"(本|这|下)?(?:星期|周|週)([一二三四五六日天])",s)
    if weekday:
        target = "一二三四五六日".index(weekday[2].replace("天","日"))
        shift = target-base.weekday()
        if weekday[1]=="下":
            shift += 7
        elif not weekday[1]:
            shift %= 7
        return (base+timedelta(days=shift)).isoformat()
    try:
        parts = re.fullmatch(r"(?:(\d{4})[-年/])?(\d{1,2})[-月/](\d{1,2})[日号]?",s)
        if parts:
            return date(int(parts[1] or base.year),int(parts[2]),int(parts[3])).isoformat()
        parts = re.fullmatch(r"([a-zA-Z]+)\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?",s)
        if parts and parts[1].lower() in MONTHS:
            return date(int(parts[3] or base.year),MONTHS[parts[1].lower()],int(parts[2])).isoformat()
    except ValueError:
        pass
    return ""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_state(db):
    meetings = [dict(id=r["id"],day=r["day"],title=json.loads(r["summary"])["title"])
                for r in db.execute("SELECT id,day,summary FROM meetings ORDER BY day DESC,rowid DESC")]
    tasks = [dict(r) for r in db.execute("SELECT id,meeting,action,owner,due,deadline,reminder,seen,completed,state,revision FROM tasks WHERE state!='dismissed' ORDER BY rowid")]
    names = db.execute("SELECT aliases FROM profile WHERE id=1").fetchone()
    return dict(meetings=meetings,tasks=tasks,aliases=json.loads(names[0]) if names else [])


def detail(db, mid):
    row = db.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
    if not row:
        fail("找不到该会议。")
    tasks = []
    for r in db.execute("SELECT * FROM tasks WHERE meeting=? AND state!='dismissed' ORDER BY rowid",(mid,)):
        item = dict(r)
        item["original"] = json.loads(item["original"])
        tasks.append(item)
    return dict(id=mid,day=row["day"],text=row["source"],summary=json.loads(row["summary"]),
                review_warning=row["warning"],tasks=tasks)


def edited_fields(original, change, day):
    action = value(change.get("action",original["action"]))
    if not action:
        fail("请填写待办行动。")
    owner = value(change.get("owner",original.get("owner") or ""),200)
    due = value(change.get("due",original.get("due") or ""),300)
    deadline = change.get("deadline", calendar_day(due,day))
    if deadline:
        deadline = iso_day(deadline)
    reminder = value(change.get("reminder","auto"),30)
    if reminder not in ("auto","off") and not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d",reminder):
        fail("提醒时间无效。")
    if reminder not in ("auto","off"):
        try:
            datetime.fromisoformat(reminder)
        except ValueError:
            fail("提醒时间无效。")
    return action,owner,due,deadline,reminder


def alarm(t):
    if t["reminder"]=="auto":
        return t["deadline"]+"T09:00" if t["deadline"] else ""
    return "" if t["reminder"]=="off" else t["reminder"]


def save(db, p):
    source=p.get("text")
    if not isinstance(source,str) or not source.strip() or len(source)>MAX_CHARS:
        fail("会议原文为空或超出长度限制。")
    day=iso_day(p.get("day"))
    fingerprint=hashlib.sha256(source.strip().encode()).hexdigest()
    analysis_cache.save_with_meeting(db,source)
    old=db.execute("SELECT id FROM meetings WHERE day=? AND fingerprint=?", (day,fingerprint)).fetchone()
    if old:
        return dict(meeting=detail(db,old[0]),existing=True)
    summary=validate(p["summary"],"summary",source)
    mid=uuid.uuid4().hex
    db.execute("INSERT INTO meetings VALUES(?,?,?,?,?,?)",(mid,day,fingerprint,source,json.dumps(summary),value(p.get("review_warning",""))))
    for t in p["tasks"]:
        raw=t["original"]
        if not isinstance(raw, dict):
            fail("待办格式无效。")
        ref=raw.get("citations",{}).get("action",{})
        checked=validate({"tasks":[dict(raw,evidence_line=ref.get("line"))]},"tasks",source)["tasks"]
        if not checked:
            continue
        original=checked[0]
        # Preserve any field-level review notes from analysis.
        if isinstance(raw.get("review"),list):
            original["review"]=[value(s) for s in raw["review"]]
        state=t.get("state","active")
        if state not in ("active","suggested","dismissed"):
            fail("待办状态无效。")
        fields=edited_fields(original,t,day)
        db.execute("""INSERT INTO tasks(id,meeting,original,action,owner,due,deadline,reminder,completed,state)
                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (uuid.uuid4().hex,mid,json.dumps(original),*fields,utc_now() if t.get("completed") else "",state))
    return dict(meeting=detail(db,mid),existing=False)


def update(db,p):
    row=db.execute("SELECT t.*,m.day FROM tasks t JOIN meetings m ON m.id=t.meeting WHERE t.id=?",(p["id"],)).fetchone()
    if not row:
        fail("找不到该待办。")
    if row["revision"]!=p.get("revision"):
        fail("该待办已在另一页面更新，请重新打开后操作。")
    edit=p["change"]
    if not isinstance(edit,dict) or set(edit)-set(FIELDS)-{"completed","state","ack"}:
        fail("待办修改字段无效。")
    t=dict(row)
    t.update(edit)
    fields=edited_fields(json.loads(row["original"]),t,row["day"])
    if t["state"]!=row["state"] and (row["state"]!="suggested" or t["state"] not in ("active","dismissed")):
        fail("无法更改该待办状态。")
    if "completed" in edit and type(edit["completed"]) is not bool:
        fail("办结状态无效。")
    completion=(row["completed"] or utc_now()) if t["completed"] else ""
    seen=row["seen"] if alarm(row)==alarm(t) and row["owner"]==t["owner"] else ""
    if edit.get("ack"):
        seen=alarm(t)
    db.execute("""UPDATE tasks SET action=?,owner=?,due=?,deadline=?,reminder=?,completed=?,state=?,seen=?,
                  revision=revision+1 WHERE id=?""",(*fields,completion,t["state"],seen,row["id"]))
    return dict(meeting=detail(db,row["meeting"]))


def database_path():
    return Path(os.getenv("MEETFLOW_DB") or DB)


def dispatch(p):
    path=database_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=8)) as db, db:
        db.row_factory=sqlite3.Row
        db.executescript(SCHEMA)
        db.execute("PRAGMA foreign_keys=ON")
        op=p.get("op")
        if op=="list":
            return get_state(db)
        if op=="search":
            q=value(p["q"]).lower()
            return dict(ids=[r["id"] for r in db.execute("SELECT id,summary,source FROM meetings")
                             if q in json.loads(r["summary"])["title"].lower() or q in r["source"].lower()])
        if op=="open":
            return dict(meeting=detail(db,p["id"]))
        if op=="date":
            return dict(deadline=calendar_day(value(p["due"]),iso_day(p["day"])))
        db.execute("BEGIN IMMEDIATE")
        if op=="save":
            return save(db,p)
        if op=="update":
            return update(db,p)
        if op=="profile":
            names=list(dict.fromkeys(value(n,100) for n in p["aliases"] if n))
            db.execute("INSERT OR REPLACE INTO profile VALUES(1,?)",(json.dumps(names),))
            return dict(aliases=names)
        fail("未知操作。")

