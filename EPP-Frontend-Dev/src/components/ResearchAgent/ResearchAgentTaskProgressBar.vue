<template>
  <div v-if="showBlock" class="ra-task-progress">
    <div v-if="showMeta" class="ra-task-progress-chips">
      <el-tag v-if="orchestratorLabel" size="small" effect="plain" type="info">{{ orchestratorLabel }}</el-tag>
      <el-tag size="small" effect="dark" :type="statusTagType">{{ statusLabel }}</el-tag>
    </div>
    <el-progress
      v-if="showBar"
      :percentage="clampedProgress"
      :stroke-width="6"
      :status="progressStatus"
      class="ra-task-progress-bar"
    />
  </div>
</template>

<script>
const ACTIVE = new Set(['pending', 'running', 'pending_action'])

const STATUS_LABEL = {
  pending: '排队中',
  running: '执行中',
  pending_action: '待确认',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消'
}

const ORCHESTRATOR_LABEL = {
  deep_research: '深度研究',
  basic: '智能编排',
  workspace: '工作区子任务'
}

export default {
  name: 'ResearchAgentTaskProgressBar',
  props: {
    status: {
      type: String,
      default: ''
    },
    progress: {
      type: Number,
      default: 0
    },
    orchestrator: {
      type: String,
      default: ''
    },
    taskId: {
      type: [String, Number],
      default: ''
    },
    sessionBound: {
      type: Boolean,
      default: false
    }
  },
  computed: {
    showMeta () {
      return Boolean(this.status) && (this.sessionBound || this.taskId)
    },
    showBar () {
      return Boolean(this.status) && ACTIVE.has(this.status)
    },
    showBlock () {
      return this.showMeta || this.showBar
    },
    clampedProgress () {
      const n = Number(this.progress)
      if (!Number.isFinite(n)) return 0
      return Math.max(0, Math.min(100, Math.round(n)))
    },
    statusLabel () {
      if (!this.status) return '无进行中任务'
      return STATUS_LABEL[this.status] || this.status
    },
    statusTagType () {
      if (this.status === 'completed') return 'success'
      if (this.status === 'failed') return 'danger'
      if (this.status === 'pending_action') return 'warning'
      if (this.status === 'running' || this.status === 'pending') return ''
      return 'info'
    },
    orchestratorLabel () {
      const key = String(this.orchestrator || '').trim()
      return ORCHESTRATOR_LABEL[key] || key
    },
    progressStatus () {
      if (this.status === 'failed') return 'exception'
      if (this.status === 'completed') return 'success'
      return undefined
    }
  }
}
</script>

<style scoped>
.ra-task-progress-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ra-task-progress-bar {
  margin-top: 10px;
  max-width: 520px;
}
</style>
