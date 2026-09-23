# Resume workspace

The workspace uses the existing Python server and native browser modules (no
frontend build or new framework). Open `http://127.0.0.1:8000/workspace/`, or choose
**Resume editor & PDF export** from the extension popup.

`RESUME_PARSER_API_URL` defaults to `http://localhost:8001/api/v1`. The server reads
it from the process environment first, then the project `.env.local`. Resume
Matcher must be running with its document parser and a configured model. Its
frontend/Playwright renderer must also be available for PDF export.

The same-origin `/api/resume-manager/` adapter supports upload, list, fetch,
update and PDF download. It preserves upstream errors and PDF response headers.
The installed API uses a **list** of section metadata, whereas the supplied plan
uses an order/visibility object; both are accepted at the boundary. The installed
upload route rejects TXT, so UTF-8 TXT is converted to a plain DOCX before upload.
Both the browser and server enforce the original 4 MB limit. DOC/PDF/DOCX parsing
and model structuring/month restoration are performed by Resume Matcher.

All standard fields and custom text, string-list and item-list sections can be
edited. Sections can be added, removed, reordered or hidden in exports. Matcher
is the authority for saved records; IndexedDB keeps unsaved drafts and the first
available parser-source text across refresh. Failed saves leave the draft intact.
Save before exporting: downloads render the persisted version, with the selected
template, page size, four margins, spacing, line height, font size and accent.

The structured timeline combines experience, education and projects. It sorts
current items first, then newest dates, with stable IDs and undated items last.
The plan's `1970-01` and January defaults are intentionally not used. Year-only
dates remain year-only; absent end dates do not mean Present; durations require
month-level endpoints. Raw dates are always shown. Model output and edited data
are not labeled as verified original-document evidence.

The existing twelve-stage recruiter pipeline, original-resume highlighting,
gap detection, reviewed/eye controls and notes remain separate and unchanged.
This integration does not replace that pipeline with an LLM.

Contracts: `types/resume.ts`. Transport: `services/resumeService.js`.
Persistence: `services/resumeStore.js`. Dates: `utils/timelineExtractor.js`.

Run regression tests from the project root:

```bash
node web/workspace.test.js
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m unittest tests.test_matcher_workspace
```

The browser test covers uploading, every custom section type, edits, save,
PDF download, filters, responsive layout and draft recovery. It uses an isolated
Matcher fixture; live service verification is separate so routine tests do not
invoke a model or alter user resumes.
