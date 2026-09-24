"""Conservative text recovery from DOCX packages with broken relationships."""
import io
import zipfile
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def recover_docx_body(raw):
    # Read only the original body XML; do not alter or invent missing parts.
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        info = package.getinfo('word/document.xml')
        if info.file_size > 64 * 1024 * 1024:
            raise ValueError('DOCX body is too large for safe text recovery')
        root = ET.fromstring(package.read(info))
    body = root.find(W + 'body')
    if body is None:
        raise ValueError('DOCX body is missing')

    def paragraph(element):
        return ''.join(node.text or '' if node.tag == W + 't' else
                       '\t' if node.tag == W + 'tab' else
                       '\n' if node.tag in (W + 'br', W + 'cr') else ''
                       for node in element.iter())

    parts = []
    for block in body:
        if block.tag == W + 'p':
            parts.append(paragraph(block))
        elif block.tag == W + 'tbl':
            for row in block.findall(W + 'tr'):
                cells = ['\n'.join(paragraph(p) for p in cell.iter(W + 'p'))
                         for cell in row.findall(W + 'tc')]
                parts.append(' | '.join(cells))
    return '\n'.join(part for part in parts if part.strip())
