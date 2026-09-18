"""CLI: timeline analysis for one resume (pdf/docx/txt) or a corpus sweep.

Usage:
    ./venv/bin/python scripts/analyze_timeline.py <resume.pdf|resume.txt> [--show-entities]
    ./venv/bin/python scripts/analyze_timeline.py --sweep dataset/text
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.timeline import analyze_resume_timeline  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_text(path):
    if path.endswith(".pdf"):
        import pdfplumber
        out = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                out.append(page.extract_text() or "")
        return "\n".join(out)
    if path.endswith(".docx"):
        from docx import Document
        return "\n".join(p.text for p in Document(path).paragraphs)
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("resume", nargs="?")
    ap.add_argument("--sweep", default="")
    ap.add_argument("--show-entities", action="store_true")
    args = ap.parse_args()

    nlp = None
    if args.show_entities:
        import spacy
        mp = os.path.join(BASE_DIR, "model_timeline")
        if os.path.isdir(mp):
            nlp = spacy.load(mp)

    if args.sweep:
        files = sorted(f for f in os.listdir(args.sweep) if f.endswith(".txt"))
        n_grad = n_job = 0
        for f in files:
            with open(os.path.join(args.sweep, f), encoding="utf-8", errors="ignore") as fh:
                r = analyze_resume_timeline(fh.read())
            n_grad += bool(r["graduation"])
            n_job += bool(r["jobs"])
        print(f"files={len(files)} with_graduation={n_grad} "
              f"({100.0 * n_grad / max(1, len(files)):.1f}%) "
              f"with_jobs={n_job} ({100.0 * n_job / max(1, len(files)):.1f}%)")
        return

    if not args.resume:
        ap.error("provide <resume> or --sweep")
    text = read_text(args.resume)
    result = analyze_resume_timeline(text)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if nlp is not None:
        print("\n--- model_timeline entities (first 20) ---")
        for ent in nlp(text[:20000]).ents[:20]:
            print(f"{ent.label_}: {ent.text[:80]}")


if __name__ == "__main__":
    main()
