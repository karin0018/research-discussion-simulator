from __future__ import annotations

import re
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .config import KNOWLEDGE_DIR, UPLOAD_DIR
from .models import KnowledgeEntry
from .storage import read_json, write_json


CHUNK_SIZE = 900
CHUNK_OVERLAP = 150


def _knowledge_index_path() -> Path:
    return KNOWLEDGE_DIR / "knowledge_index.json"


def _normalize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]+", text.lower())


def _chunk_text(text: str) -> List[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + CHUNK_SIZE)
        chunks.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = max(start + CHUNK_SIZE - CHUNK_OVERLAP, start + 1)
    return chunks


def load_entries() -> List[Dict[str, Any]]:
    return read_json(_knowledge_index_path(), [])


def save_entries(entries: List[Dict[str, Any]]) -> None:
    write_json(_knowledge_index_path(), entries)


def add_knowledge_text(
    title: str,
    text: str,
    source_filename: str,
    scope: str,
    agent_id: Optional[str] = None,
) -> Tuple[str, int]:
    entry_id = str(uuid4())
    chunks = _chunk_text(text)
    index = load_entries()

    for idx, chunk in enumerate(chunks):
        entry = KnowledgeEntry(
            entry_id=f"{entry_id}:{idx}",
            title=title,
            scope=scope,
            agent_id=agent_id,
            text=chunk,
            source_filename=source_filename,
        )
        index.append(entry.model_dump())

    save_entries(index)
    return entry_id, len(chunks)


def persist_uploaded_file(filename: str, data: bytes) -> Path:
    safe_name = f"{uuid4()}_{Path(filename).name}"
    path = UPLOAD_DIR / safe_name
    path.write_bytes(data)
    return path


def extract_text_from_upload(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        return data.decode("utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError(
                "PDF support requires pypdf. Please run: pip install pypdf"
            ) from exc
        reader = PdfReader(BytesIO(data))
        pages: List[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages).strip()
    if suffix in {".docx", ".doc"}:
        try:
            from docx import Document
        except ImportError as exc:
            raise ValueError(
                "Word support requires python-docx. Please run: pip install python-docx"
            ) from exc
        doc = Document(BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs).strip()
    raise ValueError("Unsupported file type")


def search_knowledge(query: str, agent_id: Optional[str] = None, limit: int = 4) -> List[Dict[str, Any]]:
    tokens = _normalize(query)
    if not tokens:
        return []

    query_counter = Counter(tokens)
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for entry in load_entries():
        if entry["scope"] == "agent" and entry.get("agent_id") != agent_id:
            continue
        chunk_counter = Counter(_normalize(entry["text"]))
        score = sum(min(query_counter[token], chunk_counter[token]) for token in query_counter)
        if score > 0:
            candidates.append((score, entry))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in candidates[:limit]]


def delete_agent_knowledge(agent_id: str) -> int:
    entries = load_entries()
    retained = [
        entry for entry in entries
        if not (entry.get("scope") == "agent" and entry.get("agent_id") == agent_id)
    ]
    removed = len(entries) - len(retained)
    if removed:
        save_entries(retained)
    return removed
