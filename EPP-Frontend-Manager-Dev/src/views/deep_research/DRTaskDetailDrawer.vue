<template>
    <el-drawer v-model="visible" direction="rtl" size="46%" :destroy-on-close="true" @open="loadDetail">
        <template #header>
            <div class="drawer-header">
                <span class="drawer-title">任务详情</span>
                <el-tag v-if="task.status" :type="statusTagType(task.status)" size="small" style="margin-left: 10px">
                    {{ statusLabel(task.status) }}
                </el-tag>
            </div>
        </template>

        <div v-loading="loading" class="detail-content">
            <el-descriptions v-if="task.task_id" :column="1" border size="small">
                <el-descriptions-item label="任务ID">
                    <span class="mono-text">{{ task.task_id }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="用户">{{ task.user_name || task.user_id }}</el-descriptions-item>
                <el-descriptions-item label="研究问题">
                    <div style="white-space: pre-wrap">{{ task.query || task.task_name || '—' }}</div>
                </el-descriptions-item>
                <el-descriptions-item label="当前阶段">
                    <el-tag
                        v-if="task.current_phase"
                        :color="phaseColor(task.current_phase)"
                        effect="dark"
                        size="small"
                    >
                        {{ phaseLabel(task.current_phase) }}
                    </el-tag>
                    <span v-else>—</span>
                </el-descriptions-item>
                <el-descriptions-item label="进度">
                    <el-progress :percentage="task.progress ?? 0" :stroke-width="8" style="max-width: 280px" />
                </el-descriptions-item>
                <el-descriptions-item label="步骤序号">{{ task.step_seq ?? 0 }}</el-descriptions-item>
                <el-descriptions-item label="审计条数">
                    {{ task.log_count ?? 0 }}
                    <el-tag v-if="task.exception_count > 0" type="danger" size="small" style="margin-left: 6px">
                        {{ task.exception_count }} 条异常
                    </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="创建时间">{{ formatDateTime(task.created_at) }}</el-descriptions-item>
                <el-descriptions-item label="更新时间">{{ formatDateTime(task.updated_at) }}</el-descriptions-item>
                <el-descriptions-item v-if="task.error_message" label="错误信息">
                    <span class="error-text">{{ task.error_message }}</span>
                </el-descriptions-item>
            </el-descriptions>

            <el-empty v-else-if="!loading" description="无法加载任务详情" />

            <template v-if="steps.length">
                <el-divider content-position="left">执行步骤</el-divider>
                <el-timeline>
                    <el-timeline-item
                        v-for="(step, idx) in steps"
                        :key="idx"
                        :timestamp="formatDateTime(step.timestamp || step.time || '')"
                        placement="top"
                    >
                        <div class="step-card">
                            <el-tag v-if="step.phase" size="small" effect="plain">{{ phaseLabel(step.phase) }}</el-tag>
                            <span class="step-msg">{{ stepDisplayMessage(step) }}</span>
                        </div>
                    </el-timeline-item>
                </el-timeline>
            </template>

            <template v-if="task.task_id">
                <el-divider content-position="left">管理操作</el-divider>
                <el-button v-if="canCancel" type="danger" plain :loading="cancelLoading" @click="handleCancel">
                    取消任务
                </el-button>
            </template>
        </div>
    </el-drawer>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDRTaskDetail, cancelDRTask } from '@/api/deep_research.js'
import { DR_PHASE_CONFIG, DR_STATUS_MAP } from '@/views/deep_research/dr_constants.js'
import { formatDateTime, getApiErrorMessage } from '@/utils/adminView.js'

const ACTIVE = new Set(['pending', 'running', 'pending_action'])

export default {
    emits: ['action-done'],
    data() {
        return {
            visible: false,
            loading: false,
            cancelLoading: false,
            taskId: '',
            task: {},
            steps: []
        }
    },
    computed: {
        canCancel() {
            return ACTIVE.has(this.task.status)
        }
    },
    methods: {
        formatDateTime,
        open(taskId) {
            this.taskId = taskId
            this.visible = true
        },
        statusLabel(s) {
            return DR_STATUS_MAP[s]?.label || s || '—'
        },
        statusTagType(s) {
            return DR_STATUS_MAP[s]?.type || 'info'
        },
        phaseLabel(phase) {
            return DR_PHASE_CONFIG[phase]?.label || phase || '—'
        },
        phaseColor(phase) {
            return DR_PHASE_CONFIG[phase]?.color || '#909399'
        },
        stepDisplayMessage(step) {
            return step?.message || step?.summary || JSON.stringify(step || {})
        },
        async loadDetail() {
            if (!this.taskId) return
            this.loading = true
            this.task = {}
            this.steps = []
            try {
                const res = await getDRTaskDetail(this.taskId)
                this.task = res.data || {}
                this.steps = Array.isArray(res.data?.steps) ? res.data.steps : []
            } catch (err) {
                ElMessage.error(getApiErrorMessage(err, '加载详情失败'))
            } finally {
                this.loading = false
            }
        },
        async handleCancel() {
            await ElMessageBox.confirm('确定取消该深度研究任务？', '取消任务', { type: 'warning' })
            this.cancelLoading = true
            try {
                await cancelDRTask(this.taskId)
                ElMessage.success('已取消')
                this.visible = false
                this.$emit('action-done')
            } catch (err) {
                ElMessage.error(getApiErrorMessage(err, '取消失败'))
            } finally {
                this.cancelLoading = false
            }
        }
    }
}
</script>

<style lang="scss" scoped>
.drawer-header {
    display: flex;
    align-items: center;
}
.drawer-title {
    font-weight: 600;
}
.detail-content {
    padding: 0 4px 24px;
}
.mono-text {
    font-family: monospace;
    font-size: 12px;
    word-break: break-all;
}
.error-text {
    color: #f56c6c;
    white-space: pre-wrap;
}
.step-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    .step-msg {
        font-size: 13px;
        color: #606266;
        white-space: pre-wrap;
    }
}
</style>
