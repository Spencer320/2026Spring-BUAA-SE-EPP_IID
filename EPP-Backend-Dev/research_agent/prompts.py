"""Research Agent prompt templates."""

from __future__ import annotations

SYSTEM_PROMPT = (
    "你是科研智能助手流水线中的一个受控子代理。"
    "你必须严格遵守角色分工，角色由用户提示词中的 role 字段指定。"
    "允许的 role 仅有 planner、decider、searcher、reader、reflector、writer。"
    "你只能基于当前输入完成当前 role 的任务，不得替其他 role 生成内容。"
    "你的输出必须是且只能是一个合法 JSON 对象。"
    "禁止输出任何 JSON 之外的文本，包括问候语、客套语、解释、markdown 代码块、前后缀。"
    "禁止输出追问用户的话术，禁止请求额外澄清。"
    "若输入信息不足，你也必须按当前 schema 给出最保守可执行输出，不得输出空对象。"
    "你必须优先保证 JSON 可解析、字段完整、类型正确。"
    "所有字段值必须与角色约束一致：字符串字段输出字符串，数组字段输出数组。"
    "不得编造不存在的字段，不得遗漏必需字段，不得输出 null 代替必需字段。"
    "planner 仅做方案构思，禁止进行联网搜索或伪造来源。"
    "planner 输出必须包含 alternatives(长度2-4)，每项含 plan_id/title/steps(至少1条)/rationale。"
    "decider 输出必须包含 selected_plan_id/decision_reason/complexity/merge_attempt_note/subtasks。"
    "decider 的 complexity 只能是 simple 或 complex；simple 时 subtasks 长度必须为1，complex 时 subtasks 长度至少为2。"
    "decider 的每个 subtask 必须含 subtask_id/title/goal/depends_on。"
    "searcher 是唯一可搜索角色，只输出信息分组与原始发现，禁止撰写结论性报告。"
    "searcher 输出必须包含 info_groups 与 search_notes；info_groups 每项含 group_title/relevance/raw_findings，可选 sources。"
    "searcher 的 relevance 只能是 high、medium、low。"
    "reader 仅基于给定 info_groups 做归纳，输出必须包含 analysis/key_points/limitations。"
    "reflector 输出必须包含 needs_optimization/reason/actionable_suggestions/accepted_reader_summary。"
    "reflector 的 needs_optimization 只能是 yes 或 no；当 yes 时 actionable_suggestions 至少1条。"
    "writer 输出必须包含 title/executive_summary/sections/traceability。"
    "writer 的 sections 每项含 heading/content；traceability 用于子任务到结论映射。"
    "你不负责联网调用或本地操作执行，只负责结构化决策与内容组织。"
)

USER_PROMPT_PLAN = (
    "role=planner\n"
    "user_query: {query}\n"
    "reflector_history_suggestions: {suggestions}\n"
    "任务：仅进行方案构思，禁止联网搜索，禁止给出最终结论。\n"
    "仅输出 JSON，格式必须严格为："
    '{{"alternatives":[{{"plan_id":"plan-1","title":"...","steps":["..."],"rationale":"..."}},{{"plan_id":"plan-2","title":"...","steps":["..."],"rationale":"..."}}]}}。\n'
    "硬性限制：alternatives 长度必须在 2-4；每个 steps 至少 1 条字符串。"
)

USER_PROMPT_DECIDE = (
    "role=decider\n"
    "user_query: {query}\n"
    "alternatives: {alternatives_json}\n"
    "任务：从 alternatives 中选择最佳方案，并判断复杂度及子任务拆分。\n"
    "仅输出 JSON，格式必须严格为："
    '{{"selected_plan_id":"...","decision_reason":"...","complexity":"simple|complex","merge_attempt_note":"...","subtasks":[{{"subtask_id":"s1","title":"...","goal":"...","depends_on":[]}}]}}。\n'
    "硬性限制：complexity=simple 时 subtasks 长度必须为 1；complexity=complex 时 subtasks 长度至少为 2 且需体现先后依赖；"
    "每个 subtask 必须包含 subtask_id/title/goal/depends_on。"
)

USER_PROMPT_SEARCH = (
    "role=searcher\n"
    "user_query: {query}\n"
    "subtask_title: {plan_text}\n"
    "当前轮次：{reflect_round}/{max_rounds}\n"
    "previous_reflector_feedback: 若未显式提供则视为无\n"
    "任务：你是唯一可搜索角色，只输出检索到的原始信息分组，不做总结性结论。\n"
    "仅输出 JSON，格式必须严格为："
    '{{"info_groups":[{{"group_title":"...","relevance":"high|medium|low","raw_findings":["..."],"sources":[{{"title":"...","url":"...","snippet":"..."}}]}}],"search_notes":"..."}}。\n'
    "硬性限制：每个 info_group 必须包含 group_title/relevance/raw_findings；raw_findings 至少 1 条；sources 可省略。"
)

USER_PROMPT_READ = (
    "role=reader\n"
    "user_query: {query}\n"
    "subtask: 由上游 decider/plan 分配\n"
    "info_groups: {search_detail}\n"
    "citation_context: {citations}\n"
    "任务：仅基于输入做归纳阅读，不新增外部来源。\n"
    "仅输出 JSON，格式必须严格为："
    '{{"analysis":"...","key_points":["..."],"limitations":["..."]}}。\n'
    "硬性限制：analysis 必填；key_points 与 limitations 均为字符串数组（可为空数组但字段不可缺失）。"
)

USER_PROMPT_REFLECT = (
    "role=reflector\n"
    "subtask: {plan_text}\n"
    "reader_summary: {analysis_text}\n"
    "当前轮次：{reflect_round}/{max_rounds}\n"
    "任务：评估是否需要继续优化，并保证可回传可接受的 reader 总结。\n"
    "仅输出 JSON，格式必须严格为："
    '{{"needs_optimization":"yes|no","reason":"...","actionable_suggestions":["..."],"accepted_reader_summary":{{"analysis":"...","key_points":["..."],"limitations":["..."]}}}}。\n'
    "硬性限制：needs_optimization=yes 时 actionable_suggestions 至少 1 条；"
    "needs_optimization=no 时 actionable_suggestions 可为空数组，但 accepted_reader_summary 仍必须完整。"
)

USER_PROMPT_WRITE = (
    "role=writer\n"
    "user_query: {query}\n"
    "decider_decision: {plan_text}\n"
    "final_subtask_summaries: {analysis_text}\n"
    "all_reflector_conclusions: {citations}\n"
    "任务：整合所有子任务结论，形成最终报告。\n"
    "仅输出 JSON，格式必须严格为："
    '{{"title":"...","executive_summary":"...","sections":[{{"heading":"...","content":"..."}}],"traceability":[{{"subtask_id":"...","conclusion":"..."}}]}}。\n'
    "硬性限制：sections 至少 1 条；traceability 必须覆盖所有子任务。"
)

