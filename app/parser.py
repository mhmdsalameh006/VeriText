import io
from pathlib import Path
from fastapi import HTTPException
from .config import MAX_TEXT_CHARS, MAX_UPLOAD_BYTES

ALLOWED = {'.txt', '.md', '.pdf', '.docx'}


def extract(data: bytes, filename: str) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, 'File exceeds 12 MB limit')
    ext = Path(filename or '').suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(415, 'Supported files: TXT, MD, PDF, DOCX')
    try:
        if ext in ('.txt', '.md'):
            text = data.decode('utf-8-sig')
        elif ext == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data), strict=False)
            if len(reader.pages) > 200:
                raise HTTPException(422, 'PDF exceeds 200-page limit')
            if reader.is_encrypted:
                raise HTTPException(422, 'Encrypted PDFs are not supported')
            text = '\n\n'.join(page.extract_text() or '' for page in reader.pages)
        else:
            from docx import Document
            doc = Document(io.BytesIO(data))
            paragraphs = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    paragraphs.append(' | '.join(cell.text for cell in row.cells))
            text = '\n'.join(paragraphs)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f'Cannot read file: {type(exc).__name__}') from exc
    return validate_text(text)


def validate_text(text: str):
    if not isinstance(text, str):
        raise HTTPException(422, 'Text is required')
    text = text.replace('\x00', '').replace('\r\n', '\n').strip()
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(413, f'Text exceeds {MAX_TEXT_CHARS:,} character limit')
    if len(text.split()) < 12:
        raise HTTPException(422, 'At least 12 words are required')
    return text
