<template>
    <el-drawer
        v-model="visible"
        direction="rtl"
        size="42%"
        @open="handleOpen"
    >
        <template #header>
            <div class="drawer-header">
                <span class="drawer-title">任务详情</span>
                <el-tag
                    v-if="task.status"
                    :type="statusTagType(task.status)"
                    size="small"
                    style="margin-left: 10px"
                >{{ statusLabel(task.status) }}</el-tag>
            </div>
        </template>

        <div v-loading="loading" class="detail-content">
            <!-- 基本信息 -->
            <el-descriptions :column="1" border size="small" v-if="task.task_id">
                <el-descriptions-item label="任务ID">
                    <span class="mono-text">{{ task.task_id }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="用户名">{{ task.username }}</el-descriptions-item>
                <el-descriptions-item label="研究问题">
                    <div style="white-space: pre-wrap">{{ task.query }}</div>
                </el-descriptions-item>
                <el-descriptions-item label="当前阶段">
                    <el-tag v-if="task.current_phase" :color="phaseColor(task.current_phase)" effect="dark" size="small">
                        {{ phaseLabel(task.current_phase) }}
                    </el-tag>
                    <span v-else>—</span>
                </el-descriptions-item>
                <el-descriptions-item label="进度">
                    <div style="display: flex; align-items: center; gap: 10px; width: 100%">
                        <el-progress :percentage="task.progress ?? 0" style="flex: 1" :stroke-width="8" />
                        <span>{{ task.progress ?? 0 }}%</span>
                    </div>
                </el-descriptions-item>
                <el-descriptions-item label="最新步骤">
                    <span style="color: #606266; font-size: 13px">{{ task.step_summary || '—' }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="Token 消耗">{{ formatToken(task.token_used_total) }}</el-descriptions-item>
                <el-descriptions-item label="输出状态">
                    <el-tag v-if="task.output_suppressed" type="danger" size="small">已屏蔽</el-tag>
                    <el-tag v-else type="success" size="small">正常</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="创建时间">{{ task.created_at || '—' }}</el-descriptions-item>
                <el-descriptions-item label="开始时间">{{ task.started_at || '—' }}</el-descriptions-item>
                <el-descriptions-item label="完成时间">{{ task.finished_at || '—' }}</el-descriptions-item>
            </el-descriptions>

            <el-empty v-else-if="!loading" description="无法加载任务详情" />

            <!-- 管理干预 -->
            <template v-if="task.task_id">
                <el-divider content-position="left">管理干预</el-divider>
                <div class="action-area">
                    <el-button
                        v-if="canForceStop"
                        type="danger"
                        plain
                        @click="handleForceStop"
                        :loading="actionLoading.forceStop"
                    >
                        <el-icon><i-ep-VideoPause /></el-icon>强制中断
                    </el-button>
                    <el-button
                        v-if="canSuppress"
                        type="warning"
                        plain
                        @click="handleSuppress"
                        :loading="actionLoading.suppress"
                    >
                        <el-icon><i-ep-Hide /></el-icon>屏蔽输出
                    </el-button>
                    <el-button
                        v-if="canUnsuppress"
                        type="success"
                        plain
                        @click="handleUnsuppress"
                        :loading="actionLoading.unsuppress"
                    >
                        <el-icon><i-ep-View /></el-icon>恢复输出
                    </el-button>
                </div>

                <!-- 审计日志（内联展开） -->
                <el-divider content-position="left">
                    <el-button size="small" text @click="toggleAuditLogs">
                        审计日志
                        <el-icon style="margin-left: 4px">
                            <i-ep-ArrowDown v-if="!showAuditLogs" />
                            <i-ep-ArrowUp v-else />
                        </el-icon>
                    </el-button>
                </el-divider>
                <div v-if="showAuditLogs" v-loading="auditLoading">
                    <el-timeline v-if="auditLogs.length > 0">
                        <el-timeline-item
                            v-for="log in auditLogs"
                            :key="log.log_id"
                            :timestamp="log.created_at"
                            placement="top"
                            :type="auditTagType(log.action)"
                        >
                        <div class="audit-item">
                            <el-tag :type="auditTagType(log.action)" size="small" effect="plain">
                                {{ log.action_label || auditActionLabel(log.action) }}
                            </el-tag>
                            <span class="audit-admin">by {{ log.admin_name || log.admin }}</span>
                            <div v-if="log.reason" class="audit-reason">原因：{{ log.reason }}</div>
                        </div>
                        </el-timeline-item>
                    </el-timeline>
                    <el-empty v-else-if="!auditLoading" description="暂无审计记录" :image-size="60" />
                </div>
            </template>
        </div>

        <template #footer>
            <div class="drawer-footer">
                <el-button @click="visible = false">关闭</el-button>
                <el-button type="primary" plain @click="$emit('view-trace', task.task_id)">
                    <el-icon><i-ep-List /></el-icon>查看执行轨迹
                </el-button>
            </div>
        </template>
    </el-drawer>
</template>

<script>
import { getDRTaskDetail, forceStopTask, suppressOutput, unsuppressOutput, getTaskAuditLogs } from '@/api/deep_research.js'
import { ElMessage, ElMessageBox } from 'element-plus'

const PHASE_CONFIG = {
    planning:   { label: '规划',     color: '#409EFF' },
    searching:  { label: '检索',     color: '#67C23A' },
    reading:    { label: '阅读',     color: '#E6A23C' },
    reflecting: { label: '反思',     color: '#909399' },
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

const AUDIT_ACTION_MAP = {
    force_stop:        { label: '强制中断', type: 'danger' },
    suppress_output:   { label: '屏蔽输出', type: 'warning' },
    unsuppress_output: { label: '恢复输出', type: 'success' },
    view_trace:        { label: '查看轨迹', type: 'info' }
}

export default {
    props: {
        taskId: { type: String, default: '' }
    },
    emits: ['view-trace', 'action-done'],
    data() {
        return {
            visible: false,
            loading: false,
            task: {},
            actionLoading: { forceStop: false, suppress: false, unsuppress: false },
            showAuditLogs: false,
            auditLoading: false,
            auditLogs: []
        }
    },
    computed: {
        canForceStop() {
            return this.task.status === 'running' || this.task.status === 'queued'
        },
        canSuppress() {
            return this.task.task_id && !this.task.output_suppressed && this.task.status === 'completed'
        },
        canUnsuppress() {
            return this.task.task_id && this.task.output_suppressed
        }
    },
    watch: {
        taskId(val) {
            if (val) this.open()
        }
    },
    methods: {
        open() {
            this.task = {}
            this.showAuditLogs = false
            this.auditLogs = []
            this.visible = true
        },
        handleOpen() {
            if (!this.taskId) return
            this.fetchDetail()
        },
        async fetchDetail() {
            this.loading = true
            await getDRTaskDetail(this.taskId)
                .then((res) => {
                    this.task = res.data || {}
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取任务详情失败')
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
        auditActionLabel(action) {
            return AUDIT_ACTION_MAP[action]?.label || action
        },
        auditTagType(action) {
            return AUDIT_ACTION_MAP[action]?.type || 'info'
        },
        formatToken(num) {
            if (!num && num !== 0) return '—'
            if (num >= 10000) return (num / 10000).toFixed(1) + ' 万'
            return num.toString()
        },
        handleForceStop() {
            ElMessageBox.prompt('请填写强制中断原因', '强制中断确认', {
                confirmButtonText: '确认中断',
                cancelButtonText: '取消',
                inputPlaceholder: '例如：任务资源消耗异常，已超时',
                inputValidator: (val) => !!val || '原因不能为空',
                type: 'warning'
            }).then(({ value }) => {
                this.actionLoading.forceStop = true
                return forceStopTask(this.task.task_id, { reason: value })
            }).then(() => {
                ElMessage.success('中断指令已发送，任务将在下一轮检查后停止')
                this.fetchDetail()
                this.$emit('action-done')
            }).catch((err) => {
                if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '操作失败')
            }).finally(() => {
                this.actionLoading.forceStop = false
            })
        },
        handleSuppress() {
            ElMessageBox.prompt('请填写屏蔽原因', '屏蔽报告输出', {
                confirmButtonText: '确认屏蔽',
                cancelButtonText: '取消',
                inputPlaceholder: '例如：报告内容涉及不当信息，临时屏蔽待人工复核',
                inputValidator: (val) => !!val || '原因不能为空',
                type: 'warning'
            }).then(({ value }) => {
                this.actionLoading.suppress = true
                return suppressOutput(this.task.task_id, { reason: value })
            }).then(() => {
                ElMessage.success('报告已屏蔽，用户端无法访问')
                this.fetchDetail()
                this.$emit('action-done')
            }).catch((err) => {
                if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '操作失败')
            }).finally(() => {
                this.actionLoading.suppress = false
            })
        },
        handleUnsuppress() {
            ElMessageBox.confirm('确定恢复该任务报告的输出访问权限吗？', '恢复报告输出', {
                confirmButtonText: '确认恢复',
                cancelButtonText: '取消',
                type: 'info'
            }).then(() => {
                this.actionLoading.unsuppress = true
                return unsuppressOutput(this.task.task_id, {})
            }).then(() => {
                ElMessage.success('报告输出已恢复')
                this.fetchDetail()
                this.$emit('action-done')
            }).catch((err) => {
                if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '操作失败')
            }).finally(() => {
                this.actionLoading.unsuppress = false
            })
        },
        async toggleAuditLogs() {
            this.showAuditLogs = !this.showAuditLogs
            if (this.showAuditLogs && this.auditLogs.length === 0) {
                this.auditLoading = true
                await getTaskAuditLogs(this.task.task_id)
                    .then((res) => {
                        this.auditLogs = res.data.logs || []
                    })
                    .catch((err) => {
                        ElMessage.error(err.response?.data?.message || '获取审计日志失败')
                    })
                this.auditLoading = false
            }
        }
    }
}
</script>

<style lang="scss" scoped>
.drawer-header {
    display: flex;
    align-items: center;
    .drawer-title { font-size: 16px; font-weight: bold; }
}
.detail-content {
    padding: 0 4px;
}
.mono-text {
    font-family: monospace;
    font-size: 12px;
    color: #606266;
    word-break: break-all;
}
.action-area {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 8px;
}
.audit-item {
    .audit-admin {
        font-size: 12px;
        color: #909399;
        margin-left: 8px;
    }
    .audit-reason {
        font-size: 12px;
        color: #606266;
        margin-top: 4px;
    }
}
.drawer-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
}
</style>
