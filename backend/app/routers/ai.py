from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, field_validator
from typing import Optional
import httpx

from app.core.config import settings
from app.core.deps import require_role
from app.ai.llm_providers import call_llm

router = APIRouter(tags=["ai"])

ALLOWED_UPLOAD_EXTENSIONS = {
    "csv", "txt", "json", "md", "log", "xml", "html", "css", "js",
    "py", "sql", "yaml", "yml", "toml", "ini", "cfg", "env", "tsv",
}


class ChatRequest(BaseModel):
    provider: str
    api_key: str
    model: str
    system_prompt: str
    user_message: str
    max_tokens: int = 2048
    base_url: Optional[str] = None

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
        if len(v) > 200:
            raise ValueError("Model name too long")
        if not v:
            raise ValueError("Model name is required")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: str) -> str:
        if len(v) > settings.MAX_PROMPT_LENGTH:
            raise ValueError(f"System prompt exceeds maximum length of {settings.MAX_PROMPT_LENGTH}")
        return v

    @field_validator("user_message")
    @classmethod
    def validate_user_message(cls, v: str) -> str:
        if len(v) > settings.MAX_PROMPT_LENGTH:
            raise ValueError(f"User message exceeds maximum length of {settings.MAX_PROMPT_LENGTH}")
        if not v.strip():
            raise ValueError("User message cannot be empty")
        return v

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        if v < 1 or v > 16384:
            raise ValueError("max_tokens must be between 1 and 16384")
        return v


@router.post("/ai/chat")
async def ai_chat(req: ChatRequest, ctx: dict = Depends(require_role("member"))):
    messages = [{"role": "user", "content": req.user_message}]

    try:
        result_text = await call_llm(
            provider=req.provider,
            api_key=req.api_key,
            model=req.model,
            system_prompt=req.system_prompt,
            messages=messages,
            max_tokens=req.max_tokens,
            base_url=req.base_url,
        )
        return {"text": result_text}

    except HTTPException:
        raise
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="LLM provider returned an error")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to reach LLM provider")


@router.post("/ai/upload")
async def ai_upload(
    files: list[UploadFile] = File(...),
    ctx: dict = Depends(require_role("member")),
):
    if len(files) > settings.MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Too many files. Maximum is {settings.MAX_UPLOAD_FILES}",
        )

    results = []
    for f in files:
        ext = (f.filename or "").rsplit(".", 1)[-1].lower()
        if ext and ext not in ALLOWED_UPLOAD_EXTENSIONS and ext not in {
            "png", "jpg", "jpeg", "gif", "pdf", "docx", "xlsx", "pptx",
        }:
            raise HTTPException(status_code=422, detail=f"File type '.{ext}' is not allowed")

        content_bytes = await f.read()
        if len(content_bytes) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File '{f.filename}' exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit",
            )

        text_content = ""
        if ext in ALLOWED_UPLOAD_EXTENSIONS:
            try:
                text_content = content_bytes.decode("utf-8")[:10000]
            except UnicodeDecodeError:
                try:
                    text_content = content_bytes.decode("latin-1")[:10000]
                except Exception:
                    text_content = "[Could not decode file]"
        else:
            text_content = f"[Binary file: {f.content_type} - {len(content_bytes)} bytes]"

        results.append({
            "name": f.filename,
            "size": len(content_bytes),
            "type": f.content_type,
            "content": text_content,
        })

    return {"files": results, "count": len(results)}
