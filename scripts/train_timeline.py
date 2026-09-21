"""Train the timeline NER model (model_timeline/) from dataset/text/*.txt.

Weak supervision: regex labels for DEGREE / GRAD_DATE / JOB_DATE / COMPANY /
JOB_TITLE / PROJECT (see MODEL_TRAINING.md). Overlaps resolved by priority.
Saves spaCy model to model_timeline/ and raw labels to
dataset/timeline_training_data.json.

Usage:
    ./venv/bin/python scripts/train_timeline.py --epochs 30 --out model_timeline
"""

import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spacy.training import Example
import spacy

from backend.cues import load as _load_cues

_CUES = _load_cues()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_DIR = os.path.join(BASE_DIR, "dataset", "text")

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
YEAR = r"(?:19|20)\d{2}"
PRESENT = r"(?:" + "|".join(_CUES.get("present_words_regex", ["present"])) + r")"
DATE_BIT = rf"(?:{MONTH}[\s.\-/]*?)?{YEAR}|{PRESENT}|(?:0?[1-9]|1[0-2])[\-/]{YEAR}|{YEAR}[\-/](?:0?[1-9]|1[0-2])"
SEP = r"(?:\s*(?:\u2013|\u2014|-|–|—|to|till|until|through|/)\s*)"
RANGE_RE = re.compile(rf"(?P<a>{DATE_BIT}){SEP}(?P<b>{DATE_BIT})", re.IGNORECASE)
SINGLE_RE = re.compile(rf"\b{DATE_BIT}\b", re.IGNORECASE)

_fam = "|".join(f"(?:{f})" for f in _CUES["job_family_words_regex"])
_roles = "|".join(f"(?:{f})" for f in _CUES["title_words_regex"])
_suf = "|".join(f"(?:{f})" for f in _CUES["company_suffixes_regex"])
_deg = "|".join(f"(?:{f})" for f in _CUES["degree_words_regex"])

DEGREE_RE = re.compile(_deg, re.IGNORECASE)
COMPANY_RE = re.compile(
    r"(?:Worked\s+at\s+)?([A-Z][A-Za-z&.,\- ]{2,60}?\s+(?:" + _suf + r"))",
)
TITLE_RE = re.compile(
    r"\b((?:Senior|Junior|Associate|Lead|Principal)?\s*?(?:" + _fam + r")\s*?(?:" + _roles + r"))\b",
    re.IGNORECASE,
)
PROJECT_HEAD_RE = re.compile(r"^(?:#\d+\s*)?(?:Project(?:\s+name)?\s*[:#]\s*.+|.+\s+project)$",
                             re.IGNORECASE)

PRIORITY = {"GRAD_DATE": 0, "JOB_DATE": 1, "DEGREE": 2,
            "COMPANY": 3, "JOB_TITLE": 4, "PROJECT": 5}


def _norm(text):
    if not text:
        return text
    text = text.replace("So\x00ware", "Software").replace("so\x00ware", "software")
    text = text.replace("Pro\x00cient", "Proficient").replace("pro\x00ciency", "proficiency")
    text = text.replace("con\x00g", "config").replace("Con\x00g", "Config")
    text = re.sub(r"(?<![A-Za-z])\x00x(?![A-Za-z])", "fix", text)
    text = text.replace("\x00", "ti")
    return text


def _section(text, headers, stoppers):
    """Header-line anchored section (ignores 'years of experience' body copy)."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip().strip(":").strip()
        low = s.lower()
        if low in [h.lower() for h in headers] or any(
                re.fullmatch(h, s, re.IGNORECASE) for h in headers if len(h) < 40):
            # skip summary lines like 'Exp Total Years Experience: 5.7'
            if re.search(r"\d", s) and "experience" in low and "professional" not in low and "work" not in low:
                continue
            start = i
            break
    if start is None:
        return None, ""
    buf = []
    for ln in lines[start + 1:]:
        s = ln.strip().strip(":").strip()
        if any(re.fullmatch(st, s, re.IGNORECASE) for st in stoppers):
            break
        buf.append(ln)
    sec = "\n".join(buf)
    return (sec, sec)


def _spans(text):
    text = _norm(text)
    cands = []
    edu_m = re.search(r"(EDUCATION|ACADEMIC|QUALIFICATION)(.*?)(EXPERIENCE|PROJECTS|SKILLS|CERTIFICATION|$)",
                      text, re.IGNORECASE | re.DOTALL)
    _, exp_sec = _section(text,
                          ["PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE", "EMPLOYMENT HISTORY", "EXPERIENCE"],
                          ["KEY PROJECTS", "PROJECTS", "PROJECT PROFILE", "EDUCATION", "SKILLS", "TECHNICAL SKILLS", "CERTIFICATION"])
    exp_m = None
    exp = exp_sec
    if exp_sec:
        # fake match offsets: locate section in text
        exp_m = True
        base_exp = text.find(exp_sec)
    else:
        exp_m = re.search(r"(PROFESSIONAL EXPERIENCE|WORK EXPERIENCE|EMPLOYMENT)(.*?)(PROJECTS|EDUCATION|SKILLS|CERTIFICATION|$)",
                          text, re.IGNORECASE | re.DOTALL)
        exp = exp_m.group(2) if exp_m else ""
        base_exp = exp_m.start(2) if exp_m else 0

    def add(scope_text, base, label, match):
        cands.append((base + match.start(), base + match.end(), label))

    edu = edu_m.group(2) if edu_m else ""
    if edu_m:
        base = edu_m.start(2)
        for m in DEGREE_RE.finditer(edu):
            add(edu, base, "DEGREE", m)
        for m in list(RANGE_RE.finditer(edu)) + list(SINGLE_RE.finditer(edu)):
            if re.search(YEAR, m.group(0)):
                add(edu, base, "GRAD_DATE", m)
    if exp_m:
        base = base_exp
        for m in list(RANGE_RE.finditer(exp)) + list(SINGLE_RE.finditer(exp)):
            if re.search(rf"{YEAR}|{PRESENT}", m.group(0), re.IGNORECASE):
                add(exp, base, "JOB_DATE", m)
        for m in COMPANY_RE.finditer(exp):
            g = m.group(1) or m.group(0)
            s = m.start(0) + m.group(0).find(g)
            cands.append((base + s, base + s + len(g), "COMPANY"))
        for m in TITLE_RE.finditer(exp):
            add(exp, base, "JOB_TITLE", m)

    proj_m = re.search(r"(KEY PROJECTS|\bPROJECTS\b)(.*?)(EDUCATION|CERTIFICATION|DECLARATION|$)",
                       text, re.IGNORECASE | re.DOTALL)
    if proj_m:
        base = proj_m.start(2)
        for line_m in re.finditer(r"^(.+)$", proj_m.group(2), re.MULTILINE):
            line = line_m.group(1).strip()
            if PROJECT_HEAD_RE.match(line) and len(line) < 100:
                s = base + line_m.start(1) + line_m.group(1).find(line)
                cands.append((s, s + len(line), "PROJECT"))

    # resolve overlaps: priority then longest
    cands.sort(key=lambda e: (e[0], PRIORITY.get(e[2], 9), -(e[1] - e[0])))
    kept, last_end, by_label = [], -1, {}
    ordered = sorted(cands, key=lambda e: (e[0], PRIORITY.get(e[2], 9)))
    # greedy non-overlap preferring priority: sort by start, then priority
    kept = []
    for s, e, lab in ordered:
        if all(e <= ks or s >= ke for ks, ke, _ in kept):
            kept.append((s, e, lab))
    kept.sort(key=lambda e: e[0])
    return kept


def build_data(limit=None):
    files = sorted(f for f in os.listdir(TEXT_DIR) if f.endswith(".txt"))
    if limit:
        files = files[:limit]
    data, counts = [], {}
    for f in files:
        with open(os.path.join(TEXT_DIR, f), encoding="utf-8", errors="ignore") as fh:
            text = _norm(fh.read())
        if len(text) > 20000:
            text = text[:20000]
        ents = _spans(text)
        for _, _, lab in ents:
            counts[lab] = counts.get(lab, 0) + 1
        if ents:
            data.append({"text": text, "entities": [list(e) for e in ents]})
    return data, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--out", default=os.path.join(BASE_DIR, "model_timeline"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    data, counts = build_data(limit=args.limit or None)
    print(f"Resumes with labels: {len(data)} | spans: {counts}")
    with open(os.path.join(BASE_DIR, "dataset", "timeline_training_data.json"), "w",
              encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    print("saved dataset/timeline_training_data.json")

    train = [(d["text"], {"entities": [tuple(e) for e in d["entities"]]}) for d in data]
    nlp = spacy.blank("en")
    ner = nlp.add_pipe("ner")
    for _, ann in train:
        for _, _, lab in ann["entities"]:
            ner.add_label(lab)
    nlp.begin_training()
    for epoch in range(args.epochs):
        random.shuffle(train)
        losses = {}
        for text, ann in train:
            try:
                doc = nlp.make_doc(text)
                nlp.update([Example.from_dict(doc, ann)], drop=0.3, losses=losses)
            except Exception:
                continue
        print(f"Epoch {epoch + 1}/{args.epochs} loss={losses}")
    nlp.to_disk(args.out)
    print(f"saved model -> {args.out}")


if __name__ == "__main__":
    main()
