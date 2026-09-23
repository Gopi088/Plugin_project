import io
import json
import os
import subprocess
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from backend import resume_matcher as matcher, server

ROOT=Path(__file__).resolve().parents[1]


def multipart(filename,content):
    body=(f'--test\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+content+b'\r\n--test--\r\n'
    return body,'multipart/form-data; boundary=test'


class FakeMatcher(BaseHTTPRequestHandler):
    data={'personalInfo':{'name':'Test Candidate'},'summary':'Original','workExperience':[], 'education':[], 'personalProjects':[], 'additional':{},'customSections':{},'sectionMeta':[]}
    upload=None
    def log_message(self,*args):pass
    def reply(self,data,content_type='application/json'):
        body=data if isinstance(data,bytes) else json.dumps(data).encode()
        self.send_response(200);self.send_header('content-type',content_type)
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if '/pdf' in self.path:return self.reply(b'%PDF-1.7\ntest','application/pdf')
        if '/health' in self.path:return self.reply({'status':'healthy'})
        if '/list' in self.path:return self.reply({'data':[{'resume_id':'test','processing_status':'ready'}]})
        return self.reply({'data':{'resume_id':'test','processed_resume':type(self).data,'raw_resume':{'processing_status':'ready','content':'Original source','content_type':'md'}}})
    def do_POST(self):
        type(self).upload=self.rfile.read(int(self.headers['Content-Length']))
        self.reply({'resume_id':'test','processing_status':'ready'})
    def do_PATCH(self):
        type(self).data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.do_GET()


class TestMatcherWorkspace(unittest.TestCase):
    def test_node_contracts(self):
        result=subprocess.run(['node','web/workspace.test.js'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_txt_adapter_and_invalid_files(self):
        from docx import Document
        from email.parser import BytesParser
        from email.policy import default
        body,ctype=matcher.prepare_upload(*multipart('resume.txt','Engineer\n08/2014 – 07/2018'.encode()))
        parsed=BytesParser(policy=default).parsebytes(('Content-Type: '+ctype+'\r\n\r\n').encode()+body)
        part=list(parsed.iter_parts())[0]
        self.assertEqual(part.get_filename(),'resume.txt.docx')
        document=Document(io.BytesIO(part.get_payload(decode=True)))
        self.assertEqual([p.text for p in document.paragraphs],['Engineer','08/2014 – 07/2018'])
        for filename,content in [('bad.exe',b'x'),('empty.pdf',b''),('big.pdf',b'x'*(matcher.MAX_FILE_SIZE+1))]:
            with self.assertRaises(ValueError):matcher.prepare_upload(*multipart(filename,content))

    def test_workspace_javascript_syntax(self):
        for path in (ROOT/'web').rglob('*.js'):
            result=subprocess.run(['node','--check',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_live_proxy_contract_and_static_workspace(self):
        upstream=ThreadingHTTPServer(('127.0.0.1',0),FakeMatcher)
        api=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        for service in (upstream,api):threading.Thread(target=service.serve_forever,daemon=True).start()
        try:
            with patch.dict(os.environ,{'RESUME_PARSER_API_URL':f'http://127.0.0.1:{upstream.server_port}/api/v1'}):
                base=f'http://127.0.0.1:{api.server_port}'
                def request(path,body=None,method=None,content_type='application/json'):
                    req=urllib.request.Request(base+path,data=body,method=method,headers={'Content-Type':content_type})
                    return urllib.request.urlopen(req,timeout=10)
                with request('/workspace/') as response:self.assertIn(b'Resume workspace',response.read())
                with request('/workspace/services/resumeService.js') as response:self.assertIn('javascript',response.headers['Content-Type'])
                with self.assertRaises(urllib.error.HTTPError):request('/workspace/%2e%2e/backend/data/store.db')
                payload={'personalInfo':{'name':'Updated'},'customSections':{'volunteer':{'sectionType':'text','text':'Helped'}},'sectionMeta':{'order':['volunteer'],'visible':{'volunteer':False}}}
                with request('/api/resume-manager/resumes/test',json.dumps(payload).encode(),'PATCH') as response:
                    record=json.load(response)['data']['processed_resume']
                self.assertEqual(record['personalInfo']['name'],'Updated')
                self.assertFalse(record['sectionMeta'][0]['isVisible'])
                self.assertEqual(record['customSections']['volunteer']['text'],'Helped')
                body,ctype=multipart('test.txt',b'Engineer')
                with request('/api/resume-manager/resumes/upload',body,'POST',ctype) as response:self.assertEqual(json.load(response)['resume_id'],'test')
                self.assertIn(b'test.txt.docx',FakeMatcher.upload)
                with request('/api/resume-manager/resumes/test/pdf?template=modern') as response:
                    self.assertEqual(response.headers['Content-Type'],'application/pdf')
                    self.assertTrue(response.read().startswith(b'%PDF'))
                with self.assertRaises(urllib.error.HTTPError):request('/api/resume-manager/config/llm-api-key')
        finally:
            for service in (api,upstream):service.shutdown();service.server_close()

    def test_offline_response(self):
        from urllib.error import URLError
        with patch.object(matcher,'urlopen',side_effect=URLError('offline')):
            code,body,_=matcher.forward('GET','/health')
        self.assertEqual(code,503);self.assertIn('port 8001',json.loads(body)['detail'])

    def test_browser_full_workspace(self):
        import shutil
        import tempfile
        import time
        chrome=shutil.which('google-chrome')
        if chrome:
            try:
                if subprocess.run([chrome, '--version'], capture_output=True, timeout=5).returncode != 0:
                    chrome = None
            except Exception:
                chrome = None
        if not chrome:self.skipTest('Working Chrome required')
        FakeMatcher.data={
            'personalInfo':{'name':'Workspace Test'},'summary':'Original summary',
            'workExperience':[{'id':1,'title':'Engineer','company':'Alpha Ltd','years':'Jan 2021 - Present','description':['Build APIs']}],
            'education':[{'id':1,'degree':'B.Tech','institution':'University','years':'2014 - 2018','description':'Honors'}],
            'personalProjects':[{'id':1,'name':'Project','role':'Developer','years':'','description':['Created a tool']}],
            'additional':{'languages':['English']},
            'customSections':{'volunteer':{'sectionType':'text','text':'Original volunteer'},'publications':{'sectionType':'stringList','strings':['Paper A']},'speaking':{'sectionType':'itemList','items':[{'id':1,'title':'Talk','description':['First bullet']}]}},'sectionMeta':[]}
        upstream=ThreadingHTTPServer(('127.0.0.1',0),FakeMatcher)
        api=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        for service in (upstream,api):threading.Thread(target=service.serve_forever,daemon=True).start()
        try:
            with patch.dict(os.environ,{'RESUME_PARSER_API_URL':f'http://127.0.0.1:{upstream.server_port}/api/v1'}), tempfile.TemporaryDirectory(prefix='.rt-workspace-',dir=ROOT,ignore_cleanup_errors=True) as tmp:
                folder=Path(tmp);profile=folder/'profile';downloads=folder/'downloads';downloads.mkdir()
                sample=folder/'test.txt';sample.write_text('WORK EXPERIENCE\nEngineer, Alpha Ltd Jan 2021 - Present')
                with open(folder/'chrome.log','w') as log:
                    browser=subprocess.Popen([chrome,'--headless','--no-sandbox','--disable-gpu','--no-proxy-server','--disable-dev-shm-usage','--remote-debugging-port=0','--user-data-dir='+str(profile),'--window-size=1440,1000','about:blank'],stdout=log,stderr=log)
                    try:
                        for _ in range(100):
                            if (profile/'DevToolsActivePort').exists():break
                            time.sleep(.1)
                        port=int((profile/'DevToolsActivePort').read_text().splitlines()[0])
                        config={'port':port,'url':f'http://127.0.0.1:{api.server_port}/workspace/','file':str(sample),'downloads':str(downloads),'screenshot':str(folder/'workspace.png')}
                        path=folder/'config.json';path.write_text(json.dumps(config))
                        result=subprocess.run(['node',str(ROOT/'tests/workspace_browser.cjs'),str(path)],capture_output=True,text=True,timeout=120)
                        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                        self.assertEqual(FakeMatcher.data['personalInfo']['name'],'Updated Test Candidate')
                        self.assertEqual(FakeMatcher.data['additional']['languages'],['English','Hindi'])
                        self.assertEqual(FakeMatcher.data['education'][0]['description'],'Graduated with honors')
                        self.assertEqual(FakeMatcher.data['customSections']['volunteer']['text'],'Updated volunteer text')
                        self.assertEqual(FakeMatcher.data['customSections']['publications']['strings'],['Paper A','Paper B'])
                        self.assertEqual(FakeMatcher.data['customSections']['speaking']['items'][0]['description'],['Updated talk','Second bullet'])
                        self.assertFalse(next(m for m in FakeMatcher.data['sectionMeta'] if m['key']=='speaking')['isVisible'])
                        self.assertTrue((downloads/'resume-test.pdf').read_bytes().startswith(b'%PDF'))
                        if os.environ.get('RT_WORKSPACE_SCREENSHOT'):shutil.copyfile(config['screenshot'],os.environ['RT_WORKSPACE_SCREENSHOT'])
                    finally:
                        browser.terminate()
                        try:browser.wait(timeout=5)
                        except subprocess.TimeoutExpired:browser.kill();browser.wait()
        finally:
            for service in (api,upstream):service.shutdown();service.server_close()
