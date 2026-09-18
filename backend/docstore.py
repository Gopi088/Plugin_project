"""Storage layer (sqlite3, stdlib only).

Stores: documents, per-stage results, events, gaps, lineage, model versions,
errors, and recruiter feedback/overrides — so every result is auditable,
debuggable, and evaluable. Default DB: backend/data/store.db
"""

import json
import os
import sqlite3
import time
import uuid

_BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(_BASE, "data", "store.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY, filename TEXT, source TEXT, status TEXT,
  created REAL, pages INTEGER, chars INTEGER, model_versions TEXT);
CREATE TABLE IF NOT EXISTS stages(
  doc_id TEXT, stage TEXT, status TEXT, confidence REAL,
  errors TEXT, warnings TEXT, output TEXT,
  PRIMARY KEY(doc_id, stage));
CREATE TABLE IF NOT EXISTS events(
  doc_id TEXT, event_id TEXT, type TEXT, title TEXT, org TEXT,
  start TEXT, end TEXT, precision TEXT, status TEXT, confidence REAL,
  PRIMARY KEY(doc_id, event_id));
CREATE TABLE IF NOT EXISTS gaps(
  doc_id TEXT, gap_id TEXT, start TEXT, end TEXT, months INTEGER,
  state TEXT, confidence REAL, reasons TEXT, evidence TEXT,
  PRIMARY KEY(doc_id, gap_id));
CREATE TABLE IF NOT EXISTS lineage(
  doc_id TEXT, gap_id TEXT, chain TEXT, PRIMARY KEY(doc_id, gap_id));
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, created REAL,
  dismissed_gap_ids TEXT, overrides TEXT, notes TEXT);
"""


def connect(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cx = sqlite3.connect(path)
    cx.executescript(SCHEMA)
    return cx


def new_doc_id():
    return uuid.uuid4().hex[:12]


def save_result(cx, ctx, overall):
    now = time.time()
    cx.execute(
        "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?,?)",
        (ctx.doc_id, ctx.filename, ctx.source, overall, now,
         ctx.meta.get("pages", 0), ctx.meta.get("char_count", 0),
         json.dumps(dict(ctx.model_versions))))
    for name, r in ctx.stage_results.items():
        cx.execute(
            "INSERT OR REPLACE INTO stages VALUES(?,?,?,?,?,?,?)",
            (ctx.doc_id, name, r.status, r.confidence,
             json.dumps(r.errors), json.dumps(r.warnings),
             json.dumps(r.to_dict()["output"], default=str)[:20000]))
    for e in ctx.events:
        cx.execute(
            "INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ctx.doc_id, e.id, e.type, e.title, e.org,
             str(e.start), str(e.end), e.precision, e.status, e.confidence))
    for g in ctx.gaps:
        cx.execute(
            "INSERT OR REPLACE INTO gaps VALUES(?,?,?,?,?,?,?,?,?)",
            (ctx.doc_id, g.id, str(g.start), str(g.end), g.months, g.state,
             g.confidence, json.dumps(g.reasons),
             json.dumps(g.evidence, default=str)))
    for gid, chain in ctx.lineage.items():
        cx.execute("INSERT OR REPLACE INTO lineage VALUES(?,?,?)",
                   (ctx.doc_id, gid, json.dumps(chain, default=str)[:40000]))
    cx.commit()


def get_status(cx, doc_id):
    doc = cx.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not doc:
        return None
    stages = cx.execute(
        "SELECT stage,status,confidence FROM stages WHERE doc_id=?", (doc_id,)).fetchall()
    return {"doc_id": doc[0], "filename": doc[1], "source": doc[2],
            "status": doc[3], "created": doc[4],
            "stages": [{"stage": s[0], "status": s[1], "confidence": s[2]} for s in stages]}


def get_timeline(cx, doc_id):
    """Recruiter DTO rebuilt from storage + stored feedback applied."""
    doc = cx.execute("SELECT filename,status FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not doc:
        return None
    events = [dict(zip(("id", "type", "title", "org", "start", "end",
                         "precision", "status", "confidence"), r))
              for r in cx.execute(
                  "SELECT event_id,type,title,org,start,end,precision,status,confidence"
                  " FROM events WHERE doc_id=?", (doc_id,)).fetchall()]
    # dated events form the visual timeline; undated ones stay visible but separate
    timeline = [e for e in events if e.get("start") and e["start"] != "None"]
    unresolved = [e for e in events if not (e.get("start") and e["start"] != "None")]
    gaps = [dict(zip(("id", "start", "end", "months", "state", "confidence",
                       "reasons", "evidence"), r))
            for r in cx.execute(
                "SELECT gap_id,start,end,months,state,confidence,reasons,evidence"
                " FROM gaps WHERE doc_id=?", (doc_id,)).fetchall()]
    for g in gaps:
        for k in ("reasons", "evidence"):
            try:
                g[k] = json.loads(g[k])
            except Exception:
                pass
    fb = cx.execute(
        "SELECT dismissed_gap_ids,overrides,notes FROM feedback WHERE doc_id=? ORDER BY id",
        (doc_id,)).fetchall()
    dismissed, overrides = set(), []
    for d, o, _n in fb:
        try:
            dismissed.update(json.loads(d or "[]"))
        except Exception:
            pass
        try:
            overrides.extend(json.loads(o or "[]"))
        except Exception:
            pass
    for g in gaps:
        if g["id"] in dismissed:
            g["dismissed_by_recruiter"] = True
            if g["state"] == "POTENTIAL_GAP":
                g["state"] = "DISMISSED_GAP"
    return {"doc_id": doc_id, "filename": doc[0], "status": doc[1],
            "timeline": timeline, "unresolved_events": unresolved, "gaps": gaps,
            "recruiter_overrides": overrides,
            "disclaimer": ("Potential gaps mark periods with no clearly represented "
                           "activity in the resume. They are not evidence of unemployment. "
                           "The recruiter makes the final decision.")}


def get_evidence(cx, doc_id, gap_id=None, event_id=None):
    if gap_id:
        row = cx.execute("SELECT chain FROM lineage WHERE doc_id=? AND gap_id=?",
                         (doc_id, gap_id)).fetchone()
        return {"doc_id": doc_id, "gap_id": gap_id,
                "chain": json.loads(row[0]) if row else None}
    if event_id:
        row = cx.execute("SELECT * FROM events WHERE doc_id=? AND event_id=?",
                         (doc_id, event_id)).fetchone()
        if not row:
            return {"doc_id": doc_id, "event_id": event_id, "event": None}
        keys = ("doc_id", "event_id", "type", "title", "org", "start", "end",
                "precision", "status", "confidence")
        return {"doc_id": doc_id, "event_id": event_id, "event": dict(zip(keys, row))}
    return {"doc_id": doc_id, "error": "provide gap_id or event_id"}


def get_stages(cx, doc_id):
    rows = cx.execute(
        "SELECT stage,status,confidence,errors,warnings,output FROM stages WHERE doc_id=?",
        (doc_id,)).fetchall()
    out = []
    for s, st, c, e, w, o in rows:
        try:
            e, w, o = json.loads(e), json.loads(w), json.loads(o)
        except Exception:
            pass
        out.append({"stage": s, "status": st, "confidence": c,
                    "errors": e, "warnings": w, "output": o})
    return {"doc_id": doc_id, "stages": out} if out else None


def save_feedback(cx, doc_id, dismissed, overrides, notes):
    cx.execute(
        "INSERT INTO feedback(doc_id,created,dismissed_gap_ids,overrides,notes)"
        " VALUES(?,?,?,?,?)",
        (doc_id, time.time(), json.dumps(dismissed or []),
         json.dumps(overrides or []), notes or ""))
    cx.commit()
    return True
