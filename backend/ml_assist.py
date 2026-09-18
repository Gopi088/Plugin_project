"""Optional ML assist. Deterministic logic always decides; the spaCy
``model_timeline`` model (if present) only supplies hints, each recorded with
a *_ML_HINT reason and the model version. Never required, never trusted blindly.
"""

import os

_MODEL = None
_VERSION = "none"


def _load():
    global _MODEL, _VERSION
    if _MODEL is not None or _VERSION != "none":
        return
    try:
        import spacy
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        mp = os.path.join(base, "model_timeline")
        if os.path.isdir(mp):
            _MODEL = spacy.load(mp)
            try:
                _VERSION = f"model_timeline@{os.path.getmtime(mp):.0f}"
            except OSError:
                _VERSION = "model_timeline@1"
    except Exception:
        _MODEL = None


def version():
    _load()
    return _VERSION


def section_hints(text):
    """Return [(start, end, label)] NER hints or [] when model unavailable."""
    _load()
    if _MODEL is None:
        return []
    try:
        return [(e.start_char, e.end_char, e.label_)
                for e in _MODEL((text or "")[:20000]).ents]
    except Exception:
        return []
