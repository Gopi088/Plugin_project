/* Recruiter view-model adapter (pure functions, no chrome APIs).
   The UI consumes this model — never backend DTOs directly.
   Backend DTOs remain the source of truth; this layer only decides
   PRESENTATION PRIORITY. Usable in browser (global RT_VM) and node. */
var RT_VM = (() => {
  // Tunable by the product team after evaluation — NOT business truth.
  const attentionRules = {
    minimumGapMonthsForHighAttention: 4,
    minimumConfidenceForHighAttention: 0.7,
    minorGapMonths: 2,
    lowConfidenceThreshold: 0.5,
  };

  // Phrases that must never reach a recruiter as a system claim.
  const BANNED_CLAIMS = [
    "was unemployed",
    "is unemployed",
    "unemployment confirmed",
    "employment gap confirmed",
    "bad career history",
    "red flag candidate",
  ];

  const TYPE_ICON = {
    EMPLOYMENT: "💼",
    EDUCATION: "🎓",
    INTERNSHIP: "🧑‍💻",
    PROJECT: "📁",
    OTHER: "📄",
  };

  function verbalConfidence(c) {
    if (c === null || c === undefined) return { label: "Insufficient evidence", level: "unknown" };
    if (c >= 0.75) return { label: "High confidence", level: "high" };
    if (c >= 0.5) return { label: "Needs review", level: "review" };
    return { label: "Low confidence", level: "low" };
  }

  function fmtRange(start, end) {
    const f = (s) => (s && s.length >= 7 ? s.slice(0, 7) : s || "?");
    return { start: f(start), end: f(end) };
  }

  // Presentation priority for a POTENTIAL_GAP. Duration + confidence +
  // upstream uncertainty only — never candidate judgement.
  function presentationPriority(gap, rules = attentionRules) {
    const months = gap.months || 0;
    const conf = gap.confidence ?? 0;
    if (months >= rules.minimumGapMonthsForHighAttention &&
        conf >= rules.minimumConfidenceForHighAttention) return "HIGH";
    if (months <= rules.minorGapMonths || conf < rules.lowConfidenceThreshold) return "LOW";
    return "REVIEW";
  }

  function tidyFilename(name) {
    return String(name || "Resume")
      .replace(/\.(pdf|docx?|txt)$/i, "")
      .replace(/[_+]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 60);
  }

  function mapTimelineResultToRecruiterViewModel(dto, rules = attentionRules) {
    const events = (dto.timeline || []).map((e) => ({
      ...e,
      icon: TYPE_ICON[e.type] || TYPE_ICON.OTHER,
      range: fmtRange(e.start, e.end),
      confidenceVerbal: verbalConfidence(e.confidence),
    }));
    const gaps = (dto.gaps || []).map((g) => ({
      ...g,
      range: g.start ? fmtRange(g.start_label || String(g.start), g.end_label || String(g.end)) : null,
      confidenceVerbal: verbalConfidence(g.confidence),
      priority: g.state === "POTENTIAL_GAP" ? presentationPriority(g, rules) : null,
    }));

    const active = gaps.filter((g) => g.state === "POTENTIAL_GAP" && !g.dismissed_by_recruiter);
    const high = active.filter((g) => g.priority === "HIGH");
    const reviewOnly = active.filter((g) => g.priority === "REVIEW");
    const lowOnly = active.filter((g) => g.priority === "LOW");
    const dismissed = gaps.filter((g) => g.dismissed_by_recruiter || g.state === "DISMISSED_GAP");

    const reviewItems = [];
    // Undated projects/education are normal (not ambiguous) — only surface
    // employment-type entries whose dates are missing.
    for (const e of dto.unresolved_events || []) {
      if (e.type === "PROJECT" || e.type === "EDUCATION") continue;
      reviewItems.push({
        kind: "ENTRY", title: e.title || e.org || "Undated entry",
        detail: "Employment dates unclear — could not be reliably associated.",
        event: e,
      });
    }
    for (const e of events.filter((e) => e.status === "AMBIGUOUS")) {
      reviewItems.push({
        kind: "DATE", title: e.title || "Dated entry",
        detail: "Date could not be reliably associated with this entry.",
        event: e,
      });
    }
    for (const g of active.filter((g) => g.priority === "LOW")) {
      reviewItems.push({
        kind: "GAP", title: `Possible short period (${g.months} mo)`,
        detail: "Weak evidence or minor duration — kept for completeness.",
        gap: g,
      });
    }

    let overallStatus, headline, summary;
    if (dto.status === "FAILED") {
      overallStatus = "REVIEW";
      headline = "Unable to build timeline";
      summary = "The resume could not be processed reliably.";
    } else if (events.length === 0) {
      overallStatus = "INSUFFICIENT_EVIDENCE";
      headline = "Timeline needs review";
      summary = "Some dates could not be confidently interpreted.";
    } else if (high.length > 0) {
      overallStatus = "ATTENTION";
      headline = "Attention needed";
      summary = `${high.length} potential unrepresented period${high.length > 1 ? "s" : ""}`;
    } else if (reviewOnly.length > 0 || reviewItems.length > 0) {
      overallStatus = "REVIEW";
      headline = reviewOnly.length ? "Potential period to review" : "Timeline needs review";
      summary = reviewOnly.length
        ? `${reviewOnly.length} potential unrepresented period${reviewOnly.length > 1 ? "s" : ""}`
        : "Some findings need a human look.";
    } else {
      overallStatus = "CLEAR";
      headline = "Timeline looks continuous";
      summary = "No meaningful issue requiring attention.";
    }

    return {
      overallStatus, headline, summary,
      candidateName: dto.candidate_name || tidyFilename(dto.filename),
      filename: dto.filename,
      docStatus: dto.status,
      disclaimer: dto.disclaimer,
      counts: {
        events: events.length,
        potentialGaps: active.length,
        reviewItems: reviewItems.length + reviewOnly.length,
      },
      highGaps: high,
      reviewGaps: reviewOnly,
      lowGaps: lowOnly,
      dismissedGaps: dismissed,
      insufficient: gaps.filter((g) => g.state === "INSUFFICIENT_EVIDENCE"),
      noGap: gaps.some((g) => g.state === "NO_GAP_DETECTED"),
      timelineEvents: events,
      reviewItems,
      decisions: dto.recruiter_overrides || [],
    };
  }

  return {
    attentionRules, BANNED_CLAIMS, TYPE_ICON,
    verbalConfidence, presentationPriority,
    mapTimelineResultToRecruiterViewModel, tidyFilename,
  };
})();

if (typeof module !== "undefined" && module.exports) module.exports = RT_VM;
