"""Document management endpoints — upload, list, get, delete, download, search, summarize."""
import os
import uuid
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import require_role
from app.ai.llm_providers import call_llm

logger = logging.getLogger("stratroom.documents")

router = APIRouter(prefix="/documents", tags=["documents"])

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "storage", "documents")
ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx"}
MAX_DOC_SIZE_MB = 20
os.makedirs(STORAGE_DIR, exist_ok=True)


def _safe_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    safe = uuid.uuid4().hex[:16]
    return f"{safe}.{ext}" if ext else safe


def _validate_storage_path(path: str) -> str:
    """Ensure storage path doesn't escape the storage directory."""
    real_storage = os.path.realpath(STORAGE_DIR)
    real_path = os.path.realpath(path)
    if not real_path.startswith(real_storage + os.sep) and real_path != real_storage:
        raise ValueError("Path traversal detected")
    return real_path


async def _extract_text(content: bytes, ext: str) -> str:
    """Best-effort text extraction. Returns empty string on failure."""
    if ext == "pdf":
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            text_parts = [page.get_text() for page in doc]
            doc.close()
            return "\n".join(text_parts)[:50000]
        except Exception:
            return ""
    elif ext == "docx":
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)[:50000]
        except Exception:
            return ""
    elif ext == "xlsx":
        try:
            from openpyxl import load_workbook
            import io
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            parts = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                for row in ws.iter_rows(values_only=True):
                    parts.append(" | ".join(str(c) if c is not None else "" for c in row))
            wb.close()
            return "\n".join(parts)[:50000]
        except Exception:
            return ""
    return ""


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]

    filename = file.filename or "document"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"File type '.{ext}' not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    content = await file.read()
    max_bytes = MAX_DOC_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_DOC_SIZE_MB}MB limit")

    if not content:
        raise HTTPException(status_code=422, detail="Empty file")

    safe_name = _safe_filename(filename)
    storage_path = os.path.join(STORAGE_DIR, safe_name)
    _validate_storage_path(storage_path)

    with open(storage_path, "wb") as f:
        f.write(content)

    extracted = await _extract_text(content, ext)

    result = await db.execute(
        text(
            "INSERT INTO documents (org_id, user_id, filename, original_filename, content_type, file_size, extracted_text, storage_path) "
            "VALUES (:org_id, :user_id, :filename, :original, :ctype, :size, :text, :path) RETURNING id"
        ),
        {
            "org_id": org_id,
            "user_id": user_id,
            "filename": safe_name,
            "original": filename,
            "ctype": file.content_type or f"application/{ext}",
            "size": len(content),
            "text": extracted,
            "path": storage_path,
        },
    )
    await db.commit()
    doc_id = result.scalar()

    logger.info("Document uploaded: id=%s user=%s file=%s size=%d", doc_id, user_id, filename, len(content))

    return {
        "id": doc_id,
        "filename": filename,
        "size": len(content),
        "content_type": file.content_type,
        "has_extracted_text": bool(extracted),
    }


@router.get("")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT d.id, d.original_filename, d.content_type, d.file_size, d.created_at, "
                "u.full_name AS uploaded_by "
                "FROM documents d LEFT JOIN users u ON d.user_id = u.id "
                "WHERE d.org_id = :org_id ORDER BY d.created_at DESC LIMIT 100"
            ),
            {"org_id": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT d.id, d.original_filename, d.content_type, d.file_size, d.created_at, "
                "u.full_name AS uploaded_by "
                "FROM documents d LEFT JOIN users u ON d.user_id = u.id "
                "WHERE d.org_id = :org_id AND d.user_id = :user_id ORDER BY d.created_at DESC LIMIT 100"
            ),
            {"org_id": org_id, "user_id": user_id},
        )
    rows = result.mappings().all()
    return {"documents": [dict(r) for r in rows]}


@router.get("/search")
async def search_documents(
    q: str = Query(..., min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]
    search_term = f"%{q}%"

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT d.id, d.original_filename, d.content_type, d.file_size, d.created_at, "
                "u.full_name AS uploaded_by "
                "FROM documents d LEFT JOIN users u ON d.user_id = u.id "
                "WHERE d.org_id = :org_id "
                "AND (d.original_filename ILIKE :q OR d.extracted_text ILIKE :q "
                "OR EXISTS (SELECT 1 FROM document_summaries ds WHERE ds.document_id = d.id AND ds.summary ILIKE :q)) "
                "ORDER BY d.created_at DESC LIMIT 50"
            ),
            {"org_id": org_id, "q": search_term},
        )
    else:
        result = await db.execute(
            text(
                "SELECT d.id, d.original_filename, d.content_type, d.file_size, d.created_at, "
                "u.full_name AS uploaded_by "
                "FROM documents d LEFT JOIN users u ON d.user_id = u.id "
                "WHERE d.org_id = :org_id AND d.user_id = :user_id "
                "AND (d.original_filename ILIKE :q OR d.extracted_text ILIKE :q "
                "OR EXISTS (SELECT 1 FROM document_summaries ds WHERE ds.document_id = d.id AND ds.summary ILIKE :q)) "
                "ORDER BY d.created_at DESC LIMIT 50"
            ),
            {"org_id": org_id, "user_id": user_id, "q": search_term},
        )
    rows = result.mappings().all()
    return {"documents": [dict(r) for r in rows], "query": q}


@router.get("/{document_id}")
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT d.id, d.original_filename, d.content_type, d.file_size, d.extracted_text, "
                "d.created_at, u.full_name AS uploaded_by "
                "FROM documents d LEFT JOIN users u ON d.user_id = u.id "
                "WHERE d.id = :did AND d.org_id = :org_id"
            ),
            {"did": document_id, "org_id": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT d.id, d.original_filename, d.content_type, d.file_size, d.extracted_text, "
                "d.created_at, u.full_name AS uploaded_by "
                "FROM documents d LEFT JOIN users u ON d.user_id = u.id "
                "WHERE d.id = :did AND d.org_id = :org_id AND d.user_id = :user_id"
            ),
            {"did": document_id, "org_id": org_id, "user_id": user_id},
        )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    summaries_result = await db.execute(
        text(
            "SELECT id, summary, provider, model, created_at "
            "FROM document_summaries WHERE document_id = :did ORDER BY created_at DESC"
        ),
        {"did": document_id},
    )
    summaries = [dict(r) for r in summaries_result.mappings().all()]

    doc = dict(row)
    doc["summaries"] = summaries
    return doc


@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    from fastapi.responses import FileResponse

    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT original_filename, storage_path, content_type "
                "FROM documents WHERE id = :did AND org_id = :org_id"
            ),
            {"did": document_id, "org_id": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT original_filename, storage_path, content_type "
                "FROM documents WHERE id = :did AND org_id = :org_id AND user_id = :user_id"
            ),
            {"did": document_id, "org_id": org_id, "user_id": user_id},
        )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    path = row["storage_path"]
    _validate_storage_path(path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=path,
        filename=row["original_filename"],
        media_type=row["content_type"],
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("manager")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]

    if is_admin:
        result = await db.execute(
            text("SELECT storage_path FROM documents WHERE id = :did AND org_id = :org_id"),
            {"did": document_id, "org_id": org_id},
        )
    else:
        result = await db.execute(
            text("SELECT storage_path FROM documents WHERE id = :did AND org_id = :org_id AND user_id = :user_id"),
            {"did": document_id, "org_id": org_id, "user_id": user_id},
        )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found or not yours to delete")

    try:
        path = row["storage_path"]
        _validate_storage_path(path)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        logger.warning("Failed to delete file from disk: %s", row["storage_path"])

    await db.execute(text("DELETE FROM document_summaries WHERE document_id = :did"), {"did": document_id})
    await db.execute(text("DELETE FROM documents WHERE id = :did AND org_id = :org_id"), {"did": document_id, "org_id": org_id})
    await db.commit()
    return {"ok": True}


class SummarizeRequest(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    model: str = "gpt-4o-mini"

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in settings.ALLOWED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {v}. Allowed: {', '.join(sorted(settings.ALLOWED_PROVIDERS))}")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Model name is required")
        if len(v) > 200:
            raise ValueError("Model name too long")
        return v


@router.post("/{document_id}/summarize")
async def summarize_document(
    document_id: int,
    req: SummarizeRequest,
    db: AsyncSession = Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    user_id = ctx["user_id"]
    org_id = ctx["org_id"]
    is_admin = ctx["is_admin"]
    is_manager = ctx["is_manager"]

    if is_admin or is_manager:
        result = await db.execute(
            text(
                "SELECT original_filename, extracted_text FROM documents "
                "WHERE id = :did AND org_id = :org_id"
            ),
            {"did": document_id, "org_id": org_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT original_filename, extracted_text FROM documents "
                "WHERE id = :did AND org_id = :org_id AND user_id = :user_id"
            ),
            {"did": document_id, "org_id": org_id, "user_id": user_id},
        )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    text_content = row["extracted_text"] or ""
    if not text_content.strip():
        raise HTTPException(status_code=422, detail="No extractable text found in this document")

    truncated = text_content[:15000]
    system_prompt = (
        "You are a document summarization assistant for StratRoom, an enterprise governance platform. "
        "Provide a concise, structured summary of the document. Include: "
        "1) Document type and purpose, "
        "2) Key points and findings, "
        "3) Action items or recommendations if any. "
        "Format with clear headers and bullet points."
    )

    try:
        summary = await call_llm(
            provider=req.provider,
            api_key=req.api_key,
            model=req.model,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": f"Summarize this document ({row['original_filename']}):\n\n{truncated}"}],
            max_tokens=2048,
        )
    except Exception:
        logger.exception("Document summarization failed [doc=%s user=%s]", document_id, user_id)
        raise HTTPException(status_code=502, detail="Summarization failed")

    await db.execute(
        text(
            "INSERT INTO document_summaries (document_id, summary, provider, model) "
            "VALUES (:did, :summary, :provider, :model)"
        ),
        {"did": document_id, "summary": summary[:10000], "provider": req.provider, "model": req.model},
    )
    await db.commit()

    return {"summary": summary, "provider": req.provider, "model": req.model}
