from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from .config import DATA_DIR, LLM_SERVICE_PRESETS, MEMORY_DIR, USER_PROFILE_PATH
from .knowledge import delete_agent_knowledge
from .models import AgentProfile, UpdateAgentLLMRequest, UpdateUserProfileRequest, UserProfile
from .storage import read_json, write_json


CUSTOM_AGENTS_PATH = DATA_DIR / "custom_agents.json"
AGENT_LLM_CONFIG_PATH = DATA_DIR / "agent_llm_config.json"
DEFAULT_USER_PROFILE = UserProfile()

BUILTIN_AGENTS: Dict[str, AgentProfile] = {
    "advisor": AgentProfile(
        agent_id="advisor",
        name="Prof. Lin",
        title="导师型 PI",
        expertise=["研究问题定义", "论文贡献设计", "实验路线规划", "科研叙事"],
        style="冷静、严格、鼓励式追问，强调研究价值和可落地性。",
        objective="帮助学生把模糊想法打磨成可执行、可验证、可发表的研究方案。",
    ),
    "peer_ml": AgentProfile(
        agent_id="peer_ml",
        name="Dr. Chen",
        title="同方向同行",
        expertise=["机器学习方法", "实验设计", "基线比较", "消融实验"],
        style="技术细节导向，习惯拆解方法假设和实现细节。",
        objective="检查方法是否扎实、实验是否公平、结论是否足够可信。",
    ),
    "cross_domain": AgentProfile(
        agent_id="cross_domain",
        name="Dr. Rivera",
        title="跨方向研究者",
        expertise=["跨学科迁移", "问题重构", "应用场景创新", "系统视角"],
        style="发散、类比丰富、善于把别的领域方法迁移过来。",
        objective="提供不同学科的视角，帮助打开新的方法与应用空间。",
    ),
    "skeptic": AgentProfile(
        agent_id="skeptic",
        name="Reviewer K",
        title="审稿人型批判者",
        expertise=["漏洞排查", "可证伪性", "失败模式", "评审标准"],
        style="尖锐直接，优先指出薄弱点、风险和可能被拒稿的原因。",
        objective="尽早暴露方案中的不充分之处，提升最终方案的稳健性。",
    ),
}


def _load_custom_agents() -> Dict[str, AgentProfile]:
    payload = read_json(CUSTOM_AGENTS_PATH, [])
    agents: Dict[str, AgentProfile] = {}
    for item in payload:
        profile = AgentProfile(**item)
        profile.is_custom = True
        agents[profile.agent_id] = profile
    return agents


def _save_custom_agents(agents: Dict[str, AgentProfile]) -> None:
    payload = [agent.model_dump() for agent in agents.values()]
    write_json(CUSTOM_AGENTS_PATH, payload)


def _load_agent_llm_overrides() -> Dict[str, Dict[str, str]]:
    return read_json(AGENT_LLM_CONFIG_PATH, {})


def _save_agent_llm_overrides(payload: Dict[str, Dict[str, str]]) -> None:
    write_json(AGENT_LLM_CONFIG_PATH, payload)


def _apply_llm_overrides(profile: AgentProfile, overrides: Dict[str, Dict[str, str]]) -> AgentProfile:
    override = overrides.get(profile.agent_id, {})
    if override:
        profile.llm_service = override.get("service")
        profile.llm_model = override.get("model")
    return profile


def _build_custom_agent_id(name: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    normalized = "_".join(part for part in normalized.split("_") if part)
    if not normalized:
        normalized = "custom_agent"
    return "custom_{name}_{suffix}".format(name=normalized, suffix=uuid4().hex[:8])


def list_agents() -> List[AgentProfile]:
    custom_agents = _load_custom_agents()
    overrides = _load_agent_llm_overrides()
    builtin = [
        _apply_llm_overrides(AgentProfile(**agent.model_dump()), overrides)
        for agent in BUILTIN_AGENTS.values()
    ]
    custom = [
        _apply_llm_overrides(AgentProfile(**agent.model_dump()), overrides)
        for agent in custom_agents.values()
    ]
    return builtin + custom


def agent_exists(agent_id: str) -> bool:
    return agent_id in BUILTIN_AGENTS or agent_id in _load_custom_agents()


def get_agent(agent_id: str) -> AgentProfile:
    overrides = _load_agent_llm_overrides()
    if agent_id in BUILTIN_AGENTS:
        return _apply_llm_overrides(AgentProfile(**BUILTIN_AGENTS[agent_id].model_dump()), overrides)
    custom_agents = _load_custom_agents()
    return _apply_llm_overrides(AgentProfile(**custom_agents[agent_id].model_dump()), overrides)


def create_custom_agent(
    name: str,
    title: str,
    expertise: List[str],
    style: str,
    objective: str,
) -> AgentProfile:
    custom_agents = _load_custom_agents()
    profile = AgentProfile(
        agent_id=_build_custom_agent_id(name),
        name=name.strip(),
        title=title.strip(),
        expertise=[item.strip() for item in expertise if item.strip()],
        style=style.strip(),
        objective=objective.strip(),
        is_custom=True,
    )
    custom_agents[profile.agent_id] = profile
    _save_custom_agents(custom_agents)
    return profile


def update_custom_agent(
    agent_id: str,
    name: str,
    title: str,
    expertise: List[str],
    style: str,
    objective: str,
) -> AgentProfile:
    custom_agents = _load_custom_agents()
    if agent_id not in custom_agents:
        raise KeyError(agent_id)
    profile = AgentProfile(
        agent_id=agent_id,
        name=name.strip(),
        title=title.strip(),
        expertise=[item.strip() for item in expertise if item.strip()],
        style=style.strip(),
        objective=objective.strip(),
        is_custom=True,
    )
    custom_agents[agent_id] = profile
    _save_custom_agents(custom_agents)
    return profile


def delete_custom_agent(agent_id: str) -> bool:
    custom_agents = _load_custom_agents()
    if agent_id not in custom_agents:
        return False
    del custom_agents[agent_id]
    _save_custom_agents(custom_agents)
    memory_path = MEMORY_DIR / f"{agent_id}.json"
    if memory_path.exists():
        memory_path.unlink()
    overrides = _load_agent_llm_overrides()
    if agent_id in overrides:
        del overrides[agent_id]
        _save_agent_llm_overrides(overrides)
    delete_agent_knowledge(agent_id)
    return True


def update_agent_llm_config(agent_id: str, request: UpdateAgentLLMRequest) -> AgentProfile:
    if not agent_exists(agent_id):
        raise KeyError(agent_id)

    service = (request.service or "").strip()
    model = (request.model or "").strip()
    overrides = _load_agent_llm_overrides()

    if not service and not model:
        overrides.pop(agent_id, None)
        _save_agent_llm_overrides(overrides)
        return get_agent(agent_id)

    if service not in LLM_SERVICE_PRESETS:
        raise ValueError(f"Unknown llm service: {service}")
    preset = LLM_SERVICE_PRESETS[service]
    if model not in preset["models"]:
        raise ValueError(f"Unsupported model for {service}: {model}")

    overrides[agent_id] = {
        "service": service,
        "model": model,
    }
    _save_agent_llm_overrides(overrides)
    return get_agent(agent_id)


def get_agent_llm_config(agent_id: str) -> Dict[str, Optional[str]]:
    overrides = _load_agent_llm_overrides()
    payload = overrides.get(agent_id, {})
    return {
        "service": payload.get("service"),
        "model": payload.get("model"),
    }


def get_user_profile() -> UserProfile:
    payload = read_json(USER_PROFILE_PATH, DEFAULT_USER_PROFILE.model_dump())
    return UserProfile(**payload)


def save_user_profile(profile: UserProfile) -> UserProfile:
    profile.updated_at = datetime.now().isoformat(timespec="seconds")
    write_json(USER_PROFILE_PATH, profile.model_dump())
    return profile


def update_user_profile(request: UpdateUserProfileRequest) -> UserProfile:
    current = get_user_profile()
    profile = UserProfile(
        agent_id=current.agent_id,
        name=request.name.strip() or current.name,
        title=request.title.strip() or current.title,
        expertise=[item.strip() for item in request.expertise if item.strip()] or current.expertise,
        style=request.style.strip() or current.style,
        objective=request.objective.strip() or current.objective,
        profile_summary=request.profile_summary.strip() or current.profile_summary,
        updated_at=current.updated_at,
    )
    return save_user_profile(profile)
