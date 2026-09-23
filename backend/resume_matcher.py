"""Resume Matcher boundary: transport and contract adaptation only.

The original twelve-stage evidence pipeline remains independent. Structured
resume edits are persisted by Matcher, never written over original evidence.
"""
import io
import json
import os
import re
import socket
import uuid
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_FILE_SIZE = 4 * 1024 * 1024
MAX_UPLOAD_BODY = MAX_FILE_SIZE + 65536
ROOT = Path(__file__).resolve().parents[1]


def api_base():
    value = os.environ.get('RESUME_PARSER_API_URL')
    if not value:
        config = ROOT / '.env.local'
        if config.exists():
            for line in config.read_text().splitlines():
                key, sep, val = line.partition('=')
                if sep and key.strip() == 'RESUME_PARSER_API_URL':
                    value = val.strip().strip('\"\'')
                    break
    value = (value or 'http://localhost:8001/api/v1').rstrip('/')
    if urlparse(value).scheme not in ('http', 'https'):
        raise ValueError('RESUME_PARSER_API_URL must be an HTTP(S) URL.')
    return value


def forward(method, path, body=None, content_type=None):
    headers = {'Accept': 'application/json, application/pdf'}
    if content_type:
        headers['Content-Type'] = content_type
    request = Request(api_base() + path, data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=180) as response:
            return response.status, response.read(), {k.title():v for k,v in response.headers.items()}
    except HTTPError as exc:
        return exc.code, exc.read(), {k.title():v for k,v in exc.headers.items()}
    except (URLError, TimeoutError, socket.timeout):
        message = ('Resume Matcher is unavailable or took too long to respond. '
                   'Check the service on port 8001 and try again. Your draft is kept.')
        return 503, json.dumps({'detail': message}).encode(), {'Content-Type': 'application/json'}


def is_available(timeout=0.8):
    """Fast non-blocking liveness check for RESUME_PARSER_API_URL."""
    try:
        req = Request(api_base() + '/health', headers={'Accept': 'application/json'})
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def parse_with_api(raw_bytes, filename='resume.pdf', timeout=15):
    """Attempt to parse resume using upstream RESUME_PARSER_API_URL if available."""
    if not raw_bytes or not is_available(timeout=0.8):
        return None
    try:
        suffix = Path(filename).suffix.lower()
        if suffix not in ('.pdf', '.docx', '.doc', '.txt'):
            suffix = '.pdf'
            filename = Path(filename).stem + '.pdf'
        mime = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.txt': 'text/plain'
        }.get(suffix, 'application/pdf')

        boundary = 'ResumeBoundary' + uuid.uuid4().hex
        safe = re.sub(r'[\r\n"\\]', '_', filename)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\n'
                f'Content-Type: {mime}\r\n\r\n').encode() + raw_bytes + f'\r\n--{boundary}--\r\n'.encode()
        content_type = 'multipart/form-data; boundary=' + boundary

        req = Request(api_base() + '/resumes/upload', data=body, method='POST',
                      headers={'Accept': 'application/json', 'Content-Type': content_type})
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            upload_data = json.loads(resp.read().decode('utf-8'))

        resume_id = upload_data.get('resume_id') or upload_data.get('data', {}).get('resume_id')
        if not resume_id:
            return None

        req = Request(api_base() + f'/resumes/{resume_id}', headers={'Accept': 'application/json'})
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            detail = json.loads(resp.read().decode('utf-8'))
            return detail.get('data', {}).get('processed_resume') or detail.get('processed_resume')
    except Exception:
        return None



def prepare_upload(body, content_type):
    """Validate the file independently of browser checks; bridge TXT support."""
    if len(body) > MAX_UPLOAD_BODY:
        raise ValueError('File exceeds the 4 MB limit.')
    if not content_type.startswith('multipart/form-data;') or '\r' in content_type or '\n' in content_type:
        raise ValueError('Upload a file using multipart/form-data.')
    message = BytesParser(policy=default).parsebytes(
        ('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
    files = [p for p in message.iter_parts() if p.get_param('name', header='content-disposition') == 'file']
    if len(files) != 1:
        raise ValueError('Exactly one resume file is required.')
    file = files[0]
    filename = Path(file.get_filename() or '').name
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.pdf', '.docx', '.doc', '.txt'):
        raise ValueError('Choose a PDF, DOCX, DOC, or TXT resume.')
    content = file.get_payload(decode=True) or b''
    if not content or len(content) > MAX_FILE_SIZE:
        raise ValueError('Choose a nonempty resume no larger than 4 MB.')
    if suffix == '.txt':
        from docx import Document
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('TXT resumes must use UTF-8 encoding.') from None
        document = Document()
        for line in text.splitlines():
            document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        content, filename, suffix = buffer.getvalue(), filename+'.docx', '.docx'
        if len(content) > MAX_FILE_SIZE:
            raise ValueError('Converted TXT resume exceeds the 4 MB limit.')
    mime = {'.pdf':'application/pdf','.doc':'application/msword',
            '.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}[suffix]
    boundary = 'ResumeBoundary'+uuid.uuid4().hex
    # Sanitize MIME headers; no document content is logged.
    safe = re.sub(r'[\r\n"\\]', '_', filename)
    prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\n'
              f'Content-Type: {mime}\r\n\r\n').encode()
    return prefix+content+f'\r\n--{boundary}--\r\n'.encode(), 'multipart/form-data; boundary='+boundary


def adapt_update(value):
    """Accept blueprint metadata as well as the real API's richer metadata list."""
    if not isinstance(value, dict):
        raise ValueError('Resume data must be a JSON object.')
    metadata = value.get('sectionMeta')
    if isinstance(metadata, dict):
        order = metadata.get('order', [])
        visible = metadata.get('visible', {})
        if not isinstance(order, list) or not isinstance(visible, dict):
            raise ValueError('Invalid section metadata.')
        types = {'summary':'text','workExperience':'itemList','education':'itemList',
                 'personalProjects':'itemList','additional':'stringList'}
        value = dict(value)
        value['sectionMeta'] = [dict(id=key,key=key,displayName=key,
            sectionType=types.get(key, value.get('customSections',{}).get(key,{}).get('sectionType','text')),
            isDefault=key in types,isVisible=visible.get(key,True),order=i)
            for i,key in enumerate(order) if isinstance(key,str)]
    return value


def allowed_route(method, path):
    # A fixed upstream, with a narrow allowlist; never a general-purpose proxy.
    if method == 'GET' and path in ('/health','/resumes','/resumes/list'):
        return True
    if method == 'POST' and path == '/resumes/upload':
        return True
    return bool(re.fullmatch(r'/resumes/[a-zA-Z0-9_-]+', path) and method == 'PATCH'
                or re.fullmatch(r'/resumes/[a-zA-Z0-9_-]+/pdf', path) and method == 'GET')
