# Extension — Resume Timeline & Gap Detection (MV3)

## Install (Chrome/Edge, developer mode)

1. Start the backend: `venv/bin/python backend/server.py` (serves `127.0.0.1:8000`).
2. Open `chrome://extensions`, enable **Developer mode** → **Load unpacked** → select `extension/`.
3. Pin the action; set the API base in the popup if your backend differs.

## Recruiter flow (no manual start needed)

Open resume → pill appears → click **Timeline** → panel auto-detects and analyzes → timeline + unrepresented periods with confidence, reasons, and resume quotes.

Detection, in order: PDF/DOCX file URL → embedded PDF → ATS/HTML resume text
(Experience + Education + dates) → resume link on page. Otherwise the popup
offers file upload or URL submit. The original page is never modified — the UI
is a dismissible side dock.

## Review / override

- **Evidence** expands the full chain: event → entry → date association → date
  mention (original text) → text block/page.
- **Dismiss** records recruiter feedback; dismissed gaps reload as
  `DISMISSED_GAP` (audit trail in backend `feedback` table).

## Permissions rationale

`activeTab` + `scripting` (inject dock), `storage` (API base, last doc),
`contextMenus` (analyze link), `webNavigation` (badge on PDF/DOCX pages),
`host_permissions` limited to `127.0.0.1:8000`/`localhost:8000` (backend only —
resume URLs are fetched server-side, so no broad host access is needed).
No data leaves the machine except recruiter-initiated backend calls.
