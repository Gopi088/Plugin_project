"""Central vocabulary/config loader. All pipeline word lists live in
``backend/data/cues.json`` (override via RT_CUES_PATH) so tuning never
requires code changes.
"""
import json
import os

_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cues.json")
_cache = {}


def load(path=None):
    p = path or os.environ.get("RT_CUES_PATH", _DEFAULT)
    if p not in _cache:
        with open(p, encoding="utf-8") as fh:
            _cache[p] = json.load(fh)
    return _cache[p]


def clear_cache():
    _cache.clear()
