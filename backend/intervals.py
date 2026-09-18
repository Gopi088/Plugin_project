"""Stage 9 engine: deterministic interval & coverage analysis.

Events are month-resolution intervals [start, end] inclusive. Overlapping
events are unioned (never double-counted, never treated as errors).
Year-precision dates expand to Jan..Dec of that year.
"""

from .dates import month_index


def normalize_interval(start, end, precision="month"):
    """Expand year-precision bounds to full-year coverage."""
    if precision == "year":
        return ((start[0], 1), (end[0], 12))
    return (start, end)


def union(intervals):
    """Merge overlapping/adjacent [start,end] month intervals (inclusive)."""
    if not intervals:
        return []
    pts = sorted(intervals, key=lambda iv: month_index(iv[0]))
    merged = [pts[0]]
    for s, e in pts[1:]:
        ls, le = merged[-1]
        if month_index(s) <= month_index(le) + 1:  # overlap or adjacency
            if month_index(e) > month_index(le):
                merged[-1] = (ls, e)
        else:
            merged.append((s, e))
    return merged


def total_months(intervals):
    """Inclusive month count of (already unioned) intervals."""
    return sum(month_index(e) - month_index(s) + 1 for s, e in intervals)


def uncovered(covered, span_start, span_end):
    """Gaps in coverage within [span_start, span_end] given unioned coverage."""
    gaps = []
    cursor = span_start
    for s, e in union(covered):
        if month_index(s) > month_index(cursor):
            gaps.append((cursor, (s[0], s[1] - 1) if s[1] > 1 else (s[0] - 1, 12)))
        if month_index(e) >= month_index(cursor):
            em = e[1] + 1
            ey = e[0] + (1 if em == 13 else 0)
            cursor = (ey, 1 if em == 13 else em)
    if month_index(cursor) <= month_index(span_end):
        gaps.append((cursor, span_end))
    return gaps


def span_of(intervals):
    ss = min(intervals, key=lambda iv: month_index(iv[0]))[0]
    ee = max(intervals, key=lambda iv: month_index(iv[1]))[1]
    return (ss, ee)
