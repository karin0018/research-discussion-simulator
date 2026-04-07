from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DATA_DIR = APP_DIR / "data"
STATIC_DIR = APP_DIR / "static"

UPLOAD_DIR = DATA_DIR / "uploads"
MEMORY_DIR = DATA_DIR / "memory"
CONVERSATION_DIR = DATA_DIR / "conversations"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
USER_PROFILE_PATH = DATA_DIR / "user_profile.json"

LLM_CONFIG_PATH = PROJECT_DIR / "llm_config.json"

LLM_SERVICE_PRESETS: Dict[str, Dict[str, Any]] = {
    "codex": {
        "label": "Codex",
        "provider": "codex_cli",
        "models": ["gpt-5.4", "gpt-5", "gpt-5-mini"],
        "default_model": "gpt-5.4",
        "cli_command": ["codex", "exec", "--skip-git-repo-check", "{combined_prompt}"],
        "cli_timeout_seconds": 180,
    },
    "claude": {
        "label": "Claude",
        "provider": "claude_cli",
        "models": ["claude-sonnet", "claude-opus"],
        "default_model": "claude-sonnet",
        "cli_command": ["claude", "-p", "{combined_prompt}"],
        "cli_timeout_seconds": 180,
    },
}


def _load_file_config() -> Dict[str, Any]:
    if not LLM_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def get_llm_settings() -> Dict[str, str]:
    file_config = _load_file_config()
    selected_service = str(file_config.get("service") or "").strip()
    preset = LLM_SERVICE_PRESETS.get(selected_service, {})
    provider = str(file_config.get("provider", "openai_compatible")).strip()
    api_key = str(file_config.get("api_key") or os.getenv("OPENAI_API_KEY", "")).strip()
    model = str(file_config.get("model") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")).strip()
    base_url = str(file_config.get("base_url") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).strip()
    cli_command = file_config.get("cli_command") or []
    cli_timeout_seconds = str(file_config.get("cli_timeout_seconds", 180)).strip()
    if preset:
        provider = str(preset["provider"])
        model = str(file_config.get("model") or preset.get("default_model") or model).strip()
        cli_command = file_config.get("cli_command") or list(preset.get("cli_command") or [])
        cli_timeout_seconds = str(file_config.get("cli_timeout_seconds") or preset.get("cli_timeout_seconds", 180)).strip()
    return {
        "service": selected_service,
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "cli_timeout_seconds": cli_timeout_seconds,
        "cli_command": cli_command,
    }


def ensure_directories() -> None:
    for path in [DATA_DIR, STATIC_DIR, UPLOAD_DIR, MEMORY_DIR, CONVERSATION_DIR, KNOWLEDGE_DIR]:
        path.mkdir(parents=True, exist_ok=True)
