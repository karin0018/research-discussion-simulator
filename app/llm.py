from __future__ import annotations

import os
import shutil
import subprocess
from typing import Iterator, List

from openai import OpenAI

from .config import LLM_SERVICE_PRESETS, get_llm_settings


class LLMClient:
    def __init__(self, settings: dict = None) -> None:
        settings = settings or get_llm_settings()
        self.provider = settings["provider"]
        self.model = settings["model"]
        self.api_key = settings["api_key"]
        self.base_url = settings["base_url"]
        self.cli_timeout_seconds = int(settings.get("cli_timeout_seconds") or 180)
        self.cli_command = settings.get("cli_command") or []
        self.service = settings.get("service", "")
        self._client = None

        if self.provider == "openai_compatible" and self.api_key:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def status(self) -> dict:
        settings = {
            "service": self.service,
        }
        if self.provider == "openai_compatible":
            return {
                "service": settings.get("service", ""),
                "provider": self.provider,
                "model": self.model,
                "enabled": bool(self._client is not None),
                "transport": "api",
                "base_url": self.base_url,
                "cli_command": [],
                "message": "Using OpenAI-compatible API." if self._client is not None else "API key missing, falling back to mock mode.",
            }

        if self.provider in {"codex_cli", "claude_cli", "openclaw_cli"}:
            executable = ""
            if isinstance(self.cli_command, list) and self.cli_command:
                executable = str(self.cli_command[0])
            else:
                if self.provider == "codex_cli":
                    executable = "codex"
                elif self.provider == "claude_cli":
                    executable = "claude"
                else:
                    executable = "openclaw"
            available = shutil.which(executable) is not None
            default_cmd = {
                "codex_cli": ["codex", "exec", "{combined_prompt}"],
                "claude_cli": ["claude", "-p", "{combined_prompt}"],
                "openclaw_cli": ["openclaw", "-p", "{combined_prompt}"],
            }[self.provider]
            return {
                "service": settings.get("service", ""),
                "provider": self.provider,
                "model": self.model,
                "enabled": available,
                "transport": "cli",
                "base_url": "",
                "cli_command": self._normalize_command_template(default_cmd),
                "message": f"{executable} CLI detected." if available else f"{executable} CLI not found; responses will fall back to mock mode.",
            }

        return {
            "service": settings.get("service", ""),
            "provider": self.provider,
            "model": self.model,
            "enabled": False,
            "transport": "mock",
            "base_url": "",
            "cli_command": [],
            "message": "Unknown provider, using mock mode.",
        }

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "openai_compatible":
            if self._client is None:
                return self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            return self._generate_openai(system_prompt=system_prompt, user_prompt=user_prompt)

        if self.provider == "codex_cli":
            return self._generate_cli(
                cli_name="codex",
                default_command=["codex", "exec", "--skip-git-repo-check", "{combined_prompt}"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        if self.provider == "claude_cli":
            return self._generate_cli(
                cli_name="claude",
                default_command=["claude", "-p", "{combined_prompt}"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        if self.provider == "openclaw_cli":
            return self._generate_cli(
                cli_name="openclaw",
                default_command=["openclaw", "-p", "{combined_prompt}"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        return self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)

    def stream_generate(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        if self.provider == "openai_compatible":
            if self._client is None:
                yield from self._mock_response_chunks(system_prompt=system_prompt, user_prompt=user_prompt)
                return
            yield from self._generate_openai_stream(system_prompt=system_prompt, user_prompt=user_prompt)
            return

        if self.provider == "codex_cli":
            yield from self._generate_cli_stream(
                cli_name="codex",
                default_command=["codex", "exec", "--skip-git-repo-check", "{combined_prompt}"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            return

        if self.provider == "claude_cli":
            yield from self._generate_cli_stream(
                cli_name="claude",
                default_command=["claude", "-p", "{combined_prompt}"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            return

        if self.provider == "openclaw_cli":
            yield from self._generate_cli_stream(
                cli_name="openclaw",
                default_command=["openclaw", "-p", "{combined_prompt}"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            return

        yield from self._mock_response_chunks(system_prompt=system_prompt, user_prompt=user_prompt)

    def _generate_openai(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
        )
        return response.output_text.strip()

    def _generate_openai_stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta

    def _generate_cli(
        self,
        cli_name: str,
        default_command: List[str],
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        combined_prompt = self._combine_prompts(system_prompt=system_prompt, user_prompt=user_prompt)
        command_template = self._normalize_command_template(default_command=default_command)
        executable = command_template[0]

        if shutil.which(executable) is None:
            return (
                f"{cli_name} CLI not found. Please install `{executable}` or update `cli_command` in llm_config.json.\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )

        command = [
            self._substitute_placeholders(
                part,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                combined_prompt=combined_prompt,
            )
            for part in command_template
        ]

        try:
            env = None
            if cli_name == "codex":
                env = dict(os.environ)
                env["OTEL_SDK_DISABLED"] = "true"
            result = subprocess.run(
                command,
                input=combined_prompt,
                capture_output=True,
                text=True,
                timeout=self.cli_timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return (
                f"{cli_name} CLI timed out after {self.cli_timeout_seconds} seconds.\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )
        except Exception as exc:
            return (
                f"{cli_name} CLI invocation failed: {exc}\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            error_text = stderr or stdout or f"exit code {result.returncode}"
            return (
                f"{cli_name} CLI returned an error: {error_text}\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )

        if stdout:
            return stdout

        return self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)

    def _generate_cli_stream(
        self,
        cli_name: str,
        default_command: List[str],
        system_prompt: str,
        user_prompt: str,
    ) -> Iterator[str]:
        combined_prompt = self._combine_prompts(system_prompt=system_prompt, user_prompt=user_prompt)
        command_template = self._normalize_command_template(default_command=default_command)
        executable = command_template[0]

        if shutil.which(executable) is None:
            fallback = (
                f"{cli_name} CLI not found. Please install `{executable}` or update `cli_command` in llm_config.json.\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )
            yield fallback
            return

        command = [
            self._substitute_placeholders(
                part,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                combined_prompt=combined_prompt,
            )
            for part in command_template
        ]

        env = None
        if cli_name == "codex":
            env = dict(os.environ)
            env["OTEL_SDK_DISABLED"] = "true"

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except Exception as exc:
            yield (
                f"{cli_name} CLI invocation failed: {exc}\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )
            return

        try:
            if process.stdin:
                process.stdin.write(combined_prompt)
                process.stdin.close()

            if process.stdout is None:
                yield self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
                return

            while True:
                chunk = process.stdout.read(64)
                if chunk:
                    yield chunk
                    continue
                if process.poll() is not None:
                    break

            stderr_text = process.stderr.read().strip() if process.stderr else ""
            return_code = process.wait(timeout=1)
            if return_code != 0 and stderr_text:
                yield (
                    f"\n\n{cli_name} CLI returned an error: {stderr_text}\n\n"
                    + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
                )
        except subprocess.TimeoutExpired:
            process.kill()
            yield (
                f"{cli_name} CLI timed out after {self.cli_timeout_seconds} seconds.\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )
        except Exception as exc:
            process.kill()
            yield (
                f"{cli_name} CLI invocation failed: {exc}\n\n"
                + self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
            )

    def _normalize_command_template(self, default_command: List[str]) -> List[str]:
        if isinstance(self.cli_command, list) and self.cli_command:
            return [str(item) for item in self.cli_command]
        return default_command

    @classmethod
    def from_service_selection(cls, service: str, model: str) -> "LLMClient":
        base = get_llm_settings()
        preset = LLM_SERVICE_PRESETS[service]
        settings = {
            "service": service,
            "provider": preset["provider"],
            "api_key": base.get("api_key", ""),
            "model": model,
            "base_url": base.get("base_url", ""),
            "cli_timeout_seconds": preset["cli_timeout_seconds"],
            "cli_command": list(preset["cli_command"]),
        }
        return cls(settings=settings)

    def _substitute_placeholders(
        self,
        value: str,
        system_prompt: str,
        user_prompt: str,
        combined_prompt: str,
    ) -> str:
        return (
            value.replace("{system_prompt}", system_prompt)
            .replace("{user_prompt}", user_prompt)
            .replace("{combined_prompt}", combined_prompt)
            .replace("{model}", self.model)
        )

    def _combine_prompts(self, system_prompt: str, user_prompt: str) -> str:
        return (
            "System Prompt:\n"
            f"{system_prompt}\n\n"
            "User Prompt:\n"
            f"{user_prompt}\n"
        )

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        persona = "专家"
        if "Prof. Lin" in system_prompt:
            persona = "Prof. Lin"
        elif "Dr. Chen" in system_prompt:
            persona = "Dr. Chen"
        elif "Dr. Rivera" in system_prompt:
            persona = "Dr. Rivera"
        elif "Reviewer K" in system_prompt:
            persona = "Reviewer K"
        elif "主持人" in system_prompt:
            persona = "主持人"

        snippet = user_prompt[:280].replace("\n", " ")
        if "会后复盘" in system_prompt or "个人复盘" in system_prompt:
            return (
                f"{persona} 的会后复盘：这次讨论说明用户的想法已经有明确问题意识，但研究假设和验证路径还需要进一步收敛。"
                "我认为最值得保留的是用户已经开始主动寻找可行的实验闭环，这说明方案具备继续打磨的价值。"
                "目前最大的风险是创新点、评估指标和实验设计之间还没有形成足够紧密的一一对应关系。"
                "如果下次继续讨论，我会优先追问核心假设、关键对照实验，以及什么结果会真正支持或推翻当前设想。"
                f"本轮问题摘要：{snippet}"
            )
        if persona == "主持人":
            return (
                "综合来看，先把核心假设再收窄一点会更稳。"
                "优先补最关键的验证实验，再决定是否扩展方案。"
                f"当前最该立刻推进的是把争议点列成实验清单。问题摘要：{snippet}"
            )

        return (
            f"{persona} 的看法：先别铺太大，先把最核心假设钉住。"
            "我更担心的是你的验证路径还不够收敛。"
            f"下一步建议优先补一个最能暴露问题的小实验。问题摘要：{snippet}"
        )

    def _mock_response_chunks(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        text = self._mock_response(system_prompt=system_prompt, user_prompt=user_prompt)
        for start in range(0, len(text), 48):
            yield text[start:start + 48]
