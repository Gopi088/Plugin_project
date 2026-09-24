"""Real Chromium rendering/click regression, with API data from the actual PDF.

The Chrome transport is stubbed; PDF extraction, storage DTO, review UI, page
rendering, image loading, scrolling and coordinate overlays are real.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from backend import docstore, source
from backend.pipeline import runner
from backend.pipeline_context import PipelineContext

ROOT = Path(__file__).resolve().parents[1]

CHROME = shutil.which('google-chrome') or shutil.which('chromium')
if CHROME:
    try:
        if subprocess.run([CHROME, '--version'], capture_output=True, timeout=5).returncode != 0:
            CHROME = None
    except Exception:
        CHROME = None


@unittest.skipUnless(CHROME, 'Chrome/Chromium required for browser regression')
class TestBrowserSource(unittest.TestCase):
    def test_abhishek_review_click_highlights_original_pages(self):
        pdf = ROOT / 'dataset/resumes/Abhishek Kumar Singh.pdf'
        ctx = PipelineContext('browser', pdf.name, raw_bytes=pdf.read_bytes())
        runner.run(ctx)
        with tempfile.TemporaryDirectory(prefix='.rt-browser-', dir=ROOT, ignore_cleanup_errors=True) as tmp:
            cx = docstore.connect(str(Path(tmp) / 'test.db'))
            docstore.save_result(cx, ctx, 'SUCCESS')
            dto = docstore.get_timeline(cx, ctx.doc_id)
            cx.close()
            pages = {i: source.render_page(ctx.raw_bytes, i) for i in (1, 2)}
            setup = r'''
const fixture = FIXTURE;
fixture.notes=Array.from({length:6},(_,i)=>({id:'legacy:'+i,author:'Author not recorded',text:'[gap:g0] note',created_at:'2026-09-21T12:00:0'+i+'+00:00'}));
let receive;
const saved = {};
window.open=()=>{throw Error('A second window must not open');};
window.chrome = {storage:{local:{get:async()=>saved,set:async v=>Object.assign(saved,v)}},runtime: {
  sendMessage(msg, callback) {
    if (msg.type === 'rt-timeline') callback(fixture);
    else if(msg.type==='rt-state') {
      fixture.item_state ||= {};
      const {target_id,...state}=msg.payload;
      callback(fixture.item_state[target_id]={...fixture.item_state[target_id],...state});
    } else if(msg.type==='rt-add-note') {
      fixture.notes ||= [];
      fixture.notes.push({...msg.payload,created_at:'2026-09-21T12:34:56+00:00'});callback(fixture.notes);
    } else callback({_rtError:'Unexpected message: ' + msg.type});
  }, onMessage: {addListener(fn) {receive = fn;}}
}};
'''.replace('FIXTURE', json.dumps(dto))
            checks = r'''
const check=(value,message)=>{if(!value)throw Error(message);};
(async()=>{
  const originalImages=[...document.images];
  await new Promise(resolve=>receive({type:'rt-show-doc',docId:'browser'},{},resolve));
  check(document.querySelector('.rt-period').textContent.includes('2 months'),'Wrong gap duration');
  check(document.querySelector('.rt-sum') && document.querySelectorAll('[role=tab]').length===2,'Original summary/tabs missing');
  check(!document.querySelector('#rt-notes').open,'Notes should start collapsed');
  check(!document.querySelector('#rt-note-history').open,'Legacy notes should start collapsed');
  check(document.querySelectorAll('#rt-note-history .rt-note').length===1,'Repeated legacy notes were not grouped');
  check(document.querySelectorAll('#rt-note-history time').length===6,'Original note dates were lost');
  check(!document.querySelector('#rt-note-history').textContent.includes('[gap:g0]'),'Internal note marker leaked');
  document.querySelector('[data-tab=timeline]').click();
  check(!document.querySelector('#rt-pane-timeline').hidden && document.querySelector('#rt-pane-overview').hidden,'Timeline tab does not switch');
  check(document.querySelector('.rt-tl .rt-year') && document.querySelectorAll('.rt-tdot').length===fixture.timeline.length,'Year-grouped timeline missing');
  document.querySelector('[data-tab=overview]').click();
  check(!document.querySelector('#rt-panel').textContent.includes('22 months'),'22-month regression');
  check([...document.querySelectorAll('.rt-entry')].every(e=>!e.open),'Rows must start collapsed');
  const gap=document.querySelector('.rt-period');gap.open=true;
  await gap.querySelector('[data-view]').onclick();
  check(document.querySelector('.page[data-page-number="2"] mark')?.title.includes('Bachelor'),'Education evidence missing');
  check(document.querySelector('.page[data-page-number="1"] mark')?.title.includes('Cavisson'),'Job evidence missing');
  check(document.images.length===originalImages.length && originalImages.every(i=>i.isConnected),'Resume was copied or replaced');
  const job=fixture.timeline.find(e=>e.org.includes('Cavisson'));
  for(const field of ['company','dates','title']){
    await RT_SOURCE.show('browser',job.source[field],()=>{throw Error('Unexpected second viewer');});
    const loc=job.source[field][0],mark=document.querySelector('.rt-original-highlight');
    check(mark.title===loc.text,'Wrong '+field+' evidence');
    check(Math.abs(parseFloat(mark.style.left)-parseFloat(RT_SOURCE.rectStyle(loc).left))<.001,'Wrong coordinates');
  }
  await document.querySelector('#rt-top-reviewed').onclick();
  check(document.querySelector('#rt-top-reviewed').classList.contains('is-reviewed'),'Review not retained');
  await document.querySelector(`[data-hide="${job.id}"]`).onclick();
  check(document.querySelector('.rt-hidden-items [data-item]')?.dataset.item===job.id,'Hide failed');
  document.querySelector('#rt-notes').open=true;
 const form=document.querySelector('#rt-note-form');form.author.value='Recruiter One';form.note.value='Verify original dates';form.oninput();
  await form.onsubmit(new Event('submit',{cancelable:true}));
  check(document.querySelector('.rt-note').textContent.includes('Recruiter One'),'Author missing');
  check(document.querySelector('.rt-note time').dateTime==='2026-09-21T12:34:56+00:00','Timestamp missing');
  await new Promise(resolve=>receive({type:'rt-show-doc',docId:'browser'},{},resolve));
  check(document.querySelector('.rt-note').textContent.includes('Verify original dates'),'Saved note lost on reopen');
  check(!document.querySelector('#rt-source-viewer'),'Duplicate viewer');
  // Python uses Unicode code points; DOM ranges use UTF-16 code units.
  const resume=document.createElement('div');resume.textContent='😀 Engineer, Alpha Ltd';document.body.append(resume);
  const snapshot=RT_SOURCE.captureText();const start=Array.from(snapshot.text).join('').indexOf('😀');
  const prefix=Array.from(snapshot.text.slice(0,start)).length;
  RT_SOURCE.bind({docId:'unicode',nodes:snapshot.nodes,inPage:true});
  RT_SOURCE.bind({docId:'unicode',inPage:true});
  await RT_SOURCE.show('unicode',[{kind:'text',start:prefix+2,end:prefix+10}],()=>{});
  check([...CSS.highlights.get('rt-evidence')].map(r=>r.toString()).join('')==='Engineer','Unicode offsets are wrong: '+[...CSS.highlights.get('rt-evidence')].map(r=>r.toString()).join('|'));
  resume.firstChild.textContent='Changed Engineer, Alpha Ltd';
  let rejected=false;
  try {await RT_SOURCE.show('unicode',[{kind:'text',start:prefix+2,end:prefix+10}]);} catch(e){rejected=e.message.includes('changed');}
  check(rejected && !CSS.highlights.has('rt-evidence'),'Changed resume must not match another occurrence');
  let missing=false;try {RT_SOURCE.locationsFor({title:'Engineer'});}catch(e){missing=true;}
  check(missing,'Missing evidence must not invent a page-one source');
  document.querySelector('[data-tab=timeline]').click();
  document.querySelector('#rt-notes').open=false;
  const permissionStatus=document.createElement('div');document.body.append(permissionStatus);
  let retried=0;
  chrome.permissions={request:async()=>false};
  RT_SOURCE.offerPdfPermission(permissionStatus,()=>retried++);
  permissionStatus.querySelector('button').click();await new Promise(r=>setTimeout(r,0));
  check(!retried && permissionStatus.textContent.includes('not granted'),'Denied permission must not highlight');
  chrome.permissions.request=async()=>true;
  RT_SOURCE.offerPdfPermission(permissionStatus,()=>retried++);
  permissionStatus.querySelector('button').click();await new Promise(r=>setTimeout(r,0));
  check(retried===1,'Grant must retry the original evidence click');
  document.body.dataset.testResult='PASS';
})().catch(error=>{document.body.dataset.testResult='FAIL: '+error.message;});
'''
            scripts = '\n'.join((ROOT / 'extension' / f).read_text() for f in
                                ('viewmodel.js', 'source-viewer.js', 'content.js'))
            css = (ROOT / 'extension/sidebar.css').read_text()
            html = '<!doctype html><html><head><meta charset="utf-8"><style>' + css + '</style></head><body>'
            html += '<div class="pdfViewer" style="width:800px">' + ''.join(
                '<div class="page" data-page-number="'+str(i)+'" style="position:relative"><img style="width:100%" src="'+pages[i]['image']+'"></div>' for i in (1,2)) + '</div>'
            html += '<script>'  + setup + scripts + checks + '</script></body></html>'
            path = Path(tmp) / 'test.html'
            path.write_text(html)
            if os.environ.get('RT_BROWSER_FIXTURE'):
                Path(os.environ['RT_BROWSER_FIXTURE']).write_text(html)
            screenshot = str(Path(tmp) / 'verified.png')
            run = subprocess.run([CHROME, '--headless', '--no-sandbox', '--disable-gpu',
                                  '--no-proxy-server', '--allow-file-access-from-files',
                                  '--user-data-dir=' + str(Path(tmp) / 'profile'),
                                  '--window-size=1440,1000', '--virtual-time-budget=12000',
                                  '--screenshot=' + screenshot, '--dump-dom', path.as_uri()],
                                 capture_output=True, text=True, timeout=45)
            if os.environ.get('RT_BROWSER_SCREENSHOT') and Path(screenshot).exists():
                shutil.copyfile(screenshot, os.environ['RT_BROWSER_SCREENSHOT'])
            result = re.search(r'data-test-result="([^"]+)"', run.stdout)
            self.assertEqual(result.group(1) if result else (run.stdout[:500] + run.stderr[-2000:]), 'PASS')
