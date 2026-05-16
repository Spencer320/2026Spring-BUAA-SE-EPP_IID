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

        <footer class="ra-input-bar">
          <el-input
            v-model="draft"
            type="textarea"
            :rows="2"
            placeholder="输入指令…可对话、可让我做文件操作、也可勾选『深度思考』触发深度调研"
            :disabled="inputLocked"
            @keydown.enter.native.prevent="send"
          />
          <div class="ra-input-options">
            <el-tooltip
              effect="dark"
              placement="top"
              content="开启后允许编排器拆解出『research』子任务，触发完整的 6 阶段联网调研，响应较慢但更深入；关闭时仅做对话回答与工作区文件操作。"
            >
              <el-checkbox v-model="enableDeepThinking" class="ra-image-switch">深度思考</el-checkbox>
            </el-tooltip>
            <el-checkbox v-model="enableImage" class="ra-image-switch">启用图文输出</el-checkbox>
          </div>
          <el-button type="primary" :disabled="inputLocked || !draft.trim()" @click="send">发送</el-button>
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
                :loading="wsLoading" :disabled="wsLoading" title="刷新"
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
                    :disabled="!!wsDeletingPath"
                    @click="wsDownload(item)"
                  />
                  <el-button
                    type="text" icon="el-icon-delete" size="mini"
                    class="ws-del-btn" title="删除"
                    :loading="wsDeletingPath === item.rel_path"
                    :disabled="!!wsDeletingPath"
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
                :disabled="wsUploading || wsLoading"
                class="ws-upload-btn"
              >
                <el-button size="mini" icon="el-icon-upload2" :loading="wsUploading" :disabled="wsUploading || wsLoading">上传文件</el-button>
              </el-upload>
              <el-button size="mini" icon="el-icon-folder-add" :disabled="wsLoading || wsMakingDir" @click="wsMkdirDialogOpen">新建文件夹</el-button>
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
            <el-button :disabled="wsMakingDir" @click="wsMkdirDialog = false">取消</el-button>
            <el-button type="primary" :loading="wsMakingDir" :disabled="!wsMkdirName.trim()" @click="wsMkdir">创建</el-button>
          </span>
        </el-dialog>
        <!-- ══════════════════════════════════════════════════ -->

        <h3>执行看板</h3>
        <div class="ra-current-card">
          <div class="ra-current-head">接下来要去哪里呢</div>
          <p><strong>阶段：</strong>{{ currentStatus.phaseLabel }}</p>
          <p><strong>子任务：</strong>{{ currentStatus.subtaskTitle }}</p>
          <p><strong>轮次：</strong>{{ currentStatus.roundLabel }}</p>
          <p><strong>最近动作：</strong>{{ currentStatus.recentAction }}</p>
        </div>

        <div class="ra-side-section">
          <div class="ra-side-section-head">
            <strong>工具活动</strong>
            <el-button
              v-if="shouldCollapseToolEvents"
              type="text"
              size="mini"
              class="ra-step-expand"
              @click="historyExpanded = !historyExpanded"
            >
              {{ historyExpanded ? '收起旧活动' : `展开全部（${toolTimelineItems.length}）` }}
            </el-button>
          </div>
          <ul v-if="displayedToolEvents.length" class="tool-timeline">
            <li v-for="event in displayedToolEvents" :key="event.id" class="tool-event" :class="'is-' + event.status">
              <div class="tool-event-icon">
                <i :class="event.icon"></i>
              </div>
              <div class="tool-event-body">
                <div class="tool-event-top">
                  <span class="tool-event-title">{{ event.title }}</span>
                  <el-tag size="mini" :type="event.statusTagType">{{ event.statusLabel }}</el-tag>
                </div>
                <div class="tool-event-meta">
                  <span>{{ event.toolLabel }}</span>
                  <span>{{ event.phaseLabel }}</span>
                  <span v-if="event.action">{{ actionLabel(event.action) }}</span>
                  <span v-if="event.riskLevel" :class="'risk-' + event.riskLevel">{{ riskLabel(event.riskLevel) }}</span>
                </div>
                <span v-if="event.ts" class="ra-ts">{{ event.ts }}</span>
                <div class="ra-detail">
                  <p v-for="(line, lineIdx) in getEventDisplayLines(event)" :key="`${event.id}-${lineIdx}`">
                    {{ line }}
                  </p>
                  <el-button
                    v-if="eventHasMoreLines(event)"
                    type="text"
                    size="mini"
                    class="ra-step-expand"
                    @click="toggleStepExpand(event.id)"
                  >
                    {{ stepExpanded[event.id] ? '收起' : '展开更多' }}
                  </el-button>
                </div>
              </div>
            </li>
          </ul>
          <p v-else class="ra-muted">尚无工具活动，发送指令后可见</p>
        </div>

        <div class="ra-side-section">
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
          <p v-else class="ra-muted">暂无方案信息</p>
          <div v-if="deciderDecision.decision_reason" class="ra-decision-meta">
            <p><strong>复杂度：</strong>{{ deciderDecision.complexity || 'unknown' }}</p>
            <p><strong>选型理由：</strong>{{ deciderDecision.decision_reason }}</p>
            <p><strong>合并说明：</strong>{{ deciderDecision.merge_attempt_note || '无' }}</p>
          </div>
        </div>

        <div class="ra-side-section">
          <strong>子任务进度</strong>
          <ul v-if="subtaskProgressList.length" class="ra-subtask-list">
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
          <p v-else class="ra-muted">暂无子任务信息</p>
        </div>

        <div class="ra-side-section">
          <strong>反思结论</strong>
          <ul v-if="reflectorConclusions.length" class="ra-subtask-list">
            <li v-for="(item, idx) in reflectorConclusions.slice(-6)" :key="`${item.subtask_id || 'unknown'}-${idx}`" class="ra-subtask-item">
              <div class="ra-subtask-title">{{ item.subtask_title || item.subtask_id || '未命名子任务' }}</div>
              <p class="ra-muted-line">轮次：{{ item.round || '-' }} · 继续优化：{{ item.needs_optimization === 'yes' ? '是' : '否' }}</p>
              <p class="ra-muted-line">原因：{{ item.reason || '无' }}</p>
            </li>
          </ul>
          <p v-else class="ra-muted">暂无反思结论</p>
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
const TOOL_META = {
  web_search: { label: '联网检索', icon: 'el-icon-search' },
  tool_router: { label: '工具路由', icon: 'el-icon-share' },
  workspace: { label: '工作区文件', icon: 'el-icon-folder-opened' },
  local_file: { label: '本地文件', icon: 'el-icon-document' },
  local_command: { label: '本地命令', icon: 'el-icon-monitor' },
  llm: { label: '模型推理', icon: 'el-icon-cpu' },
  orchestrator: { label: '编排器', icon: 'el-icon-s-operation' }
}
const TOOL_ACTION_LABELS = {
  list_files: '列出文件',
  file_info: '查看信息',
  read_text: '读取文本',
  write_text: '写入文本',
  append_text: '追加文本',
  mkdir: '新建目录',
  delete_path: '删除路径',
  copy_path: '复制路径',
  move_path: '移动路径',
  archive_zip: '压缩归档',
  extract_zip: '解压归档',
  find_files: '查找文件',
  download_url: '下载资源'
}

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
      enableImage: false,
      enableDeepThinking: false,
      pollTimer: null,
      stepExpanded: {},
      historyExpanded: false,
      collapseAfterSteps: 12,
      pollFailureCount: 0,
      pollInFlight: false,
      autoFollowMessages: true,
      showScrollToBottom: false,
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
      wsDeletingPath: '',
      wsMakingDir: false,
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
    runtimeConfig () {
      const cfg = this.taskResultPayload.runtime_config
      return cfg && typeof cfg === 'object' ? cfg : {}
    },
    toolTimelineItems () {
      const events = []
      const list = Array.isArray(this.steps) ? this.steps : []
      list.forEach((step, idx) => {
        events.push(this.normalizeStepEvent(step, idx))
      })
      if (this.interventionVisible) {
        events.push(this.normalizePendingActionEvent())
      }
      return events
    },
    shouldCollapseToolEvents () {
      return (this.toolTimelineItems || []).length > this.collapseAfterSteps
    },
    displayedToolEvents () {
      const list = Array.isArray(this.toolTimelineItems) ? this.toolTimelineItems : []
      if (!this.shouldCollapseToolEvents || this.historyExpanded) return list
      return list.slice(-this.collapseAfterSteps)
    },
    interventionDetailLines () {
      if (!this.intervention || typeof this.intervention !== 'object') return []
      const lines = []
      if (this.intervention.type) lines.push(`类型：${this.intervention.type}`)
      if (this.intervention.conflict_target) lines.push(`冲突目标：${this.intervention.conflict_target}`)
      const args = this.intervention.args
      if (args && typeof args === 'object') {
        Object.keys(args).slice(0, 6).forEach((key) => {
          lines.push(`${key}：${this.formatInlineValue(args[key])}`)
        })
      }
      return lines
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
      if (!this.shouldCollapseToolEvents) this.historyExpanded = false
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
    getEventDisplayLines (event) {
      const lines = Array.isArray(event.detailLines) ? event.detailLines : []
      if (this.stepExpanded[event.id]) return lines
      return lines.slice(0, 4)
    },
    eventHasMoreLines (event) {
      return Array.isArray(event.detailLines) && event.detailLines.length > 4
    },
    normalizeStepEvent (step, idx) {
      const safeStep = step && typeof step === 'object' ? step : {}
      const lines = this.extractStepLines(safeStep)
      const toolType = this.inferStepTool(safeStep, lines)
      const rawStatus = this.extractDetailField(lines, ['执行状态', '工具状态', '状态'])
      const status = this.normalizeToolStatus(rawStatus || (safeStep.phase === 'pending_action' ? 'pending_action' : 'succeeded'))
      const action = this.extractDetailField(lines, ['动作'])
      const stepIndex = this.parseStepIndex(lines)
      const riskLevel = this.normalizeRiskLevel(this.extractDetailField(lines, ['风险等级', '风险']))
      const detailLines = lines.slice()
      if (toolType === 'workspace') {
        this.runtimeWorkspaceLines(action, stepIndex).forEach((line) => {
          if (detailLines.indexOf(line) === -1) detailLines.push(line)
        })
      }
      return {
        id: `step-${safeStep.seq || idx}`,
        seq: safeStep.seq || idx,
        ts: safeStep.ts || '',
        title: safeStep.title || this.toolLabel(toolType),
        phase: safeStep.phase || '',
        phaseLabel: this.phaseLabel(safeStep.phase || ''),
        toolType,
        toolLabel: this.toolLabel(toolType),
        icon: this.toolIcon(toolType),
        action,
        riskLevel,
        status,
        statusLabel: this.statusLabel(status),
        statusTagType: this.statusTagType(status),
        detailLines
      }
    },
    normalizePendingActionEvent () {
      const item = this.intervention && typeof this.intervention === 'object' ? this.intervention : {}
      const toolType = this.normalizeToolType(item.tool || 'orchestrator')
      const detailLines = [
        item.summary || item.message || '该任务来自旧版人工确认流程，当前版本不再支持继续确认。',
        item.risk_hint || '',
        ...this.interventionDetailLines
      ].filter(Boolean)
      return {
        id: `pending-${this.taskId || 'task'}-${item.tool || 'tool'}-${item.action || 'action'}`,
        seq: Number.MAX_SAFE_INTEGER,
        ts: '',
        title: '旧确认流程已停用',
        phase: 'pending_action',
        phaseLabel: this.phaseLabel('pending_action'),
        toolType,
        toolLabel: this.toolLabel(toolType),
        icon: this.toolIcon(toolType),
        action: item.action || '',
        riskLevel: this.normalizeRiskLevel(item.risk_level),
        status: 'pending_action',
        statusLabel: this.statusLabel('pending_action'),
        statusTagType: this.statusTagType('pending_action'),
        detailLines
      }
    },
    inferStepTool (step, lines) {
      const phase = String(step && step.phase ? step.phase : '').toLowerCase()
      const title = String(step && step.title ? step.title : '')
      const detail = lines.join('\n')
      const text = `${title}\n${detail}`.toLowerCase()
      if (text.indexOf('工作区文件工具') !== -1 || text.indexOf('workspace') !== -1 || phase === 'workspace') return 'workspace'
      if (text.indexOf('本地命令工具') !== -1 || text.indexOf('local_command') !== -1) return 'local_command'
      if (text.indexOf('本地文件工具') !== -1 || text.indexOf('local_file') !== -1) return 'local_file'
      if (text.indexOf('联网检索') !== -1 || text.indexOf('工具检索') !== -1 || text.indexOf('web_search') !== -1) return 'web_search'
      if (phase === 'search') return 'web_search'
      if (['plan', 'decide', 'read', 'reflect', 'write', 'workspace_content'].indexOf(phase) !== -1) return 'llm'
      if (phase === 'route') return 'tool_router'
      return 'orchestrator'
    },
    normalizeToolType (raw) {
      const key = String(raw || '').trim().toLowerCase()
      if (key === 'search') return 'web_search'
      if (key === 'local-command') return 'local_command'
      if (key === 'local-file') return 'local_file'
      return key || 'orchestrator'
    },
    normalizeToolStatus (raw) {
      const value = String(raw || '').trim().toLowerCase()
      if (!value) return 'running'
      if (['ok', 'success', 'succeeded', 'completed', 'done'].indexOf(value) !== -1) return 'succeeded'
      if (['pending', 'pending_action', 'waiting', 'confirm'].indexOf(value) !== -1) return 'pending_action'
      if (['failed', 'error', 'exception', 'blocked', 'cancelled', 'aborted'].indexOf(value) !== -1) return 'failed'
      if (['running', 'executing', 'in_progress'].indexOf(value) !== -1) return 'running'
      return value
    },
    normalizeRiskLevel (raw) {
      const value = String(raw || '').trim().toLowerCase()
      return ['low', 'medium', 'high'].indexOf(value) !== -1 ? value : ''
    },
    extractDetailField (lines, labels) {
      const list = Array.isArray(lines) ? lines : []
      for (let i = 0; i < list.length; i += 1) {
        for (let j = 0; j < labels.length; j += 1) {
          const prefix = `${labels[j]}：`
          if (list[i].indexOf(prefix) === 0) return list[i].slice(prefix.length).trim()
        }
      }
      return ''
    },
    parseStepIndex (lines) {
      const raw = this.extractDetailField(lines, ['步骤序号'])
      const num = Number.parseInt(raw, 10)
      return Number.isFinite(num) ? num : null
    },
    runtimeWorkspaceLines (action, stepIndex) {
      const cfg = this.runtimeConfig || {}
      const pools = []
      const resultKeys = ['workspace_plan_results', 'smart_workspace_results', 'lite_workspace_results']
      resultKeys.forEach((key) => {
        const list = cfg[key]
        if (Array.isArray(list)) pools.push(...list)
      })
      if (!pools.length) return []
      const actionKey = String(action || '').trim()
      const match = pools.find((item) => {
        const itemAction = String(item && item.action ? item.action : '').trim()
        const itemIndex = Number(item && item.step_index)
        const indexMatched = stepIndex === null || !Number.isFinite(itemIndex) || itemIndex === stepIndex - 1
        return indexMatched && (!actionKey || !itemAction || itemAction === actionKey)
      })
      if (!match || !match.output || typeof match.output !== 'object') return []
      return this.workspaceOutputLines(match.output)
    },
    workspaceOutputLines (output) {
      const lines = []
      if (output.path) lines.push(`结果路径：${output.path}`)
      if (output.rel_path) lines.push(`结果文件：${output.rel_path}`)
      if (output.download_url) lines.push(`下载链接：${output.download_url}`)
      if (output.item && typeof output.item === 'object') {
        const item = output.item
        if (item.rel_path || item.name) lines.push(`结果项：${item.rel_path || item.name}`)
        if (item.type) lines.push(`类型：${item.type}`)
      }
      if (Array.isArray(output.items)) {
        lines.push(`结果数量：${output.items.length}`)
        output.items.slice(0, 3).forEach((item) => {
          if (item && (item.rel_path || item.name)) lines.push(`- ${item.rel_path || item.name}`)
        })
      }
      return lines
    },
    toolLabel (toolType) {
      const key = this.normalizeToolType(toolType)
      return (TOOL_META[key] && TOOL_META[key].label) || key || '工具'
    },
    toolIcon (toolType) {
      const key = this.normalizeToolType(toolType)
      return (TOOL_META[key] && TOOL_META[key].icon) || 'el-icon-s-operation'
    },
    actionLabel (action) {
      const key = String(action || '').trim()
      return TOOL_ACTION_LABELS[key] || key || '默认动作'
    },
    statusLabel (status) {
      const map = {
        running: '执行中',
        succeeded: '成功',
        failed: '失败',
        pending_action: '待确认'
      }
      return map[status] || status || '未知'
    },
    statusTagType (status) {
      const map = {
        succeeded: 'success',
        failed: 'danger',
        pending_action: 'warning',
        running: 'info'
      }
      return map[status] || 'info'
    },
    riskLabel (risk) {
      const map = {
        low: '低风险',
        medium: '中风险',
        high: '高风险'
      }
      return map[this.normalizeRiskLevel(risk)] || '风险未标注'
    },
    riskTagType (risk) {
      const map = {
        low: 'success',
        medium: 'warning',
        high: 'danger'
      }
      return map[this.normalizeRiskLevel(risk)] || 'info'
    },
    formatInlineValue (value) {
      if (value === null || value === undefined) return ''
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
      }
      try {
        const text = JSON.stringify(value)
        return text.length > 120 ? `${text.slice(0, 117)}...` : text
      } catch (e) {
        return String(value)
      }
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
          enable_image: this.enableImage,
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
    // ══ 工作区方法 ════════════════════════════════════════════

    normalizeWorkspacePath (path) {
      return String(path || '')
        .trim()
        .replace(/\\/g, '/')
        .split('/')
        .map(part => part.trim())
        .filter(Boolean)
        .join('/')
    },

    validateWorkspacePath (path, options = {}) {
      const label = options.label || '路径'
      const allowEmpty = Boolean(options.allowEmpty)
      const raw = String(path || '').trim()
      if (!raw && allowEmpty) return { ok: true, path: '' }
      if (!raw) return { ok: false, message: `${label}不能为空` }
      if (/^[a-zA-Z]:/.test(raw) || raw.indexOf('/') === 0 || raw.indexOf('\\') === 0) {
        return { ok: false, message: `${label}必须是工作区内的相对路径` }
      }
      const parts = raw.replace(/\\/g, '/').split('/').map(part => part.trim()).filter(Boolean)
      if (!parts.length) return { ok: false, message: `${label}不能为空` }
      if (parts.some(part => part === '.' || part === '..')) {
        return { ok: false, message: `${label}不能包含 . 或 ..` }
      }
      return { ok: true, path: parts.join('/') }
    },

    wsJoinPath (base, child) {
      return [this.normalizeWorkspacePath(base), this.normalizeWorkspacePath(child)]
        .filter(Boolean)
        .join('/')
    },

    /** 加载当前路径的目录内容 */
    async wsRefresh () {
      this.wsLoading = true
      this.wsError = ''
      try {
        const checked = this.validateWorkspacePath(this.wsPath, { allowEmpty: true, label: '当前目录' })
        if (!checked.ok) throw new Error(checked.message)
        this.wsPath = checked.path
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
      const checked = this.validateWorkspacePath(relPath, { allowEmpty: true, label: '目录路径' })
      if (!checked.ok) {
        this.$message.warning(checked.message)
        return
      }
      this.wsPath = checked.path
      await this.wsRefresh()
    },

    /** 下载文件到用户本机 */
    async wsDownload (item) {
      try {
        const checked = this.validateWorkspacePath(item && item.rel_path, { label: '文件路径' })
        if (!checked.ok) throw new Error(checked.message)
        await downloadWorkspaceFile(checked.path, item.name)
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
      const checked = this.validateWorkspacePath(item && item.rel_path, { label: '删除路径' })
      if (!checked.ok) {
        this.$message.warning(checked.message)
        return
      }
      this.wsDeletingPath = item.rel_path
      try {
        await deleteWorkspacePath(checked.path)
        this.$message.success(`已删除 ${item.name}`)
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('删除失败：' + ((e && e.message) || '未知错误'))
      } finally {
        this.wsDeletingPath = ''
      }
    },

    /** el-upload 自定义上传处理 */
    async wsUploadHandler ({ file }) {
      this.wsUploadActiveCount += 1
      this.wsUploading = true
      try {
        const checked = this.validateWorkspacePath(this.wsPath, { allowEmpty: true, label: '上传目录' })
        if (!checked.ok) throw new Error(checked.message)
        this.wsPath = checked.path
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
      const checked = this.validateWorkspacePath(this.wsMkdirName, { label: '文件夹名称' })
      if (!checked.ok) {
        this.$message.warning(checked.message)
        return
      }
      const name = checked.path
      const fullPath = this.wsJoinPath(this.wsPath, name)
      this.wsMakingDir = true
      try {
        await mkdirWorkspace(fullPath)
        this.$message.success(`目录「${name}」创建成功`)
        this.wsMkdirDialog = false
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('创建失败：' + ((e && e.message) || '未知错误'))
      } finally {
        this.wsMakingDir = false
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
.ra-current-head {
  font-size: 12px;
  color: #409eff;
  margin-bottom: 6px;
}
.ra-current-card p {
  margin: 6px 0;
  font-size: 12px;
  color: #303133;
}
.tool-event-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  color: #909399;
  font-size: 11px;
  line-height: 1.4;
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
.ra-input-options {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}
.ra-image-switch {
  margin-bottom: 0;
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
.tool-timeline {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
}
.tool-event {
  display: flex;
  gap: 8px;
  padding: 9px 0;
  border-bottom: 1px solid #ebeef5;
}
.tool-event:last-child {
  border-bottom: none;
}
.tool-event-icon {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f4f4f5;
  color: #606266;
}
.tool-event.is-succeeded .tool-event-icon {
  background: #f0f9eb;
  color: #67c23a;
}
.tool-event.is-failed .tool-event-icon {
  background: #fef0f0;
  color: #f56c6c;
}
.tool-event.is-pending_action .tool-event-icon {
  background: #fdf6ec;
  color: #e6a23c;
}
.tool-event-body {
  min-width: 0;
  flex: 1;
}
.tool-event-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 3px;
}
.tool-event-title {
  min-width: 0;
  color: #303133;
  font-size: 13px;
  line-height: 1.35;
  font-weight: 600;
  word-break: break-word;
}
.risk-low {
  color: #67c23a;
}
.risk-medium {
  color: #e6a23c;
}
.risk-high {
  color: #f56c6c;
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

@media (max-width: 1180px) {
  .ra-layout {
    flex-wrap: wrap;
    height: auto;
  }
  .ra-main {
    min-height: 560px;
  }
  .ra-sidebar-right {
    width: 100%;
    height: auto;
    max-height: none;
  }
}

@media (max-width: 900px) {
  .ra-session {
    padding: 76px 10px 12px;
  }
  .ra-layout {
    flex-direction: column;
  }
  .ra-sidebar-left {
    width: 100%;
    height: auto;
    max-height: 240px;
  }
  .ra-sidebar-left.is-collapsed {
    width: 100%;
    height: 44px;
  }
  .ra-main {
    min-height: 520px;
  }
  .ra-input-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .ra-input-options {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .ra-bubble {
    max-width: 92%;
  }
  .ws-toolbar {
    flex-wrap: wrap;
  }
}
</style>
