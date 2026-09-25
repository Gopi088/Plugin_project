"""Source anchors captured during extraction, before normalization or segmentation."""
from difflib import SequenceMatcher
import base64
import io


def normalized_line(text, chars, normalize, page, width=None, height=None, offset=0):
    if width is None:
        chars = [{"offset": offset + i} for i in range(len(text))]
    clean = normalize(text)
    mapped = [None] * len(clean)
    for tag, a, b, c, d in SequenceMatcher(None, text, clean, autojunk=False).get_opcodes():
        if tag == 'equal':
            mapped[c:d] = chars[a:b]
        elif tag == 'replace':
            original = next((x for x in chars[a:b] if x), None)
            mapped[c:d] = [original] * (d - c)
    left = len(clean) - len(clean.lstrip())
    right = len(clean.rstrip())
    return {'text': clean[left:right], 'chars': mapped[left:right], 'page': page,
            'width': width, 'height': height, 'offset': offset + left,
            'bold': (sum(bool(c and c.get('bold')) for c in chars) > len(text.strip()) / 2)
                    if width is not None else None}


def _extract_textmap_lines(page, normalize, root_page=None):
    root = root_page or page
    lines, text, chars = [], '', []
    for value, char in page.get_textmap().tuples:
        for letter in value:
            if letter == '\n':
                lines.append(normalized_line(text, chars, normalize, root.page_number,
                                             root.width, root.height))
                text, chars = '', []
            else:
                text += letter
                chars.append({'x0': char['x0'] - root.bbox[0], 'top': char['top'] - root.bbox[1],
                              'x1': char['x1'] - root.bbox[0], 'bottom': char['bottom'] - root.bbox[1],
                              'bold': any(weight in char.get('fontname', '').lower()
                                          for weight in ('bold', 'black', 'demi'))} if char else None)
    lines.append(normalized_line(text, chars, normalize, root.page_number, root.width, root.height))
    return [l for l in lines if l['text'].strip()]


def pdf_lines(page, normalize):
    # TextMap provides the exact character objects used by extract_text(),
    # including inserted whitespace (None); no fuzzy text-to-page search.
    words = page.extract_words() if hasattr(page, 'extract_words') else []
    if not words or len(words) < 20:
        return _extract_textmap_lines(page, normalize)

    w, h = page.width, page.height
    best = None
    min_cross = 999
    # Check vertical gutters for two-column or sidebar layouts
    for x in range(int(0.18 * w), int(0.82 * w), 5):
        left_words = [wd for wd in words if wd['x1'] <= x]
        right_words = [wd for wd in words if wd['x0'] >= x]
        crossing_words = [wd for wd in words if wd['x0'] < x < wd['x1']]
        if len(left_words) >= 12 and len(right_words) >= 15:
            if len(crossing_words) <= 2:
                if len(crossing_words) < min_cross:
                    min_cross = len(crossing_words)
                    best = (x, 0)
            elif len(crossing_words) <= 12:
                max_crossing_y = max(wd['bottom'] for wd in crossing_words)
                if max_crossing_y < h * 0.5:
                    below_cross = [wd for wd in words if wd['top'] >= max_crossing_y and wd['x0'] < x < wd['x1']]
                    if len(below_cross) == 0:
                        if len(crossing_words) < min_cross:
                            min_cross = len(crossing_words)
                            best = (x, max_crossing_y)

    if best is None:
        return _extract_textmap_lines(page, normalize)

    gx, split_y = best
    header_lines = []
    if split_y > 0:
        top_crop = page.crop((0, 0, w, split_y + 3))
        header_lines = _extract_textmap_lines(top_crop, normalize, root_page=page)

    left_crop = page.crop((0, split_y, gx, h))
    right_crop = page.crop((gx, split_y, w, h))

    left_lines = _extract_textmap_lines(left_crop, normalize, root_page=page)
    right_lines = _extract_textmap_lines(right_crop, normalize, root_page=page)

    # Check row alignment: do dates in left match titles in right?
    import re
    l_words = left_crop.extract_words()
    r_words = right_crop.extract_words()
    date_ys = [wd['top'] for wd in l_words if re.search(r'\d{2}/\d{4}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b|\b(?:19|20)\d{2}\b', wd['text'])]
    row_aligned = False
    for dy in date_ys:
        near = [rw for rw in r_words if abs(rw['top'] - dy) <= 18]
        near_text = ' '.join(rw['text'] for rw in near)
        if any(k in near_text.lower() for k in ['manager', 'developer', 'analyst', 'engineer', 'consultant', 'programmer', 'bachelor', 'master', 'diploma', 'lead', 'architect', 'specialist', 'officer', 'associate']):
            row_aligned = True
            break

    body_lines = []
    if row_aligned:
        def get_line_top(line):
            chars = [c for c in line['chars'] if c and 'top' in c]
            return min((c['top'] for c in chars), default=0)

        date_tops = []
        for l in left_lines:
            if re.search(r'\b\d{2}/\d{4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b', l['text']):
                top = get_line_top(l)
                if top > 0:
                    date_tops.append(top)
        date_tops = sorted(list(set(date_tops)))
        if date_tops:
            first_top = date_tops[0]
            pre_l = [l for l in left_lines if get_line_top(l) < first_top - 5]
            pre_r = [l for l in right_lines if get_line_top(l) < first_top - 5]
            body_lines.extend(pre_l)
            body_lines.extend(pre_r)

            for k, y_s in enumerate(date_tops):
                y_e = date_tops[k+1] if k+1 < len(date_tops) else h + 10
                band_l = [l for l in left_lines if y_s - 5 <= get_line_top(l) < y_e - 5]
                band_r = [l for l in right_lines if y_s - 5 <= get_line_top(l) < y_e - 5]

                def split_header_body(lines_list, y_anchor):
                    hdr, body = [], []
                    in_body = False
                    for l in lines_list:
                        t = l['text'].strip()
                        top = get_line_top(l)
                        if in_body or t.startswith(('•', '●', '■', '▪', '·', '*', '-')) or top > y_anchor + 75:
                            in_body = True
                            body.append(l)
                        else:
                            hdr.append(l)
                    return hdr, body

                hdr_l, body_l = split_header_body(band_l, y_s)
                hdr_r, body_r = split_header_body(band_r, y_s)

                body_lines.extend(hdr_l)
                body_lines.extend(hdr_r)
                body_lines.extend(body_r)
                body_lines.extend(body_l)
        else:
            body_lines.extend(left_lines)
            body_lines.extend(right_lines)
    else:
        # Standard sidebar
        if gx < w * 0.5:
            body_lines.extend(left_lines)
            body_lines.extend(right_lines)
        else:
            body_lines.extend(left_lines)
            body_lines.extend(right_lines)

    return header_lines + body_lines


def locations(block, start=0, end=None):
    """Map a normalized block span back to original page rectangles/offsets."""
    end = len(block.text) if end is None else end
    result = []
    for part in getattr(block, 'source_parts', []):
        lo, hi = max(start, part['start']), min(end, part['end'])
        if lo >= hi or not block.text[lo:hi].strip(" •▪·-*\t"):
            continue
        line = part['line']
        a, b = lo - part['start'], hi - part['start']
        chars = [x for x in line['chars'][a:b] if x]
        loc = {'page': line['page'], 'text': block.text[lo:hi], 'block_id': block.id}
        if line.get('method') == 'ocr':
            loc['method'] = 'ocr'
        if line['width'] and chars:
            loc.update(kind='pdf', page_width=line['width'], page_height=line['height'],
                       bbox=[min(x['x0'] for x in chars), min(x['top'] for x in chars),
                             max(x['x1'] for x in chars), max(x['bottom'] for x in chars)])
        else:
            loc.update(kind='text', start=min((c['offset'] for c in chars), default=line['offset'] + a),
                       end=max((c['offset'] + 1 for c in chars), default=line['offset'] + b))
        result.append(loc)
    return result


def entity_span(text, entity):
    # Entity labels may omit punctuation. Resolve once during extraction and
    # keep the original offsets, never repeat this search in the viewer.
    indexes, letters = [], []
    for i, char in enumerate(text):
        if char.isalnum():
            letters.extend(char.casefold())
            indexes.extend([i] * len(char.casefold()))
    key = ''.join(char.casefold() for char in entity if char.isalnum())
    normalized = ''.join(letters)
    at = normalized.find(key) if key else -1
    if at < 0:
        return None
    return indexes[at], indexes[at + len(key) - 1] + 1


def event_source(ctx, event):
    if getattr(event, 'project_source', None):
        return event.project_source
    ent = ctx.entries_by_id().get(event.entry_id)
    blocks = ctx.blocks_by_id()
    mentions = [m for m in ctx.mentions if ent and m.entry_id == ent.id]
    # Date-bearing headers are the source of dated roles, even if segmentation
    # retained preceding wrapped descriptions in the same entry.
    bids = getattr(event, "header_block_ids", None) or list(dict.fromkeys(m.block_id for m in mentions if m.is_range))
    if not bids and ent:
        bids = ent.block_ids
    result = {'entry': [loc for bid in bids for loc in locations(blocks[bid])],
              'dates': [loc for m in mentions for loc in locations(blocks[m.block_id], m.char_start, m.char_end)],
              'company': [], 'title': [],
              'section': getattr(event, 'section', ''), 'date_label': getattr(event, 'date_label', ''),
              'is_present': getattr(event, 'is_present', False)}
    for field, value in [('company', event.org), ('title', event.title)]:
        if ent and value:
            for bid in bids:
                span = entity_span(blocks[bid].text, value)
                if span:
                    result[field].extend(locations(blocks[bid], *span))
                    break
    return result


def render_page(raw, page_number):
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(raw) as pdf:
        if not 1 <= page_number <= len(pdf):
            raise ValueError('page out of range')
        page = pdf[page_number - 1]
        try:
            # Extraction uses the MediaBox. Ignore a smaller viewer CropBox so
            # the image and saved coordinates have the same origin and scale.
            page.set_cropbox(*page.get_mediabox())
            width, height = page.get_size()
            bitmap = page.render(scale=120 / 72)
            try:
                out = io.BytesIO()
                bitmap.to_pil().save(out, format='PNG')
                return {'page': page_number, 'width': width, 'height': height,
                        'image': 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()}
            finally:
                bitmap.close()
        finally:
            page.close()


def attach_native_fragments(ctx):
    """Use original PDFium glyphs inside stored rectangles for native PDF links.

    A fragment is emitted only when its exact text is unique in the document.
    Ambiguous selectors fail closed; they must not highlight a different entry.
    """
    if not ctx.raw_bytes.startswith(b'%PDF-'):
        return
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(ctx.raw_bytes) as pdf:
        pages, texts = [], []
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                page.set_cropbox(*page.get_mediabox())
                textpage = page.get_textpage()
                pages.append((page, textpage))
                texts.append(' '.join(textpage.get_text_range().split()))
            all_text = '\n'.join(texts)
            for event in ctx.events:
                for field in ('entry','dates','company','title'):
                    for loc in event.source.get(field, []):
                        if loc.get('kind') != 'pdf':
                            continue
                        page, textpage = pages[loc['page'] - 1]
                        x0, top, x1, bottom = loc['bbox']
                        native = ' '.join(textpage.get_text_bounded(
                            left=x0, bottom=page.get_height()-bottom,
                            right=x1, top=page.get_height()-top).split())
                        if native and all_text.count(native) == 1:
                            loc['fragment_text'] = native
        finally:
            for page, textpage in pages:
                textpage.close()
                page.close()
