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
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(_BASE, "data", "store.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS resume_notes(
  id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, author TEXT NOT NULL,
  text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS item_state(
  doc_id TEXT, target_id TEXT, reviewed INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
  PRIMARY KEY(doc_id,target_id));
CREATE TABLE IF NOT EXISTS document_sources(
  doc_id TEXT PRIMARY KEY, pdf BLOB, original_text TEXT);
CREATE TABLE IF NOT EXISTS event_sources(
  doc_id TEXT, event_id TEXT, source TEXT, PRIMARY KEY(doc_id,event_id));
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
CREATE TABLE IF NOT EXISTS projects(
  doc_id TEXT, project_id TEXT, name TEXT, client TEXT, role TEXT, duration TEXT,
  details TEXT, source TEXT, raw_text TEXT,
  PRIMARY KEY(doc_id, project_id));
"""


_initialized_paths = set()


def init_db(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cx = sqlite3.connect(path, timeout=30.0)
    try:
        cx.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    cx.executescript(SCHEMA)
    try:
        cx.execute("ALTER TABLE documents ADD COLUMN candidate TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cx.execute("ALTER TABLE events ADD COLUMN entry_quote TEXT DEFAULT ''")
    except Exception:
        pass
    cx.close()
    _initialized_paths.add(path)


def connect(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path not in _initialized_paths:
        init_db(path)
    return sqlite3.connect(path, timeout=30.0)


def new_doc_id():
    return uuid.uuid4().hex[:12]


def save_result(cx, ctx, overall):
    now = time.time()
    # Carry forward notes from earlier UUID-based analyses of identical source.
    if ctx.raw_bytes.startswith(b"%PDF-"):
        older = cx.execute("SELECT doc_id FROM document_sources WHERE pdf=? AND doc_id<>?",
                           (ctx.raw_bytes, ctx.doc_id)).fetchall()
    elif not ctx.raw_bytes:
        older = cx.execute("SELECT doc_id FROM document_sources WHERE pdf IS NULL AND original_text=? AND doc_id<>?",
                           (ctx.meta.get("original_text", ctx.raw_text), ctx.doc_id)).fetchall()
    else:
        older = []
    for (old_id,) in older:
        # Keep old records available through their existing URLs as well.
        for note_id, author, text, created in cx.execute(
                "SELECT id,author,text,created_at FROM resume_notes WHERE doc_id=?", (old_id,)).fetchall():
            copied_id = "migrated:"+note_id.removeprefix("migrated:")
            cx.execute("INSERT OR IGNORE INTO resume_notes VALUES(?,?,?,?,?)",
                       (copied_id, ctx.doc_id, author, text, created))
        for fid, created, note in cx.execute("SELECT id,created,notes FROM feedback WHERE doc_id=?", (old_id,)).fetchall():
            if note:
                cx.execute("INSERT OR IGNORE INTO resume_notes VALUES(?,?,?,?,?)",
                           ("legacy:"+str(fid),ctx.doc_id,"Author not recorded",note,
                            datetime.fromtimestamp(created,timezone.utc).isoformat()))
    # Reanalysis replaces derived artifacts; human notes/state remain intact.
    for table in ("events", "event_sources", "gaps", "lineage", "stages", "projects"):
        try:
            cx.execute(f"DELETE FROM {table} WHERE doc_id=?", (ctx.doc_id,))
        except Exception:
            pass
    cx.execute("INSERT OR REPLACE INTO document_sources VALUES(?,?,?)",
               (ctx.doc_id, ctx.raw_bytes if ctx.raw_bytes.startswith(b"%PDF-") else None,
                ctx.meta.get("original_text", ctx.raw_text)))
    cx.execute(
        "INSERT OR REPLACE INTO documents"
        "(doc_id,filename,source,status,created,pages,chars,model_versions,candidate)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (ctx.doc_id, ctx.filename, ctx.source, overall, now,
         ctx.meta.get("pages", 0), ctx.meta.get("char_count", 0),
         json.dumps(dict(ctx.model_versions)),
         (ctx.recruiter_output or {}).get("candidate_name", "")))
    for name, r in ctx.stage_results.items():
        cx.execute(
            "INSERT OR REPLACE INTO stages VALUES(?,?,?,?,?,?,?)",
            (ctx.doc_id, name, r.status, r.confidence,
             json.dumps(r.errors), json.dumps(r.warnings),
             json.dumps(r.to_dict()["output"], default=str)[:20000]))
    entries_by_id = ctx.entries_by_id()
    for e in ctx.events:
        cx.execute("INSERT OR REPLACE INTO event_sources VALUES(?,?,?)",
                   (ctx.doc_id, e.id, json.dumps(getattr(e, "source", {}))))
        ent = entries_by_id.get(e.entry_id)
        anchored = [loc["text"] for loc in getattr(e, "source", {}).get("entry", [])]
        quote = " ".join(anchored)[:300] if anchored else (ent.text[:300] if ent else "")
        cx.execute(
            "INSERT OR REPLACE INTO events"
            "(doc_id,event_id,type,title,org,start,end,precision,status,confidence,entry_quote)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (ctx.doc_id, e.id, e.type, e.title, e.org,
             str(e.start), str(e.end), e.precision, e.status, e.confidence, quote))
    for g in ctx.gaps:
        cx.execute(
            "INSERT OR REPLACE INTO gaps VALUES(?,?,?,?,?,?,?,?,?)",
            (ctx.doc_id, g.id, str(g.start), str(g.end), g.months, g.state,
             g.confidence, json.dumps(g.reasons),
             json.dumps(g.evidence, default=str)))
    for gid, chain in ctx.lineage.items():
        cx.execute("INSERT OR REPLACE INTO lineage VALUES(?,?,?)",
                   (ctx.doc_id, gid, json.dumps(chain, default=str)))
    projects = (ctx.recruiter_output or {}).get("projects", [])
    for p in projects:
        cx.execute("INSERT OR REPLACE INTO event_sources VALUES(?,?,?)",
                   (ctx.doc_id, p["id"], json.dumps(p.get("source", {}))))
        try:
            cx.execute(
                "INSERT OR REPLACE INTO projects"
                "(doc_id,project_id,name,client,role,duration,details,source,raw_text)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (ctx.doc_id, p["id"], p.get("name", ""), p.get("client", ""),
                 p.get("role", ""), p.get("duration", ""),
                 json.dumps(p.get("details", [])), json.dumps(p.get("source", {})),
                 p.get("raw_text", "")))
        except Exception:
            pass
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


def _ym(value):
    """Normalize stored dates ('(2025, 5)', '[2025, 5]', '2025-05') -> 'YYYY-MM'."""
    import re
    if not value or value in ("None", ""):
        return None
    m = re.search(r"\(?\[?(\d{4})\s*,\s*(\d{1,2})\]?\)?", str(value))
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{4})-(\d{1,2})", str(value))
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return str(value)


def get_timeline(cx, doc_id):
    """Recruiter DTO rebuilt from storage + stored feedback applied."""
    doc = cx.execute("SELECT filename,status,candidate FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not doc:
        return None
    try:
        ev_rows = cx.execute(
            "SELECT event_id,type,title,org,start,end,precision,status,confidence,entry_quote"
            " FROM events WHERE doc_id=?", (doc_id,)).fetchall()
        keys = ("id", "type", "title", "org", "start", "end", "precision", "status", "confidence", "quote")
    except Exception:
        ev_rows = cx.execute(
            "SELECT event_id,type,title,org,start,end,precision,status,confidence"
            " FROM events WHERE doc_id=?", (doc_id,)).fetchall()
        keys = ("id", "type", "title", "org", "start", "end", "precision", "status", "confidence")
    events = [dict(zip(keys, r)) for r in ev_rows]
    sources = {eid: json.loads(value) for eid, value in cx.execute(
        "SELECT event_id,source FROM event_sources WHERE doc_id=?", (doc_id,))}
    for event in events:
        event["source"] = sources.get(event["id"], {})
        event["date_label"] = event["source"].get("date_label", "")
        event["section"] = event["source"].get("section", "")
        event["is_present"] = event["source"].get("is_present", False)
    # dated events form the visual timeline; undated ones stay visible but separate
    timeline = []
    unresolved = []
    for e in events:
        e["start"], e["end"] = _ym(e.get("start")), _ym(e.get("end"))
        (timeline if e["start"] else unresolved).append(e)
    timeline.sort(key=lambda e: (e["start"], e["end"] or e["start"]))
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
        g["start"] = _ym(g.get("start")) or g.get("start")
        g["end"] = _ym(g.get("end")) or g.get("end")
        if g["start"] and g["end"]:
            g["start_label"], g["end_label"] = g["start"], g["end"]
        lineage_row = cx.execute(
            "SELECT chain FROM lineage WHERE doc_id=? AND gap_id=?", (doc_id, g["id"])).fetchone()
        if lineage_row and lineage_row[0]:
            try:
                ch = json.loads(lineage_row[0])
                quotes, details = [], []
                for link in ch.get("links", []):
                    q = link.get("entry_quote", "")
                    ev_info = link.get("event", {})
                    hdr = f"{ev_info.get('title', '')} at {ev_info.get('org', '')}".strip(" at ")
                    if q:
                        quotes.append(q[:300])
                        details.append({"header": hdr, "quote": q[:300], "event_id": ev_info.get("id"), "source": ev_info.get("source", {})})
                g["evidence_quotes"] = quotes
                g["evidence_details"] = details
            except Exception:
                pass
    fb = cx.execute(
        "SELECT dismissed_gap_ids,overrides,notes FROM feedback WHERE doc_id=? ORDER BY id",
        (doc_id,)).fetchall()
    dismissed, overrides, recruiter_notes = set(), [], []
    for d, o, n in fb:
        try:
            dismissed.update(json.loads(d or "[]"))
        except Exception:
            pass
        try:
            overrides.extend(json.loads(o or "[]"))
        except Exception:
            pass
        if n and str(n).strip():
            recruiter_notes.append(str(n).strip())
    for g in gaps:
        if g["id"] in dismissed:
            g["dismissed_by_recruiter"] = True
            if g["state"] == "POTENTIAL_GAP":
                g["state"] = "DISMISSED_GAP"
    total_ev = len(timeline) + len(unresolved)
    confs = [e["confidence"] for e in timeline if e.get("confidence") is not None]
    quality = {
        "dated_events": len(timeline),
        "total_events": total_ev,
        "dated_share": round(len(timeline) / total_ev, 3) if total_ev else 0.0,
        "unresolved": len(unresolved),
        "ambiguous": sum(1 for e in timeline if e.get("status") == "AMBIGUOUS"),
        "mean_event_confidence": round(sum(confs) / len(confs), 3) if confs else None,
    }
    is_reviewed = False
    for o in overrides:
        if isinstance(o, dict) and o.get("reviewed") is not None:
            is_reviewed = bool(o.get("reviewed"))
    try:
        p_rows = cx.execute(
            "SELECT project_id,name,client,role,duration,details,source,raw_text"
            " FROM projects WHERE doc_id=?", (doc_id,)).fetchall()
        projects = []
        for r in p_rows:
            projects.append({
                "id": r[0], "name": r[1], "client": r[2], "role": r[3],
                "duration": r[4], "details": json.loads(r[5] or "[]"),
                "source": json.loads(r[6] or "{}"), "raw_text": r[7] or ""
            })
    except Exception:
        projects = []
    from .periods import analyze_timeline
    return {"period_analysis": analyze_timeline(timeline, unresolved, projects),
            "doc_id": doc_id, "filename": doc[0], "status": doc[1],
            "candidate_name": doc[2] or "",
            "is_reviewed": is_reviewed,
            "original_text": get_source_text(cx, doc_id),
            "timeline": timeline, "unresolved_events": unresolved,
            "projects": projects, "gaps": gaps,
            "quality": quality,
            "notes": get_notes(cx, doc_id), "item_state": get_item_state(cx, doc_id),
            "recruiter_notes": recruiter_notes,
            "recruiter_overrides": overrides,
            "disclaimer": ("Potential gaps mark periods with no clearly represented "
                           "activity in the resume. They are not evidence of unemployment. "
                           "The recruiter makes the final decision.")}


def get_source_text(cx, doc_id):
    row = cx.execute("SELECT original_text FROM document_sources WHERE doc_id=?", (doc_id,)).fetchone()
    return row[0] if row else ""



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
        return {"doc_id": doc_id, "event_id": event_id, "event": dict(zip(keys, row)),
                "source": get_event_source(cx, doc_id, event_id)}
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


def get_event_source(cx, doc_id, event_id):
    row = cx.execute("SELECT source FROM event_sources WHERE doc_id=? AND event_id=?",
                     (doc_id, event_id)).fetchone()
    return json.loads(row[0]) if row else {}


def get_source_page(cx, doc_id, page):
    from .source import render_page
    row = cx.execute("SELECT pdf,original_text FROM document_sources WHERE doc_id=?", (doc_id,)).fetchone()
    if not row:
        return None
    if row[0]:
        return render_page(row[0], page)
    if page != 1:
        raise ValueError("page out of range")
    return {"page": 1, "text": row[1]}


def get_notes(cx, doc_id):
    return [dict(zip(("id", "author", "text", "created_at"), row)) for row in cx.execute(
        "SELECT id,author,text,created_at FROM resume_notes WHERE doc_id=? ORDER BY created_at,id", (doc_id,))]


def add_note(cx, doc_id, payload):
    author, text = payload.get("author"), payload.get("text")
    if not isinstance(author, str) or not author.strip() or len(author) > 200:
        raise ValueError("Enter your name (maximum 200 characters).")
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ValueError("Enter a note (maximum 10000 characters).")
    note_id = payload.get("id") or uuid.uuid4().hex
    if not isinstance(note_id, str) or len(note_id) > 100:
        raise ValueError("Invalid note ID.")
    # A retry is idempotent; never overwrite somebody else's saved note.
    existing = cx.execute("SELECT doc_id,author,text FROM resume_notes WHERE id=?", (note_id,)).fetchone()
    if existing and existing != (doc_id, author.strip(), text.strip()):
        raise ValueError("Note ID already exists with different content.")
    cx.execute("INSERT OR IGNORE INTO resume_notes VALUES(?,?,?,?,?)",
               (note_id, doc_id, author.strip(), text.strip(), datetime.now(timezone.utc).isoformat()))
    cx.commit()
    return get_notes(cx, doc_id)


def get_item_state(cx, doc_id):
    return {row[0]: {"reviewed": bool(row[1]), "hidden": bool(row[2])} for row in cx.execute(
        "SELECT target_id,reviewed,hidden FROM item_state WHERE doc_id=?", (doc_id,))}


def save_item_state(cx, doc_id, payload):
    target = payload.get("target_id")
    if not isinstance(target, str) or not target:
        raise ValueError("Timeline item not found.")
    exists = (cx.execute("SELECT 1 FROM events WHERE doc_id=? AND event_id=?", (doc_id,target)).fetchone()
              or cx.execute("SELECT 1 FROM gaps WHERE doc_id=? AND gap_id=? AND state='POTENTIAL_GAP'", (doc_id,target)).fetchone())
    if not exists:
        raise ValueError("Timeline item not found.")
    changes = {k: payload[k] for k in ("reviewed", "hidden") if k in payload}
    if not changes or any(type(value) is not bool for value in changes.values()):
        raise ValueError("Review and visibility values must be boolean.")
    now = datetime.now(timezone.utc).isoformat()
    cx.execute("INSERT OR IGNORE INTO item_state VALUES(?,?,?,?,?)", (doc_id,target,0,0,now))
    assignments = ",".join(k+"=?" for k in changes)
    cx.execute("UPDATE item_state SET "+assignments+",updated_at=? WHERE doc_id=? AND target_id=?",
               (*[int(v) for v in changes.values()],now,doc_id,target))
    cx.commit()
    return get_item_state(cx, doc_id)[target]
