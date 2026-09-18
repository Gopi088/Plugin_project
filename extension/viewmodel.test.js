/* Node tests for the recruiter view-model adapter. Run: node extension/viewmodel.test.js */
const assert = require("assert");
const VM = require("./viewmodel.js");

const ev = (org, start, end, extra = {}) => ({
  id: `v-${org}`, type: "EMPLOYMENT", title: "Engineer", org,
  start, end, precision: "month", status: "CONFIRMED", confidence: 0.9, reasons: [], ...extra,
});
const gap = (start, end, months, conf, state = "POTENTIAL_GAP") => ({
  id: `g-${start}`, start: [2020, 1], end: [2021, 1], months, state,
  confidence: conf, reasons: ["GAP_NO_COVERAGE"], evidence: {},
  start_label: start, end_label: end,
});
const base = (timeline, gaps, extra = {}) => ({
  doc_id: "d", filename: "resume.pdf", candidate_name: "Test Person",
  status: "SUCCESS", timeline, gaps, unresolved_events: [],
  recruiter_overrides: [], disclaimer: "d", ...extra,
});

// verbal confidence bands
assert.deepStrictEqual(VM.verbalConfidence(0.9).label, "High confidence");
assert.deepStrictEqual(VM.verbalConfidence(0.6).label, "Needs review");
assert.deepStrictEqual(VM.verbalConfidence(0.2).label, "Low confidence");
assert.deepStrictEqual(VM.verbalConfidence(null).label, "Insufficient evidence");

// presentation priority: duration + confidence, configurable
assert.strictEqual(VM.presentationPriority(gap("a", "b", 6, 0.9)), "HIGH");
assert.strictEqual(VM.presentationPriority(gap("a", "b", 1, 0.9)), "LOW");
assert.strictEqual(VM.presentationPriority(gap("a", "b", 6, 0.2)), "LOW");
assert.strictEqual(VM.presentationPriority(gap("a", "b", 3, 0.6)), "REVIEW");
assert.strictEqual(
  VM.presentationPriority(gap("a", "b", 6, 0.9),
    { ...VM.attentionRules, minimumGapMonthsForHighAttention: 12 }),
  "REVIEW");

// clean resume -> CLEAR
let vm = VM.mapTimelineResultToRecruiterViewModel(
  base([ev("A", "2020-01", "2022-01")], [{ ...gap("x", "y", 0, 0.9, "NO_GAP_DETECTED") }]));
assert.strictEqual(vm.overallStatus, "CLEAR");
assert.strictEqual(vm.headline, "Timeline looks continuous");

// meaningful gap -> ATTENTION with dates + duration surfaced
vm = VM.mapTimelineResultToRecruiterViewModel(
  base([ev("A", "2020-01", "2022-01"), ev("B", "2022-07", "2023-01")],
    [gap("2022-01", "2022-07", 6, 0.9)]));
assert.strictEqual(vm.overallStatus, "ATTENTION");
assert.strictEqual(vm.highGaps.length, 1);
assert.strictEqual(vm.counts.potentialGaps, 1);

// no dated events -> INSUFFICIENT_EVIDENCE
vm = VM.mapTimelineResultToRecruiterViewModel(base([], [{ id: "g0", months: 0, state: "INSUFFICIENT_EVIDENCE", confidence: 0.4, reasons: [], evidence: {} }]));
assert.strictEqual(vm.overallStatus, "INSUFFICIENT_EVIDENCE");

// unresolved entries become review items, never raw dumps;
// undated projects are normal and stay out of the review list
vm = VM.mapTimelineResultToRecruiterViewModel(
  base([], [{ id: "g0", months: 0, state: "INSUFFICIENT_EVIDENCE", confidence: 0.4, reasons: [], evidence: {} }],
    { unresolved_events: [
      { id: "v8", type: "EMPLOYMENT", title: "Role X", entry_text: "raw stuff" },
      { id: "v9", type: "PROJECT", title: "P3", entry_text: "raw stuff" },
    ] }));
assert.strictEqual(vm.reviewItems.length, 1);
assert.strictEqual(vm.reviewItems[0].kind, "ENTRY");
assert.strictEqual(vm.reviewItems[0].title, "Role X");

// banned claims never produced by the adapter
const blob = JSON.stringify(vm).toLowerCase();
for (const b of VM.BANNED_CLAIMS) assert.ok(!blob.includes(b), b);

console.log("viewmodel.test.js: all assertions passed");
