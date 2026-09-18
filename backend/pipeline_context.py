"""Pipeline context: all artifacts shared across the 12 stages."""

from . import datamodel as M


class PipelineContext:
    def __init__(self, doc_id, filename, raw_text="", raw_bytes=b"",
                 source="upload", model_versions=None):
        self.doc_id = doc_id
        self.filename = filename
        self.raw_text = raw_text or ""
        self.raw_bytes = raw_bytes or b""
        self.source = source  # upload | extension-url | extension-text
        self.model_versions = model_versions or {}

        self.blocks = []      # TextBlock
        self.sections = []    # Section
        self.entries = []     # Entry
        self.mentions = []    # DateMention
        self.assocs = []      # DateAssoc
        self.events = []      # Event
        self.unresolved = []  # entry ids with no usable date
        self.coverage = []    # unioned [start,end] intervals
        self.total_months = 0
        self.gaps = []        # Gap
        self.lineage = {}     # gap_id -> chain
        self.recruiter_output = {}
        self.stage_results = {}  # stage name -> StageResult
        self.meta = {}           # doc-level facts (pages, section_conf...)

    # lookup helpers (evidence lineage)
    def blocks_by_id(self):
        return {b.id: b for b in self.blocks}

    def entries_by_id(self):
        return {e.id: e for e in self.entries}

    def assocs_by_id(self):
        return {a.id: a for a in self.assocs}

    def mentions_by_id(self):
        return {m.id: m for m in self.mentions}

    def events_by_id(self):
        return {e.id: e for e in self.events}

    def entry_of_block(self, block_id):
        for e in self.entries:
            if block_id in e.block_ids:
                return e
        return None
