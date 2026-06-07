<template>
  <div class="dr-shell">
  <div class="dr-container">
    <!-- 左侧历史会话侧边栏 -->
    <aside :class="['dr-sidebar-left', sidebarCollapsed ? 'is-collapsed' : '']">
      <div class="dr-side-top">
        <el-tooltip :content="sidebarCollapsed ? '展开侧栏' : '隐藏侧栏'" placement="right">
          <el-button
            class="dr-icon-btn dr-collapse-btn"
            type="text"
            :icon="sidebarCollapsed ? 'el-icon-s-unfold' : 'el-icon-s-fold'"
            @click="sidebarCollapsed = !sidebarCollapsed"
          />
        </el-tooltip>
        <el-tooltip v-if="!sidebarCollapsed" content="新建会话" placement="right">
          <el-button
            class="dr-icon-btn"
            type="primary"
            icon="el-icon-plus"
            circle
            size="mini"
            @click="createNewSession"
          />
        </el-tooltip>
      </div>
      <div v-if="!sidebarCollapsed" class="dr-side-list">
        <div
          v-for="s in sessionList"
          :key="s.session_id"
          :class="['dr-side-item', s.session_id === currentSessionId ? 'is-active' : '']"
          @click="switchSession(s.session_id)"
        >
          <div class="dr-side-title">{{ s.title || '新会话' }}</div>
          <div class="dr-side-time">{{ formatDate(s.updated_at) }}</div>
        </div>
        <p v-if="sessionList.length === 0" class="dr-muted">暂无历史会话</p>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="dr-main">
      <div class="dr-task-header">
        <ResearchAgentTaskProgressBar
          :status="taskStatus"
          :progress="taskProgress"
          :orchestrator="taskOrchestrator"
          :task-id="taskId"
          :session-bound="!!currentSessionId"
        />
        <UserAccessQuotaBar ref="quotaBar" :features="['deep_research']" compact />
      </div>
      <!-- 滚动区域 -->
      <div class="dr-messages-wrapper" ref="scrollContainer">
        <div class="dr-messages">
          <!-- 空状态 -->
          <div v-if="messages.length === 0 && !isLoading" class="dr-welcome">
            <div class="dr-welcome-content">
              <h1>深度研究</h1>
              <p>适合做“基于多篇论文的综述、比较和论证”。请先在右侧勾选要分析的文献，再输入你的研究问题；未勾选文献时，我会先按普通科研问答处理。</p>
              <div class="dr-guide-steps">
                <span>1. 勾选右侧文献</span>
                <span>2. 选择一个研究问题</span>
                <span>3. 生成带参考来源的报告</span>
              </div>
              
              <div class="dr-mode-toggle">
                <div class="mode-toggle-card" :class="{ active: enableDeepThinking }" @click="enableDeepThinking = !enableDeepThinking">
                  <div class="mode-info">
                    <div class="mode-title">基于已选文献做深度研究</div>
                    <div class="mode-desc">右侧已勾选文献时，会围绕这些材料生成综述报告；还没勾选时，可以先把问题发给我做初步梳理。</div>
                  </div>
                  <el-switch v-model="enableDeepThinking" @click.native.stop />
                </div>
              </div>

              <el-input
                v-model="searchQuery"
                type="textarea"
                :rows="3"
                placeholder="输入研究问题，例如：请基于已选文献，比较它们在研究方法、实验数据和结论上的差异"
                class="dr-input"
                @keydown.enter.native.exact.prevent="startResearch"
              />
              
              <div class="dr-examples">
                <span class="examples-label">试试：</span>
                <el-tag
                  v-for="example in examples"
                  :key="example"
                  size="small"
                  type="info"
                  @click="searchQuery = example"
                  class="example-tag"
                >
                  {{ example }}
                </el-tag>
              </div>
              
              <el-button
                type="primary"
                size="medium"
                :loading="isLoading"
                :disabled="!searchQuery.trim()"
                class="dr-start-btn"
                @click="startResearch"
              >
                {{ isLoading ? '研究中...' : (enableDeepThinking ? '开始深度研究' : '发送') }}
              </el-button>
            </div>
          </div>

          <!-- 消息列表 -->
          <div
            v-for="(m, idx) in messages"
            :key="idx"
            :class="['dr-bubble-row', m.role === 'user' ? 'is-user' : 'is-assistant']"
          >
            <div :class="['dr-bubble', m.role === 'user' ? 'is-user' : 'is-assistant']">
              <div class="dr-bubble-head">
                <span class="dr-role">{{ m.role === 'user' ? '我' : '助手' }}</span>
              </div>
              
              <!-- 执行历史面板 -->
              <div v-if="m.role === 'assistant' && getStepsForMessage(idx).length > 0" class="thinking-process">
                <div class="process-header" @click="toggleProcessCollapse(idx)">
                  <i :class="stepCollapsed[idx] ? 'el-icon-caret-right' : 'el-icon-caret-bottom'" />
                  <span class="process-title">深度研究过程</span>
                  <span class="process-badge">{{ getStepsForMessage(idx).length }}个步骤</span>
                  <span v-if="stepCollapsed[idx]" class="process-summary">{{ getStepsSummary(getStepsForMessage(idx)) }}</span>
                </div>
                <transition name="slide-fade">
                  <div class="process-detail" v-if="!stepCollapsed[idx]">
                    <div v-for="(step, stepIdx) in getStepsForMessage(idx)" :key="stepIdx" class="process-step">
                      <div class="step-dot">{{ stepIdx + 1 }}</div>
                      <div class="step-content">
                        <div class="step-title">{{ step.title || '处理中' }}</div>
                        <div class="step-detail">{{ step.detail || '' }}</div>
                        <div class="step-time">{{ formatTime(step.ts) }}</div>
                      </div>
                    </div>
                  </div>
                </transition>
              </div>

              <!-- 普通消息内容 -->
              <div v-if="!isReportMessage(m)" class="dr-content" v-html="formatMsg(m.content)"></div>
              
              <!-- 报告消息内容 -->
              <template v-else>
                <div class="dr-content">以下是研究结果：</div>
                <div class="dr-report-block">
                  <div class="dr-report-title">研究成果</div>
                  <div class="dr-md" v-html="formatReport(extractReportMarkdown(m))"></div>
                  <div class="reference-footer">
                    <el-button type="text" icon="el-icon-document" class="reference-btn" @click="toggleReferencePanelForMessage(m)">
                      展示参考来源
                    </el-button>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <div v-if="isLoading && messages.length > 0" class="dr-loading">
            <i class="el-icon-loading" /> 深度研究中...
          </div>
        </div>
      </div>

      <!-- 底部追问输入框（固定在底部） -->
      <div v-if="messages.length > 0" class="dr-followup">
        <el-input
          v-model="followUpQuery"
          type="textarea"
          :rows="2"
          placeholder="追问或继续研究..."
          @keydown.enter.native.exact.prevent="submitFollowUp"
        />
        <div class="followup-actions">
          <div class="mode-toggle-mini">
            <span>深度研究模式</span>
            <el-switch v-model="enableDeepThinking" size="small" />
          </div>
          <el-button type="primary" :loading="isLoading" :disabled="!followUpQuery.trim()" @click="submitFollowUp">发送</el-button>
        </div>
      </div>
    </main>

    <!-- 右侧论文展示区 -->
    <aside :class="['dr-sidebar-shelf', shelfCollapsed ? 'is-collapsed' : '']">
      <div class="dr-shelf-toggle-anchor">
        <el-tooltip :content="shelfCollapsed ? '展开论文展示区' : '收起论文展示区'" placement="left">
          <el-button
            class="dr-icon-btn dr-shelf-collapse-btn"
            type="text"
            :icon="shelfCollapsed ? 'el-icon-s-unfold' : 'el-icon-s-fold'"
            @click="shelfCollapsed = !shelfCollapsed"
          />
        </el-tooltip>
      </div>
      <div class="dr-shelf-header">
        <span v-if="!shelfCollapsed" class="dr-shelf-title">论文展示区</span>
      </div>
      <div v-if="!shelfCollapsed" class="dr-shelf-body">
        <PaperShelfPanel
          ref="paperShelfPanel"
          :session-id="currentSessionId || ''"
          :pending-citations="pendingShelfCitations"
          :input-locked="isLoading"
          :refresh-token="shelfRefreshToken"
          @preview="onShelfPreview"
          @loaded="onShelfLoaded"
          @selection-change="onShelfSelectionChange"
          @pending-added="bumpShelfRefresh"
          @quota-exceeded="refreshQuota"
        >
          <template #intro>
            这里是深度研究的材料篮。先勾选 1 篇或多篇文献，再发送问题，我会围绕这些材料做综述、比较和归纳。
          </template>
          <template #footer>
            <span v-if="!shelfSelectedPaperIds.length" class="dr-shelf-hint">请先勾选文献；不勾选也可以提问，但不会生成基于文献的深度报告。</span>
            <span v-else class="dr-shelf-hint is-ready">已勾选 {{ shelfSelectedPaperIds.length }} 篇文献，可以开始深度研究。</span>
          </template>
        </PaperShelfPanel>
      </div>
    </aside>

    <!-- 右侧参考来源侧边栏 -->
<aside class="dr-sidebar-right" v-if="referencePanelVisible">
  <div class="dr-right-header">
    <span>📄 参考来源</span>
    <el-button type="text" icon="el-icon-close" @click="referencePanelVisible = false" />
  </div>
  <div class="dr-right-content">
    <div 
      v-for="(paper, idx) in currentCitations" 
      :key="idx" 
      class="reference-item" 
      @click="openPaperLink(paper.url)"
    >
      <div class="ref-title">{{ paper.title || '未命名论文' }}</div>
    </div>
    <div v-if="currentCitations.length === 0" class="empty-ref">暂无参考来源</div>
  </div>
</aside>
  </div>
    <PaperShelfPreviewOverlay ref="shelfPreviewOverlay" />
  </div>
</template>

<script>
import MarkdownIt from 'markdown-it'
import UserAccessQuotaBar from '@/components/UserAccessQuotaBar.vue'
import ResearchAgentTaskProgressBar from '@/components/ResearchAgent/ResearchAgentTaskProgressBar.vue'
import PaperShelfPanel from '@/components/ResearchAgent/PaperShelfPanel.vue'
import PaperShelfPreviewOverlay from '@/components/ResearchAgent/PaperShelfPreviewOverlay.vue'
import { formatDate as formatDisplayDate, formatTime as formatDisplayTime } from '@/utils/dateTime.js'
import {
  createSession,
  createDeepResearchTask,
  getSession,
  getTask,
  postMessage,
  listSessions,
  deleteSession as apiDeleteSession
} from '@/views/ResearchAgent/researchAgentApi.js'
import { consumeDeepResearchHandoff } from '@/constants/researchAgentHandoff.js'

const md = new MarkdownIt({ breaks: true, linkify: true })
const REPORT_MESSAGE_PREFIX = '[[RA_REPORT]]\n'

export default {
  name: 'DeepResearchNew',
  components: { UserAccessQuotaBar, ResearchAgentTaskProgressBar, PaperShelfPanel, PaperShelfPreviewOverlay },
  data() {
    return {
      sidebarCollapsed: false,
      shelfCollapsed: false,  // 新增：论文展示区收起状态
      sessionList: [],
      currentSessionId: null,
      messages: [],
      taskStepsMap: {},
      stepCollapsed: {},
      taskId: null,
      taskStatus: '',
      taskOrchestrator: '',
      taskProgress: 0,
      searchQuery: '',
      followUpQuery: '',
      enableDeepThinking: true,
      isLoading: false,
      pollingTimer: null,
      referencePanelVisible: false,
      currentCitations: [],
      shelfRefreshToken: 0,
      pendingHandoffIds: null,
      resultBody: null,
      paperShelfItems: [],
      shelfSelectedPaperIds: [],
      examples: [
        '请基于已选文献，比较它们的研究问题、方法和实验结论',
        '请围绕已选论文，总结这个方向近年的主要进展和争议',
        '请从已选文献中提炼一个适合课程论文的综述提纲'
      ]
    }
  },
  computed: {
    pendingShelfCitations () {
      const cfg = this.resultBody && this.resultBody.runtime_config
      const outs = cfg && Array.isArray(cfg.basic_step_outputs) ? cfg.basic_step_outputs : []
      const onShelf = new Set()
      for (const it of this.paperShelfItems || []) {
        const u = String(it.primary_url || it.external_jump_url || '').trim().toLowerCase()
        if (u) onShelf.add(u)
      }
      const seen = new Set()
      const pending = []
      for (const o of outs) {
        if (!o || o.step_type !== 'search' || !Array.isArray(o.citations)) continue
        const q = String(o.search_query || '').trim()
        for (const c of o.citations) {
          if (!c || typeof c !== 'object') continue
          const url = String(c.url || '').trim()
          const key = url.toLowerCase() || `${c.title || ''}|${c.source || ''}`
          if (seen.has(key) || (url && onShelf.has(url.toLowerCase()))) continue
          seen.add(key)
          pending.push({ ...c, search_query: q })
        }
      }
      return pending
    }
  },
  watch: {
  '$route.path' (path, oldPath) {
    if (
      path &&
      path.includes('/deep-research') &&
      oldPath &&
      !oldPath.includes('/deep-research')
    ) {
      this.$nextTick(() => this.applyHandoffFromResearchAgent())
    }
  },
  // 监听整个 $route 对象的变化
  $route: {
    handler(newRoute) {
      const sessionId = newRoute.query.session_id
      if (sessionId && this.currentSessionId !== sessionId) {
        this.switchSession(sessionId)
      }
    },
    immediate: false,
    deep: true
  }
},
  created () {
  // 先检查 URL 中是否有 session_id 参数
  const sessionId = this.$route.query.session_id
  if (sessionId) {
    // 如果有，直接切换到该会话
    this.switchSession(sessionId)
  }
  this.loadSessionList()
  this.$nextTick(() => {
    this.applyHandoffFromResearchAgent()
  })
},
  mounted() {
    this.$nextTick(() => {
      const container = this.$refs.scrollContainer
      if (container) {
        container.addEventListener('scroll', this.handleScroll)
      }
    })
  },
  beforeDestroy () {
    this.stopPolling()
    const overlay = this.$refs.shelfPreviewOverlay
    if (overlay && typeof overlay.close === 'function') overlay.close()
    const container = this.$refs.scrollContainer
    if (container) {
      container.removeEventListener('scroll', this.handleScroll)
    }
  },
  methods: {
    formatDate(dateStr) {
      return formatDisplayDate(dateStr, '')
    },
    formatTime(ts) {
      return formatDisplayTime(ts, '')
    },

    //getCitationCount(paper) {
    //  const count = paper.citation_count || paper.citations || 0
    //  return count + ' citation' + (count !== 1 ? 's' : '')
    //},
    getStepsSummary(steps) {
      const completed = steps.filter(s => s.title).length
      return `已完成 ${completed}/${steps.length} 个步骤`
    },
    getStepsForMessage(msgIdx) {
      return this.taskStepsMap[msgIdx] || []
    },
    toggleProcessCollapse(msgIdx) {
      this.$set(this.stepCollapsed, msgIdx, !this.stepCollapsed[msgIdx])
    },
    handleScroll() {
      // 可以在这里添加滚动监听逻辑
    },
    formatMsg(text) {
      return md.render(text || '')
    },
    formatReport(text) {
      return md.render(text || '')
    },
    makeSessionTitle (content) {
      const text = String(content || '').replace(/\s+/g, ' ').trim()
      if (!text) return '新会话'
      return text.length > 28 ? `${text.slice(0, 28)}...` : text
    },
    isReportMessage(msg) {
      return Boolean(msg && msg.role === 'assistant' && typeof msg.content === 'string' && msg.content.startsWith(REPORT_MESSAGE_PREFIX))
    },
    extractReportMarkdown(msg) {
      if (!this.isReportMessage(msg)) return ''
      return String(msg.content || '').slice(REPORT_MESSAGE_PREFIX.length)
    },
    openPaperLink(url) {
      if (url) window.open(url, '_blank')
    },
    onShelfPreview (it) {
      const overlay = this.$refs.shelfPreviewOverlay
      if (overlay && typeof overlay.open === 'function') {
        overlay.open(it)
      }
    },
    bumpShelfRefresh () {
      this.shelfRefreshToken += 1
    },
    getSelectedShelfIds () {
      const panel = this.$refs.paperShelfPanel
      if (panel && typeof panel.getSelectedIds === 'function') {
        return panel.getSelectedIds()
      }
      return []
    },
    applyHandoffFromResearchAgent () {
      const ids = consumeDeepResearchHandoff()
      if (!ids || !ids.length) return
      this.pendingHandoffIds = [...ids]
      this.createNewSession()
      this.$nextTick(() => this.applyPendingHandoffSelection())
    },
    onShelfLoaded (items) {
      this.paperShelfItems = items || []
      this.applyPendingHandoffSelection()
    },
    onShelfSelectionChange (ids) {
      this.shelfSelectedPaperIds = Array.isArray(ids) ? ids : []
    },
    applyTaskPayload (at) {
      if (!at) {
        this.taskId = null
        this.taskStatus = ''
        this.taskOrchestrator = ''
        this.taskProgress = 0
        this.resultBody = null
        return
      }
      this.taskId = at.task_id
      this.taskStatus = at.status
      this.taskProgress = at.progress || 0
      this.resultBody = at.result || null
      this.taskOrchestrator = at.orchestrator || this.taskOrchestrator
    },
    isTaskActiveStatus (status = this.taskStatus) {
      const s = String(status || '').trim()
      return s === 'pending' || s === 'running' || s === 'pending_action'
    },
    async refreshActiveTaskPayload (sessionData) {
      const at = sessionData.active_task || sessionData.latest_task
      this.applyTaskPayload(at)
      const needTaskDetail = this.taskId && this.isTaskActiveStatus()
      if (needTaskDetail) {
        try {
          const tRes = await getTask(this.taskId)
          this.applyTaskPayload(tRes.data || {})
        } catch (e) {}
      }
      return at
    },
    applyPendingHandoffSelection () {
      if (!this.pendingHandoffIds || !this.pendingHandoffIds.length) return
      const panel = this.$refs.paperShelfPanel
      if (!panel || typeof panel.setSelectedIds !== 'function') return
      panel.setSelectedIds(this.pendingHandoffIds)
      const applied = panel.getSelectedIds()
      if (!applied.length && panel.loading) return
      this.pendingHandoffIds = null
      if (applied.length) {
        this.$message.success(`已带入 ${applied.length} 篇文献，可在对话区开启深度研究模式并发送`)
      } else {
        this.$message.warning('未能勾选带入的文献，请确认展示区中仍有对应条目')
      }
    },
    async onStartDeepResearch ({ content, selectedPapers, done, success }) {
      const selected = selectedPapers || []
      try {
        let sid = this.currentSessionId
        if (!sid) {
          const cr = await createSession({ title: this.makeSessionTitle(content) })
          sid = cr.data.session_id
          this.currentSessionId = sid
        }
        /* eslint-disable camelcase */
        const res = await createDeepResearchTask({
          session_id: sid,
          content,
          selected_papers: selected
        })
        /* eslint-enable camelcase */
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        this.taskOrchestrator = 'deep_research'
        this.taskProgress = 0
        this.searchQuery = ''
        if (typeof success === 'function') success()
        this.messages.push({ role: 'user', content })
        const assistantMsgIndex = this.messages.length
        this.messages.push({ role: 'assistant', content: '我开始做深度研究了，会在这里展示过程和报告。' })
        this.$set(this.stepCollapsed, assistantMsgIndex, false)
        await this.loadSessionList()
        this.startPolling(assistantMsgIndex)
        this.scrollToBottom()
        this.refreshQuota()
        this.bumpShelfRefresh()
      } catch (e) {
        console.error('启动深度研究失败', e)
        const data = e && e.response && e.response.data
        const msg = (data && data.message) || (data && data.error) || '启动深度研究失败'
        this.$message.error(msg)
        if (e && e.response && e.response.status === 429) this.refreshQuota()
      } finally {
        if (typeof done === 'function') done()
      }
    },
    toggleReferencePanelForMessage(msg) {
      if (this.currentCitations.length > 0) {
        this.referencePanelVisible = !this.referencePanelVisible
      } else {
        this.$message.info('暂无参考来源')
      }
    },
    async loadSessionList() {
      try {
        const res = await listSessions({ page: 1, page_size: 50 })
        this.sessionList = res.data.items || []
      } catch (e) {
        console.error('加载会话列表失败', e)
      }
    },
    async createNewSession() {
      this.currentSessionId = null
      this.messages = []
      this.taskStepsMap = {}
      this.stepCollapsed = {}
      this.taskId = null
      this.taskStatus = ''
      this.taskOrchestrator = ''
      this.taskProgress = 0
      this.resultBody = null
      this.searchQuery = ''
      this.followUpQuery = ''
      this.referencePanelVisible = false
      this.stopPolling()
      await this.loadSessionList()
      this.$message.success('已创建新会话')
    },
    async switchSession(sessionId) {
      if (this.currentSessionId === sessionId) return
      this.currentSessionId = sessionId
      this.stopPolling()
      this.isLoading = true
      this.referencePanelVisible = false
      
      try {
        const res = await getSession(sessionId)
        const data = res.data
        this.messages = data.messages || []
        const at = await this.refreshActiveTaskPayload(data)
        if (at) {
          const lastAssistantIdx = this.getLastAssistantMessageIndex()
          if (lastAssistantIdx !== -1 && at.steps) {
            this.$set(this.taskStepsMap, lastAssistantIdx, at.steps || [])
          }
          if (at.result && at.result.citations) {
            this.currentCitations = at.result.citations
          }
          if (this.isTaskActiveStatus(at.status)) {
            const pollIdx = lastAssistantIdx !== -1 ? lastAssistantIdx : Math.max(this.messages.length - 1, 0)
            this.isLoading = true
            this.startPolling(pollIdx)
          }
        }
        this.scrollToBottom()
      } catch (e) {
        console.error('加载会话失败', e)
        this.$message.error('加载会话失败')
      } finally {
        this.isLoading = false
      }
    },
    getLastAssistantMessageIndex() {
      for (let i = this.messages.length - 1; i >= 0; i--) {
        if (this.messages[i].role === 'assistant') {
          return i
        }
      }
      return -1
    },
    async startResearch () {
      const content = this.searchQuery.trim()
      if (!content) {
        this.$message.warning('请输入研究问题')
        return
      }
      const selectedPapers = this.getSelectedShelfIds()
      this.searchQuery = ''
      if (this.enableDeepThinking) {
        this.isLoading = true
        await this.onStartDeepResearch({
          content,
          selectedPapers,
          done: () => { this.isLoading = false },
          success: () => {}
        })
        return
      }
      this.isLoading = true
      try {
        let sid = this.currentSessionId
        if (!sid) {
          const cr = await createSession({ title: this.makeSessionTitle(content) })
          sid = cr.data.session_id
          this.currentSessionId = sid
        }
        const res = await postMessage(sid, { content })
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        this.messages.push({ role: 'user', content })
        const assistantMsgIndex = this.messages.length
        this.messages.push({ role: 'assistant', content: '我开始处理了，会把进展和结果整理在这里。' })
        this.$set(this.stepCollapsed, assistantMsgIndex, false)
        await this.loadSessionList()
        this.startPolling(assistantMsgIndex)
        this.scrollToBottom()
        this.refreshQuota()
      } catch (e) {
        console.error('发送失败', e)
        this.$message.error('发送失败')
        this.isLoading = false
      }
    },
    refreshQuota() {
      const bar = this.$refs.quotaBar
      if (bar && typeof bar.load === 'function') bar.load()
    },
    startPolling(assistantMsgIndex) {
      this.stopPolling()
      this.pollingTimer = setInterval(async () => {
        if (!this.currentSessionId) return
        try {
          const res = await getSession(this.currentSessionId)
          const data = res.data
          const at = await this.refreshActiveTaskPayload(data)

          if (at) {
            this.messages = data.messages || []

            if (at.steps && at.steps.length) {
              const currentAssistantIdx = this.getLastAssistantMessageIndex()
              if (currentAssistantIdx !== -1) {
                this.$set(this.taskStepsMap, currentAssistantIdx, at.steps || [])
              }
            }

            if (at.status === 'completed') {
              this.stopPolling()
              this.isLoading = false
              this.bumpShelfRefresh()
              if (at.result && at.result.citations) {
                this.currentCitations = at.result.citations
              }
              this.scrollToBottom()
              this.refreshQuota()
            } else if (at.status === 'failed' || at.status === 'cancelled') {
              this.stopPolling()
              this.isLoading = false
              this.$message.error('研究失败')
              this.refreshQuota()
            }
          }
        } catch (e) {
          console.error('轮询失败', e)
        }
      }, 2000)
    },
    stopPolling() {
      if (this.pollingTimer) {
        clearInterval(this.pollingTimer)
        this.pollingTimer = null
      }
    },
    async submitFollowUp () {
      const content = this.followUpQuery.trim()
      if (!content) return
      this.followUpQuery = ''
      const selectedPapers = this.getSelectedShelfIds()
      if (this.enableDeepThinking) {
        this.isLoading = true
        await this.onStartDeepResearch({
          content,
          selectedPapers,
          done: () => { this.isLoading = false },
          success: () => {}
        })
        return
      }
      if (!this.currentSessionId) {
        this.$message.warning('请先创建或选择会话')
        return
      }
      this.isLoading = true
      try {
        const res = await postMessage(this.currentSessionId, { content })
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        this.messages.push({ role: 'user', content })
        const assistantMsgIndex = this.messages.length
        this.messages.push({ role: 'assistant', content: '我开始处理了，会把进展和结果整理在这里。' })
        this.$set(this.stepCollapsed, assistantMsgIndex, false)
        await this.loadSessionList()
        this.startPolling(assistantMsgIndex)
        this.scrollToBottom()
      } catch (e) {
        console.error('追问失败', e)
        this.$message.error('追问失败')
        this.isLoading = false
      }
    },
    scrollToBottom() {
      this.$nextTick(() => {
        const container = this.$refs.scrollContainer
        if (container) {
          container.scrollTop = container.scrollHeight
        }
      })
    }
  }
}
</script>

<style scoped>
.dr-shell {
  position: relative;
  height: calc(100vh - 64px);
  max-height: calc(100vh - 64px);
  padding: 64px 12px 2px;
  text-align: left;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  background: linear-gradient(165deg, #e8f0ff 0%, #f5f9ff 35%, #fafbff 70%, #ffffff 100%);  /* ← 改为渐变背景 */
  opacity: 0.95;
}
.dr-container {
  position: relative;
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 10px;
  overflow: hidden;
}

/* 左侧边栏 */
.dr-sidebar-left {
  width: 260px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  margin: 0;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  transition: width 0.2s ease;
}
.dr-sidebar-left.is-collapsed {
  width: 60px;
}
.dr-side-top {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-bottom: 1px solid #f0f0f0;
}
.dr-icon-btn {
  width: 32px;
  height: 32px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
  background: transparent;
  border: none;
  font-size: 18px;
}

.dr-icon-btn:hover {
  background-color: #f0f2f5;
}

.dr-side-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.dr-side-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.dr-side-item:hover { background: #f5f7fa; }
.dr-side-item.is-active { border-color: #409eff; background: #ecf5ff; }
.dr-side-title { font-size: 13px; font-weight: 500; color: #303133; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dr-side-time { font-size: 11px; color: #909399; margin-top: 4px; }
.dr-muted { text-align: center; color: #c0c4cc; padding: 20px; font-size: 13px; }

/* 主内容区 - 关键修改 */
.dr-task-header {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 16px 0;
}
.dr-task-header .ra-task-progress {
  flex: 1;
  min-width: 0;
}
.dr-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
  padding: 12px 16px 16px;
  height: 100%;
  overflow: hidden;
  box-sizing: border-box;
  margin-top: 0;
  border-radius: 8px;
}

/* 滚动区域 - 独立滚动条 */
.dr-messages-wrapper {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  margin-bottom: 16px;
}

/* 消息列表容器 */
.dr-messages {
  padding-bottom: 20px;
}

/* 底部输入框 - 固定在底部不被滚动 */
.dr-followup {
  background: white;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  flex-shrink: 0;
}

/* 欢迎页 */
.dr-welcome {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 500px;
}
.dr-welcome-content {
  max-width: 700px;
  width: 100%;
  text-align: center;
}
.dr-welcome-content h1 { font-size: 32px; font-weight: 700; color: #1f2f3d; margin-bottom: 12px; }
.dr-welcome-content p { font-size: 14px; color: #667085; margin-bottom: 14px; line-height: 1.7; }
.dr-guide-steps {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-bottom: 24px;
}
.dr-guide-steps span {
  font-size: 12px;
  color: #42618a;
  background: #f3f8ff;
  border: 1px solid #d8e8ff;
  border-radius: 999px;
  padding: 5px 10px;
}
.dr-mode-toggle { margin-bottom: 20px; text-align: left; }
.mode-toggle-card {
  background: white;
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}
.mode-toggle-card.active { border-color: #409eff; background: #ecf5ff; }
.mode-info { flex: 1; text-align: left; }
.mode-title { font-size: 14px; font-weight: 600; color: #303133; }
.mode-desc { font-size: 12px; color: #909399; margin-top: 2px; }
.dr-input { margin-bottom: 16px; }
.dr-examples { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
.examples-label { font-size: 13px; color: #909399; }
.example-tag { cursor: pointer; }
.dr-start-btn { width: 120px; border-radius: 24px; }

/* 消息气泡 */
.dr-bubble-row {
  display: flex;
  margin-bottom: 20px;
}
.dr-bubble-row.is-user {
  justify-content: flex-end;
}
.dr-bubble-row.is-assistant {
  justify-content: flex-start;
}
.dr-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 12px;
}
.dr-bubble.is-user {
  background: #ecf5ff;
}
.dr-bubble.is-assistant {
  background: white;
  border: 1px solid #e8e8e8;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.dr-bubble-head {
  margin-bottom: 6px;
  text-align: left;
}
.dr-role {
  font-size: 12px;
  color: #909399;
}
.dr-content {
  font-size: 14px;
  line-height: 1.6;
  color: #303133;
  text-align: left;
}

/* 思考过程 */
.thinking-process {
  background: #f8f9fa;
  border-radius: 12px;
  margin-bottom: 12px;
  border: 1px solid #e8e8e8;
}
.process-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
}
.process-header i { font-size: 14px; color: #409eff; }
.process-title { font-size: 13px; font-weight: 500; color: #303133; }
.process-badge { font-size: 11px; color: #909399; background: #e8eef5; padding: 2px 8px; border-radius: 20px; }
.process-summary { font-size: 12px; color: #909399; margin-left: auto; }
.process-detail { padding: 0 14px 14px; border-top: 1px solid #e8e8e8; }
.process-step { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
.process-step:last-child { border-bottom: none; }
.step-dot {
  width: 24px; height: 24px; background: #e8eef5; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600; color: #606266; flex-shrink: 0;
}
.step-content { flex: 1; }
.step-title { font-size: 13px; font-weight: 500; color: #303133; }
.step-detail { font-size: 12px; color: #909399; margin-top: 4px; }
.step-time { font-size: 11px; color: #c0c4cc; margin-top: 4px; }

/* Markdown 内容样式 */
.dr-content >>> h1,
.dr-content >>> h2,
.dr-content >>> h3 {
  font-weight: 650;
  color: #1a2b4a;
  line-height: 1.35;
  margin: 0.65em 0 0.4em;
}
.dr-content >>> h1 {
  font-size: 1.15rem;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 0.25em;
}
.dr-content >>> h2 {
  font-size: 1.05rem;
}
.dr-content >>> h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #303133;
}
.dr-content p {
  margin: 0.5em 0;
  line-height: 1.6;
}
.dr-content ul, .dr-content ol {
  margin: 0.5em 0;
  padding-left: 1.8em;
}
.dr-content li {
  margin: 0.3em 0;
  line-height: 1.5;
}
.dr-content code {
  background: #f5f7fa;
  padding: 0.1em 0.3em;
  border-radius: 4px;
  font-family: monospace;
  font-size: 0.9em;
  color: #c7254e;
}
.dr-content pre {
  background: #f5f7fa;
  padding: 0.8em;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.8em 0;
}
.dr-content pre code {
  background: transparent;
  padding: 0;
  color: #303133;
}
.dr-content blockquote {
  margin: 0.5em 0;
  padding: 0.3em 0.8em;
  border-left: 3px solid #409eff;
  background: #f8f9fa;
  color: #606266;
}
.dr-content a {
  color: #409eff;
  text-decoration: none;
}
.dr-content a:hover {
  text-decoration: underline;
}

/* 报告区块 */
.dr-report-block {
  margin-top: 8px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
  padding: 10px 12px;
}
.dr-report-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  text-align: left;
}
.dr-md {
  text-align: left;
  line-height: 1.6;
}
.dr-md >>> h1,
.dr-md >>> h2,
.dr-md >>> h3 {
  font-weight: 650;
  color: #1a2b4a;
  line-height: 1.35;
  margin: 0.65em 0 0.4em;
}
.dr-md >>> h1 {
  font-size: 1.15rem;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 0.25em;
}
.dr-md >>> h2 {
  font-size: 1.05rem;
}
.dr-md >>> h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #303133;
}
.dr-md p {
  margin: 0.5em 0;
}
.dr-md ul, .dr-md ol {
  margin: 0.4em 0;
  padding-left: 1.8em;
}
.dr-md li {
  margin: 0.2em 0;
}
.dr-md code {
  background: #f5f7fa;
  padding: 0.1em 0.3em;
  border-radius: 4px;
  font-family: monospace;
}
.dr-md pre {
  background: #f5f7fa;
  padding: 0.8em;
  border-radius: 8px;
  overflow-x: auto;
}
.dr-md blockquote {
  margin: 0.5em 0;
  padding: 0.3em 0.8em;
  border-left: 3px solid #409eff;
  background: #f8f9fa;
}

.reference-footer {
  margin-top: 12px;
  text-align: right;
  border-top: 1px solid #f0f0f0;
  padding-top: 8px;
}
.reference-btn {
  color: #909399;
  font-size: 12px;
}
.reference-btn:hover {
  color: #409eff;
}

.dr-loading { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 32px; color: #909399; }
.dr-loading i { animation: rotate 1s linear infinite; }
@keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.followup-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
}
.mode-toggle-mini { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #909399; }

/* 右侧论文展示区 - 新增收起功能 */
.dr-sidebar-shelf {
  width: 440px;
  flex-shrink: 0;
  position: relative;
  background: #fff;
  border-radius: 8px;
  margin: 0;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  transition: width 0.2s ease;
}
.dr-sidebar-shelf.is-collapsed {
  width: 60px;
}
.dr-shelf-toggle-anchor {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 4;
}
.dr-shelf-header {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: 12px;
  padding: 12px 56px 12px 12px;
  border-bottom: 1px solid #f0f0f0;
  flex-shrink: 0;
}
.dr-shelf-collapse-btn {
  width: 32px;
  height: 32px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
  border: none;
  font-size: 18px;
  box-shadow: 0 10px 22px rgba(31, 45, 61, 0.16);
}
.dr-shelf-collapse-btn:hover {
  background-color: #f0f2f5;
}
.dr-shelf-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.dr-shelf-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 8px 12px 12px;
  display: flex;
  flex-direction: column;
}
.dr-shelf-body >>> .ps-panel {
  height: 100%;
}
.dr-shelf-hint {
  display: block;
  font-size: 12px;
  line-height: 1.5;
  color: #7b8aa0;
}
.dr-shelf-hint.is-ready {
  color: #2f7d4f;
}

/* 右侧参考来源侧边栏 */
.dr-sidebar-right {
  width: 300px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  margin: 0;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.dr-right-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #e8e8e8;
  font-weight: 600;
  font-size: 14px;
  background: #fafafa;
}
.dr-right-content { flex: 1; overflow-y: auto; padding: 12px; }
.reference-item {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
  cursor: pointer;
  border: 1px solid #f0f0f0;
  transition: all 0.2s;
}
.reference-item:hover { border-color: #409eff; background: #f5faff; }
.ref-title { font-size: 13px; font-weight: 500; color: #303133; margin-bottom: 6px; }
.ref-meta { font-size: 11px; color: #909399; margin-bottom: 4px; }
.ref-source { font-size: 11px; color: #c0c4cc; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-ref { text-align: center; color: #c0c4cc; padding: 40px 16px; }

.slide-fade-enter-active, .slide-fade-leave-active { transition: all 0.2s ease; }
.slide-fade-enter, .slide-fade-leave-to { transform: translateY(-10px); opacity: 0; }

@media (max-width: 768px) {
  .dr-sidebar-left { position: fixed; left: 0; top: 60px; z-index: 100; height: calc(100vh - 60px); transform: translateX(0); transition: transform 0.3s; }
  .dr-sidebar-left.is-collapsed { transform: translateX(-100%); }
  .dr-sidebar-right { position: fixed; right: 0; top: 60px; z-index: 100; height: calc(100vh - 60px); }
  .dr-sidebar-shelf { position: fixed; right: 0; top: 60px; z-index: 100; height: calc(100vh - 60px); transform: translateX(0); transition: transform 0.3s; }
  .dr-sidebar-shelf.is-collapsed { transform: translateX(100%); }
}

/* 修复按钮图标显示 */
.dr-side-top .el-button--primary.is-circle {
  background-color: #409eff;
  border-color: #409eff;
  color: white;
  width: 32px;
  height: 32px;
  padding: 0;
  font-size: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
}

.dr-side-top .el-button--primary.is-circle:hover {
  background-color: #66b1ff;
  border-color: #66b1ff;
}

.dr-collapse-btn .el-icon-s-unfold,
.dr-collapse-btn .el-icon-s-fold {
  font-size: 20px;
  color: #606266;
}

.dr-icon-btn .el-icon-plus {
  font-size: 16px;
}
</style>
