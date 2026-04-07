# Research Discussion Simulator

[English README](README.md)

Research Discussion Simulator 是一个本地运行的多角色科研讨论工具。你可以从一个还不成熟的想法开始，让不同角色一起参与讨论，逐步把研究问题、方法路线、实验设计和潜在风险梳理清楚。

系统默认是干净的初始状态，只包含内置角色和空白示例数据。你的对话、记忆、个人角色卡、上传文件和模型配置都会保存在本地，除非你自己选择分享。

## 你可以用它做什么

- 和单个研究角色一对一讨论
- 让多个角色参与一场小组讨论
- 让导师型角色帮助收敛研究问题、贡献点和实验路线
- 让同方向同行检查方法细节、baseline 和消融实验
- 让跨方向研究者提供问题重构、迁移思路和新视角
- 让审稿人型角色专门指出薄弱假设、失败模式和可能被质疑的地方
- 为每场讨论选择是否启用长期记忆
- 随讨论进展编辑自己的用户角色卡
- 创建、编辑和删除自定义角色
- 上传笔记、论文、草稿或其他参考材料作为本地知识库
- 在某一轮对话里临时附加文件
- 在浏览器里查看流式输出
- 给不同角色分配不同模型后端

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

然后打开：

```text
http://127.0.0.1:8000
```

建议使用 Python 3.9+。

## 选择模型后端

启动系统后，可以在左侧的模型设置区域选择 provider 和 model。

也可以在项目根目录创建本地 `llm_config.json`：

```bash
cp llm_config.example.json llm_config.json
```

`llm_config.json` 已经被 Git 忽略，默认不会提交你的 API Key 或本地命令配置。

OpenAI 或 OpenAI-compatible API：

```json
{
  "provider": "openai_compatible",
  "api_key": "your_api_key",
  "model": "gpt-4o-mini",
  "base_url": "https://api.openai.com/v1"
}
```

本地 vLLM 或 Ollama 兼容服务：

```json
{
  "provider": "openai_compatible",
  "api_key": "dummy",
  "model": "Qwen2.5-7B-Instruct",
  "base_url": "http://127.0.0.1:8000/v1"
}
```

Codex CLI：

```json
{
  "service": "codex",
  "provider": "codex_cli",
  "model": "gpt-5.4",
  "cli_timeout_seconds": 180,
  "cli_command": ["codex", "exec", "--skip-git-repo-check", "{combined_prompt}"]
}
```

Claude CLI：

```json
{
  "service": "claude",
  "provider": "claude_cli",
  "model": "claude-sonnet",
  "cli_timeout_seconds": 180,
  "cli_command": ["claude", "-p", "{combined_prompt}"]
}
```

如果暂时不配置模型，系统也可以用 mock 模式运行，方便先体验界面和讨论流程。

## 内置角色

- `advisor`：帮助定义研究问题、贡献点和实验路线
- `peer_ml`：检查技术细节、baseline、公平性和消融实验
- `cross_domain`：从其他领域带来类比、迁移思路和问题重构
- `skeptic`：从审稿视角指出薄弱假设、失败模式和潜在质疑

你也可以在左侧面板创建自己的角色。

## 上传文件

支持格式：

```text
.txt .md .pdf .docx .doc
```

如果一份材料希望在多轮讨论里反复使用，可以上传到知识库。如果某个文件只和当前问题有关，可以作为本轮对话附件上传。

## 隐私说明

运行时数据会保存在本机 `app/data/` 目录。公开的初始数据只包含：

- 空角色记忆文件
- 空知识库索引
- 通用用户角色卡
- 空白会话示例

生成的对话、本地上传文件、本地模型配置、虚拟环境和 Python 缓存都已经被 Git 忽略。

## 反馈和共建

欢迎在 Issue 里提建议，也欢迎直接提交 PR。尤其欢迎这些方向的反馈：

- 哪些科研讨论流程有用，哪些地方不顺手
- 还需要哪些预设角色
- 多角色讨论编排哪里容易跑偏
- 长期记忆和知识库检索应该如何改进
- 还希望支持哪些模型后端
- 前端交互哪里需要优化
- bug、测试和文档修复

请不要在 Issue 或 PR 里提交私有 API Key、个人对话、本地记忆文件或私有上传文档。

## 项目结构

```text
research-discussion-simulator/
├── app/
│   ├── main.py
│   ├── agents.py
│   ├── knowledge.py
│   ├── llm.py
│   ├── models.py
│   ├── orchestrator.py
│   ├── storage.py
│   ├── config.py
│   ├── data/
│   └── static/
├── requirements.txt
├── environment.yml
├── llm_config.example.json
├── README.md
└── README.zh-CN.md
```
