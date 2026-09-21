"""Convert dataset/resumes/* -> dataset/text/*.txt (incremental).

    venv/bin/python scripts/convert_corpus.py [--force]

PDF via pdfplumber, DOCX via python-docx, legacy DOC via antiword.
Skips files whose .txt already exists unless --force is given.
"""
import argparse
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_DIR = os.path.join(BASE, "dataset", "resumes")
OUT_DIR = os.path.join(BASE, "dataset", "text")


def pdf_text(path):
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def docx_text(path):
    from docx import Document
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:  # content often lives in table cells
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(t for t in parts if t.strip())


def doc_text(path):
    r = subprocess.run(["antiword", path], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"antiword failed: {r.stderr[:200]!r}")
    text = ""
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = r.stdout.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text.strip():
        raise RuntimeError("empty extraction")
    return text


def iter_inputs():
    """Yield (src_path, stem) recursively; subfolder files get prefixed stems."""
    for root, _dirs, files in os.walk(IN_DIR):
        for f in sorted(files):
            src = os.path.join(root, f)
            rel = os.path.relpath(src, IN_DIR)
            stem, ext = os.path.splitext(rel)
            flat = stem.replace(os.sep, "__")
            yield src, flat, ext


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    ok, skipped, failed = 0, 0, []
    for src, flat, ext in iter_inputs():
        dst = os.path.join(OUT_DIR, flat + ".txt")
        if os.path.exists(dst) and not args.force:
            skipped += 1
            continue
        try:
            ext = ext.lower()
            if ext == ".pdf":
                text = pdf_text(src)
            elif ext == ".docx":
                text = docx_text(src)
            elif ext == ".doc":
                text = doc_text(src)
            else:
                skipped += 1
                continue
            if not text.strip():
                raise RuntimeError("empty extraction")
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(text)
            ok += 1
        except Exception as exc:
            failed.append((os.path.relpath(src, IN_DIR), str(exc)[:120]))
    print(f"converted={ok} skipped={skipped} failed={len(failed)}")
    for f, e in failed:
        print(f"  FAIL {f}: {e}")


if __name__ == "__main__":
    main()
