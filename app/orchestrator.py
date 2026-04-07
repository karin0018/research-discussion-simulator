from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from .agents import get_agent, get_user_profile, save_user_profile
from .config import CONVERSATION_DIR, LLM_SERVICE_PRESETS, MEMORY_DIR
from .knowledge import add_knowledge_text, search_knowledge
from .llm import LLMClient
from .models import ChatRequest, ConversationTurn, Message, UserProfile
from .storage import read_json, write_json


class DiscussionOrchestrator:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self._agent_order_priority = {
            "advisor": 0,
            "peer_ml": 1,
            "cross_domain": 2,
            "skeptic": 3,
        }
        self._detailed_request_markers = [
            "详细",
            "展开",
            "具体讲讲",
            "仔细讲",
            "深入",
            "长一点",
            "完整分析",
            "系统讲",
            "细说",
            "具体说说",
        ]

    def _conversation_path(self, conversation_id: str) -> Path:
        return CONVERSATION_DIR / f"{conversation_id}.json"

    def _memory_path(self, agent_id: str) -> Path:
        return MEMORY_DIR / f"{agent_id}.json"

    def _default_conversation(self, conversation_id: str) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "conversation_id": conversation_id,
            "mode": "one_to_one",
            "selected_agents": [],
            "memory_enabled": True,
            "user_context": "",
            "perspectives": {},
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }

    def _load_conversation(self, conversation_id: str) -> Dict[str, Any]:
        payload = read_json(self._conversation_path(conversation_id), self._default_conversation(conversation_id))
        if isinstance(payload, list):
            default = self._default_conversation(conversation_id)
            default["messages"] = payload
            return default
        payload.setdefault("conversation_id", conversation_id)
        payload.setdefault("mode", "one_to_one")
        payload.setdefault("selected_agents", [])
        payload.setdefault("memory_enabled", True)
        payload.setdefault("user_context", "")
        payload.setdefault("perspectives", {})
        payload.setdefault("messages", [])
        payload.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        payload.setdefault("updated_at", payload["created_at"])
        return payload

    def _save_conversation(self, conversation_id: str, payload: Dict[str, Any]) -> None:
        write_json(self._conversation_path(conversation_id), payload)

    def create_conversation(
        self,
        mode: str = "one_to_one",
        selected_agents: Optional[List[str]] = None,
        memory_enabled: bool = True,
    ) -> Dict[str, Any]:
        conversation_id = str(uuid4())
        payload = self._default_conversation(conversation_id)
        payload["mode"] = mode
        payload["selected_agents"] = selected_agents or []
        payload["memory_enabled"] = memory_enabled
        self._save_conversation(conversation_id, payload)
        return payload

    def _load_agent_memory(self, agent_id: str) -> List[Dict[str, Any]]:
        return read_json(self._memory_path(agent_id), [])

    def _save_agent_memory(self, agent_id: str, payload: List[Dict[str, Any]]) -> None:
        write_json(self._memory_path(agent_id), payload)

    def _build_user_context(self, messages: List[Dict[str, Any]], previous_context: str) -> str:
        user_messages = [item["content"] for item in messages if item.get("speaker_id") == "user"]
        if not user_messages:
            return previous_context or "暂无用户上下文。"

        latest = user_messages[-5:]
        lines = [f"用户在本讨论中的持续关注点共 {len(user_messages)} 轮。"]
        if previous_context:
            lines.append(f"已有上下文摘要：{previous_context}")
        lines.append("最近几轮用户输入：")
        lines.extend(f"- {text[:180]}" for text in latest)
        return "\n".join(lines)

    def _render_memory(self, items: List[Dict[str, Any]], limit: int = 5) -> str:
        if not items:
            return "暂无长期记忆。"
        recent = items[-limit:]
        return "\n".join(f"- {item['summary']}" for item in recent)

    def _render_history(self, history: List[Dict[str, Any]], limit: int = 10) -> str:
        if not history:
            return "这是第一次讨论。"
        recent = history[-limit:]
        return "\n".join(f"{item['speaker_name']}: {item['content']}" for item in recent)

    def _render_knowledge(self, query: str, agent_id: str) -> str:
        entries = search_knowledge(query=query, agent_id=agent_id)
        if not entries:
            return "暂无匹配知识库。"
        return "\n\n".join(
            f"[{entry['title']} | {entry['source_filename']}]\n{entry['text']}" for entry in entries
        )

    def _agent_system_prompt(self, agent_id: str) -> str:
        agent = get_agent(agent_id)
        return (
            f"你是 {agent.name}，身份是{agent.title}。\n"
            f"你的专长：{', '.join(agent.expertise)}。\n"
            f"你的说话风格：{agent.style}\n"
            f"你的目标：{agent.objective}\n"
            "请始终围绕科研讨论展开，像组会里发言那样说话。"
            "默认短一点、直接一点，不要长篇大论，不要写成大段报告。"
            "除非用户明确要求你详细展开，否则把回答控制在 3 到 6 句内。"
            "如果在多人讨论中发现别人的观点有漏洞，你应该直接指出并给出更好的替代建议。"
            "回答尽量包含：你的核心判断、一个关键风险、一个可执行建议。"
            "你必须守住自己的角色边界，不要泛泛重复别人已经说过的话。"
        )

    def _wants_detailed_answer(self, user_message: str) -> bool:
        lowered = user_message.lower()
        return any(marker in user_message for marker in self._detailed_request_markers) or "detail" in lowered

    def _ordered_agent_ids(self, agent_ids: List[str]) -> List[str]:
        return sorted(
            agent_ids,
            key=lambda agent_id: (self._agent_order_priority.get(agent_id, 99), agent_id),
        )

    def _agent_group_strategy(
        self,
        agent_id: str,
        other_messages: List[Message],
        current_mode: str,
        turn_index: int,
        total_agents: int,
    ) -> str:
        if current_mode != "group":
            return (
                "当前是一对一讨论。请直接从你的专业视角给出最核心的判断、风险和建议，"
                "避免空泛铺垫。"
            )

        base_map = {
            "advisor": "优先负责收敛研究问题、判断课题价值、明确论文贡献和行动优先级。",
            "peer_ml": "优先负责检查方法假设、实验设计、公平比较、基线和消融是否站得住。",
            "cross_domain": "优先负责提出跨学科重构、替代问题定义和新的应用切口，不要重复实验细节。",
            "skeptic": "优先负责攻击漏洞、指出证据缺口、失败模式和最可能被审稿人否掉的点。",
        }
        base = base_map.get(
            agent_id,
            "优先坚持你自己的角色专长，只说最能体现你独特价值的部分。",
        )
        if not other_messages:
            return (
                f"这是多人讨论中的第 {turn_index + 1}/{total_agents} 位发言者。"
                f"{base}"
                "你负责先搭建你这个角色最核心的分析框架，给后面的专家留出可质疑和补充的空间。"
                "不要试图把所有角度一次性说完。"
            )
        return (
            f"这是多人讨论中的第 {turn_index + 1}/{total_agents} 位发言者。"
            f"{base}"
            "你已经看过前面专家的发言，严禁重复他们已经完整表达过的观点。"
            "如果你同意某一点，只允许用一句短话承接，然后立刻补充新信息。"
            "如果你不同意，请明确指出你反对谁的哪一点，以及更好的替代判断。"
            "你的发言必须满足下面三点："
            "1. 开头先点名回应前面某位专家的一点；"
            "2. 中间只展开你独有的 1 到 2 个关键视角；"
            "3. 结尾给出新的可执行建议，而不是重复前面已有建议。"
        )

    def _agent_user_prompt(
        self,
        agent_id: str,
        user_message: str,
        history: List[Dict[str, Any]],
        user_context: str,
        other_messages: List[Message],
        memory_enabled: bool,
        current_mode: str,
        turn_index: int,
        total_agents: int,
    ) -> str:
        detailed_requested = self._wants_detailed_answer(user_message)
        memory = "当前讨论已关闭长期记忆调用，仅使用角色初始设定和本轮讨论信息。" if not memory_enabled else self._render_memory(self._load_agent_memory(agent_id))
        knowledge = self._render_knowledge(query=user_message, agent_id=agent_id)
        debate_context = "\n".join(
            f"{message.speaker_name}: {message.content}" for message in other_messages
        ) or "当前还没有其他专家发言。"
        debate_strategy = self._agent_group_strategy(
            agent_id=agent_id,
            other_messages=other_messages,
            current_mode=current_mode,
            turn_index=turn_index,
            total_agents=total_agents,
        )

        return (
            f"用户当前问题：\n{user_message}\n\n"
            f"当前会话历史：\n{self._render_history(history)}\n\n"
            f"用户上下文摘要：\n{user_context or '暂无用户上下文。'}\n\n"
            f"你的长期记忆：\n{memory}\n\n"
            f"可参考知识库：\n{knowledge}\n\n"
            f"其他专家本轮观点：\n{debate_context}\n\n"
            f"本轮发言策略：\n{debate_strategy}\n\n"
            f"用户是否明确要求详细展开：{'是' if detailed_requested else '否'}。\n\n"
            "请结合以上信息发言。不要泛泛而谈，要尽量指出具体研究动作。"
            "如果前面已经有人说过类似内容，你必须换成更具体的补充、反驳或重构视角。"
            "如果用户没有明确要求详细展开，请保持短答，像讨论里接话，不要输出很长的分点大段文字。"
        )

    def _moderator_prompt(self, user_message: str, messages: List[Message]) -> Tuple[str, str]:
        detailed_requested = self._wants_detailed_answer(user_message)
        system_prompt = (
            "你是科研讨论主持人。你的任务是综合多方意见，指出共识、分歧和最终可执行方案。"
            "默认用简洁讨论式语言总结，不要写成长报告。"
            "除非用户明确要求详细展开，否则控制在 4 到 7 句。"
            "输出必须清晰，包含：核心判断、建议方案、立刻可做的下一步。"
        )
        user_prompt = (
            f"用户问题：\n{user_message}\n\n"
            f"用户是否明确要求详细展开：{'是' if detailed_requested else '否'}\n\n"
            "专家讨论：\n"
            + "\n\n".join(f"{message.speaker_name}：{message.content}" for message in messages)
        )
        return system_prompt, user_prompt

    def _agent_reflection_prompt(
        self,
        agent_id: str,
        user_message: str,
        expert_messages: List[Message],
        synthesis: str,
        conversation_id: str,
    ) -> Tuple[str, str]:
        agent = get_agent(agent_id)
        own_message = next((message.content for message in expert_messages if message.speaker_id == agent_id), "本轮未发言。")
        others = [
            f"{message.speaker_name}: {message.content}"
            for message in expert_messages
            if message.speaker_id != agent_id
        ]
        others_text = "\n\n".join(others) or "本轮没有其他专家观点。"
        system_prompt = (
            f"你是 {agent.name}，身份是{agent.title}。"
            "现在不是继续和用户对话，而是在讨论结束后做个人复盘。"
            "请像真实研究者一样，记录你对这次讨论的判断、对用户想法的评价、你认为最关键的风险，"
            "以及你认为下一次见面时最该追问的点。"
            "输出写成一段适合长期记忆保存的中文总结，控制在 4 到 7 句。"
        )
        user_prompt = (
            f"会话 ID: {conversation_id}\n\n"
            f"用户本轮问题：\n{user_message}\n\n"
            f"你本轮发言：\n{own_message}\n\n"
            f"其他专家观点：\n{others_text}\n\n"
            f"主持人总结：\n{synthesis}\n\n"
            "请生成你的会后复盘，内容要包含："
            "1. 你对用户当前想法成熟度的判断；"
            "2. 你认为最值得保留的亮点；"
            "3. 你最担心的漏洞或风险；"
            "4. 下次应继续追问或验证的重点。"
        )
        return system_prompt, user_prompt

    def _user_profile_update_prompt(
        self,
        profile: UserProfile,
        user_message: str,
        expert_messages: List[Message],
        synthesis: str,
        conversation_id: str,
    ) -> Tuple[str, str]:
        system_prompt = (
            "你是一名科研角色卡编辑器。"
            "你的任务是根据本轮讨论，更新用户自己的角色卡。"
            "输出必须是 JSON，不要输出额外解释。"
            'JSON 字段固定为: name, title, expertise, style, objective, profile_summary。'
            "其中 expertise 必须是字符串数组，其余字段必须是字符串。"
            "更新时保留用户长期稳定的特征，只把新暴露出来的研究兴趣、思考方式和阶段性目标融入角色卡。"
        )
        user_prompt = (
            f"会话 ID: {conversation_id}\n\n"
            "当前用户角色卡：\n"
            f"{json.dumps(profile.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"用户本轮输入：\n{user_message}\n\n"
            "专家反馈：\n"
            + "\n\n".join(f"{message.speaker_name}: {message.content}" for message in expert_messages)
            + f"\n\n主持人总结：\n{synthesis}\n\n"
            "请输出更新后的 JSON。"
        )
        return system_prompt, user_prompt

    def _user_reflection_prompt(
        self,
        profile: UserProfile,
        user_message: str,
        synthesis: str,
        conversation_id: str,
    ) -> Tuple[str, str]:
        system_prompt = (
            "你现在要从上帝视角为用户生成一条长期记忆。"
            "请总结用户这轮讨论里暴露出来的研究偏好、当前卡点和下一步最值得继续推进的方向。"
            "输出 4 到 6 句中文总结。"
        )
        user_prompt = (
            f"会话 ID: {conversation_id}\n\n"
            f"用户角色卡：\n{json.dumps(profile.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"用户本轮输入：\n{user_message}\n\n"
            f"主持人总结：\n{synthesis}\n"
        )
        return system_prompt, user_prompt

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("No JSON object found")
        return json.loads(match.group(0))

    def _build_agent_reflection(
        self,
        agent_id: str,
        user_message: str,
        expert_messages: List[Message],
        synthesis: str,
        conversation_id: str,
    ) -> str:
        system_prompt, user_prompt = self._agent_reflection_prompt(
            agent_id=agent_id,
            user_message=user_message,
            expert_messages=expert_messages,
            synthesis=synthesis,
            conversation_id=conversation_id,
        )
        return self._llm_for_agent(agent_id).generate(system_prompt=system_prompt, user_prompt=user_prompt)

    def _llm_for_agent(self, agent_id: str) -> LLMClient:
        agent = get_agent(agent_id)
        if agent.llm_service and agent.llm_model and agent.llm_service in LLM_SERVICE_PRESETS:
            return LLMClient.from_service_selection(agent.llm_service, agent.llm_model)
        return self.llm

    def _update_user_profile_after_turn(
        self,
        user_message: str,
        expert_messages: List[Message],
        synthesis: str,
        conversation_id: str,
        memory_enabled: bool,
    ) -> Tuple[UserProfile, str]:
        profile = get_user_profile()
        system_prompt, user_prompt = self._user_profile_update_prompt(
            profile=profile,
            user_message=user_message,
            expert_messages=expert_messages,
            synthesis=synthesis,
            conversation_id=conversation_id,
        )
        raw_update = self.llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        updated_profile = profile
        try:
            parsed = self._extract_json_object(raw_update)
            updated_profile = UserProfile(
                agent_id="user_self",
                name=str(parsed.get("name") or profile.name).strip(),
                title=str(parsed.get("title") or profile.title).strip(),
                expertise=[str(item).strip() for item in parsed.get("expertise", []) if str(item).strip()] or profile.expertise,
                style=str(parsed.get("style") or profile.style).strip(),
                objective=str(parsed.get("objective") or profile.objective).strip(),
                profile_summary=str(parsed.get("profile_summary") or profile.profile_summary).strip(),
                updated_at=profile.updated_at,
            )
        except Exception:
            updated_profile.profile_summary = raw_update.strip() or profile.profile_summary

        if memory_enabled:
            updated_profile = save_user_profile(updated_profile)

        reflection_system, reflection_user = self._user_reflection_prompt(
            profile=updated_profile,
            user_message=user_message,
            synthesis=synthesis,
            conversation_id=conversation_id,
        )
        reflection = self.llm.generate(system_prompt=reflection_system, user_prompt=reflection_user)
        if memory_enabled:
            memory = self._load_agent_memory("user_self")
            memory.append(
                {
                    "conversation_id": conversation_id,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "summary": reflection,
                }
            )
            self._save_agent_memory("user_self", memory[-30:])
        return updated_profile, reflection

    def _time_bucket(self, iso_time: str) -> str:
        try:
            updated = datetime.fromisoformat(iso_time)
        except ValueError:
            return "更早"
        now = datetime.now()
        delta_days = (now.date() - updated.date()).days
        if delta_days == 0:
            return "今天"
        if delta_days <= 7:
            return "近 7 天"
        if delta_days <= 30:
            return "近 30 天"
        return "更早"

    def _prepare_turn(self, request: ChatRequest) -> Dict[str, Any]:
        conversation_id = request.conversation_id or str(uuid4())
        conversation = self._load_conversation(conversation_id)
        history = conversation["messages"]

        user_msg = Message(
            role="user",
            speaker_id="user",
            speaker_name="You",
            content=request.user_message.strip(),
        )

        selected_agents = request.selected_agents[:] or conversation.get("selected_agents", [])
        if request.mode == "one_to_one" and len(selected_agents) > 1:
            selected_agents = selected_agents[:1]

        current_mode = request.mode or conversation.get("mode", "one_to_one")
        prior_context = conversation.get("user_context", "")
        updated_history = history + [user_msg.model_dump()]
        user_context = self._build_user_context(updated_history, prior_context)
        created_at = conversation.get("created_at") or datetime.now().isoformat(timespec="seconds")

        return {
            "conversation_id": conversation_id,
            "conversation": conversation,
            "history": history,
            "user_msg": user_msg,
            "selected_agents": selected_agents,
            "current_mode": current_mode,
            "user_context": user_context,
            "created_at": created_at,
        }

    def _finalize_turn(
        self,
        request: ChatRequest,
        prepared: Dict[str, Any],
        expert_messages: List[Message],
        synthesis: str,
    ) -> ConversationTurn:
        user_msg: Message = prepared["user_msg"]
        turn_messages: List[Message] = [user_msg] + expert_messages

        moderator_message = Message(
            role="assistant",
            speaker_id="moderator",
            speaker_name="Moderator",
            content=synthesis,
        )
        turn_messages.append(moderator_message)

        perspectives: Dict[str, str] = {}
        for agent_id in prepared["selected_agents"]:
            reflection = self._build_agent_reflection(
                agent_id=agent_id,
                user_message=request.user_message,
                expert_messages=expert_messages,
                synthesis=synthesis,
                conversation_id=prepared["conversation_id"],
            )
            perspectives[agent_id] = reflection
            if request.memory_enabled:
                memory = self._load_agent_memory(agent_id)
                memory.append(
                    {
                        "conversation_id": prepared["conversation_id"],
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "summary": reflection,
                    }
                )
                self._save_agent_memory(agent_id, memory[-30:])
                add_knowledge_text(
                    title=f"{agent_id} reflective note",
                    text=reflection,
                    source_filename="auto_reflection",
                    scope="agent",
                    agent_id=agent_id,
                )

        updated_profile, user_reflection = self._update_user_profile_after_turn(
            user_message=request.user_message,
            expert_messages=expert_messages,
            synthesis=synthesis,
            conversation_id=prepared["conversation_id"],
            memory_enabled=request.memory_enabled,
        )
        perspectives["user_self"] = user_reflection

        history: List[Dict[str, Any]] = prepared["history"]
        stored_history = history + [message.model_dump() for message in turn_messages]
        updated_at = datetime.now().isoformat(timespec="seconds")
        self._save_conversation(
            prepared["conversation_id"],
            {
                "conversation_id": prepared["conversation_id"],
                "mode": prepared["current_mode"],
                "selected_agents": prepared["selected_agents"],
                "memory_enabled": request.memory_enabled,
                "user_context": prepared["user_context"],
                "perspectives": perspectives,
                "messages": stored_history,
                "created_at": prepared["created_at"],
                "updated_at": updated_at,
                "user_profile_snapshot": updated_profile.model_dump(),
            },
        )

        return ConversationTurn(
            conversation_id=prepared["conversation_id"],
            mode=prepared["current_mode"],
            selected_agents=prepared["selected_agents"],
            memory_enabled=request.memory_enabled,
            user_context=prepared["user_context"],
            messages=turn_messages,
            synthesis=synthesis,
            perspectives=perspectives,
        )

    def run_turn(self, request: ChatRequest) -> ConversationTurn:
        prepared = self._prepare_turn(request)
        expert_messages: List[Message] = []

        ordered_agents = self._ordered_agent_ids(prepared["selected_agents"])
        for turn_index, agent_id in enumerate(ordered_agents):
            content = self._llm_for_agent(agent_id).generate(
                system_prompt=self._agent_system_prompt(agent_id),
                user_prompt=self._agent_user_prompt(
                    agent_id=agent_id,
                    user_message=request.user_message,
                    history=prepared["history"],
                    user_context=prepared["user_context"],
                    other_messages=expert_messages,
                    memory_enabled=request.memory_enabled,
                    current_mode=prepared["current_mode"],
                    turn_index=turn_index,
                    total_agents=len(ordered_agents),
                ),
            )
            agent = get_agent(agent_id)
            expert_messages.append(
                Message(
                    role="assistant",
                    speaker_id=agent_id,
                    speaker_name=agent.name,
                    content=content,
                )
            )

        system_prompt, user_prompt = self._moderator_prompt(request.user_message, expert_messages)
        synthesis = self.llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        return self._finalize_turn(
            request=request,
            prepared=prepared,
            expert_messages=expert_messages,
            synthesis=synthesis,
        )

    def stream_turn(self, request: ChatRequest) -> Iterable[Dict[str, Any]]:
        prepared = self._prepare_turn(request)
        yield {
            "type": "conversation",
            "conversation_id": prepared["conversation_id"],
            "mode": prepared["current_mode"],
            "selected_agents": prepared["selected_agents"],
            "memory_enabled": request.memory_enabled,
        }

        expert_messages: List[Message] = []
        ordered_agents = self._ordered_agent_ids(prepared["selected_agents"])
        for turn_index, agent_id in enumerate(ordered_agents):
            agent = get_agent(agent_id)
            message = Message(
                role="assistant",
                speaker_id=agent_id,
                speaker_name=agent.name,
                content="",
            )
            yield {"type": "message_start", "message": message.model_dump()}
            chunks: List[str] = []
            for delta in self._llm_for_agent(agent_id).stream_generate(
                system_prompt=self._agent_system_prompt(agent_id),
                user_prompt=self._agent_user_prompt(
                    agent_id=agent_id,
                    user_message=request.user_message,
                    history=prepared["history"],
                    user_context=prepared["user_context"],
                    other_messages=expert_messages,
                    memory_enabled=request.memory_enabled,
                    current_mode=prepared["current_mode"],
                    turn_index=turn_index,
                    total_agents=len(ordered_agents),
                ),
            ):
                chunks.append(delta)
                yield {"type": "message_delta", "speaker_id": agent_id, "delta": delta}
            message.content = "".join(chunks).strip()
            expert_messages.append(message)
            yield {"type": "message_end", "message": message.model_dump()}

        moderator = Message(
            role="assistant",
            speaker_id="moderator",
            speaker_name="Moderator",
            content="",
        )
        yield {"type": "message_start", "message": moderator.model_dump()}
        system_prompt, user_prompt = self._moderator_prompt(request.user_message, expert_messages)
        chunks = []
        for delta in self.llm.stream_generate(system_prompt=system_prompt, user_prompt=user_prompt):
            chunks.append(delta)
            yield {"type": "message_delta", "speaker_id": "moderator", "delta": delta}
        moderator.content = "".join(chunks).strip()
        yield {"type": "message_end", "message": moderator.model_dump()}

        turn = self._finalize_turn(
            request=request,
            prepared=prepared,
            expert_messages=expert_messages,
            synthesis=moderator.content,
        )
        yield {"type": "done", "turn": turn.model_dump()}

    def list_conversations(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for path in CONVERSATION_DIR.glob("*.json"):
            payload = read_json(path, [])
            stat = path.stat()
            if isinstance(payload, dict):
                messages = payload.get("messages", [])
                selected_agents = payload.get("selected_agents", [])
                mode = payload.get("mode", "one_to_one")
                user_context = payload.get("user_context", "")
                updated_at = payload.get("updated_at") or datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
                created_at = payload.get("created_at") or datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds")
                memory_enabled = payload.get("memory_enabled", True)
            else:
                messages = payload
                selected_agents = []
                mode = "one_to_one"
                user_context = ""
                updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
                created_at = datetime.fromtimestamp(stat.st_ctime).isoformat(timespec="seconds")
                memory_enabled = True
            user_messages = [item for item in messages if item.get("speaker_id") == "user"]
            last_user = user_messages[-1]["content"] if user_messages else ""
            results.append(
                {
                    "conversation_id": path.stem,
                    "mode": mode,
                    "selected_agents": selected_agents,
                    "turn_count": len(user_messages),
                    "last_topic": last_user[:120],
                    "user_context": user_context[:240],
                    "memory_enabled": memory_enabled,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "time_bucket": self._time_bucket(updated_at),
                }
            )
        results.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return results

    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        payload = self._load_conversation(conversation_id)
        path = self._conversation_path(conversation_id)
        if path.exists():
            payload["updated_at"] = payload.get("updated_at") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            payload["created_at"] = payload.get("created_at") or datetime.fromtimestamp(path.stat().st_ctime).isoformat(timespec="seconds")
        return payload

    def delete_conversation(self, conversation_id: str) -> bool:
        path = self._conversation_path(conversation_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def get_role_view(self, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        conversation = self._load_conversation(conversation_id) if conversation_id else None
        perspectives = conversation.get("perspectives", {}) if conversation else {}

        roles: List[Dict[str, Any]] = []
        user_profile = get_user_profile()
        user_memories = list(reversed(self._load_agent_memory("user_self")[-10:]))
        roles.append(
            {
                "agent_id": user_profile.agent_id,
                "name": user_profile.name,
                "title": user_profile.title,
                "expertise": user_profile.expertise,
                "style": user_profile.style,
                "objective": user_profile.objective,
                "profile_summary": user_profile.profile_summary,
                "is_user": True,
                "latest_thought": perspectives.get("user_self") or (user_memories[0]["summary"] if user_memories else ""),
                "memories": user_memories,
            }
        )

        from .agents import list_agents

        for agent in list_agents():
            memories = list(reversed(self._load_agent_memory(agent.agent_id)[-10:]))
            roles.append(
                {
                    "agent_id": agent.agent_id,
                    "name": agent.name,
                    "title": agent.title,
                    "expertise": agent.expertise,
                    "style": agent.style,
                    "objective": agent.objective,
                    "profile_summary": "",
                    "is_user": False,
                    "latest_thought": perspectives.get(agent.agent_id) or (memories[0]["summary"] if memories else ""),
                    "memories": memories,
                }
            )

        return {
            "conversation_id": conversation_id,
            "available_perspectives": list(perspectives.keys()),
            "roles": roles,
        }
