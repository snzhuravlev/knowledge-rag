from pathlib import Path
from typing import List

from docx import Document
from ebooklib import epub
from lxml import etree
from pypdf import PdfReader


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\r", " ").split())


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: List[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)
    return normalize_text("\n\n".join(parts))


def extract_text_from_docx(path: Path) -> str:
    doc = Document(str(path))
    parts: List[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    return normalize_text("\n\n".join(parts))


def extract_text_from_epub(path: Path) -> str:
    book = epub.read_epub(str(path))
    parts: List[str] = []
    for item in book.get_items():
        if item.get_type() == epub.ITEM_DOCUMENT:
            html = item.get_body_content().decode("utf-8", errors="ignore")
            root = etree.HTML(html)
            if root is not None:
                text = " ".join(root.itertext())
                if text.strip():
                    parts.append(text)
    return normalize_text("\n\n".join(parts))


def extract_text_from_fb2(path: Path) -> str:
    parser = etree.XMLParser(recover=True)
    tree = etree.parse(str(path), parser=parser)
    root = tree.getroot()
    texts: List[str] = []
    for body in root.findall(".//{*}body"):
        for p in body.iterfind(".//{*}p"):
            if p.text:
                texts.append(p.text)
    return normalize_text("\n\n".join(texts))


def extract_text_from_txt(path: Path) -> str:
    data = path.read_text(encoding="utf-8", errors="ignore")
    return normalize_text(data)


def split_into_chunks(text: str, max_chars: int = 2000, overlap: int = 200) -> List[str]:
    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        chunk = text[start:end]
        chunks.append(chunk.strip())
        if end == length:
            break
        start = max(0, end - overlap)
    return [c for c in chunks if c]
