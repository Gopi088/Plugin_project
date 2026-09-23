"""Evidence & confidence framework (used by stage 11).

Lineage chain (every gap must resolve through it):
    Gap -> Event(s) -> Entry -> Date Association -> Date Mention
        -> Text Block -> Original Resume

Confidence rule (documented, deterministic):
  - each link carries a 0..1 link confidence;
  - chain confidence = product of link confidences;
  - ambiguity penalties: AMBIGUOUS assoc x0.7, UNRESOLVED x0.4,
    year-precision x0.85, ML-hint section x0.9;
  - gap confidence = min(bounding-event confidences) x coverage factor,
    where coverage factor = 1.0 when both bounds exist, 0.6 when the gap
    touches the analysis boundary (open-ended).
"""

from .source import locations

AMBIGUITY_PENALTY = {"CONFIRMED": 1.0, "AMBIGUOUS": 0.7, "UNRESOLVED": 0.4}
PRECISION_PENALTY = {"month": 1.0, "year": 0.85}


def chain_confidence(link_confidences):
    c = 1.0
    for v in link_confidences:
        c *= max(0.0, min(1.0, v))
    return round(c, 3)


def event_confidence(assoc_status, precision, section_conf=1.0, ml_hint=False):
    c = (AMBIGUITY_PENALTY.get(assoc_status, 0.4)
         * PRECISION_PENALTY.get(precision, 0.85)
         * section_conf * (0.9 if ml_hint else 1.0))
    return round(c, 3)


def gap_confidence(conf_before, conf_after, bounded_both_sides=True):
    base = min(conf_before if conf_before else 0.5,
               conf_after if conf_after else 0.5)
    factor = 1.0 if bounded_both_sides else 0.6
    return round(base * factor, 3)


def lineage(gap, events_by_id, entries_by_id, assocs_by_id,
            mentions_by_id, blocks_by_id, doc_id):
    """Build the Gap -> ... -> Resume chain as nested dicts with quotes."""
    chain = {"gap_id": gap.id, "doc_id": doc_id, "links": []}
    for eid in (gap.evidence.get("event_before"),
                gap.evidence.get("event_after")):
        if not eid or eid not in events_by_id:
            continue
        ev = events_by_id[eid]
        link = {"event": ev.to_dict()}
        ent = entries_by_id.get(ev.entry_id)
        if ent is not None:
            link["entry"] = ent.to_dict()
            blk_texts = [blocks_by_id[b].text for b in ent.block_ids
                         if b in blocks_by_id]
            link["text_blocks"] = [
                {"block_id": b, "text": blocks_by_id[b].text,
                 "page": blocks_by_id[b].page,
                 "source": locations(blocks_by_id[b])}
                for b in ent.block_ids if b in blocks_by_id]
            anchored = [loc["text"] for loc in getattr(ev, "source", {}).get("entry", [])]
            link["entry_quote"] = " ".join(anchored or blk_texts)[:500]
        assocs = [assocs_by_id[a] for a in ev.assoc_ids if a in assocs_by_id]
        link["associations"] = [a.to_dict() for a in assocs]
        link["mentions"] = [mentions_by_id[a.mention_id].to_dict()
                            for a in assocs if a.mention_id in mentions_by_id]
        chain["links"].append(link)
    return chain
