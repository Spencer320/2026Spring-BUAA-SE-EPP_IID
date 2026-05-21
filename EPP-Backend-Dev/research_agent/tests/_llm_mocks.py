"""科研助手测试用 LLM mock（深度研究 / basic / Smart Planner）。"""

from __future__ import annotations

import json

from research_agent.llm_client import LLMCallResult


_MOCK_SEARCH_QUERIES = (
    '[{"q":"transformer attention survey","intent":"background","rationale":"mock"}]'
)


def _mock_subtask_json() -> str:
    return (
        '{"subtask_id":"s1","title":"执行子任务","goal":"完成研究","depends_on":[],'
        f'"search_queries":{_MOCK_SEARCH_QUERIES}}}'
    )


def fake_deep_research_llm_call(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    if "role=reflector" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=(
                '{"needs_optimization":"no","reason":"当前信息已足够完成报告",'
                '"actionable_suggestions":[],"additional_search_queries":[],'
                '"search_evidence_adequate":"yes","accepted_reader_summary":{'
                '"analysis":"基于当前证据，研究方向可行。","key_points":["研究方向可行"],'
                '"limitations":["证据数量有限"]}}'
            ),
            model="mock-llm",
        )
    if "role=writer" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=(
                '{"title":"研究报告","executive_summary":"这是执行摘要。",'
                '"sections":[{"heading":"研究问题","content":"测试问题"},'
                '{"heading":"结论","content":"这是来自 LLM 的测试报告。"}],'
                '"traceability":[{"subtask_id":"s1","conclusion":"结论1"}]}'
            ),
            model="mock-llm",
        )
    if "role=reader" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=(
                '{"analysis":"基于当前证据，研究方向可行。","key_points":["研究方向可行"],'
                '"limitations":["证据数量有限"]}'
            ),
            model="mock-llm",
        )
    if "role=searcher" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=(
                '{"info_groups":[{"group_title":"基础信息","relevance":"high",'
                '"raw_findings":["发现1"],'
                '"sources":[{"title":"source1","url":"https://example.com","snippet":"snippet"}]}],'
                '"search_notes":"检索完成"}'
            ),
            model="mock-llm",
        )
    if "role=decider" in user_prompt:
        subtask = _mock_subtask_json()
        return LLMCallResult(
            ok=True,
            content=(
                '{"selected_plan_id":"plan-1","decision_reason":"方案可执行","complexity":"simple",'
                '"merge_attempt_note":"任务已合并",'
                f'"subtasks":[{subtask}]}}'
            ),
            model="mock-llm",
        )
    if "role=plan_decider" in user_prompt:
        subtask = _mock_subtask_json()
        return LLMCallResult(
            ok=True,
            content=(
                '{"alternatives":[{"plan_id":"plan-1","title":"方案A","steps":["步骤1"],"rationale":"理由A"},'
                '{"plan_id":"plan-2","title":"方案B","steps":["步骤1"],"rationale":"理由B"}],'
                '"selected_plan_id":"plan-1","decision_reason":"方案可执行","complexity":"simple",'
                '"merge_attempt_note":"任务已合并",'
                f'"subtasks":[{subtask}]}}'
            ),
            model="mock-llm",
        )
    return LLMCallResult(
        ok=True,
        content=(
            '{"alternatives":[{"plan_id":"plan-1","title":"方案A","steps":["步骤1"],"rationale":"理由A"},'
            '{"plan_id":"plan-2","title":"方案B","steps":["步骤1"],"rationale":"理由B"}]}'
        ),
        model="mock-llm",
    )


def fake_deep_research_llm_invalid_reflect(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    if "role=reflector" in user_prompt:
        return LLMCallResult(ok=True, content="not-json", model="mock-llm")
    return fake_deep_research_llm_call(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


def fake_deep_research_llm_audit_style(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    if "role=planner" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "alternatives": [
                        {
                            "plan_id": "plan-1",
                            "title": "方案一",
                            "steps": ["检索背景", "分析证据"],
                            "rationale": "覆盖核心问题",
                        },
                        {
                            "plan_id": "plan-2",
                            "title": "方案二",
                            "steps": ["先写后查"],
                            "rationale": "快速收敛",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=decider" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "selected_plan_id": "plan-1",
                    "decision_reason": "覆盖更完整",
                    "complexity": "simple",
                    "merge_attempt_note": "不需要合并",
                    "subtasks": [
                        {
                            "subtask_id": "s1",
                            "title": "背景与证据",
                            "goal": "完成基础调研",
                            "depends_on": [],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=searcher" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "info_groups": [
                        {
                            "group_title": "基础资料",
                            "relevance": "high",
                            "raw_findings": ["找到若干公开来源"],
                            "sources": [
                                {
                                    "title": "source",
                                    "url": "https://example.org",
                                    "snippet": "snippet",
                                }
                            ],
                        }
                    ],
                    "search_notes": "可继续阅读",
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=reader" in user_prompt:
        return LLMCallResult(
            ok=True,
            content='{"analysis":"阅读分析","key_points":["点1"],"limitations":["限1"]}',
            model="mock-llm",
        )
    if "role=reflector" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "needs_optimization": "no",
                    "reason": "已满足要求",
                    "actionable_suggestions": [],
                    "accepted_reader_summary": {
                        "analysis": "阅读分析",
                        "key_points": ["点1"],
                        "limitations": ["限1"],
                    },
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    if "role=writer" in user_prompt:
        return LLMCallResult(
            ok=True,
            content=json.dumps(
                {
                    "title": "研究报告",
                    "executive_summary": "摘要",
                    "sections": [{"heading": "结论", "content": "测试"}],
                    "traceability": [{"subtask_id": "s1", "conclusion": "完成调研"}],
                },
                ensure_ascii=False,
            ),
            model="mock-llm",
        )
    return LLMCallResult(ok=True, content="{}", model="mock-llm")


def fake_smart_planner_llm_call(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    return LLMCallResult(
        ok=True,
        content=json.dumps(
            {
                "summary": "单步对话（测试）",
                "steps": [
                    {
                        "type": "chat",
                        "title": "直接回复用户",
                        "prompt": "请用简洁中文回答用户问题。",
                        "use_history": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        model="mock-llm",
    )


def fake_basic_chat_llm_call(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    return LLMCallResult(
        ok=True,
        content="（测试）basic 编排器 mock 回复。",
        model="mock-llm",
    )


def fake_smart_planner_agent_zip_llm_call(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    return LLMCallResult(
        ok=True,
        content=json.dumps(
            {
                "summary": "工作区压缩任务",
                "steps": [
                    {
                        "type": "agent",
                        "title": "压缩 papers",
                        "delegate_prompt": "将 papers 目录压缩为 papers.zip",
                        "intent": "压缩工作区目录",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        model="mock-llm",
    )


def fake_smart_planner_agent_write_llm_call(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    return LLMCallResult(
        ok=True,
        content=json.dumps(
            {
                "summary": "工作区写文件",
                "steps": [
                    {
                        "type": "agent",
                        "title": "写入 intro.md",
                        "delegate_prompt": "新建 intro.md 并写入介绍检索增强生成的段落",
                        "intent": "写入工作区文件",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        model="mock-llm",
    )


def fake_basic_step_refill_llm_call(
    *, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int, **kwargs
):
    return LLMCallResult(
        ok=True,
        content=json.dumps({"query": "测试检索词", "delegate_prompt": "测试工作区任务"}, ensure_ascii=False),
        model="mock-llm",
    )
