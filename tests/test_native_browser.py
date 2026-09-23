"""The installed Chrome PDF viewer: real side-panel clicks highlight the loaded PDF without navigation."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote
from PIL import Image
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from backend import docstore

ROOT = Path(__file__).resolve().parents[1]
def _find_chrome():
    for c in [os.environ.get('CHROME_BIN'), shutil.which('google-chrome'), shutil.which('chromium'), shutil.which('chromium-browser'), str(Path.home()/'.cache/ms-playwright/chromium-1234/chrome-linux64/chrome')]:
        if c and Path(c).exists():
            try:
                if subprocess.run([c, '--version'], capture_output=True, timeout=2).returncode == 0:
                    return c
            except Exception:
                pass
    return None
CHROME = _find_chrome()


@unittest.skipUnless(CHROME and shutil.which('node'), 'Chrome and Node required')
class TestNativeBrowser(unittest.TestCase):
    def test_existing_pdf_tab_is_not_reloaded(self):
        pdf=Path(os.environ.get('RT_NATIVE_PDF',ROOT/'dataset/resumes/Abhishek Kumar Singh.pdf')).resolve()
        ctx=PipelineContext('native',pdf.name,raw_bytes=pdf.read_bytes());runner.run(ctx)
        edu=next(e for e in ctx.events if e.type=='EDUCATION')
        loc=edu.source['entry'][0]
        with tempfile.TemporaryDirectory(prefix='.rt-native-',dir=ROOT,ignore_cleanup_errors=True) as tmp:
            cx=docstore.connect(str(Path(tmp)/'fixture.db'));docstore.save_result(cx,ctx,'SUCCESS')
            fixture=docstore.get_timeline(cx,'native');cx.close()
            profile=Path(tmp)/'profile'
            extension=Path(tmp)/'extension';shutil.copytree(ROOT/'extension',extension)
            manifest=json.loads((extension/'manifest.json').read_text())
            manifest['permissions'].append('debugger')
            manifest.pop('optional_permissions',None)
            (extension/'manifest.json').write_text(json.dumps(manifest))
            log=open(Path(tmp)/'chrome.log','w')
            browser=subprocess.Popen([CHROME,'--headless','--no-sandbox','--disable-gpu','--no-proxy-server','--disable-dev-shm-usage',
                '--allow-file-access-from-files','--load-extension='+str(extension),'--remote-debugging-port=0','--user-data-dir='+str(profile),
                '--window-size=1440,1000','about:blank'],stdout=log,stderr=log)
            try:
                port_file=profile/'DevToolsActivePort'
                for _ in range(100):
                    if port_file.exists() and port_file.read_text().splitlines():break
                    time.sleep(.1)
                self.assertTrue(port_file.exists(), 'Chrome did not start')
                port=int(port_file.read_text().splitlines()[0])
                screenshot=str(Path(tmp)/'native.png')
                config=Path(tmp)/'config.json';config.write_text(json.dumps(dict(port=port,url=pdf.as_uri(),locations=[loc],screenshot=screenshot,fixture=fixture)))
                result=subprocess.run(['node',str(ROOT/'tests/native_browser.cjs'),str(config)],capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stderr)
                data=json.loads(result.stdout)
                self.assertEqual(data['countBefore'],data['countAfter'])
                self.assertEqual(data['url'],pdf.as_uri())
                self.assertEqual(data['loaderBefore'],data['loaderAfter'],'PDF reloaded')
                self.assertTrue(data['result']['highlighted'],data['result'])
                self.assertFalse(data['attached'],'Debugger must detach after each highlight')
                with Image.open(screenshot).convert('RGB') as im:
                    count=sum(b>180 and r>140 and b>g*1.08 and r>g*1.04 for r,g,b in im.get_flattened_data())
                self.assertGreater(count,250,'Native PDF glyphs were not highlighted')
                if os.environ.get('RT_NATIVE_SCREENSHOT'):shutil.copyfile(screenshot,os.environ['RT_NATIVE_SCREENSHOT'])
            finally:
                browser.terminate()
                try:browser.wait(timeout=8)
                except subprocess.TimeoutExpired:browser.kill();browser.wait()
                log.close()
