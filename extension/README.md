# Resume Timeline extension (MV3)

Start `venv/bin/python backend/server.py`, then load `extension/` unpacked at
`chrome://extensions`. Enable **Allow access to file URLs** for local resumes.
After updating, reload the extension and reopen the resume.

Open the resume and click **Timeline**. In Chrome's native PDF viewer, use the
pinned extension icon: it analyzes the open file automatically. **Open timeline**
opens the results side panel, without a second resume tab. Manual upload and URL
entry remain under **Analyze another resume**.

Overview, Timeline and Needs review tabs organize the original card layout.
The timeline is grouped by year with a vertical line and event markers.
Cards show roles, dates and review/eye/evidence actions; source details expand on demand. Only ambiguous dates or missing dates on actual employment entries need review.
An undated degree and valid month/year dates do not create review items.
An empty Needs review tab is hidden. Detected periods appear at the top with
dates, duration and the two bounding employers; employment-only findings are
labeled as gaps in listed employment.
**View in Resume** highlights original HTML offsets, existing PDF.js page
coordinates without navigating, reloading, or rendering a copy. The button only
reports success after the existing viewer confirms a highlight. Chrome's built-in
PDF viewer uses optional `debugger` access (Chrome 125+). On the first PDF click,
choose **Enable live PDF highlighting** and accept Chrome's permission prompt.
The extension attaches only to the bound resume tab, highlights its original PDF
text and disconnects immediately. A temporary Chrome debugging banner is normal.
It does not navigate, reload, or open another document. Declining permission leaves
the resume unchanged; unsupported viewer versions show an explicit error. Missing or stale
source locations produce a message instead of an approximate text match.

Use the reviewed checkbox and eye icon to track review and hide/show information.
One collapsed general notes section saves the recruiter's name, text, date and time. Notes,
review state and hidden items persist across refresh/reanalysis of identical
contents. Repeated legacy notes are grouped under collapsed Earlier notes without deleting
the original records or timestamps. Local drafts survive a failed save.

The popup's **Evaluation accuracy** reports labeled-set mean F1, case count and
date. It is not the verified accuracy of the currently opened resume.

Permissions: `activeTab`/`scripting` support page integration; `sidePanel` hosts
results beside native PDFs; `storage` holds settings, document bindings and note
drafts; `contextMenus`/`webNavigation` support document detection. HTTP/HTTPS and
file host permissions allow the worker to read the requested resume and contact
the configured backend. Online document reads include browser credentials.

## Full resume workspace

The popup's **Resume editor & PDF export** link opens the full management
workspace on the configured project backend. This adds Matcher upload, all-section
editing, custom sections, category-filtered timelines and template PDF downloads.
Matcher runs separately on port 8001; the extension's original evidence workflow
continues to use the existing twelve-stage backend. See [workspace details](../web/README.md).

The panel header shows the loaded extension version (currently **1.1.3**). If
Chrome still shows the old viewer error without this version, update/reload the
loaded extension folder and reopen its panel. Native PDF routing works from both
the in-page Timeline panel and the side panel, including when an older content
script replies with a generic unsupported-source message.

Results display **Evaluation accuracy**, fetched from `/api/quality`, with the
labeled test count and evaluation date. This is the measured benchmark F1 score,
not a claim that the current candidate's resume is independently verified. If
no valid report is available, the UI says unavailable rather than inventing a
percentage.
