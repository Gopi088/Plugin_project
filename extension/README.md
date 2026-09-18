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

## Recruiter UI (attention-first)

The panel consumes a recruiter view-model (`viewmodel.js`), never raw DTOs:

- **Summary card** — CLEAR / ATTENTION / REVIEW / insufficient-evidence, with
  candidate name, headline, and counts. Understood in ~5 seconds.
- **Tabs** — Overview (attention items only) · Timeline (visual vertical
  timeline, year-grouped, expandable cards) · Review (badge-counted).
- **Gap cards** — status → dates → duration; confidence verbalized
  (High confidence / Needs review / Low confidence); numeric detail hidden in
  Advanced. Presentation priority (HIGH/REVIEW/LOW) comes from configurable
  `attentionRules` (duration + confidence) — backend results stay source of truth.
- **Review cards** — one per ambiguous/unresolved finding, never a text dump.
- **Evidence drawer** — Why? (bounding activities) + resume quotes with page
  numbers, date mentions, association status; numeric confidence under Advanced.
- **Actions** — Confirm / Mark as explained / Needs follow-up / Dismiss, each
  with optional note, stored as feedback (evidence itself is never modified).
- Footer disclaimer stays subtle; status is always icon + label + color;
  `Esc` closes; all styling via `--status-*` design tokens.

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
