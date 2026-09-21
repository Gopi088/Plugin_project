"""Resume profile: timeline gaps + positives/negatives + JD fit (cosine).

Usage:
    venv/bin/python scripts/profile.py <resume.pdf> [--jd <jd.pdf|jd.txt>] [--json out.json]

Output: timeline (graduation/jobs/gaps/totals), positives[], negatives[],
        fit {score 0-100, matched/missing skills, verdict} when --jd is given.
No new dependencies (pure-python cosine).
"""

import argparse
import json
import math
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.timeline import analyze_resume_timeline  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_stop():
    try:
        with open(os.path.join(BASE_DIR, "backend", "data", "cues.json"), encoding="utf-8") as fh:
            return set(json.load(fh).get("stop_words", []))
    except Exception:
        return set("and or the a an of to in for with on as at by from is are was were be been".split())


STOP = _load_stop()

def _load_vocab():
    """Shared skill vocabulary (backend/data/skills.json); falls back to built-in."""
    try:
        with open(os.path.join(BASE_DIR, "backend", "data", "skills.json"), encoding="utf-8") as fh:
            return [s.lower() for s in json.load(fh)]
    except Exception:
        return [
            "python", "java", "javascript", "typescript", "sql",
            "aws", "azure", "gcp", "docker", "kubernetes", "jenkins",
            "react", "angular", "node.js", "spring", "spring boot", "microservices",
            "hibernate", "rest", "kafka", "spark", "hadoop", "airflow",
            "mongodb", "mysql", "postgresql", "redis",
            "llm", "rag", "langchain", "embeddings", "huggingface", "faiss", "pinecone",
            "mlops", "devops", "mlflow", "github", "jira", "ci/cd", "terraform",
            "fastapi", "django", "flask", "html", "css", "git", "maven",
        ]


SKILL_VOCAB = _load_vocab()


def _norm(text):
    if not text:
        return text
    text = text.replace("So\x00ware", "Software").replace("so\x00ware", "software")
    text = text.replace("Pro\x00cient", "Proficient").replace("pro\x00ciency", "proficiency")
    text = text.replace("con\x00g", "config").replace("Con\x00g", "Config")
    text = re.sub(r"(?<![A-Za-z])\x00x(?![A-Za-z])", "fix", text)
    text = text.replace("\x00", "ti")
    text = text.replace("\u2022", "•").replace("\uf0b7", "•").replace("\uf0a7", "•").replace("", "•")
    return text


def read_text(path):
    if path.lower().endswith(".pdf"):
        import pdfplumber
        out = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                out.append(page.extract_text() or "")
        return _norm("\n".join(out))
    if path.lower().endswith(".docx"):
        from docx import Document
        return _norm("\n".join(p.text for p in Document(path).paragraphs))
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return _norm(fh.read())


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9+#./]+", (text or "").lower()) if t not in STOP and len(t) > 1]


def cosine(a, b):
    ca, cb = Counter(tokens(a)), Counter(tokens(b))
    if not ca or not cb:
        return 0.0
    inter = set(ca) & set(cb)
    dot = sum(ca[t] * cb[t] for t in inter)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb) if na and nb else 0.0


def resume_skills(text):
    low = (text or "").lower()
    found = set()
    for s in SKILL_VOCAB:
        if re.search(r"(?<![a-z0-9+#])" + re.escape(s) + r"(?![a-z0-9+#])", low):
            found.add(s)
    return found


def jd_skills(text):
    return resume_skills(text)


def pros_cons(tl, text):
    pos, neg = [], []
    jobs = tl.get("jobs", [])
    total = tl.get("total_experience_months", 0)
    gaps = tl.get("job_gaps", [])
    grad_gap = tl.get("graduation_to_first_job_months")
    proj = tl.get("projects", {})

    if total >= 60:
        pos.append(f"Strong total experience: {total // 12}y {total % 12}m.")
    elif total >= 24:
        pos.append(f"Decent total experience: {total // 12}y {total % 12}m.")
    elif not jobs and re.search(r"undergraduate|student|fresher|simulation|intern|cgpa", text, re.IGNORECASE):
        pos.append("Entry-level profile: hands-on project/simulation experience (no dated full-time roles).")
    else:
        neg.append(f"Low total experience: {total}m.")

    big_gaps = [g for g in gaps if g["gap_months"] > 3]
    overlaps = [g for g in gaps if g["gap_months"] < 0]
    if not big_gaps and jobs:
        pos.append("No career gaps over 3 months between jobs.")
    for g in big_gaps:
        neg.append(f"Gap of {g['gap_months']} months: '{g['from']}' -> '{g['to']}'.")
    for g in overlaps:
        neg.append(f"Overlapping jobs ({abs(g['gap_months'])}m): '{g['from']}' <-> '{g['to']}' (moonlighting/contract?).")

    if grad_gap is not None:
        if grad_gap <= 6:
            pos.append(f"Smooth college-to-job transition ({grad_gap}m after graduation).")
        elif grad_gap > 6:
            neg.append(f"Late career start: first job {grad_gap}m after graduation ({tl['graduation']['date']}).")
    elif not tl.get("graduation"):
        neg.append("No graduation date found — education section unclear.")

    short = [j for j in jobs if j.get("duration_months", 0) < 12]
    stable = [j for j in jobs if j.get("duration_months", 0) >= 24]
    if stable:
        pos.append(f"Stable tenure ({len(stable)} role(s) >= 2 years).")
    for j in short:
        neg.append(f"Short stint ({j.get('duration_months', 0)}m): '{j.get('title')}' @ '{j.get('company')}' — job-hopping risk.")

    if proj.get("unexplained", 0) > 0:
        neg.append(f"Claims {proj.get('claimed')} projects but describes {proj.get('described')} — {proj.get('unexplained')} unexplained.")
    elif proj.get("described", 0) >= 2:
        pos.append(f"Good project evidence: {proj['described']} projects described.")

    skills = resume_skills(text)
    hot = {"llm", "rag", "langchain", "aws", "docker", "kubernetes", "python"}
    hit = sorted(skills & hot)
    if hit:
        pos.append(f"In-demand skills: {', '.join(hit)}.")
    if len(skills) < 5:
        neg.append("Few recognizable skills extracted — resume may lack keywords.")
    return pos, neg


def fit_score(resume_text, jd_text):
    r_sk = resume_skills(resume_text)
    j_sk = jd_skills(jd_text)
    if not j_sk:
        return {"score": 0, "verdict": "Weak fit",
                "reason": "No known skills found in JD; check JD file.",
                "matched_skills": [], "missing_skills": [], "text_cosine": 0.0, "skill_cosine": 0.0}
    matched = sorted(r_sk & j_sk)
    missing = sorted(j_sk - r_sk)
    # skill cosine over skill-token strings
    s_cos = cosine(" ".join(r_sk), " ".join(j_sk))
    t_cos = cosine(resume_text, jd_text)
    score = round(100 * (0.7 * s_cos + 0.3 * t_cos), 1)
    verdict = "Strong fit" if score >= 60 else ("Partial fit" if score >= 35 else "Weak fit")
    return {"score": score, "verdict": verdict,
            "matched_skills": matched, "missing_skills": missing,
            "text_cosine": round(t_cos, 3), "skill_cosine": round(s_cos, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("resume")
    ap.add_argument("--jd", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    resume_text = read_text(args.resume)
    tl = analyze_resume_timeline(resume_text)
    pos, neg = pros_cons(tl, resume_text)

    out = {"resume": os.path.basename(args.resume),
           "timeline": tl, "positives": pos, "negatives": neg}
    if args.jd:
        jd_text = read_text(args.jd)
        out["fit"] = fit_score(resume_text, jd_text)
        out["fit"]["jd"] = os.path.basename(args.jd)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
        print(f"\nsaved -> {args.json}")


if __name__ == "__main__":
    main()
