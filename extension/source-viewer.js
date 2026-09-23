/* Highlight the analyzed document in its existing viewer. Never render a copy. */
var RT_SOURCE = (() => {
  let binding = null;
  const marks = [];
  function clear() {
    for (const mark of marks.splice(0)) mark.remove();
    if (globalThis.CSS?.highlights) CSS.highlights.delete('rt-evidence');
  }
  function bind(value) { clear(); binding = value && binding?.docId===value.docId ? {...binding,...value} : value; }
  function captureText() {
    const nodes = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || parent.closest('#rt-panel,#rt-pill,script,style,noscript,[hidden]') || !parent.getClientRects().length)
          return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let text = '', node, previousBlock = null;
    while ((node = walker.nextNode())) {
      const block = node.parentElement.closest('p,li,div,section,article,h1,h2,h3,h4,tr,pre') || node.parentElement;
      if (previousBlock && previousBlock !== block) text += '\n';
      const start = Array.from(text).length;
      text += node.textContent;
      nodes.push({ node, start, end: Array.from(text).length, text: node.textContent });
      previousBlock = block;
    }
    return { text, nodes };
  }
  function rectStyle(loc) {
    const [x0, y0, x1, y1] = loc.bbox;
    return { left: `${100*x0/loc.page_width}%`, top: `${100*y0/loc.page_height}%`,
      width: `${100*(x1-x0)/loc.page_width}%`, height: `${100*(y1-y0)/loc.page_height}%` };
  }
  function nativeUrl(url, locations) {
    const exact = (locations || []).filter(loc => loc.fragment_text || loc.text).map(loc => ({
      ...loc,
      fragment_text: String(loc.fragment_text || loc.text || '').trim()
    })).filter(loc => loc.fragment_text);
    if (!exact.length) throw new Error('This viewer has no unique exact text anchor for this item.');
    const encode = value => encodeURIComponent(value).replace(/[!'()*-]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
    return url.split('#')[0] + '#page=' + (exact[0].page || 1) + ':~:' + exact.map(loc => 'text=' + encode(loc.fragment_text)).join('&');
  }
  async function show(docId, locations, send) {
    if (!binding || binding.docId !== docId) throw new Error('Analyze the open resume before viewing its evidence.');
    if (!locations?.length) throw new Error('No exact source location is available for this item.');
    clear();
    if (locations[0].kind === 'text' && binding.nodes) {
      if (binding.nodes.some(saved=>!saved.node.isConnected || saved.node.textContent!==saved.text))
        throw new Error('The resume text changed. Analyze this page again.');
      const ranges = [];
      for (const loc of locations) {
        if (loc.kind!=='text' || !Number.isInteger(loc.start) || !Number.isInteger(loc.end) || loc.start<0 || loc.end<=loc.start)
          throw new Error('The source text offsets are invalid.');
        const count=ranges.length;
        for (const saved of binding.nodes) {
          if (saved.end <= loc.start || saved.start >= loc.end) continue;
          if (!saved.node.isConnected || saved.node.textContent !== saved.text)
            throw new Error('The resume text changed. Analyze this page again.');
          const range = document.createRange();
          const offset = n => Array.from(saved.text).slice(0, Math.max(0,n)).join('').length;
          range.setStart(saved.node, offset(loc.start - saved.start));
          range.setEnd(saved.node, offset(loc.end - saved.start));
          ranges.push(range);
        }
        if (ranges.length===count) throw new Error('The source is no longer present in this page.');
      }
      if (!ranges.length) throw new Error('The source is no longer present in this page.');
      if (globalThis.CSS?.highlights && globalThis.Highlight) CSS.highlights.set('rt-evidence', new Highlight(...ranges));
      else { const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(ranges[0]); }
      ranges[0].startContainer.parentElement.scrollIntoView({block:'center', behavior:'instant'});
      return { highlighted: true, method: 'original-dom-offsets' };
    }
    // An accessible PDF.js viewer already exposes page containers. Overlay its
    // existing page, preserving its canvas, document and zoom; no second image.
    const firstPage = document.querySelector(`.pdfViewer .page[data-page-number="${Number(locations[0].page)}"]`);
    if (binding.inPage && firstPage) {
      const targets=locations.map(loc=>{
        const page=document.querySelector(`.pdfViewer .page[data-page-number="${Number(loc.page)}"]`);
        if (!page) throw new Error('This PDF page has not been rendered yet.');
        if (!Array.isArray(loc.bbox) || loc.bbox.length!==4 || !loc.bbox.every(Number.isFinite) ||
            !(loc.page_width>0 && loc.page_height>0) || loc.bbox[0]<0 || loc.bbox[1]<0 ||
            loc.bbox[2]<=loc.bbox[0] || loc.bbox[3]<=loc.bbox[1] ||
            loc.bbox[2]>loc.page_width || loc.bbox[3]>loc.page_height)
          throw new Error('The source page coordinates are invalid.');
        return {loc,page};
      });
      for (const {loc,page} of targets) {
        const mark = document.createElement('mark');
        mark.className = 'rt-original-highlight';
        mark.title = loc.text;
        Object.assign(mark.style, rectStyle(loc));
        page.appendChild(mark); marks.push(mark);
      }
      marks[0].scrollIntoView({block:'center',behavior:'instant'});
      return { highlighted: true, method: 'existing-pdf-coordinates' };
    }
    throw new Error('This viewer does not expose the original source location for live highlighting. The resume has not been reloaded.');
  }
  function locationsFor(item) {
    const own=item?.source?.entry;
    const locations=own?.length ? own : (item?.evidence_details || []).flatMap(d=>d.source?.entry || []);
    if (!locations.length) throw new Error('No exact source location is available for this item.');
    return locations;
  }

  function offerPdfPermission(container,retry) {
    container.hidden=false;
    if (!chrome.permissions?.request) {
      container.textContent='Open the Resume Timeline extension popup and click View in Resume there to enable live PDF highlighting once.';
      return;
    }
    container.textContent='Live PDF highlighting needs Chrome’s optional debugging permission for this resume tab. ';
    const button=document.createElement('button');button.type='button';button.textContent='Enable live PDF highlighting';
    button.onclick=()=>{
      chrome.permissions.request({permissions:['debugger']}).then(granted=>{
        if(granted)return retry();
        container.textContent='Permission was not granted. The resume is unchanged.';
      }).catch(error=>{container.textContent=error.message;});
    };
    container.append(button);
  }
  return { show, bind, captureText, rectStyle, nativeUrl, locationsFor, offerPdfPermission, close: clear };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = RT_SOURCE;
