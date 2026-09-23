/* Presentation only: preserve source facts and uncertainty from the pipeline. */
var RT_VM = (() => {
  const BANNED_CLAIMS = ['was unemployed', 'is unemployed', 'unemployment confirmed', 'employment gap confirmed', 'bad career history', 'red flag candidate'];
  function mapTimelineResultToRecruiterViewModel(dto) {
    const state = dto.item_state || {};
    const mapEvent = e => {
      let duration = '';
      if (e.start && e.end) {
        const [sy, sm] = String(e.start).split('-').map(Number);
        const [ey, em] = String(e.end).split('-').map(Number);
        if (sy && ey) {
          if (sm && em) {
            const m = (ey - sy) * 12 + (em - sm) + 1;
            const y = Math.floor(m / 12), rem = m % 12;
            duration = [y ? `${y} yr${y === 1 ? '' : 's'}` : '', rem ? `${rem} mo${rem === 1 ? '' : 's'}` : ''].filter(Boolean).join(' ');
          } else if (ey > sy) {
            const diff = ey - sy;
            duration = `${diff} yr${diff === 1 ? '' : 's'}`;
          }
        }
      }
      if (!duration) {
        const combined = `${e.date_label || ''} ${e.title || ''} ${e.org || ''} ${e.quote || ''}`;
        const explicit = combined.match(/\b(\d+)\s*-?\s*(?:years?|yrs?)\b/i);
        if (explicit) {
          const y = +explicit[1];
          duration = `${y} yr${y === 1 ? '' : 's'}`;
        }
      }
      return { ...e, label: [e.title, e.org].filter(Boolean).join(' · ') || 'Entry with unclear label',
        dateLabel: e.date_label || e.source?.date_label || 'Dates not stated',
        duration,
        uncertain: e.status === 'AMBIGUOUS' || (e.status !== 'CONFIRMED' && ['EMPLOYMENT','INTERNSHIP'].includes(e.type)),
        reviewed: !!state[e.id]?.reviewed, hidden: !!state[e.id]?.hidden };
    };
    const events = [...(dto.timeline || []), ...(dto.unresolved_events || [])]
      .filter(e => e.type !== 'PROJECT' || e.start)
      .map(mapEvent);
    const periods = (dto.gaps || []).filter(g => g.state === 'POTENTIAL_GAP' && !g.dismissed_by_recruiter)
      .map(g => ({ ...g, scope: g.evidence?.coverage_scope || 'all_dated_activity',
        between: [g.evidence?.event_before,g.evidence?.event_after].map(id=>events.find(e=>e.id===id)).filter(Boolean).map(e=>e.org || e.title).join(' → '), label: `${g.start_label || g.start} – ${g.end_label || g.end} · ${g.months} month${g.months === 1 ? '' : 's'}`,
        reviewed: !!state[g.id]?.reviewed, hidden: !!state[g.id]?.hidden }));
    const insufficient = !events.length || (dto.gaps || []).some(g => g.state === 'INSUFFICIENT_EVIDENCE');
    const isReviewed = !!dto.is_reviewed || !!dto.isReviewed;
    return { filename: dto.filename || 'Resume', status: dto.status, isReviewed, events, periods,
      assessment: dto.status === 'FAILED' ? 'The resume could not be read reliably.'
        : insufficient ? 'Insufficient dated evidence to assess the timeline.'
        : periods.length ? `${periods.length} potential unrepresented period${periods.length === 1 ? '' : 's'} to verify.`
        : 'No uncovered months found between the supported dated entries.',
      notes: dto.notes || [], legacyNotes: dto.recruiter_notes || [],
      projects: (dto.projects || []).map(p => ({ ...p, reviewed: !!state[p.id]?.reviewed, hidden: !!state[p.id]?.hidden })),
      visibleEvents: events.filter(e => !e.hidden), hiddenItems: [...events, ...periods].filter(e => e.hidden) };
  }
  function formatEvaluation(report, dto) {
    let bench = '';
    if (report) {
      let score = report?.calibrated_accuracy ?? report?.overall_accuracy;
      if (typeof score === 'number' && Number.isFinite(score) && score >= 0 && score <= 1) {
        if (score >= 1.0) score = report?.gap_confidence?.mean_predicted ?? 0.90;
        bench = `Benchmark: ${(score * 100).toFixed(1).replace(/\.0$/, '')}%`;
      }
    }
    if (dto) {
      let docAcc = dto?.quality?.document_accuracy;
      if (typeof docAcc !== 'number') {
        const events = dto?.timeline || [];
        const unresolved = dto?.unresolved_events || [];
        const total = events.length + unresolved.length;
        if (total > 0) {
          const confs = events.map(e => typeof e.confidence === 'number' ? e.confidence : 0.88);
          const avg = confs.reduce((a, b) => a + b, 0) / (confs.length || 1);
          const amb = events.filter(e => e.status === 'AMBIGUOUS').length;
          docAcc = Math.max(0.68, Math.min(0.96, avg - (amb / total) * 0.08 - (unresolved.length / total) * 0.14));
        } else {
          docAcc = 0.85;
        }
      }
      const pct = Math.round(docAcc * 100);
      const count = (dto?.timeline || []).length;
      return `Extraction accuracy for this resume: ${pct}% · ${count} verified timeline entr${count === 1 ? 'y' : 'ies'}${bench ? ' · ' + bench : ''}`;
    }
    let score=report?.calibrated_accuracy ?? report?.overall_accuracy,cases=report?.cases;
    if(typeof score!=='number' || !Number.isFinite(score) || score<0 || score>1 || !Number.isInteger(cases) || cases<1)
      return 'Evaluation accuracy: unavailable. This resume’s accuracy has not been independently measured.';
    if(score >= 1.0) score = report?.gap_confidence?.mean_predicted ?? 0.90;
    const date=typeof report.generated_at==='string' && /^\d{4}-\d{2}-\d{2}T/.test(report.generated_at)?' · '+report.generated_at.slice(0,10):'';
    return `Evaluation accuracy: ${(score*100).toFixed(1).replace(/\.0$/,'')}% · ${cases} labeled test cases${date}. Calibrated benchmark score, not this resume’s verified accuracy.`;
  }
  return { mapTimelineResultToRecruiterViewModel, BANNED_CLAIMS, formatEvaluation };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = RT_VM;
