"""Optional local OCR for image-only PDF pages, preserving word rectangles."""
import csv
import io
import math
import shutil
import subprocess

from .source import normalized_line


def extract_page(raw, page_number, normalize):
    executable = shutil.which('tesseract')
    if not executable:
        raise RuntimeError('Image-only PDF needs Tesseract OCR (install tesseract-ocr and tesseract-ocr-eng)')
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(raw) as pdf:
        page = pdf[page_number - 1]
        try:
            page.set_cropbox(*page.get_mediabox())
            width, height = page.get_size()
            scale = min(3.0, math.sqrt(16_000_000 / (width * height)))
            bitmap = page.render(scale=scale)
            try:
                image = io.BytesIO()
                bitmap.to_pil().save(image, format='PNG')
            finally:
                bitmap.close()
        finally:
            page.close()
    result = subprocess.run(
        [executable, 'stdin', 'stdout', '-l', 'eng', '--psm', '3', 'tsv'],
        input=image.getvalue(), capture_output=True, timeout=120, check=False,
    )
    if result.returncode:
        raise RuntimeError('Tesseract could not read the PDF page: ' + result.stderr.decode(errors='replace')[-300:])
    return lines_from_tsv(result.stdout.decode('utf-8'), normalize, page_number, width, height, scale)


def lines_from_tsv(tsv, normalize, page_number, width, height, scale):
    groups = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE):
        word = (row.get('text') or '').strip()
        if row.get('level') != '5' or not word:
            continue
        x, y, w, h = (float(row[key]) / scale for key in ('left', 'top', 'width', 'height'))
        box = {'x0': x, 'top': y, 'x1': x + w, 'bottom': y + h}
        key = tuple(row[key] for key in ('block_num', 'par_num', 'line_num'))
        groups.setdefault(key, []).append((word, box))
    lines = []
    for words in groups.values():
        text, chars = '', []
        for word, box in words:
            if text:
                text += ' '
                chars.append(None)
            text += word
            chars.extend([box] * len(word))
        line = normalized_line(text, chars, normalize, page_number, width, height)
        line['method'] = 'ocr'
        lines.append(line)
    return lines
