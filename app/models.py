from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


DiscussionMode = Literal["one_to_one", "group"]
KnowledgeScope = Literal["global", "agent"]


class AgentProfile(BaseModel):
    agent_id: str
    name: str
    title: str
    expertise: List[str]
    style: str
    objective: str
    is_custom: bool = False
    llm_service: Optional[str] = None
    llm_model: Optional[str] = None


class CreateAgentRequest(BaseModel):
    name: str
    title: str
    expertise: List[str] = Field(default_factory=list)
    style: str
    objective: str


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    mode: DiscussionMode = "one_to_one"
    selected_agents: List[str] = Field(default_factory=list)
    memory_enabled: bool = True
    user_message: str


class Message(BaseModel):
    role: str
    speaker_id: str
    speaker_name: str
    content: str


class ConversationTurn(BaseModel):
    conversation_id: str
    mode: DiscussionMode
    selected_agents: List[str]
    memory_enabled: bool = True
    user_context: str
    messages: List[Message]
    synthesis: str
    perspectives: Dict[str, str] = Field(default_factory=dict)


class KnowledgeUploadResponse(BaseModel):
    entry_id: str
    filename: str
    scope: KnowledgeScope
    agent_id: Optional[str] = None
    chunks: int


class KnowledgeEntry(BaseModel):
    entry_id: str
    title: str
    scope: KnowledgeScope
    agent_id: Optional[str] = None
    text: str
    source_filename: str


class ConversationSummary(BaseModel):
    conversation_id: str
    mode: DiscussionMode
    selected_agents: List[str]
    turn_count: int
    user_context: str = ""


class UserProfile(BaseModel):
    agent_id: str = "user_self"
    name: str = "你"
    title: str = "正在打磨课题的博士生"
    expertise: List[str] = Field(default_factory=lambda: ["当前研究方向仍在逐步收敛"])
    style: str = "愿意提出想法、接受批评，并希望把模糊设想打磨成严谨方案。"
    objective: str = "通过持续讨论，把研究问题、方法路线和实验计划变成可执行方案。"
    profile_summary: str = "用户正在探索自己的研究方向，希望通过和不同角色反复讨论来改进想法。"
    updated_at: Optional[str] = None


class UpdateUserProfileRequest(BaseModel):
    name: str
    title: str
    expertise: List[str] = Field(default_factory=list)
    style: str
    objective: str
    profile_summary: str = ""


class UpdateAgentLLMRequest(BaseModel):
    service: Optional[str] = None
    model: Optional[str] = None
