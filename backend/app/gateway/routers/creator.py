"""AI-assisted creator routes for Agents and Skills."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class DraftRequest(BaseModel):
    goal: str
    details: dict[str, str] = Field(default_factory=dict)


class SaveRequest(BaseModel):
    draft: dict


class CreatorChatMessage(BaseModel):
    role: str
    content: str


class CreatorChatRequest(BaseModel):
    kind: str = Field(pattern="^(agent|skill|mcp)$")
    message: str
    thread_id: str | None = None
    messages: list[CreatorChatMessage] = Field(default_factory=list)
    draft: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None


def _slug_with_hash(value: str, fallback_prefix: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:48].strip("-")
    if slug and slug not in {"agent", "skill", "custom", "new"}:
        return slug
    digest = hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{fallback_prefix}-{digest}"


def _summary(kind: str, draft: dict) -> str:
    name = draft.get("name") or draft.get("id") or kind
    return f"已生成 {kind} 草稿：{name}。请检查配置，确认后保存。"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _strip_frontmatter(content: str) -> str:
    text = content.strip()
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) == 3:
        return parts[2].strip()
    return text


def _compact_text(value: str, *, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _conversation_goal(body: CreatorChatRequest) -> str:
    user_parts = [item.content.strip() for item in body.messages if item.role == "user" and item.content.strip()]
    current = body.message.strip()
    if current and (not user_parts or user_parts[-1] != current):
        user_parts.append(current)
    if not user_parts:
        return current
    return "\n".join(user_parts[-6:])


def _title_from_goal(goal: str, fallback: str) -> str:
    first = re.split(r"[\n。！？!?；;]", goal.strip(), maxsplit=1)[0]
    first = re.sub(r"\b(agent|skill)\b", "", first, flags=re.IGNORECASE)
    first = re.sub(r"(智能体|能力包|能力|助手)", "", first)
    first = re.sub(r"(帮我|请|我想|我要|需要|创建|新建|生成|设计|打造|做一个|做一份|做个|一个|一份)", "", first)
    first = re.sub(r"(可以|能够|能|用于|负责|专门|当前|这个|这个)", "", first)
    first = first.strip(" ：:，,、-_/")

    keyword_pairs = [
        ("合同", "审阅", "合同审阅"),
        ("合同", "风险", "合同审阅"),
        ("邮件", "总结", "邮件总结"),
        ("客服", "质检", "客服质检"),
        ("论文", "精读", "论文精读"),
        ("论文", "阅读", "论文精读"),
        ("财务", "报表", "财务报表分析"),
        ("周报", "生成", "周报生成"),
        ("竞品", "分析", "竞品分析"),
        ("知识库", "问答", "知识库问答"),
    ]
    compact = _compact_text(goal, limit=240)
    for left, right, title in keyword_pairs:
        if left in compact and right in compact:
            return title

    if not first:
        return fallback
    first = re.split(r"[，,、]", first, maxsplit=1)[0].strip()
    first = re.sub(r"(输出|包含|给出|并|和).*", "", first).strip(" ：:，,、-_/")
    if not first:
        return fallback
    if len(first) > 18:
        return first[:18].rstrip()
    return first


def _agent_system_prompt_from_goal(goal: str, name: str, existing_prompt: str = "") -> str:
    goal_text = _compact_text(goal or name, limit=900)
    existing = _compact_text(existing_prompt, limit=500)
    existing_section = []
    if existing:
        existing_section = [
            "",
            "## 已有草案要点",
            existing,
            "在不违背这些要点的前提下，用下面的职责、流程和输出规范稳定执行任务。",
        ]
    return "\n".join(
        [
            f"# {name} Agent 系统提示词",
            "",
            "## 角色定位",
            f"你是 NexAgent 中的「{name}」Agent，负责围绕以下目标交付可执行、可复查的结果：{goal_text}",
            "你不是泛泛聊天助手。你需要主动识别用户的真实任务、业务背景、输入材料、约束条件和交付标准，并把它们转化为清晰的行动步骤。",
            *existing_section,
            "",
            "## 核心职责",
            "- 提炼用户目标，识别必须完成的子任务、关键约束、风险点和验收标准。",
            "- 在信息不足时只提出最关键的澄清问题；如果用户要求直接推进，则基于上下文做合理假设并标明假设。",
            "- 需要资料、知识库、Skills、MCP 或内置工具时，先说明使用目的，再选择最小必要资源完成任务。",
            "- 将结论、证据、推理过程和下一步建议分开表达，避免把未经验证的猜测写成事实。",
            "- 对高风险、不可逆或需要专业资质的事项，明确提示限制，并给出可执行但不过度承诺的建议。",
            "",
            "## 工作流程",
            "1. 理解请求：复述目标、输入、输出和限制，发现缺口时优先澄清影响结果的关键信息。",
            "2. 制定路径：把任务拆成 2-5 个可完成步骤，并判断是否需要调用工具、查询知识库或委派子 Agent。",
            "3. 执行分析：逐步处理材料，保留关键依据；遇到冲突信息时说明冲突来源和取舍理由。",
            "4. 生成结果：用用户可直接使用的格式输出，不只给思路；必要时给出表格、清单、模板或行动项。",
            "5. 自检交付：检查是否覆盖用户目标、是否遗漏约束、是否存在未经验证的结论，并给出后续可选动作。",
            "",
            "## 输出格式",
            "默认按以下结构组织，除非用户指定其他格式：",
            "- 结论摘要：用 2-4 句话说明最重要的结果。",
            "- 关键发现：列出事实、风险、机会或问题，每条尽量附依据。",
            "- 建议方案：给出可执行步骤、优先级、负责人或使用条件。",
            "- 待确认事项：只列真正会影响结果的缺口，不把普通背景问题伪装成阻塞。",
            "",
            "## 工具与协作策略",
            "- 优先使用已绑定的知识库、Skills、MCP 和内置工具；没有绑定资源时，先基于用户提供的信息工作。",
            "- 允许子 Agent 时，只把可并行、边界清晰的子任务委派出去，并汇总它们的结果和不确定性。",
            "- 不要虚构工具执行结果、文件内容、外部数据或已经完成的操作。",
            "",
            "## 边界与安全",
            "- 不编造法规、财务、医疗、安全等高风险结论；无法确认时明确说明不确定性。",
            "- 不输出会泄露密钥、绕过权限、破坏系统或误导用户的步骤。",
            "- 用户要求保存、发布或执行前，确认结果已经满足当前上下文的最低可用标准。",
            "",
            "## 质量标准",
            "- 结果必须具体、可复用、可验证，而不是只给泛泛建议。",
            "- 重要判断要有依据；没有依据时用“假设/推测/待确认”标记。",
            "- 语言保持简洁直接，默认使用用户使用的语言。",
        ]
    )


def _agent_draft_from_goal(goal: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    details = details or {}
    name = str(details.get("name") or _title_from_goal(goal, "自定义 Agent")).strip()
    system_prompt = str(details.get("system_prompt") or "").strip()
    return {
        "name": name,
        "description": str(details.get("description") or goal).strip(),
        "base_type": str(details.get("base_type") or "chatbot").strip(),
        "model_name": str(details.get("model_name") or "").strip(),
        "system_prompt": system_prompt or _agent_system_prompt_from_goal(goal, name),
        "tools": [],
        "kb_ids": [],
        "skill_ids": [],
        "mcp_ids": [],
        "memory_enabled": False,
        "thinking_enabled": False,
        "thinking_budget": 8000,
        "reasoning_mode": str(details.get("reasoning_mode") or "balanced").strip(),
        "allow_subagents": True,
        "avatar_color": "emerald",
    }


def _skill_body_from_goal(goal: str, name: str, existing_content: str = "") -> str:
    goal_text = _compact_text(goal or name, limit=900)
    existing = _compact_text(existing_content, limit=500)
    existing_section = []
    if existing:
        existing_section = [
            "",
            "## 已有草案要点",
            existing,
            "保留这些意图，但按下面的触发条件、流程、输出和检查标准执行。",
        ]
    return "\n".join(
        [
            f"# {name}",
            "",
            "## 适用场景 / 触发条件",
            f"当用户需要完成以下目标或表达相近需求时使用本 Skill：{goal_text}",
            "如果用户只给出简短目标，也应先根据上下文做合理假设，产出可直接使用的第一版结果；只有缺少会改变结论的关键信息时才追问。",
            "- 用户要求生成、审阅、总结、分析、改写、规划或整理与该目标相关的材料。",
            "- 用户希望得到结构化交付物，而不是只要泛泛建议。",
            "- 任务需要稳定复用同一套流程、检查项或输出格式。",
            *existing_section,
            "",
            "## 输入",
            "- 用户的目标、背景、约束、偏好的输出格式和截止条件。",
            "- 用户提供的文本、文件、数据、链接或业务规则。",
            "- 可选的知识库、工具、MCP 或其他 Skill 结果；没有这些资源时，基于当前上下文完成可用版本。",
            "",
            "## 工作流程",
            "1. 明确任务：提炼目标、受众、输入材料、输出形态和验收标准。",
            "2. 检查信息：找出会影响结果的缺口；如果缺口不关键，写明假设并继续推进。",
            "3. 选择方法：根据任务性质决定是否需要检索、计算、对比、评分、抽取证据或生成模板。",
            "4. 执行产出：按步骤处理材料，保留关键依据、判断标准和取舍理由。",
            "5. 自检修订：对照质量检查清单补齐遗漏，移除空泛表述，确保结果能被用户直接使用。",
            "",
            "## 输出格式",
            "默认输出以下结构，可按用户要求调整：",
            "- 结论摘要：说明最终判断或生成结果的重点。",
            "- 处理过程：列出关键步骤、依据、分类或评分标准。",
            "- 成品内容：给出可复制使用的正文、表格、清单、方案或模板。",
            "- 风险与假设：标注未验证信息、边界条件和可能影响结果的风险等级。",
            "- 下一步：给出最少必要的后续动作或需要用户确认的问题。",
            "",
            "## 质量检查",
            "- 是否完整回应用户目标，而不是只复述需求。",
            "- 是否把事实、假设、建议和不确定性分开表达。",
            "- 是否包含足够具体的证据、标准、示例或可执行步骤。",
            "- 是否避免泄露敏感信息、编造外部事实或承诺无法验证的结果。",
            "- 保存前确认 `SKILL.md` 无 YAML frontmatter 以外的重复元数据，正文从一级标题开始。",
            "",
            "## 示例",
            "输入：用户要求围绕该主题生成可复用结果，并补充边界条件。",
            "输出：先给出结论摘要，再按流程列出关键发现、证据或评分，最后提供可直接复制的成品和待确认事项。",
        ]
    )


def _skill_draft_from_goal(goal: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    details = details or {}
    skill_id = _slug_with_hash(str(details.get("id") or goal), "skill")
    name = str(details.get("name") or _title_from_goal(goal, skill_id)).strip()
    content = str(details.get("content") or "").strip()
    return {
        "id": skill_id,
        "name": name,
        "description": str(details.get("description") or goal).strip(),
        "version": str(details.get("version") or "0.1.0").strip(),
        "tags": _string_list(details.get("tags")),
        "required_mcp_ids": _string_list(details.get("required_mcp_ids")),
        "required_tools": _string_list(details.get("required_tools")),
        "skill_dependencies": _string_list(details.get("skill_dependencies")),
        "content": content or _skill_body_from_goal(goal, name),
    }


def _thin_agent_prompt(content: str) -> bool:
    if len(content.strip()) < 500:
        return True
    terms = ["角色", "职责", "流程", "输出", "边界", "质量"]
    return sum(1 for term in terms if term in content) < 4


def _thin_skill_content(content: str) -> bool:
    if len(content.strip()) < 700:
        return True
    sections = [
        "## 适用场景 / 触发条件",
        "## 输入",
        "## 工作流程",
        "## 输出格式",
        "## 质量检查",
        "## 示例",
    ]
    return sum(1 for section in sections if section in content) < 5


def _available_configurable_tool_names() -> set[str]:
    fallback = {
        "knowledge_search",
        "web_search",
        "web_fetch",
        "execute_python",
        "list_skills",
        "read_skill",
        "skill_manage",
        "bash",
        "ls",
        "read_file",
        "glob",
        "grep",
        "write_file",
        "str_replace",
        "present_artifacts",
    }
    try:
        from nexagent.tools.registry import list_tool_specs

        return {spec.name for spec in list_tool_specs() if spec.configurable}
    except Exception:
        return fallback


def _merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    merged = list(existing)
    seen = set(existing)
    for item in additions:
        if item and item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


def _requested_tools_from_goal(goal: str) -> list[str]:
    text = goal.lower()
    if not re.search(r"工具|tool|搜索|联网|网页|python|代码|执行|计算|知识库|文件", text, re.IGNORECASE):
        return []

    requested: list[str] = []

    def add(*names: str) -> None:
        for name in names:
            if name not in requested:
                requested.append(name)

    for name in _available_configurable_tool_names():
        if name.lower() in text:
            add(name)

    if re.search(r"知识库|资料库|rag|检索", text, re.IGNORECASE):
        add("knowledge_search")
    if re.search(r"网页搜索|联网搜索|搜索|web search|internet", text, re.IGNORECASE):
        add("web_search", "web_fetch")
    if re.search(r"网页|链接|url|fetch|抓取", text, re.IGNORECASE):
        add("web_fetch")
    if re.search(r"python|代码|执行|计算|统计|分析工具", text, re.IGNORECASE):
        add("execute_python")
    if re.search(r"文件|读取文件|查文件", text, re.IGNORECASE):
        add("read_file", "grep", "glob")
    if re.search(r"工具|tools?", text, re.IGNORECASE) and not requested:
        add("knowledge_search", "web_search", "web_fetch", "execute_python")

    available = _available_configurable_tool_names()
    return [name for name in requested if name in available]


def _tool_notes(tools: list[str]) -> list[str]:
    descriptions = {
        "knowledge_search": "检索已绑定知识库或 RAG 资料，用于查询标准、话术、历史资料和业务规则。",
        "web_search": "搜索当前网页信息，用于需要最新外部资料的任务。",
        "web_fetch": "读取指定 URL 的正文内容，用于核对搜索结果或用户给出的链接。",
        "execute_python": "执行 Python 计算或数据处理，用于评分、统计、抽样和结构化分析。",
        "read_file": "读取沙箱工作区内的文本文件。",
        "grep": "在沙箱文件中按关键词或正则查找内容。",
        "glob": "按模式查找沙箱文件。",
        "list_skills": "列出已安装 Skills，便于选择可复用能力。",
        "read_skill": "读取指定 Skill 的说明和文件内容。",
    }
    return [f"- `{tool}`：{descriptions.get(tool, '按需调用该工具完成任务。')}" for tool in tools]


def _resource_purpose(kind: str, resource_id: str) -> str:
    if kind == "tool":
        purposes = {
            "knowledge_search": "检索已绑定知识库、业务规则和历史资料。",
            "web_search": "查找当前外部资料，适合需要最新信息的任务。",
            "web_fetch": "读取用户提供或搜索得到的网页正文。",
            "execute_python": "执行计算、抽样、评分和结构化数据处理。",
            "read_file": "读取沙箱工作区中的文件内容。",
            "grep": "在沙箱文件中按关键词或正则定位信息。",
            "glob": "按文件名模式发现沙箱文件。",
            "list_skills": "查找可复用的已安装 Skills。",
            "read_skill": "读取指定 Skill 的说明和资源文件。",
            "skill_manage": "受控创建、修改或维护自定义 Skill。",
        }
        return purposes.get(resource_id, "按需调用该工具完成任务。")
    if kind == "knowledge":
        return "作为 Agent 的检索资料来源，支撑回答、证据和业务规则核对。"
    if kind == "skill":
        return "作为可复用流程或能力包，在运行时辅助 Agent 稳定完成任务。"
    if kind == "mcp":
        return "通过 MCP 暴露外部系统、业务工具或专用数据源。"
    if kind == "dependency":
        return "保存 Skill 后需要同时存在的上游 Skill 能力。"
    return "运行时依赖资源。"


def _resource_item(kind: str, resource_id: str) -> dict[str, str]:
    return {
        "kind": kind,
        "id": resource_id,
        "label": resource_id,
        "purpose": _resource_purpose(kind, resource_id),
    }


def _resource_plan(kind: str, draft: dict[str, Any]) -> dict[str, Any]:
    if kind == "agent":
        tools = _string_list(draft.get("tools"))
        kb_ids = _string_list(draft.get("kb_ids"))
        skill_ids = _string_list(draft.get("skill_ids"))
        mcp_ids = _string_list(draft.get("mcp_ids"))
        return {
            "summary": _resource_plan_summary([*tools, *kb_ids, *skill_ids, *mcp_ids]),
            "counts": {
                "tools": len(tools),
                "kb_ids": len(kb_ids),
                "skill_ids": len(skill_ids),
                "mcp_ids": len(mcp_ids),
            },
            "items": [
                *[_resource_item("tool", item) for item in tools],
                *[_resource_item("knowledge", item) for item in kb_ids],
                *[_resource_item("skill", item) for item in skill_ids],
                *[_resource_item("mcp", item) for item in mcp_ids],
            ],
        }

    required_tools = _string_list(draft.get("required_tools"))
    required_mcp_ids = _string_list(draft.get("required_mcp_ids"))
    skill_dependencies = _string_list(draft.get("skill_dependencies"))
    return {
        "summary": _resource_plan_summary([*required_tools, *required_mcp_ids, *skill_dependencies]),
        "counts": {
            "required_tools": len(required_tools),
            "required_mcp_ids": len(required_mcp_ids),
            "skill_dependencies": len(skill_dependencies),
        },
        "items": [
            *[_resource_item("tool", item) for item in required_tools],
            *[_resource_item("mcp", item) for item in required_mcp_ids],
            *[_resource_item("dependency", item) for item in skill_dependencies],
        ],
    }


def _resource_plan_summary(resource_ids: list[str]) -> str:
    if not resource_ids:
        return "当前草稿未声明外部资源依赖，保存后可先基于用户输入和基础能力运行。"
    return f"当前草稿声明了 {len(resource_ids)} 个运行资源或依赖，保存前请确认这些资源在目标环境中可用。"


def _quality_check(check_id: str, label: str, status: str, message: str) -> dict[str, str]:
    return {"id": check_id, "label": label, "status": status, "message": message}


def _quality_report(kind: str, draft: dict[str, Any]) -> dict[str, Any]:
    checks = _agent_quality_checks(draft) if kind == "agent" else _skill_quality_checks(draft)
    blockers = [item["message"] for item in checks if item["status"] == "fail"]
    warnings = [item["message"] for item in checks if item["status"] == "review"]
    score = 100
    for item in checks:
        if item["status"] == "fail":
            score -= 25
        elif item["status"] == "review":
            score -= 10
    score = max(0, min(100, score))
    status = "blocked" if blockers else "review" if warnings else "ready"
    if status == "ready":
        recommendation = "当前草稿结构完整，可以保存后继续在管理页绑定更多资源。"
    elif status == "review":
        recommendation = "当前草稿可保存，但建议先补齐审查项中标记为需确认的内容。"
    else:
        recommendation = "当前草稿存在阻塞项，请补齐后再保存。"
    return {
        "score": score,
        "status": status,
        "checks": checks,
        "missing": blockers,
        "warnings": warnings,
        "recommendation": recommendation,
    }


def _agent_quality_checks(draft: dict[str, Any]) -> list[dict[str, str]]:
    name = str(draft.get("name") or "").strip()
    description = str(draft.get("description") or "").strip()
    system_prompt = str(draft.get("system_prompt") or "").strip()
    resource_count = sum(
        len(_string_list(draft.get(field)))
        for field in ("tools", "kb_ids", "skill_ids", "mcp_ids")
    )
    return [
        _quality_check(
            "name",
            "名称",
            "pass" if name else "fail",
            "Agent 名称已设置。" if name else "Agent 名称不能为空。",
        ),
        _quality_check(
            "description",
            "职责描述",
            "pass" if len(description) >= 8 else "review",
            "职责描述已覆盖主要用途。" if len(description) >= 8 else "建议补充触发场景、输入和交付物。",
        ),
        _quality_check(
            "system_prompt",
            "系统提示词",
            "pass" if not _thin_agent_prompt(system_prompt) else "fail",
            "系统提示词包含角色、职责、流程、输出和边界。"
            if not _thin_agent_prompt(system_prompt)
            else "系统提示词过短或缺少关键章节。",
        ),
        _quality_check(
            "runtime_resources",
            "运行资源",
            "pass" if resource_count else "review",
            "已声明运行资源或依赖。" if resource_count else "未声明工具、知识库、Skill 或 MCP；可保存后再绑定。",
        ),
        _quality_check(
            "save_target",
            "保存目标",
            "pass",
            "将保存为 NexAgent 自定义 Agent，并继续兼容现有 Agent 管理页。",
        ),
    ]


def _skill_quality_checks(draft: dict[str, Any]) -> list[dict[str, str]]:
    skill_id = str(draft.get("id") or "").strip()
    name = str(draft.get("name") or "").strip()
    description = str(draft.get("description") or "").strip()
    content = str(draft.get("content") or "").strip()
    valid_skill_id = bool(skill_id and _slug_with_hash(skill_id, "skill") == skill_id)
    dependency_count = sum(
        len(_string_list(draft.get(field)))
        for field in ("required_tools", "required_mcp_ids", "skill_dependencies")
    )
    return [
        _quality_check(
            "skill_id",
            "Skill ID",
            "pass" if valid_skill_id else "fail",
            "Skill ID 可作为安装目录使用。" if valid_skill_id else "Skill ID 必须是稳定的 hyphen-case 标识。",
        ),
        _quality_check(
            "name",
            "名称",
            "pass" if name else "fail",
            "Skill 名称已设置。" if name else "Skill 名称不能为空。",
        ),
        _quality_check(
            "description",
            "触发描述",
            "pass" if len(description) >= 8 else "review",
            "触发描述已说明适用场景。" if len(description) >= 8 else "建议补充 Skill 适用场景。",
        ),
        _quality_check(
            "skill_content",
            "SKILL.md 正文",
            "pass" if not _thin_skill_content(content) else "fail",
            "正文包含触发条件、输入、流程、输出、质量检查和示例。"
            if not _thin_skill_content(content)
            else "正文过短或缺少标准章节。",
        ),
        _quality_check(
            "dependencies",
            "依赖声明",
            "pass" if dependency_count else "review",
            "已声明工具、MCP 或上游 Skill 依赖。" if dependency_count else "未声明依赖；适合纯流程类 Skill。",
        ),
        _quality_check(
            "installable_metadata",
            "安装元数据",
            "pass",
            "保存时会写入标准 YAML frontmatter，正文保持为 SKILL.md 内容。",
        ),
    ]


def _append_tool_section(content: str, tools: list[str], *, title: str) -> str:
    missing = [tool for tool in tools if tool not in content]
    if not missing:
        return content
    return "\n".join(
        [
            content.rstrip(),
            "",
            f"## {title}",
            *_tool_notes(missing),
            "- 调用工具前先判断是否真的需要；工具结果必须和用户输入、上下文一起核对后再写入结论。",
        ]
    )


def _apply_agent_directives(goal: str, draft: dict[str, Any]) -> dict[str, Any]:
    requested_tools = _requested_tools_from_goal(goal)
    if not requested_tools:
        return draft
    tools = _merge_unique(_string_list(draft.get("tools")), requested_tools)
    draft = {**draft, "tools": tools}
    draft["system_prompt"] = _append_tool_section(
        str(draft.get("system_prompt") or ""),
        requested_tools,
        title="已绑定工具使用要求",
    )
    return draft


def _apply_skill_directives(goal: str, draft: dict[str, Any]) -> dict[str, Any]:
    requested_tools = _requested_tools_from_goal(goal)
    if not requested_tools:
        return draft
    required_tools = _merge_unique(_string_list(draft.get("required_tools")), requested_tools)
    draft = {**draft, "required_tools": required_tools}
    draft["content"] = _append_tool_section(
        str(draft.get("content") or ""),
        requested_tools,
        title="工具依赖说明",
    )
    return draft


def _directive_message(kind: str, goal: str, draft: dict[str, Any]) -> str:
    requested_tools = _requested_tools_from_goal(goal)
    if not requested_tools:
        return ""
    field = "tools" if kind == "agent" else "required_tools"
    added = [tool for tool in requested_tools if tool in set(_string_list(draft.get(field)))]
    if not added:
        return ""
    target = "Agent" if kind == "agent" else "Skill"
    return (
        f"已添加工具：{', '.join(added)}。"
        f"我也已把这些工具的使用方式写进 {target} 草稿，你可以继续补充细节或直接保存。"
    )


def _normalize_agent_draft(
    goal: str,
    raw: dict[str, Any] | None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = _agent_draft_from_goal(goal, previous)
    draft.update({key: value for key, value in (raw or {}).items() if value is not None})
    base_type = str(draft.get("base_type") or "chatbot").strip()
    if base_type not in {"chatbot", "deep_research"}:
        base_type = "chatbot"
    reasoning_mode = str(draft.get("reasoning_mode") or "balanced").strip()
    if reasoning_mode not in {"fast", "balanced", "deep", "ultra"}:
        reasoning_mode = "balanced"
    name = str(draft.get("name") or _title_from_goal(goal, "自定义 Agent")).strip()
    description = str(draft.get("description") or goal or name).strip()
    system_prompt = str(draft.get("system_prompt") or "").strip()
    if not system_prompt or _thin_agent_prompt(system_prompt):
        system_prompt = _agent_system_prompt_from_goal(goal or description or name, name, system_prompt)
    normalized = {
        "name": name,
        "description": description,
        "base_type": base_type,
        "model_name": str(draft.get("model_name") or "").strip(),
        "system_prompt": system_prompt,
        "tools": _string_list(draft.get("tools")),
        "kb_ids": _string_list(draft.get("kb_ids")),
        "skill_ids": _string_list(draft.get("skill_ids")),
        "mcp_ids": _string_list(draft.get("mcp_ids")),
        "memory_enabled": _bool(draft.get("memory_enabled"), False),
        "thinking_enabled": _bool(draft.get("thinking_enabled"), False),
        "thinking_budget": _int(draft.get("thinking_budget"), 8000, minimum=1024, maximum=32000),
        "reasoning_mode": reasoning_mode,
        "allow_subagents": _bool(draft.get("allow_subagents"), True),
        "avatar_color": str(draft.get("avatar_color") or "emerald").strip() or "emerald",
    }
    return _apply_agent_directives(goal, normalized)


def _normalize_skill_draft(
    goal: str,
    raw: dict[str, Any] | None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = _skill_draft_from_goal(goal, previous)
    draft.update({key: value for key, value in (raw or {}).items() if value is not None})
    skill_id = _slug_with_hash(str(draft.get("id") or draft.get("name") or goal), "skill")
    name = str(draft.get("name") or skill_id).strip()
    description = str(draft.get("description") or goal or name).strip()
    content = _strip_frontmatter(str(draft.get("content") or "").strip())
    if not content:
        content = _skill_body_from_goal(goal, name)
    if not content.lstrip().startswith("#"):
        content = f"# {name}\n\n{content}"
    if _thin_skill_content(content):
        content = _skill_body_from_goal(goal or description or name, name, content)
    normalized = {
        "id": skill_id,
        "name": name,
        "description": description,
        "version": str(draft.get("version") or "0.1.0").strip() or "0.1.0",
        "tags": _string_list(draft.get("tags")),
        "required_mcp_ids": _string_list(draft.get("required_mcp_ids")),
        "required_tools": _string_list(draft.get("required_tools")),
        "skill_dependencies": _string_list(draft.get("skill_dependencies")),
        "content": content,
    }
    return _apply_skill_directives(goal, normalized)


def _normalize_draft(
    kind: str,
    goal: str,
    raw: dict[str, Any] | None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind == "agent":
        return _normalize_agent_draft(goal, raw, previous)
    if kind == "skill":
        return _normalize_skill_draft(goal, raw, previous)
    raise HTTPException(status_code=404, detail="AI 创建 MCP 暂不提供，请在 MCP 管理页手动配置。")


def _creator_system_prompt(kind: str) -> str:
    if kind == "agent":
        schema = (
            '{"message":"给用户看的下一步回复","ready_to_save":true,'
            '"summary":"一句话摘要","draft":{"name":"...","description":"...",'
            '"base_type":"chatbot","system_prompt":"...","tools":[],"kb_ids":[],'
            '"skill_ids":[],"mcp_ids":[],"memory_enabled":false,"thinking_enabled":false,'
            '"thinking_budget":8000,"reasoning_mode":"balanced","allow_subagents":true,'
            '"avatar_color":"emerald"}}'
        )
        target = "NexAgent Agent 配置"
        quality_rules = (
            "Agent 草案必须是可直接保存使用的成品：name 简短明确；description 写清职责和触发场景；"
            "system_prompt 不得少于 600 个中文字符，必须包含角色定位、核心职责、工作流程、输出格式、"
            "工具与协作策略、边界与安全、质量标准。不要输出只有一句话的模板。"
        )
    else:
        schema = (
            '{"message":"给用户看的下一步回复","ready_to_save":true,'
            '"summary":"一句话摘要","draft":{"id":"hyphen-case-id","name":"...",'
            '"description":"触发时机描述","version":"0.1.0","tags":[],"required_tools":[],'
            '"required_mcp_ids":[],"skill_dependencies":[],"content":"# Skill Name\\n..."}}'
        )
        target = "NexAgent Skill"
        quality_rules = (
            "Skill 草案必须是可安装的 SKILL.md 成品：content 正文从一级标题开始，不要在 content 中写 YAML frontmatter；"
            "正文不得少于 700 个中文字符，必须包含：适用场景 / 触发条件、输入、工作流程、输出格式、质量检查、示例。"
            "description 要写触发时机，required_tools/required_mcp_ids/skill_dependencies 只填写真实需要的依赖。"
        )
    return (
        f"你是 NexAgent 的 {target} 创建助手。通过简洁中文对话收集需求，并持续维护一个可保存草案。"
        "如果信息不足，最多问 1 个关键澄清问题；如果已有足够信息，直接生成可保存成品。"
        "当用户要求保存、继续完善或已经描述了目标时，少量缺失信息应做合理假设并在草案中体现，不要让用户手写配置。"
        "不要创建 MCP。不要推荐用户再去手写 JSON。"
        f"{quality_rules}"
        "只返回一个 JSON 对象，不要 Markdown 代码块，不要额外解释。JSON 结构必须符合："
        f"{schema}"
    )


def _json_from_model_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", stripped)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Creator model returned non-object JSON")
    return parsed


def _message_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value or "")


async def _model_creator_payload(body: CreatorChatRequest, kind: str) -> dict[str, Any]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from nexagent.models.factory import load_chat_model_async

    model = await load_chat_model_async(body.model, streaming=False)
    lc_messages = [SystemMessage(content=_creator_system_prompt(kind))]
    for item in body.messages[-16:]:
        content = item.content.strip()
        if not content:
            continue
        if item.role == "assistant":
            lc_messages.append(AIMessage(content=content))
        else:
            lc_messages.append(HumanMessage(content=content))
    if body.draft:
        lc_messages.append(
            HumanMessage(content="当前未保存草案 JSON：\n" + json.dumps(body.draft, ensure_ascii=False, indent=2))
        )
    lc_messages.append(HumanMessage(content=body.message.strip()))
    response = await model.ainvoke(lc_messages)
    return _json_from_model_text(_message_content(getattr(response, "content", response)))


def _fallback_creator_payload(kind: str, body: CreatorChatRequest) -> dict[str, Any]:
    goal = _conversation_goal(body)
    if kind == "agent":
        name = str(body.draft.get("name") or _title_from_goal(goal, "自定义 Agent")).strip()
        raw = {
            **body.draft,
            "name": name,
            "description": str(body.draft.get("description") or goal).strip(),
            "system_prompt": _agent_system_prompt_from_goal(
                goal,
                name,
                str(body.draft.get("system_prompt") or "").strip(),
            ),
        }
    else:
        name = str(body.draft.get("name") or _title_from_goal(goal, "自定义 Skill")).strip()
        raw = {
            **body.draft,
            "name": name,
            "description": str(body.draft.get("description") or goal).strip(),
            "content": _skill_body_from_goal(
                goal,
                name,
                str(body.draft.get("content") or "").strip(),
            ),
        }
    draft = _normalize_draft(kind, goal, raw, body.draft)
    return {
        "message": (
            "我已根据当前对话整理出一版可保存成品草案。"
            "少量缺失信息已按上下文做了合理假设，你可以继续补充细节，也可以直接保存。"
        ),
        "ready_to_save": True,
        "summary": _summary("Agent" if kind == "agent" else "Skill", draft),
        "draft": draft,
    }


@router.post("/chat")
async def creator_chat(body: CreatorChatRequest):
    kind = body.kind.strip().lower()
    if kind == "mcp":
        raise HTTPException(status_code=404, detail="AI 创建 MCP 暂不提供，请在 MCP 管理页手动配置。")
    if kind not in {"agent", "skill"}:
        raise HTTPException(status_code=404, detail=f"Unsupported creator kind: {body.kind}")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")

    try:
        payload = await _model_creator_payload(body, kind)
    except Exception:
        payload = _fallback_creator_payload(kind, body)

    raw_draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
    goal = _conversation_goal(body)
    draft = _normalize_draft(kind, goal, raw_draft, body.draft)
    quality = _quality_report(kind, draft)
    resource_plan = _resource_plan(kind, draft)
    message = str(payload.get("message") or "已更新草案。").strip()
    message = _directive_message(kind, goal, draft) or message
    ready = _bool(payload.get("ready_to_save"), True) and quality["status"] != "blocked"
    return {
        "kind": kind,
        "thread_id": body.thread_id or str(uuid.uuid4()),
        "message": message,
        "ready_to_save": ready,
        "summary": str(payload.get("summary") or _summary(kind, draft)),
        "draft": draft,
        "quality": quality,
        "resource_plan": resource_plan,
    }


@router.post("/agent/draft")
async def draft_agent(body: DraftRequest):
    goal = body.goal.strip()
    draft = _normalize_agent_draft(goal, _agent_draft_from_goal(goal, body.details))
    return {
        "kind": "agent",
        "summary": _summary("Agent", draft),
        "draft": draft,
        "quality": _quality_report("agent", draft),
        "resource_plan": _resource_plan("agent", draft),
    }


@router.post("/skill/draft")
async def draft_skill(body: DraftRequest):
    goal = body.goal.strip()
    draft = _normalize_skill_draft(goal, _skill_draft_from_goal(goal, body.details))
    return {
        "kind": "skill",
        "summary": _summary("Skill", draft),
        "draft": draft,
        "quality": _quality_report("skill", draft),
        "resource_plan": _resource_plan("skill", draft),
    }


@router.post("/mcp/draft")
async def draft_mcp(body: DraftRequest):
    raise HTTPException(status_code=404, detail="AI 创建 MCP 暂不提供，请在 MCP 管理页手动配置。")


@router.post("/agent/save", status_code=201)
async def save_agent(body: SaveRequest):
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    raw_draft = body.draft
    goal = str(raw_draft.get("description") or raw_draft.get("name") or "").strip()
    draft = _normalize_agent_draft(goal, raw_draft)
    if not str(draft.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="Agent name is required")

    async with AsyncSessionLocal() as session:
        agent = AgentConfig(
            name=str(draft["name"]).strip(),
            description=str(draft.get("description") or ""),
            base_type=str(draft.get("base_type") or "chatbot"),
            model_name=str(draft.get("model_name") or "") or None,
            system_prompt=str(draft.get("system_prompt") or ""),
            tools=list(draft.get("tools") or []),
            memory_enabled=bool(draft.get("memory_enabled", False)),
            thinking_enabled=bool(draft.get("thinking_enabled", False)),
            thinking_budget=int(draft.get("thinking_budget") or 8000),
            reasoning_mode=str(draft.get("reasoning_mode") or "balanced"),
            allow_subagents=bool(draft.get("allow_subagents", True)),
            is_builtin=False,
            avatar_color=str(draft.get("avatar_color") or "emerald"),
        )
        agent.kb_ids = list(draft.get("kb_ids") or [])
        agent.skill_ids = list(draft.get("skill_ids") or [])
        agent.mcp_ids = list(draft.get("mcp_ids") or [])
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return {"saved": agent.to_dict(), "message": "Agent 已保存，可在 Agent 管理页面继续配置。"}


@router.post("/skill/save", status_code=201)
async def save_skill(body: SaveRequest):
    from app.gateway.routers.skills import SkillCustomRequest, custom

    raw_draft = body.draft
    goal = str(raw_draft.get("description") or raw_draft.get("name") or raw_draft.get("id") or "").strip()
    draft = _normalize_skill_draft(goal, raw_draft)
    request = SkillCustomRequest(
        id=str(draft.get("id") or ""),
        name=str(draft.get("name") or draft.get("id") or ""),
        description=str(draft.get("description") or ""),
        content=str(draft.get("content") or ""),
        version=str(draft.get("version") or "0.1.0"),
        tags=list(draft.get("tags") or []),
        required_mcp_ids=list(draft.get("required_mcp_ids") or []),
        required_tools=list(draft.get("required_tools") or []),
        skill_dependencies=list(draft.get("skill_dependencies") or []),
        force=bool(raw_draft.get("force", False)),
    )
    saved = await custom(request)
    return {"saved": saved, "message": "Skill 已保存，可在 Skills 页面绑定给 Agent。"}


@router.post("/mcp/save", status_code=201)
async def save_mcp(body: SaveRequest):
    raise HTTPException(status_code=404, detail="AI 创建 MCP 暂不提供，请在 MCP 管理页手动配置。")
