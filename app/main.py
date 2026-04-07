from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agents import (
    agent_exists,
    create_custom_agent,
    delete_custom_agent,
    get_agent_llm_config,
    get_user_profile,
    list_agents,
    update_agent_llm_config,
    update_custom_agent,
    update_user_profile,
)
from .config import LLM_CONFIG_PATH, LLM_SERVICE_PRESETS, STATIC_DIR, ensure_directories, get_llm_settings
from .knowledge import add_knowledge_text, extract_text_from_upload, persist_uploaded_file
from .models import ChatRequest, CreateAgentRequest, KnowledgeUploadResponse, UpdateAgentLLMRequest, UpdateUserProfileRequest
from .orchestrator import DiscussionOrchestrator


ensure_directories()
app = FastAPI(title="Research Discussion Simulator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

orchestrator = DiscussionOrchestrator()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/agents")
def get_agents() -> List[Dict[str, Any]]:
    return [agent.model_dump() for agent in list_agents()]


@app.get("/api/provider-status")
def get_provider_status() -> Dict[str, Any]:
    return orchestrator.llm.status()


@app.get("/api/user-profile")
def read_user_profile() -> Dict[str, Any]:
    return get_user_profile().model_dump()


@app.put("/api/user-profile")
def save_user_profile_card(request: UpdateUserProfileRequest) -> Dict[str, Any]:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not request.title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    if not request.style.strip():
        raise HTTPException(status_code=400, detail="style is required")
    if not request.objective.strip():
        raise HTTPException(status_code=400, detail="objective is required")
    return update_user_profile(request).model_dump()


@app.get("/api/god-view")
def get_god_view(conversation_id: Optional[str] = None) -> Dict[str, Any]:
    return orchestrator.get_role_view(conversation_id=conversation_id)


@app.get("/api/llm-config")
def get_llm_config() -> Dict[str, Any]:
    settings = get_llm_settings()
    # never expose api_key to frontend
    return {k: v for k, v in settings.items() if k != "api_key"}


@app.get("/api/llm-services")
def get_llm_services() -> Dict[str, Any]:
    return {
        "services": [
            {
                "service_id": service_id,
                "label": preset["label"],
                "provider": preset["provider"],
                "models": preset["models"],
                "default_model": preset["default_model"],
            }
            for service_id, preset in LLM_SERVICE_PRESETS.items()
        ]
    }


@app.post("/api/llm-config")
def save_llm_config(body: Dict[str, Any]) -> Dict[str, Any]:
    service = str(body.get("service") or "").strip()
    if service and service not in LLM_SERVICE_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown llm service: {service}")

    current: Dict[str, Any] = {}
    if LLM_CONFIG_PATH.exists():
        try:
            current = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    if service:
        preset = LLM_SERVICE_PRESETS[service]
        model = str(body.get("model") or preset["default_model"]).strip()
        if model not in preset["models"]:
            raise HTTPException(status_code=400, detail=f"Unsupported model for {service}: {model}")
        current = {
            "service": service,
            "provider": preset["provider"],
            "model": model,
            "cli_command": list(preset["cli_command"]),
            "cli_timeout_seconds": int(preset["cli_timeout_seconds"]),
        }
    else:
        allowed = {"provider", "model", "base_url", "api_key", "cli_command", "cli_timeout_seconds"}
        for key in allowed:
            if key in body:
                current[key] = body[key]

    LLM_CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    # reload orchestrator llm client
    from .llm import LLMClient
    orchestrator.llm = LLMClient()
    return {"status": "saved"}


@app.post("/api/agents")
def create_agent(request: CreateAgentRequest) -> Dict[str, Any]:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not request.title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    if not request.style.strip():
        raise HTTPException(status_code=400, detail="style is required")
    if not request.objective.strip():
        raise HTTPException(status_code=400, detail="objective is required")
    profile = create_custom_agent(
        name=request.name,
        title=request.title,
        expertise=request.expertise,
        style=request.style,
        objective=request.objective,
    )
    return profile.model_dump()


@app.put("/api/agents/{agent_id}")
def update_agent(agent_id: str, request: CreateAgentRequest) -> Dict[str, Any]:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if not request.title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    if not request.style.strip():
        raise HTTPException(status_code=400, detail="style is required")
    if not request.objective.strip():
        raise HTTPException(status_code=400, detail="objective is required")
    try:
        profile = update_custom_agent(
            agent_id=agent_id,
            name=request.name,
            title=request.title,
            expertise=request.expertise,
            style=request.style,
            objective=request.objective,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown custom agent: {agent_id}") from exc
    return profile.model_dump()


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str) -> Dict[str, str]:
    deleted = delete_custom_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Unknown custom agent: {agent_id}")
    return {"status": "deleted", "agent_id": agent_id}


@app.get("/api/agents/{agent_id}/llm-config")
def read_agent_llm(agent_id: str) -> Dict[str, Any]:
    if not agent_exists(agent_id):
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    return get_agent_llm_config(agent_id)


@app.put("/api/agents/{agent_id}/llm-config")
def save_agent_llm(agent_id: str, request: UpdateAgentLLMRequest) -> Dict[str, Any]:
    try:
        profile = update_agent_llm_config(agent_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return profile.model_dump()


@app.get("/api/conversations")
def get_conversations() -> List[Dict[str, Any]]:
    return orchestrator.list_conversations()


@app.post("/api/conversations")
def create_conversation(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = body or {}
    created = orchestrator.create_conversation(
        mode=str(payload.get("mode") or "one_to_one"),
        selected_agents=list(payload.get("selected_agents") or []),
        memory_enabled=bool(payload.get("memory_enabled", True)),
    )
    return created


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> Dict[str, Any]:
    return orchestrator.get_conversation(conversation_id)


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> Dict[str, str]:
    deleted = orchestrator.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Unknown conversation: {conversation_id}")
    return {"status": "deleted", "conversation_id": conversation_id}


@app.post("/api/chat")
def chat(request: ChatRequest) -> Dict[str, Any]:
    if not request.selected_agents:
        raise HTTPException(status_code=400, detail="At least one agent must be selected.")
    for agent_id in request.selected_agents:
        if not agent_exists(agent_id):
            raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    turn = orchestrator.run_turn(request)
    return turn.model_dump()


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    if not request.selected_agents:
        raise HTTPException(status_code=400, detail="At least one agent must be selected.")
    for agent_id in request.selected_agents:
        if not agent_exists(agent_id):
            raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")

    def event_stream():
        try:
            for event in orchestrator.stream_turn(request):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "detail": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/chat/upload")
async def chat_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Extract text from an uploaded file for inline use in chat."""
    filename = file.filename or "untitled"
    if not any(filename.endswith(ext) for ext in (".txt", ".md", ".pdf", ".docx", ".doc")):
        raise HTTPException(status_code=400, detail="Only .txt, .md, .pdf, .docx and .doc files are supported.")
    data = await file.read()
    try:
        text = extract_text_from_upload(filename=filename, data=data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {exc}") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="The file did not contain extractable text.")
    return {"filename": filename, "text": text}


@app.post("/api/knowledge/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge(
    file: UploadFile = File(...),
    scope: str = Form(...),
    agent_id: Optional[str] = Form(default=None),
) -> KnowledgeUploadResponse:
    filename = file.filename or "untitled.txt"
    if not any(filename.endswith(ext) for ext in (".txt", ".md", ".pdf", ".docx", ".doc")):
        raise HTTPException(status_code=400, detail="Only .txt, .md, .pdf, .docx and .doc files are supported.")
    if scope not in {"global", "agent"}:
        raise HTTPException(status_code=400, detail="scope must be global or agent")
    if scope == "agent" and not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required for agent scope")
    if agent_id and not agent_exists(agent_id):
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")

    data = await file.read()
    persist_uploaded_file(filename=filename, data=data)
    try:
        text = extract_text_from_upload(filename=filename, data=data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse uploaded file: {exc}") from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="The uploaded file did not contain extractable text.")

    entry_id, chunks = add_knowledge_text(
        title=filename,
        text=text,
        source_filename=filename,
        scope=scope,
        agent_id=agent_id,
    )
    return KnowledgeUploadResponse(
        entry_id=entry_id,
        filename=filename,
        scope=scope,
        agent_id=agent_id,
        chunks=chunks,
    )
