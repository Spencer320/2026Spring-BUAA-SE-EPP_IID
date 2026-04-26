<template>
  <div class="ra-session">
    <header class="ra-top">
      <div class="ra-title-wrap">
        <h1>科研智能助手</h1>
        <p class="ra-meta">
          <span>{{ sessionTitle || '新会话' }}</span>
          <el-button v-if="currentSessionId" type="text" icon="el-icon-edit" class="ra-title-edit" @click="onRenameTitle" />
          <span> · {{ taskStatusLabel }}</span>
        </p>
        <el-progress
          v-if="taskStatus"
          :percentage="taskProgress"
          :stroke-width="8"
          :status="taskStatus === 'failed' ? 'exception' : (taskStatus === 'completed' ? 'success' : undefined)"
          class="ra-progress"
        />
      </div>
    </header>

    <div class="ra-layout">
      <aside :class="['ra-sidebar-left', sidebarCollapsed ? 'is-collapsed' : '']">
        <div class="ra-side-top">
          <el-tooltip :content="sidebarCollapsed ? '展开侧栏' : '隐藏侧栏'" placement="right">
            <el-button
              class="ra-icon-btn ra-collapse-btn"
              type="text"
              :icon="sidebarCollapsed ? 'el-icon-s-unfold' : 'el-icon-s-fold'"
              @click="sidebarCollapsed = !sidebarCollapsed"
            />
          </el-tooltip>
          <el-tooltip v-if="!sidebarCollapsed" content="新建会话" placement="right">
            <el-button
              class="ra-icon-btn"
              type="primary"
              icon="el-icon-plus"
              circle
              size="mini"
              @click="createAndOpenSession"
            />
          </el-tooltip>
        </div>
        <div v-if="!sidebarCollapsed" class="ra-side-list">
          <div
            v-for="s in displayedSessionItems"
            :key="s.session_id"
            :class="['ra-side-item', s.session_id === currentSessionId ? 'is-active' : '']"
            @click="openSession(s.session_id)"
          >
            <div class="ra-side-title">{{ s.title || '新会话' }}</div>
            <div class="ra-side-time">{{ s.updated_at }}</div>
          </div>
          <p v-if="sessionItems.length > maxSessionDisplay" class="ra-side-tip">仅展示最近 {{ maxSessionDisplay }} 条</p>
          <p v-if="!sessionItems.length" class="ra-muted">暂无历史会话</p>
        </div>
        <div v-if="!sidebarCollapsed" class="ra-side-bottom">
          <el-button icon="el-icon-setting" @click="goManage">设置</el-button>
        </div>
      </aside>

      <main class="ra-main">
        <div class="ra-messages" ref="msgBox" @scroll.passive="onMsgScroll">
          <div
            v-for="(m, idx) in conversationMessages"
            :key="idx"
            :class="['ra-bubble-row', m.role === 'user' ? 'is-user' : 'is-assistant']"
          >
            <div :class="['ra-bubble', m.role === 'user' ? 'is-user' : 'is-assistant']">
              <div class="ra-bubble-head">
                <span class="ra-role">{{ m.role === 'user' ? '我' : '助手' }}</span>
                <el-button
                  v-if="m.role === 'user'"
                  type="text"
                  size="mini"
                  class="ra-copy-btn"
                  icon="el-icon-document-copy"
                  @click="copyUserMessage(m.content)"
                >复制</el-button>
              </div>
              <div v-if="!isReportMessage(m)" class="ra-content" v-html="formatMsg(m.content)"></div>
              <template v-else>
                <div class="ra-content">以下是研究结果：</div>
                <div class="ra-report-block">
                  <div class="ra-report-title">研究成果</div>
                  <div class="ra-md" v-html="formatReport(extractReportMarkdown(m))"></div>
                </div>
              </template>
            </div>
          </div>
        </div>
        <el-button
          v-if="showScrollToBottom"
          type="primary"
          size="mini"
          class="ra-scroll-bottom-btn"
          icon="el-icon-bottom"
          @click="scrollToBottomByUser"
        >
          下到底部
        </el-button>
        <div class="ra-report-action">
          <el-button size="mini" type="primary" plain :disabled="!taskId || taskStatus !== 'completed'" @click="onDownloadReport">
            下载报告
          </el-button>
        </div>

        <div v-if="interventionVisible" class="ra-intervention">
          <el-alert title="需要您确认（高风险操作）" type="warning" :closable="false" show-icon />
          <p class="ra-int-summary">{{ intervention.summary }}</p>
          <p v-if="intervention.risk_hint" class="ra-int-risk">{{ intervention.risk_hint }}</p>
          <div class="ra-int-actions">
            <el-button type="success" @click="onIntervention('approve')">允许执行</el-button>
            <el-button type="danger" @click="onIntervention('reject')">终止任务</el-button>
          </div>
          <el-input
            type="textarea"
            :rows="3"
            placeholder="若选择「按修订继续」，请在此输入新的指令"
            v-model="reviseDraft"
          />
          <el-button type="primary" plain style="margin-top:8px" @click="onIntervention('revise')">提交修订并继续</el-button>
        </div>

        <footer class="ra-input-bar">
          <el-input
            v-model="draft"
            type="textarea"
            :rows="2"
            placeholder="输入调研指令…"
            :disabled="inputLocked"
            @keydown.enter.native.prevent="send"
          />
          <el-checkbox v-model="enableImage" class="ra-image-switch">启用图文输出</el-checkbox>
          <el-button type="primary" :disabled="inputLocked || !draft.trim()" @click="send">发送</el-button>
        </footer>
      </main>

      <aside class="ra-sidebar-right">
        <h3>任务步骤</h3>
        <ul v-if="steps.length" class="ra-step-list">
          <li v-for="s in steps" :key="s.seq" class="ra-step-item">
            <span class="ra-ts">{{ s.ts }}</span>
            <strong>{{ s.title }}</strong>
            <div class="ra-phase">{{ s.phase }}</div>
            <div class="ra-detail">
              <p
                v-for="(line, lineIdx) in getStepDisplayLines(s)"
                :key="`${s.seq}-${lineIdx}`"
              >
                {{ line }}
              </p>
              <el-button
                v-if="stepHasMoreLines(s)"
                type="text"
                size="mini"
                class="ra-step-expand"
                @click="toggleStepExpand(s.seq)"
              >
                {{ stepExpanded[s.seq] ? '收起' : '展开更多' }}
              </el-button>
            </div>
          </li>
        </ul>
        <p v-else class="ra-muted">尚无步骤，发送指令后可见</p>
      </aside>
    </div>
  </div>
</template>

<script>
import MarkdownIt from 'markdown-it'
import {
  getSession,
  postMessage,
  postIntervention,
  getTask,
  listSessions,
  createSessionWithFirstMessage,
  updateSessionTitle,
  downloadTaskReport
} from './researchAgentApi.js'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])
const md = new MarkdownIt({ breaks: true, linkify: true })
const REPORT_MESSAGE_PREFIX = '[[RA_REPORT]]\n'

export default {
  name: 'ResearchAgentSession',
  data () {
    return {
      sessionTitle: '',
      currentSessionId: '',
      sessionItems: [],
      maxSessionDisplay: 50,
      sidebarCollapsed: false,
      messages: [],
      steps: [],
      taskId: null,
      taskStatus: '',
      intervention: null,
      resultBody: null,
      taskProgress: 0,
      draft: '',
      reviseDraft: '',
      enableImage: false,
      pollTimer: null,
      stepExpanded: {},
      pollFailureCount: 0,
      pollInFlight: false,
      autoFollowMessages: true,
      showScrollToBottom: false
    }
  },
  computed: {
    taskStatusLabel () {
      return this.taskStatus ? `任务：${this.taskStatus}` : '无活跃任务'
    },
    conversationMessages () {
      return Array.isArray(this.messages) ? this.messages : []
    },
    interventionVisible () {
      return this.taskStatus === 'pending_action' && this.intervention
    },
    inputLocked () {
      if (!this.taskStatus) return false
      return !TERMINAL.has(this.taskStatus)
    },
    displayedSessionItems () {
      return (this.sessionItems || []).slice(0, this.maxSessionDisplay)
    }
  },
  watch: {
    '$route.params.sessionId' () {
      this.bootstrap()
    }
  },
  created () {
    this.bootstrap()
  },
  beforeDestroy () {
    this.stopPoll()
  },
  methods: {
    apiErrorMessage (e, fallback) {
      const data = e && e.response && e.response.data
      if (data && data.error && data.error.message) return data.error.message
      return (data && (data.err || data.message)) || fallback
    },
    async bootstrap () {
      const sid = this.$route.params.sessionId
      if (!sid) {
        this.stopPoll()
        this.currentSessionId = ''
        this.sessionTitle = '新会话'
        this.messages = []
        this.steps = []
        this.taskId = null
        this.taskStatus = ''
        this.taskProgress = 0
        this.intervention = null
        this.resultBody = null
        this.$nextTick(() => this.scrollMsg(true))
        await this.loadSessionList()
        return
      }
      this.currentSessionId = sid
      await this.reload()
      await this.loadSessionList()
    },
    formatMsg (text) {
      return md.render(text || '')
    },
    formatReport (text) {
      return md.render(text || '')
    },
    isReportMessage (msg) {
      return Boolean(msg && msg.role === 'assistant' && typeof msg.content === 'string' && msg.content.startsWith(REPORT_MESSAGE_PREFIX))
    },
    extractReportMarkdown (msg) {
      if (!this.isReportMessage(msg)) return ''
      return String(msg.content || '').slice(REPORT_MESSAGE_PREFIX.length)
    },
    getStepDisplayLines (step) {
      const lines = this.extractStepLines(step)
      if (this.stepExpanded[step.seq]) return lines
      return lines.slice(0, 4)
    },
    stepHasMoreLines (step) {
      return this.extractStepLines(step).length > 4
    },
    toggleStepExpand (seq) {
      this.$set(this.stepExpanded, seq, !this.stepExpanded[seq])
    },
    extractStepLines (step) {
      const text = (step && step.detail) ? String(step.detail) : ''
      return text.split('\n').map(v => v.trim()).filter(Boolean)
    },
    async copyUserMessage (content) {
      const text = String(content || '')
      if (!text) return
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text)
        } else {
          const ta = document.createElement('textarea')
          ta.value = text
          ta.style.position = 'fixed'
          ta.style.opacity = '0'
          document.body.appendChild(ta)
          ta.select()
          document.execCommand('copy')
          document.body.removeChild(ta)
        }
        this.$message.success('已复制输入内容')
      } catch (e) {
        this.$message.error('复制失败，请手动复制')
      }
    },
    async loadSessionList () {
      try {
        const res = await listSessions({ page: 1, page_size: 100 })
        this.sessionItems = res.data.items || []
      } catch (e) {
        this.sessionItems = []
      }
    },
    async createAndOpenSession () {
      this.$router.push({ path: '/research-agent' })
    },
    openSession (sessionId) {
      this.$router.push({ path: `/research-agent/session/${sessionId}` })
    },
    goManage () {
      this.$router.push({ name: 'ResearchAgentHome' })
    },
    async onRenameTitle () {
      if (!this.currentSessionId) return
      try {
        const res = await this.$prompt('请输入新的会话标题', '重命名会话', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          inputValue: this.sessionTitle || '',
          inputValidator: (val) => !!(val && val.trim()),
          inputErrorMessage: '标题不能为空'
        })
        const nextTitle = (res.value || '').trim()
        await updateSessionTitle(this.currentSessionId, nextTitle)
        this.sessionTitle = nextTitle
        this.$message.success('标题已更新')
        this.loadSessionList()
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') {
          this.$message.error('重命名失败')
        }
      }
    },
    async reload () {
      const sid = this.$route.params.sessionId
      if (!sid) return
      try {
        const res = await getSession(sid)
        const d = res.data
        this.currentSessionId = d.session_id
        this.sessionTitle = d.title
        this.messages = d.messages || []
        const at = d.active_task || d.latest_task
        if (at) {
          this.taskId = at.task_id
          this.taskStatus = at.status
          this.taskProgress = at.progress || 0
          this.steps = at.steps || []
          this.intervention = at.intervention
          this.resultBody = at.result
        } else {
          this.taskId = null
          this.taskStatus = ''
          this.taskProgress = 0
          this.steps = []
          this.intervention = null
          this.resultBody = null
        }
        this.$nextTick(() => this.scrollMsg(true))
        this.syncPoll()
      } catch (e) {
        this.$message.error('加载会话失败')
      }
    },
    scrollMsg (force = false) {
      const el = this.$refs.msgBox
      if (!el) return
      if (!force && !this.autoFollowMessages) return
      el.scrollTop = el.scrollHeight
      this.autoFollowMessages = true
      this.showScrollToBottom = false
    },
    onMsgScroll () {
      const el = this.$refs.msgBox
      if (!el) return
      const threshold = 24
      const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      const nearBottom = distanceToBottom <= threshold
      this.autoFollowMessages = nearBottom
      this.showScrollToBottom = !nearBottom
    },
    scrollToBottomByUser () {
      this.scrollMsg(true)
    },
    async pollTick () {
      if (!this.currentSessionId) return
      if (this.pollInFlight) return
      this.pollInFlight = true
      try {
        const prevMsgCount = (this.messages || []).length
        const sRes = await getSession(this.currentSessionId)
        const s = sRes.data || {}
        this.sessionTitle = s.title || this.sessionTitle
        this.messages = s.messages || []

        const at = s.active_task || s.latest_task
        if (at) {
          this.taskId = at.task_id
          this.taskStatus = at.status || this.taskStatus
          this.taskProgress = at.progress || 0
          this.steps = at.steps || []
          this.intervention = at.intervention
          this.resultBody = at.result
        }

        const needTaskDetail = this.taskId && (this.taskStatus === 'running' || this.taskStatus === 'pending_action' || this.taskStatus === 'pending')
        if (needTaskDetail) {
          try {
            const tRes = await getTask(this.taskId)
            const t = tRes.data || {}
            this.taskStatus = t.status || this.taskStatus
            this.taskProgress = t.progress || 0
            this.steps = t.steps || []
            this.intervention = t.intervention
            this.resultBody = t.result
          } catch (e) {
            // getSession 已保证主对话可更新，这里失败只影响细粒度任务态
          }
        }

        if ((this.messages || []).length !== prevMsgCount) {
          this.$nextTick(() => this.scrollMsg())
          return
        }
        this.$nextTick(() => this.scrollMsg())
      } finally {
        this.pollInFlight = false
      }
    },
    syncPoll () {
      this.stopPoll()
      if (!this.currentSessionId) return
      this.pollFailureCount = 0
      this.pollTimer = setInterval(async () => {
        try {
          await this.pollTick()
          this.pollFailureCount = 0
        } catch (e) {
          this.pollFailureCount += 1
          if (this.pollFailureCount >= 6) {
            this.$message.warning('任务状态自动刷新失败，请手动刷新页面后重试')
            this.pollFailureCount = 0
          }
        }
      }, 2000)
    },
    stopPoll () {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
    async send () {
      const content = this.draft.trim()
      if (!content) return
      this.messages = [...this.messages, { role: 'user', content }]
      this.$nextTick(() => this.scrollMsg())
      this.draft = ''
      try {
        let res
        const options = { enable_image: this.enableImage }
        if (!this.currentSessionId) {
          res = await createSessionWithFirstMessage(content, '新会话', options)
          const newSessionId = res.data.session_id
          this.currentSessionId = newSessionId
          this.$router.push({ path: `/research-agent/session/${newSessionId}` })
        } else {
          res = await postMessage(this.currentSessionId, { content, ...options })
        }
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        this.taskProgress = 0
        await this.pollTick()
        await this.loadSessionList()
        this.syncPoll()
      } catch (e) {
        this.messages = this.messages.filter((m, idx, arr) => !(idx === arr.length - 1 && m.role === 'user' && m.content === content))
        const msg = this.apiErrorMessage(e, '发送失败')
        this.$message.error(msg)
      }
    },
    async onDownloadReport () {
      if (!this.taskId || this.taskStatus !== 'completed') return
      try {
        const blob = await downloadTaskReport(this.taskId)
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `research-report-${this.taskId}.md`
        a.click()
        window.URL.revokeObjectURL(url)
      } catch (e) {
        this.$message.error('下载报告失败')
      }
    },
    async onIntervention (decision) {
      if (!this.taskId) return
      const body = { decision }
      if (decision === 'revise') {
        body.message = this.reviseDraft.trim()
        if (!body.message) {
          this.$message.warning('请填写修订说明')
          return
        }
      }
      try {
        await postIntervention(this.taskId, body)
        this.reviseDraft = ''
        await this.reload()
        this.syncPoll()
      } catch (e) {
        this.$message.error(this.apiErrorMessage(e, '提交失败'))
      }
    }
  }
}
</script>

<style scoped>
.ra-session {
  min-height: 100vh;
  padding: 84px 16px 16px;
  background: #f0f2f5;
  text-align: left;
}
.ra-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  max-width: 1380px;
  margin: 0 auto 16px;
}
.ra-title-wrap {
  display: flex;
  flex-direction: column;
}
.ra-top h1 {
  margin: 0;
  font-size: 1.35rem;
  color: #1a1a2e;
}
.ra-meta {
  margin: 6px 0 0;
  color: #909399;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
}
.ra-progress {
  margin-top: 8px;
  max-width: 420px;
}
.ra-title-edit {
  margin: 0 2px 0 4px;
  padding: 0;
  font-size: 14px;
}
.ra-collapse-btn {
  font-size: 20px;
  margin-top: 4px;
}
.ra-layout {
  display: flex;
  max-width: 1380px;
  margin: 0 auto;
  gap: 16px;
  align-items: stretch;
  height: calc(100vh - 170px);
}
.ra-sidebar-left {
  width: 260px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  padding: 10px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  transition: width 0.2s ease;
}
.ra-sidebar-left.is-collapsed {
  width: 40px;
  padding: 8px 6px;
}
.ra-side-top {
  display: flex;
  justify-content: flex-start;
  gap: 6px;
  padding: 2px 0 8px;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 2;
}
.ra-icon-btn {
  width: 26px;
  height: 26px;
  padding: 0;
}
.ra-collapse-btn {
  margin: 0;
}
.ra-side-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.ra-side-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 8px;
  cursor: pointer;
}
.ra-side-item.is-active {
  border-color: #409eff;
  background: #ecf5ff;
}
.ra-side-title {
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ra-side-time {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.ra-side-bottom {
  border-top: 1px solid #ebeef5;
  padding-top: 8px;
  position: sticky;
  bottom: 0;
  background: #fff;
}
.ra-side-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 8px;
}
.ra-main {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.ra-sidebar-right {
  width: 280px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  height: 100%;
  overflow-y: auto;
}
.ra-sidebar-right h3 {
  margin: 0 0 12px;
  font-size: 1rem;
}
.ra-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin-bottom: 12px;
}
.ra-scroll-bottom-btn {
  align-self: center;
  margin: -2px 0 8px;
}
.ra-bubble-row {
  display: flex;
  margin-bottom: 12px;
}
.ra-bubble-row.is-user {
  justify-content: flex-end;
}
.ra-bubble-row.is-assistant {
  justify-content: flex-start;
}
.ra-bubble {
  padding: 10px 12px;
  border-radius: 8px;
  text-align: left;
  width: fit-content;
  max-width: 78%;
}
.ra-bubble.is-user {
  background: #ecf5ff;
}
.ra-bubble.is-assistant {
  background: #f4f4f5;
}
.ra-role {
  font-size: 0.75rem;
  color: #909399;
}
.ra-bubble-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ra-copy-btn {
  padding: 0;
}
.ra-content {
  margin-top: 4px;
  font-size: 0.95rem;
}
.ra-content >>> p {
  margin: 0.4em 0;
}
.ra-report-action {
  margin-bottom: 8px;
  display: flex;
  justify-content: flex-end;
}
.ra-report-block {
  margin-top: 8px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
  padding: 10px 12px;
}
.ra-report-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.ra-md {
  text-align: left;
  line-height: 1.6;
}
.ra-md >>> h1 {
  font-size: 1.6rem;
  line-height: 1.35;
  margin: 0 0 12px;
  font-weight: 700;
}
.ra-md >>> h2 {
  font-size: 1.35rem;
  line-height: 1.4;
  margin: 16px 0 10px;
  font-weight: 650;
}
.ra-md >>> h3 {
  font-size: 1.15rem;
  line-height: 1.45;
  margin: 14px 0 8px;
  font-weight: 600;
}
.ra-md >>> p,
.ra-md >>> ul,
.ra-md >>> ol,
.ra-md >>> blockquote {
  margin: 8px 0;
}
.ra-md >>> li {
  margin: 4px 0;
}
.ra-intervention {
  margin-bottom: 12px;
  padding: 12px;
  background: #fdf6ec;
  border: 1px solid #f5dab1;
  border-radius: 8px;
}
.ra-int-summary {
  margin: 8px 0;
  color: #303133;
}
.ra-int-risk {
  color: #e6a23c;
  font-size: 0.9rem;
}
.ra-int-actions {
  margin: 8px 0;
}
.ra-input-bar {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.ra-image-switch {
  margin-bottom: 8px;
  white-space: nowrap;
}
.ra-input-bar .el-textarea {
  flex: 1;
}
.ra-phase {
  font-size: 0.75rem;
  color: #909399;
  text-transform: uppercase;
}
.ra-detail {
  font-size: 0.85rem;
  color: #606266;
  margin-top: 4px;
}
.ra-detail p {
  margin: 4px 0;
  line-height: 1.5;
}
.ra-step-expand {
  padding: 0;
}
.ra-muted {
  color: #c0c4cc;
  font-size: 0.9rem;
}
.ra-step-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.ra-step-item {
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
}
.ra-ts {
  display: block;
  font-size: 0.75rem;
  color: #909399;
  margin-bottom: 4px;
}
</style>
