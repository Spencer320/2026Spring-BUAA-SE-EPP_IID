<template>
    <el-drawer
        v-model="visible"
        title="执行轨迹"
        direction="rtl"
        size="45%"
        @open="handleOpen"
    >
        <template #header>
            <div class="drawer-header">
                <span class="drawer-title">执行轨迹</span>
                <el-tag v-if="taskInfo.status" :type="statusTagType(taskInfo.status)" size="small" style="margin-left: 10px">
                    {{ statusLabel(taskInfo.status) }}
                </el-tag>
            </div>
        </template>

        <div v-loading="loading" class="trace-content">
            <!-- 任务基本信息 -->
            <div class="task-summary" v-if="taskInfo.query">
                <div class="task-query">
                    <el-icon><i-ep-Search /></el-icon>
                    <span>{{ taskInfo.query }}</span>
                </div>
                <div class="task-meta">
                    <el-tag size="small" effect="plain">进度 {{ taskInfo.progress ?? 0 }}%</el-tag>
                    <el-tag size="small" effect="plain" style="margin-left: 8px">
                        Token 消耗：{{ formatToken(taskInfo.token_used_total) }}
                    </el-tag>
                </div>
                <el-progress
                    v-if="taskInfo.status === 'running'"
                    :percentage="taskInfo.progress ?? 0"
                    :stroke-width="6"
                    style="margin-top: 8px"
                />
            </div>

            <el-divider content-position="left">步骤详情（共 {{ steps.length }} 步）</el-divider>

            <!-- 执行步骤时间线 -->
            <el-timeline v-if="steps.length > 0">
                <el-timeline-item
                    v-for="step in steps"
                    :key="step.seq"
                    :timestamp="step.created_at"
                    placement="top"
                    :color="phaseColor(step.phase)"
                >
                    <div class="step-card">
                        <div class="step-card-header">
                            <el-tag :color="phaseColor(step.phase)" effect="dark" size="small" class="phase-tag">
                                {{ phaseLabel(step.phase) }}
                            </el-tag>
                            <span class="step-seq">#{{ step.seq }}</span>
                            <span class="step-action">{{ step.action }}</span>
                            <span v-if="step.token_used > 0" class="step-token">
                                <el-icon><i-ep-Coin /></el-icon>{{ step.token_used }}
                            </span>
                        </div>
                        <div class="step-summary" v-if="step.summary">
                            <el-text class="step-summary-text" truncated>{{ step.summary }}</el-text>
                            <el-button
                                v-if="step.summary.length > 80"
                                size="small"
                                text
                                @click="toggleExpand(step.seq)"
                                style="padding: 0; margin-left: 4px"
                            >
                                {{ expandedSteps.has(step.seq) ? '收起' : '展开' }}
                            </el-button>
                            <div v-if="expandedSteps.has(step.seq)" class="step-summary-full">
                                {{ step.summary }}
                            </div>
                        </div>
                    </div>
                </el-timeline-item>
            </el-timeline>

            <el-empty v-else-if="!loading" description="暂无执行步骤记录" />
        </div>

        <template #footer>
            <div class="drawer-footer">
                <el-button @click="visible = false">关闭</el-button>
                <el-button type="primary" plain @click="handleOpen" :loading="loading">
                    <el-icon><i-ep-Refresh /></el-icon>刷新轨迹
                </el-button>
            </div>
        </template>
    </el-drawer>
</template>

<script>
import { getDRTaskTrace } from '@/api/deep_research.js'
import { ElMessage } from 'element-plus'

const PHASE_CONFIG = {
    planning:   { label: '规划', color: '#409EFF' },
    searching:  { label: '检索', color: '#67C23A' },
    reading:    { label: '阅读', color: '#E6A23C' },
    reflecting: { label: '反思', color: '#909399' },
    writing:    { label: '生成报告', color: '#F56C6C' }
}

const STATUS_MAP = {
    pending:           { label: '待处理',    type: 'info' },
    queued:            { label: '排队中',    type: 'info' },
    running:           { label: '执行中',    type: 'warning' },
    completed:         { label: '已完成',    type: 'success' },
    failed:            { label: '失败',      type: 'danger' },
    aborted:           { label: '用户中止',  type: 'info' },
    admin_stopped:     { label: '管理员中断', type: 'danger' },
    violation_pending: { label: '合规审核中', type: 'warning' },
    needs_review:      { label: '待人工审核', type: 'warning' },
    archived:          { label: '已归档',    type: 'info' }
}

export default {
    props: {
        taskId: { type: String, default: '' }
    },
    emits: ['update:taskId'],
    data() {
        return {
            visible: false,
            loading: false,
            taskInfo: {},
            steps: [],
            expandedSteps: new Set()
        }
    },
    watch: {
        taskId(val) {
            if (val) this.open()
        }
    },
    methods: {
        open() {
            this.visible = true
        },
        handleOpen() {
            if (!this.taskId) return
            this.fetchTrace()
        },
        async fetchTrace() {
            this.loading = true
            await getDRTaskTrace(this.taskId)
                .then((res) => {
                    const data = res.data || {}
                    this.taskInfo = {
                        query: data.query,
                        status: data.status,
                        progress: data.progress,
                        token_used_total: data.token_used_total
                    }
                    this.steps = data.steps || []
                    this.expandedSteps = new Set()
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取执行轨迹失败')
                })
            this.loading = false
        },
        phaseLabel(phase) {
            return PHASE_CONFIG[phase]?.label || phase
        },
        phaseColor(phase) {
            return PHASE_CONFIG[phase]?.color || '#909399'
        },
        statusLabel(status) {
            return STATUS_MAP[status]?.label || status
        },
        statusTagType(status) {
            return STATUS_MAP[status]?.type || 'info'
        },
        formatToken(num) {
            if (!num && num !== 0) return '—'
            if (num >= 10000) return (num / 10000).toFixed(1) + ' 万'
            return num.toString()
        },
        toggleExpand(seq) {
            const s = new Set(this.expandedSteps)
            if (s.has(seq)) s.delete(seq)
            else s.add(seq)
            this.expandedSteps = s
        }
    }
}
</script>

<style lang="scss" scoped>
.drawer-header {
    display: flex;
    align-items: center;
    .drawer-title {
        font-size: 16px;
        font-weight: bold;
    }
}
.trace-content {
    padding: 0 4px;
    min-height: 200px;
}
.task-summary {
    background: #f5f7fa;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 16px;
    .task-query {
        display: flex;
        align-items: flex-start;
        gap: 6px;
        font-size: 14px;
        color: #303133;
        margin-bottom: 8px;
        .el-icon { margin-top: 2px; flex-shrink: 0; }
    }
    .task-meta {
        display: flex;
        gap: 8px;
    }
}
.step-card {
    background: #fff;
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 10px 14px;
    .step-card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;
        flex-wrap: wrap;
    }
    .phase-tag {
        border: none;
    }
    .step-seq {
        font-size: 12px;
        color: #909399;
        font-weight: bold;
    }
    .step-action {
        flex: 1;
        font-size: 13px;
        font-weight: 500;
        color: #303133;
    }
    .step-token {
        font-size: 12px;
        color: #909399;
        display: flex;
        align-items: center;
        gap: 2px;
    }
    .step-summary {
        font-size: 13px;
        color: #606266;
        line-height: 1.5;
    }
    .step-summary-full {
        margin-top: 6px;
        white-space: pre-wrap;
        font-size: 12px;
        color: #606266;
        background: #f5f7fa;
        border-radius: 4px;
        padding: 8px;
    }
}
.drawer-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
}
</style>
