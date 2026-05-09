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
            placeholder="接下来要去哪里呢"
            :disabled="inputLocked"
            @keydown.enter.native.prevent="send"
          />
          <div class="ra-input-actions">
            <div class="ra-actions-spacer" aria-hidden="true"></div>
            <div class="ra-deep-slot">
              <el-tooltip
                effect="dark"
                placement="top"
                content="开启后编排器将拆解子任务，触发完整的联网调研，深度研究响应较慢"
              >
                <el-checkbox v-model="enableDeepThinking" class="ra-deep-thinking-toggle">深度思考</el-checkbox>
              </el-tooltip>
            </div>
            <el-button class="ra-action-btn ra-download-btn" size="mini" type="primary" :disabled="!taskId || taskStatus !== 'completed'" @click="onDownloadReport">
              下载报告
            </el-button>
            <el-button class="ra-action-btn ra-send-btn" type="primary" :disabled="inputLocked || !draft.trim()" @click="send">发送</el-button>
          </div>
        </footer>
      </main>

      <aside class="ra-sidebar-right">

        <!-- ══ 工作区文件面板 ══════════════════════════════════ -->
        <div class="ws-panel">
          <div class="ws-panel-head" @click="wsPanelOpen = !wsPanelOpen">
            <span><i class="el-icon-folder-opened"></i> 我的文件</span>
            <span class="ws-head-actions" @click.stop>
              <el-button
                type="text" icon="el-icon-refresh" size="mini"
                :loading="wsLoading" title="刷新"
                @click="wsRefresh"
              />
              <i :class="wsPanelOpen ? 'el-icon-arrow-up' : 'el-icon-arrow-down'" class="ws-toggle-icon" />
            </span>
          </div>

          <template v-if="wsPanelOpen">
            <!-- 面包屑导航 -->
            <div class="ws-breadcrumb">
              <span class="ws-crumb ws-crumb-link" @click="wsNavigate('')">根目录</span>
              <template v-for="(seg, i) in wsBreadcrumbs">
                <span :key="'sep-' + i" class="ws-crumb-sep">/</span>
                <span
                  :key="'seg-' + i"
                  :class="['ws-crumb', i < wsBreadcrumbs.length - 1 ? 'ws-crumb-link' : 'ws-crumb-cur']"
                  @click="i < wsBreadcrumbs.length - 1 && wsNavigate(wsBreadcrumbs.slice(0, i + 1).join('/'))"
                >{{ seg }}</span>
              </template>
            </div>

            <!-- 文件/目录列表 -->
            <div class="ws-file-list" v-loading="wsLoading">
              <p v-if="wsError" class="ws-error">{{ wsError }}</p>
              <p v-else-if="!wsLoading && !wsItems.length" class="ws-empty">此目录为空</p>
              <div
                v-for="item in wsItems"
                :key="item.rel_path"
                class="ws-item"
                :class="{ 'ws-item-dir': item.type === 'directory' }"
              >
                <div
                  class="ws-item-left"
                  :title="item.name"
                  @click="item.type === 'directory' ? wsNavigate(item.rel_path) : null"
                >
                  <i :class="item.type === 'directory' ? 'el-icon-folder' : wsFileIcon(item.name)" class="ws-item-icon" />
                  <span class="ws-item-name">{{ item.name }}</span>
                </div>
                <div class="ws-item-right">
                  <span v-if="item.type === 'file'" class="ws-size">{{ wsFormatSize(item.size) }}</span>
                  <el-button
                    v-if="item.type === 'file'"
                    type="text" icon="el-icon-download" size="mini"
                    title="下载到本机"
                    @click="wsDownload(item)"
                  />
                  <el-button
                    type="text" icon="el-icon-delete" size="mini"
                    class="ws-del-btn" title="删除"
                    @click="wsDeleteConfirm(item)"
                  />
                </div>
              </div>
            </div>

            <!-- 底部操作栏 -->
            <div class="ws-toolbar">
              <el-upload
                action="" :http-request="wsUploadHandler"
                :show-file-list="false" multiple
                :disabled="wsUploading"
                class="ws-upload-btn"
              >
                <el-button size="mini" icon="el-icon-upload2" :loading="wsUploading" :disabled="wsUploading">上传文件</el-button>
              </el-upload>
              <el-button size="mini" icon="el-icon-folder-add" @click="wsMkdirDialogOpen">新建文件夹</el-button>
            </div>
          </template>
        </div>

        <!-- 新建文件夹对话框（append-to-body 避免布局影响） -->
        <el-dialog
          title="新建文件夹"
          :visible.sync="wsMkdirDialog"
          width="280px"
          append-to-body
          @open="wsMkdirName = ''"
          @keyup.enter.native="wsMkdir"
        >
          <el-input
            v-model="wsMkdirName"
            placeholder="文件夹名称，支持 papers/2026"
            maxlength="120"
            show-word-limit
            autofocus
            @keyup.enter.native="wsMkdir"
          />
          <span slot="footer">
            <el-button @click="wsMkdirDialog = false">取消</el-button>
            <el-button type="primary" :disabled="!wsMkdirName.trim()" @click="wsMkdir">创建</el-button>
          </span>
        </el-dialog>
        <!-- ══════════════════════════════════════════════════ -->

        <div v-if="showExecutionBoard" class="ws-panel ra-board-panel">
          <div class="ws-panel-head" @click="boardPanelOpen = !boardPanelOpen">
            <span><i class="el-icon-data-analysis"></i> 执行看板</span>
            <span class="ws-head-actions">
              <i :class="boardPanelOpen ? 'el-icon-arrow-up' : 'el-icon-arrow-down'" class="ws-toggle-icon" />
            </span>
          </div>
          <template v-if="boardPanelOpen">
            <div class="ra-board-content">
              <div class="ra-current-card">
                <p><strong>阶段：</strong>{{ currentStatus.phaseLabel }}</p>
                <p><strong>子任务：</strong>{{ currentStatus.subtaskTitle }}</p>
                <p><strong>轮次：</strong>{{ currentStatus.roundLabel }}</p>
                <p><strong>最近动作：</strong>{{ currentStatus.recentAction }}</p>
              </div>

              <div v-if="displayedHistorySteps.length" class="ra-side-section">
                <div class="ra-side-section-head">
                  <strong>执行历史</strong>
                  <el-button
                    v-if="shouldCollapseHistory"
                    type="text"
                    size="mini"
                    class="ra-step-expand"
                    @click="historyExpanded = !historyExpanded"
                  >
                    {{ historyExpanded ? '收起旧步骤' : `展开全部（${steps.length}）` }}
                  </el-button>
                </div>
                <ul class="ra-step-list">
                  <li v-for="s in displayedHistorySteps" :key="s.seq" class="ra-step-item">
                    <div class="ra-step-head">
                      <div>
                        <span class="ra-ts">{{ s.ts }}</span>
                        <strong>{{ s.title }}</strong>
                        <div class="ra-phase">{{ phaseLabel(s.phase) }}</div>
                      </div>
                      <el-button
                        type="text"
                        size="mini"
                        class="ra-step-expand"
                        @click="toggleStepExpand(s.seq)"
                      >
                        {{ stepExpanded[s.seq] ? '收起详情' : '展开详情' }}
                      </el-button>
                    </div>
                    <div v-if="stepExpanded[s.seq]" class="ra-detail">
                      <p
                        v-for="(line, lineIdx) in getStepDisplayLines(s)"
                        :key="`${s.seq}-${lineIdx}`"
                      >
                        {{ line }}
                      </p>
                    </div>
                  </li>
                </ul>
              </div>

              <div v-if="hasPlannerContent" class="ra-side-section">
                <strong>方案与决策</strong>
                <div v-if="plannerAlternatives.length" class="ra-plan-list">
                  <div v-for="item in plannerAlternatives" :key="item.plan_id" class="ra-plan-item">
                    <div class="ra-plan-title">
                      {{ item.title || item.plan_id }}
                      <el-tag
                        v-if="deciderDecision.selected_plan_id && deciderDecision.selected_plan_id === item.plan_id"
                        size="mini"
                        type="success"
                      >
                        已选
                      </el-tag>
                    </div>
                    <p class="ra-muted-line">{{ item.rationale || '无说明' }}</p>
                  </div>
                </div>
                <div v-if="deciderDecision.decision_reason" class="ra-decision-meta">
                  <p><strong>复杂度：</strong>{{ deciderDecision.complexity || 'unknown' }}</p>
                  <p><strong>选型理由：</strong>{{ deciderDecision.decision_reason }}</p>
                  <p><strong>合并说明：</strong>{{ deciderDecision.merge_attempt_note || '无' }}</p>
                </div>
              </div>

              <div v-if="subtaskProgressList.length" class="ra-side-section">
                <strong>子任务进度</strong>
                <ul class="ra-subtask-list">
                  <li v-for="item in subtaskProgressList" :key="item.subtask_id" class="ra-subtask-item">
                    <div class="ra-subtask-title">
                      {{ item.title || item.subtask_id }}
                      <el-tag v-if="item.state === 'done'" size="mini" type="success">完成</el-tag>
                      <el-tag v-else-if="item.state === 'running'" size="mini">进行中</el-tag>
                      <el-tag v-else size="mini" type="info">待执行</el-tag>
                    </div>
                    <p class="ra-muted-line">目标：{{ item.goal || '未提供' }}</p>
                  </li>
                </ul>
              </div>

              <div v-if="reflectorConclusions.length" class="ra-side-section">
                <strong>反思结论</strong>
                <ul class="ra-subtask-list">
                  <li v-for="(item, idx) in reflectorConclusions.slice(-6)" :key="`${item.subtask_id || 'unknown'}-${idx}`" class="ra-subtask-item">
                    <div class="ra-subtask-title">{{ item.subtask_title || item.subtask_id || '未命名子任务' }}</div>
                    <p class="ra-muted-line">轮次：{{ item.round || '-' }} · 继续优化：{{ item.needs_optimization === 'yes' ? '是' : '否' }}</p>
                    <p class="ra-muted-line">原因：{{ item.reason || '无' }}</p>
                  </li>
                </ul>
              </div>
            </div>
          </template>
        </div>
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
import {
  listWorkspaceFiles,
  downloadWorkspaceFile,
  uploadWorkspaceFiles,
  deleteWorkspacePath,
  mkdirWorkspace
} from './workspaceApi.js'

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
      enableDeepThinking: false,
      pollTimer: null,
      stepExpanded: {},
      historyExpanded: false,
      collapseAfterSteps: 12,
      pollFailureCount: 0,
      pollInFlight: false,
      autoFollowMessages: true,
      showScrollToBottom: false,
      boardPanelOpen: true,
      // ── 工作区文件面板 ──────────────────────────────────────
      wsPanelOpen: true,
      // 当前浏览的相对路径（空表示根目录）
      wsPath: '',
      // 当前目录的文件/目录列表
      wsItems: [],
      wsLoading: false,
      wsError: '',
      wsUploading: false,
      wsUploadActiveCount: 0,
      wsMkdirDialog: false,
      wsMkdirName: ''
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
    },
    showExecutionBoard () {
      return Boolean(
        this.taskId ||
        this.taskStatus ||
        (Array.isArray(this.steps) && this.steps.length) ||
        this.plannerAlternatives.length ||
        this.subtaskProgressList.length ||
        this.reflectorConclusions.length
      )
    },
    hasPlannerContent () {
      return this.plannerAlternatives.length > 0 || Boolean(this.deciderDecision.decision_reason)
    },
    currentStep () {
      if (!Array.isArray(this.steps) || !this.steps.length) return null
      return this.steps[this.steps.length - 1]
    },
    shouldCollapseHistory () {
      return (this.steps || []).length > this.collapseAfterSteps
    },
    displayedHistorySteps () {
      const list = Array.isArray(this.steps) ? this.steps : []
      if (!this.shouldCollapseHistory || this.historyExpanded) return list
      return list.slice(-this.collapseAfterSteps)
    },
    taskResultPayload () {
      return this.resultBody && typeof this.resultBody === 'object' ? this.resultBody : {}
    },
    plannerAlternatives () {
      const list = this.taskResultPayload.planner_alternatives
      return Array.isArray(list) ? list : []
    },
    deciderDecision () {
      const decision = this.taskResultPayload.decider_decision
      return decision && typeof decision === 'object' ? decision : {}
    },
    reflectorConclusions () {
      const list = this.taskResultPayload.all_reflector_conclusions
      return Array.isArray(list) ? list : []
    },
    subtaskSummaries () {
      const list = this.taskResultPayload.subtask_summaries
      return Array.isArray(list) ? list : []
    },
    subtaskProgressList () {
      const decisionSubtasks = Array.isArray(this.deciderDecision.subtasks) ? this.deciderDecision.subtasks : []
      if (!decisionSubtasks.length) return []
      const doneIds = new Set(
        this.subtaskSummaries
          .map(item => String(item && item.subtask_id ? item.subtask_id : '').trim())
          .filter(Boolean)
      )
      const runningSubtaskId = this.detectRunningSubtaskId()
      return decisionSubtasks.map((item) => {
        const subtaskId = String(item && item.subtask_id ? item.subtask_id : '').trim()
        let state = 'pending'
        if (doneIds.has(subtaskId)) state = 'done'
        else if (runningSubtaskId && runningSubtaskId === subtaskId) state = 'running'
        return {
          subtask_id: subtaskId,
          title: item && item.title ? item.title : '',
          goal: item && item.goal ? item.goal : '',
          state
        }
      })
    },
    currentStatus () {
      const step = this.currentStep || {}
      const parsed = this.parseStepMeta(step)
      const subtaskTitle = parsed.subtaskTitle || this.detectRunningSubtaskTitle() || '等待开始'
      return {
        phaseLabel: this.phaseLabel(step.phase || this.taskStatus || 'pending'),
        subtaskTitle,
        roundLabel: parsed.roundLabel || '-',
        recentAction: step.title || (this.taskStatus ? `任务状态：${this.taskStatus}` : '暂无动作')
      }
    },
    // ── 工作区：面包屑路径段数组 ─────────────────────────────
    wsBreadcrumbs () {
      if (!this.wsPath) return []
      return this.wsPath.split('/').filter(Boolean)
    }
  },
  watch: {
    '$route.params.sessionId' () {
      this.bootstrap()
    },
    steps () {
      if (!this.shouldCollapseHistory) this.historyExpanded = false
    },
    wsPanelOpen (val) {
      if (val && !this.wsItems.length && !this.wsLoading) {
        this.wsRefresh()
      }
    }
  },
  created () {
    this.bootstrap()
    this.wsRefresh()
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
      return this.stepExpanded[step.seq] ? lines : []
    },
    toggleStepExpand (seq) {
      this.$set(this.stepExpanded, seq, !this.stepExpanded[seq])
    },
    extractStepLines (step) {
      const text = (step && step.detail) ? String(step.detail) : ''
      return text.split('\n').map(v => v.trim()).filter(Boolean)
    },
    phaseLabel (phase) {
      const map = {
        pending: '等待中',
        running: '执行中',
        plan: '规划',
        decide: '决策',
        search: '检索',
        read: '阅读',
        reflect: '反思',
        write: '写作',
        pending_action: '待确认',
        completed: '已完成',
        failed: '失败',
        cancelled: '已取消'
      }
      const key = String(phase || '').trim()
      return map[key] || key || '未知'
    },
    isTaskActive (status = this.taskStatus) {
      const s = String(status || '').trim()
      return s === 'pending' || s === 'running' || s === 'pending_action'
    },
    parseStepMeta (step) {
      const lines = this.extractStepLines(step)
      let subtaskTitle = ''
      let roundLabel = ''
      lines.forEach((line) => {
        if (line.startsWith('子任务：')) {
          subtaskTitle = line.replace('子任务：', '').trim()
        } else if (line.startsWith('轮次：')) {
          roundLabel = line.replace('轮次：', '').trim()
        } else if (line.startsWith('当前轮次：')) {
          roundLabel = line.replace('当前轮次：', '').trim()
        }
      })
      return { subtaskTitle, roundLabel }
    },
    detectRunningSubtaskTitle () {
      if (!this.currentStep) return ''
      const parsed = this.parseStepMeta(this.currentStep)
      return parsed.subtaskTitle || ''
    },
    detectRunningSubtaskId () {
      const title = this.detectRunningSubtaskTitle()
      if (!title) return ''
      const decisionSubtasks = Array.isArray(this.deciderDecision.subtasks) ? this.deciderDecision.subtasks : []
      const matched = decisionSubtasks.find(item => String(item && item.title ? item.title : '').trim() === title)
      if (!matched) return ''
      return String(matched.subtask_id || '').trim()
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
        const wasTaskActive = this.isTaskActive()
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
        if (wasTaskActive && !this.isTaskActive()) {
          this.wsRefresh()
        }
        this.$nextTick(() => this.scrollMsg(true))
        if (this.isTaskActive()) this.syncPoll()
        else this.stopPoll()
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
        const wasTaskActive = this.isTaskActive()
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

        // 任务从进行中变为终态时刷新工作区列表（助手可能刚写入/删除了文件）
        if (wasTaskActive && !this.isTaskActive()) {
          this.wsRefresh()
        }

        if ((this.messages || []).length !== prevMsgCount) {
          this.$nextTick(() => this.scrollMsg())
          if (!this.isTaskActive()) this.stopPoll()
          return
        }
        this.$nextTick(() => this.scrollMsg())
        if (!this.isTaskActive()) this.stopPoll()
      } finally {
        this.pollInFlight = false
      }
    },
    syncPoll () {
      this.stopPoll()
      if (!this.currentSessionId) return
      if (!this.isTaskActive()) return
      this.pollFailureCount = 0
      this.pollTick().catch(() => {})
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
        const options = {
          deep_thinking: this.enableDeepThinking
        }
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
        const ackMessage = '已收到请求，任务已启动。'
        const tail = this.messages[this.messages.length - 1]
        if (!tail || tail.role !== 'assistant' || tail.content !== ackMessage) {
          this.messages = [...this.messages, { role: 'assistant', content: ackMessage }]
          this.$nextTick(() => this.scrollMsg())
        }
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
    },

    // ══ 工作区方法 ════════════════════════════════════════════

    /** 加载当前路径的目录内容 */
    async wsRefresh () {
      this.wsLoading = true
      this.wsError = ''
      try {
        const data = await listWorkspaceFiles(this.wsPath)
        this.wsItems = Array.isArray(data.items) ? data.items : []
      } catch (e) {
        this.wsError = (e && e.message) || '加载失败'
      } finally {
        this.wsLoading = false
      }
    },

    /** 进入指定子目录（或返回根目录） */
    async wsNavigate (relPath) {
      this.wsPath = relPath || ''
      await this.wsRefresh()
    },

    /** 下载文件到用户本机 */
    async wsDownload (item) {
      try {
        await downloadWorkspaceFile(item.rel_path, item.name)
      } catch (e) {
        this.$message.error('下载失败：' + ((e && e.message) || '未知错误'))
      }
    },

    /** 删除前弹确认框 */
    wsDeleteConfirm (item) {
      const label = item.type === 'directory' ? `目录「${item.name}」` : `文件「${item.name}」`
      const hint = item.type === 'directory' ? '（目录必须为空才可删除）' : ''
      this.$confirm(`确定删除${label}？${hint}`, '删除确认', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(() => this.wsDelete(item)).catch(() => {})
    },

    /** 执行删除 */
    async wsDelete (item) {
      try {
        await deleteWorkspacePath(item.rel_path)
        this.$message.success(`已删除 ${item.name}`)
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('删除失败：' + ((e && e.message) || '未知错误'))
      }
    },

    /** el-upload 自定义上传处理 */
    async wsUploadHandler ({ file }) {
      this.wsUploadActiveCount += 1
      this.wsUploading = true
      try {
        const data = await uploadWorkspaceFiles([file], this.wsPath)
        const uploaded = data && Array.isArray(data.uploaded) ? data.uploaded[0] : null
        const savedName = uploaded && uploaded.name ? uploaded.name : file.name
        const renamedHint = savedName !== file.name ? `，已保存为 ${savedName}` : ''
        this.$message.success(`已上传 ${file.name}${renamedHint}`)
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('上传失败：' + ((e && e.message) || '未知错误'))
      } finally {
        this.wsUploadActiveCount = Math.max(0, this.wsUploadActiveCount - 1)
        this.wsUploading = this.wsUploadActiveCount > 0
      }
    },

    /** 打开新建文件夹对话框并重置输入 */
    wsMkdirDialogOpen () {
      this.wsMkdirName = ''
      this.wsMkdirDialog = true
    },

    /** 执行创建目录 */
    async wsMkdir () {
      const name = this.wsMkdirName.trim()
      if (!name) return
      const fullPath = this.wsPath ? `${this.wsPath}/${name}` : name
      try {
        await mkdirWorkspace(fullPath)
        this.$message.success(`目录「${name}」创建成功`)
        this.wsMkdirDialog = false
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('创建失败：' + ((e && e.message) || '未知错误'))
      }
    },

    /** 根据文件扩展名返回合适的 Element 图标类名 */
    wsFileIcon (name) {
      const ext = (name || '').split('.').pop().toLowerCase()
      const map = {
        pdf: 'el-icon-document',
        md: 'el-icon-tickets',
        txt: 'el-icon-tickets',
        doc: 'el-icon-tickets',
        docx: 'el-icon-tickets',
        xls: 'el-icon-s-grid',
        xlsx: 'el-icon-s-grid',
        png: 'el-icon-picture',
        jpg: 'el-icon-picture',
        jpeg: 'el-icon-picture',
        gif: 'el-icon-picture',
        zip: 'el-icon-files',
        tar: 'el-icon-files',
        gz: 'el-icon-files',
        py: 'el-icon-s-management',
        js: 'el-icon-s-management',
        json: 'el-icon-s-management'
      }
      return map[ext] || 'el-icon-document'
    },

    /** 将字节数格式化为人类可读字符串 */
    wsFormatSize (bytes) {
      if (bytes === 0) return '0 B'
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / 1024 / 1024).toFixed(1) + ' MB'
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
.ra-current-card {
  border: 1px solid #d9ecff;
  background: #f5faff;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 12px;
}
.ra-current-card p {
  margin: 6px 0;
  font-size: 12px;
  color: #303133;
}
.ra-side-section {
  margin-bottom: 14px;
}
.ra-side-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.ra-plan-list,
.ra-subtask-list {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
}
.ra-plan-item,
.ra-subtask-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 6px;
}
.ra-plan-title,
.ra-subtask-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 13px;
  color: #303133;
}
.ra-muted-line {
  margin: 6px 0 0;
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
.ra-decision-meta {
  margin-top: 8px;
}
.ra-decision-meta p {
  margin: 6px 0;
  font-size: 12px;
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
  font-size: 14px;
  line-height: 1.65;
  color: #303133;
}
.ra-content >>> p {
  margin: 0.45em 0;
}
.ra-content >>> h1 {
  margin: 0.55em 0 0.4em;
  font-size: 1.2rem;
  line-height: 1.4;
  font-weight: 650;
}
.ra-content >>> h2 {
  margin: 0.5em 0 0.35em;
  font-size: 1.08rem;
  line-height: 1.45;
  font-weight: 620;
}
.ra-content >>> h3 {
  margin: 0.45em 0 0.3em;
  font-size: 1rem;
  line-height: 1.5;
  font-weight: 600;
}
.ra-content >>> ul,
.ra-content >>> ol {
  margin: 0.45em 0;
  padding-left: 1.2em;
}
.ra-content >>> li {
  margin: 0.2em 0;
}
.ra-content >>> blockquote {
  margin: 0.45em 0;
  padding: 0.3em 0.75em;
  border-left: 3px solid #dcdfe6;
  color: #606266;
  background: #f8f9fb;
}
.ra-content >>> pre {
  margin: 0.5em 0;
  padding: 0.55em 0.7em;
  border-radius: 6px;
  background: #f6f8fa;
  overflow-x: auto;
}
.ra-content >>> code {
  font-size: 0.92em;
  border-radius: 4px;
  background: #f3f4f6;
  padding: 0.08em 0.3em;
}
.ra-content >>> pre code {
  background: transparent;
  padding: 0;
}
.ra-action-btn {
  width: 88px !important;
  min-width: 88px !important;
  height: 30px !important;
  line-height: 30px !important;
  border-radius: 8px !important;
  font-size: 12px !important;
  padding: 0 !important;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: 10px;
  align-items: end;
}
.ra-input-actions {
  display: grid;
  grid-template-columns: 88px 88px;
  grid-template-rows: 30px 30px;
  grid-template-areas:
    "spacer download"
    "deep send";
  gap: 8px;
  align-items: stretch;
}
.ra-input-actions > * {
  justify-self: stretch;
}
.ra-deep-thinking-toggle {
  display: block;
  margin-bottom: 0;
  white-space: nowrap;
}
.ra-actions-spacer {
  grid-area: spacer;
}
.ra-deep-slot {
  grid-area: deep;
  width: 88px;
}
.ra-download-btn {
  grid-area: download;
  margin-left: 0 !important;
}
.ra-send-btn {
  grid-area: send;
  margin-left: 0 !important;
}
.ra-deep-thinking-toggle >>> .el-checkbox__input {
  display: none;
}
.ra-deep-slot >>> .el-tooltip {
  display: block;
  width: 100%;
}
.ra-input-actions >>> .el-button + .el-button {
  margin-left: 0 !important;
}
.ra-deep-thinking-toggle >>> .el-checkbox__label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 88px;
  min-width: 88px;
  height: 30px;
  padding: 0;
  margin-left: 0 !important;
  border: 1px solid #b3d8ff;
  border-radius: 8px;
  background: #409eff;
  color: #fff;
  font-size: 12px;
  line-height: 30px;
  box-sizing: border-box;
  transition: all 0.2s ease;
}
.ra-deep-thinking-toggle.is-checked >>> .el-checkbox__label,
.ra-deep-thinking-toggle >>> .el-checkbox__input.is-checked + .el-checkbox__label {
  border-color: #409eff;
  background: #409eff;
  color: #fff;
  font-weight: 500;
}
.ra-deep-thinking-toggle >>> .el-checkbox__input + .el-checkbox__label {
  opacity: 0.82;
}
.ra-deep-thinking-toggle >>> .el-checkbox__input.is-checked + .el-checkbox__label {
  opacity: 1;
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
.ra-step-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
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
.ra-board-panel {
  margin-bottom: 0;
}
.ra-board-content {
  padding: 10px;
}

/* ══ 工作区文件面板 ═══════════════════════════════════════════ */
.ws-panel {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 14px;
  overflow: hidden;
}
.ws-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  background: #f5f7fa;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  user-select: none;
}
.ws-panel-head:hover {
  background: #ecf5ff;
}
.ws-panel-head i {
  color: #e6a23c;
  margin-right: 4px;
}
.ws-head-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}
.ws-toggle-icon {
  font-size: 12px;
  color: #909399;
}

/* 面包屑 */
.ws-breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  padding: 5px 10px;
  font-size: 11px;
  background: #fafafa;
  border-bottom: 1px solid #ebeef5;
  gap: 2px;
  min-height: 28px;
}
.ws-crumb {
  color: #909399;
  white-space: nowrap;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ws-crumb-link {
  color: #409eff;
  cursor: pointer;
}
.ws-crumb-link:hover {
  text-decoration: underline;
}
.ws-crumb-cur {
  color: #303133;
  font-weight: 500;
}
.ws-crumb-sep {
  color: #c0c4cc;
  padding: 0 1px;
}

/* 文件列表 */
.ws-file-list {
  max-height: 260px;
  overflow-y: auto;
  padding: 4px 0;
}
.ws-error {
  padding: 8px 10px;
  font-size: 12px;
  color: #f56c6c;
}
.ws-empty {
  padding: 14px 10px;
  font-size: 12px;
  color: #c0c4cc;
  text-align: center;
}
.ws-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  font-size: 12px;
  border-bottom: 1px solid #f5f5f5;
  min-width: 0;
}
.ws-item:last-child {
  border-bottom: none;
}
.ws-item:hover {
  background: #f5f7fa;
}
.ws-item-dir .ws-item-left {
  cursor: pointer;
  color: #409eff;
}
.ws-item-dir .ws-item-left:hover .ws-item-name {
  text-decoration: underline;
}
.ws-item-left {
  display: flex;
  align-items: center;
  min-width: 0;
  flex: 1;
  gap: 5px;
}
.ws-item-icon {
  font-size: 14px;
  flex-shrink: 0;
  color: #909399;
}
.ws-item-dir .ws-item-icon {
  color: #e6a23c;
}
.ws-item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #303133;
}
.ws-item-right {
  display: flex;
  align-items: center;
  gap: 0;
  flex-shrink: 0;
  margin-left: 4px;
}
.ws-size {
  font-size: 11px;
  color: #c0c4cc;
  margin-right: 2px;
  white-space: nowrap;
}
.ws-del-btn {
  color: #f56c6c !important;
}
.ws-del-btn:hover {
  color: #dd0000 !important;
}

/* 底部操作栏 */
.ws-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-top: 1px solid #ebeef5;
  background: #fafafa;
}
.ws-upload-btn {
  display: inline-block;
}
</style>
