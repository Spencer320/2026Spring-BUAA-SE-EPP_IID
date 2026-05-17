<template>
    <el-drawer v-model="visible" :title="title" direction="rtl" size="55%" :destroy-on-close="true" @open="loadChain">
        <div v-loading="loading" class="chain-container">
            <el-descriptions v-if="chainTask.task_id" border :column="1" size="small">
                <el-descriptions-item label="任务名">{{ chainTask.task_name || chainTask.query || '—' }}</el-descriptions-item>
                <el-descriptions-item label="任务ID">{{ chainTask.task_id }}</el-descriptions-item>
                <el-descriptions-item label="运行类型">{{ chainTask.run_kind || '—' }}</el-descriptions-item>
                <el-descriptions-item label="会话ID">{{ chainTask.session_id }}</el-descriptions-item>
                <el-descriptions-item label="用户">{{ chainTask.user_name || chainTask.user_id }}</el-descriptions-item>
                <el-descriptions-item label="状态">{{ chainTask.status }}</el-descriptions-item>
                <el-descriptions-item v-if="scope === 'assistant'" label="Token 消耗">
                    <span v-if="chainTask.token_usage != null">{{ formatTokens(chainTask.token_usage) }}</span>
                    <span v-else>—</span>
                </el-descriptions-item>
                <el-descriptions-item v-if="chainTask.workspace_run_count != null" label="工作区子运行">
                    {{ chainTask.workspace_run_count }}
                </el-descriptions-item>
            </el-descriptions>

            <el-timeline v-if="chainLogs.length > 0" style="margin-top: 16px">
                <el-timeline-item
                    v-for="log in chainLogs"
                    :key="log.id"
                    :timestamp="log.occurred_at"
                    :type="log.is_exception ? 'danger' : 'primary'"
                >
                    <div class="timeline-card">
                        <div class="timeline-title">
                            <el-tag size="small" effect="plain">{{ operationLabel(log.operation_type) }}</el-tag>
                            <span v-if="log.run_kind" class="timeline-domain">{{ log.run_kind }}</span>
                            <span v-if="log.target_domain" class="timeline-domain">{{ log.target_domain }}</span>
                        </div>
                        <div class="timeline-detail">{{ log.trace_detail || log.exception_message || '—' }}</div>
                        <div class="timeline-meta">
                            工具：{{ log.tool_type || '—' }} / 状态：{{ log.status || '—' }} /
                            {{ log.operation_type === 'workspace_turn' ? '轮次' : '步骤' }}：{{ log.step_id ?? '—' }}
                        </div>
                    </div>
                </el-timeline-item>
            </el-timeline>
            <el-empty v-else-if="!loading" description="该任务暂无行为审计记录" />
        </div>
    </el-drawer>
</template>

<script>
import { ElMessage } from 'element-plus'
import { getAssistantTaskBehaviorChain, getDeepResearchTaskBehaviorChain } from '@/api/research_agent_audit.js'

const OP_LABELS = {
    basic_smart_plan: 'Smart Planner 拆解',
    basic_smart_plan_fallback: 'Planner 回退',
    basic_step_refill: '子任务补参',
    basic_chat: 'Chat 子任务',
    basic_search: 'Search 子任务',
    workspace_turn: '工作区轮次',
    plan: '深度研究-规划',
    decide: '深度研究-决策',
    search: '深度研究-检索',
    read: '深度研究-阅读',
    reflect: '深度研究-反思',
    write: '深度研究-撰写'
}

export default {
    name: 'RunBehaviorChainDrawer',
    props: {
        scope: {
            type: String,
            required: true,
            validator: (v) => ['assistant', 'deep-research'].includes(v)
        }
    },
    data() {
        return {
            visible: false,
            loading: false,
            taskId: '',
            chainTask: {},
            chainLogs: []
        }
    },
    computed: {
        title() {
            return this.scope === 'deep-research' ? '深度研究 · 行为审计链路' : '科研助手 · 行为审计链路'
        }
    },
    methods: {
        operationLabel(op) {
            return OP_LABELS[op] || op || '—'
        },
        formatTokens(n) {
            const v = Number(n)
            if (!Number.isFinite(v)) return '—'
            return v.toLocaleString('zh-CN')
        },
        open(taskId) {
            this.taskId = taskId
            this.visible = true
        },
        async loadChain() {
            if (!this.taskId) return
            this.loading = true
            this.chainTask = {}
            this.chainLogs = []
            const fetcher =
                this.scope === 'deep-research'
                    ? getDeepResearchTaskBehaviorChain
                    : getAssistantTaskBehaviorChain
            await fetcher(this.taskId)
                .then((res) => {
                    this.chainTask = res.data.task || {}
                    this.chainLogs = res.data.logs || []
                })
                .catch((err) => {
                    const data = err.response?.data || {}
                    const errObj = data.error
                    const msg =
                        (typeof errObj === 'string' ? errObj : errObj?.message) ||
                        data.message ||
                        err.message ||
                        '获取行为链路失败'
                    ElMessage.error(msg)
                })
            this.loading = false
        }
    }
}
</script>

<style lang="scss" scoped>
.chain-container {
    padding: 0 4px 24px;
}
.timeline-card {
    .timeline-title {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;
        flex-wrap: wrap;
    }
    .timeline-domain {
        color: #606266;
        font-size: 13px;
    }
    .timeline-detail {
        font-size: 13px;
        color: #303133;
        margin-bottom: 4px;
        white-space: pre-wrap;
    }
    .timeline-meta {
        font-size: 12px;
        color: #909399;
    }
}
</style>
