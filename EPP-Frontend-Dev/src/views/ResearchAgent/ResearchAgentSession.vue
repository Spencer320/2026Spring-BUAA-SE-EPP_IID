<template>
  <div class="ra-shell">
    <div class="ra-bg" aria-hidden="true" />
    <div class="ra-inner">
      <header class="ra-toolbar ra-surface">
        <div class="ra-toolbar-main">
          <div class="ra-toolbar-titles">
            <h1 class="ra-h1">科研助手</h1>
            <p class="ra-toolbar-meta">
              <span class="ra-ellipsis">{{ sessionTitle || '未命名会话' }}</span>
              <el-button
                v-if="currentSessionId"
                type="text"
                icon="el-icon-edit"
                class="ra-icon-text"
                @click="onRenameTitle"
              />
            </p>
          </div>
          <div v-if="currentSessionId || taskId" class="ra-toolbar-chips">
            <el-tag v-if="taskOrchestratorLabel" size="small" effect="plain" type="info">{{ taskOrchestratorLabel }}</el-tag>
            <el-tag size="small" effect="dark" :type="taskStatusTagType">{{ taskStatusLabel }}</el-tag>
          </div>
          <el-progress
            v-if="taskStatus && isTaskActive"
            :percentage="taskProgress"
            :stroke-width="6"
            :status="taskStatus === 'failed' ? 'exception' : (taskStatus === 'completed' ? 'success' : undefined)"
            class="ra-toolbar-progress"
          />
        </div>
        <div class="ra-toolbar-actions">
          <el-tooltip content="刷新会话与列表" placement="bottom">
            <el-button circle size="small" icon="el-icon-refresh" :loading="reloadBusy" @click="onManualRefresh" />
          </el-tooltip>
          <el-tooltip :content="leftCollapsed ? '展开会话列表' : '收起会话列表'" placement="bottom">
            <el-button circle size="small" :icon="leftCollapsed ? 'el-icon-s-unfold' : 'el-icon-s-fold'" @click="leftCollapsed = !leftCollapsed" />
          </el-tooltip>
          <el-tooltip :content="rightCollapsed ? '展开侧栏' : '收起侧栏'" placement="bottom">
            <el-button circle size="small" :icon="rightCollapsed ? 'el-icon-d-arrow-left' : 'el-icon-d-arrow-right'" @click="rightCollapsed = !rightCollapsed" />
          </el-tooltip>
          <el-button size="small" plain @click="goManage">会话管理</el-button>
        </div>
      </header>

      <div class="ra-grid">
        <aside :class="['ra-col-left ra-surface', leftCollapsed && 'is-collapsed']">
          <div class="ra-side-head">
            <span v-show="!leftCollapsed" class="ra-side-head-title">历史会话</span>
            <el-tooltip content="新建会话" placement="right">
              <el-button type="primary" size="mini" icon="el-icon-plus" circle @click="createAndOpenSession" />
            </el-tooltip>
          </div>
          <div v-show="!leftCollapsed" class="ra-side-scroll">
            <div
              v-for="s in displayedSessionItems"
              :key="s.session_id"
              :class="['ra-side-card', s.session_id === currentSessionId ? 'is-active' : '']"
              @click="openSession(s.session_id)"
            >
              <div class="ra-side-card-title">{{ s.title || '新会话' }}</div>
              <div class="ra-side-card-sub">{{ s.updated_at }}</div>
            </div>
            <p v-if="sessionItems.length > maxSessionDisplay" class="ra-muted-tip">仅展示最近 {{ maxSessionDisplay }} 条</p>
            <p v-if="!sessionItems.length" class="ra-muted-tip">暂无会话，点击上方 + 创建</p>
          </div>
        </aside>

        <main class="ra-col-center ra-surface">
          <div v-if="!hasRouteSession" class="ra-welcome">
            <div class="ra-welcome-card">
              <h2>开始你的科研对话</h2>
              <p class="ra-welcome-desc">
                创建会话后，可在右侧<strong>展示区</strong>整理文献与工作区文件，勾选文献并填写研究问题后启动<strong>深度研究</strong>；在<strong>工作区</strong>多选路径，一键附加到本轮普通对话上下文。
              </p>
              <el-button type="primary" size="medium" icon="el-icon-chat-dot-round" :loading="creatingSession" @click="startBlankSession">
                创建新会话
              </el-button>
              <p class="ra-muted-tip">工作区文件浏览无需会话即可使用右侧「工作区」标签。</p>
            </div>
          </div>

          <template v-else>
            <div class="ra-messages" ref="msgBox" @scroll.passive="onMsgScroll">
              <div
                v-for="(m, idx) in conversationMessages"
                :key="idx"
                :class="['ra-msg-row', m.role === 'user' ? 'is-user' : 'is-assistant']"
              >
                <div :class="['ra-msg-bubble', m.role === 'user' ? 'is-user' : 'is-assistant']">
                  <div class="ra-msg-head">
                    <span class="ra-msg-role">{{ m.role === 'user' ? '我' : '助手' }}</span>
                    <el-button
                      v-if="m.role === 'user'"
                      type="text"
                      size="mini"
                      icon="el-icon-document-copy"
                      @click="copyUserMessage(m.content)"
                    >复制</el-button>
                  </div>
                  <div v-if="userRefsFromMeta(m).length" class="ra-msg-refs">
                    <el-tag v-for="(r, ri) in userRefsFromMeta(m)" :key="ri" size="mini" type="info" effect="plain">{{ r.kind }} · {{ r.label || r.rel_path }}</el-tag>
                  </div>
                  <div v-if="!isReportMessage(m)" class="ra-md-inline" v-html="formatMsg(m.content)" />
                  <template v-else>
                    <p class="ra-report-lead">以下为深度 / 智能编排生成的研究报告：</p>
                    <div class="ra-report-card">
                      <div class="ra-report-card-hd">研究成果</div>
                      <div class="ra-md-inline" v-html="formatReport(extractReportMarkdown(m))" />
                    </div>
                  </template>
                </div>
              </div>
            </div>

            <el-button
              v-if="showScrollToBottom"
              type="primary"
              size="mini"
              round
              class="ra-scroll-fab"
              icon="el-icon-bottom"
              @click="scrollToBottomByUser"
            >回到底部</el-button>

            <div v-if="interventionVisible" class="ra-intervention ra-surface-2">
              <el-alert title="需要您确认（高风险操作）" type="warning" :closable="false" show-icon />
              <p class="ra-int-summary">{{ intervention.summary }}</p>
              <p v-if="intervention.risk_hint" class="ra-int-risk">{{ intervention.risk_hint }}</p>
              <div class="ra-int-actions">
                <el-button type="success" size="small" @click="onIntervention('approve')">允许执行</el-button>
                <el-button type="danger" size="small" plain @click="onIntervention('reject')">终止任务</el-button>
              </div>
              <el-input v-model="reviseDraft" type="textarea" :rows="2" placeholder="若修订继续，请填写说明" />
              <el-button type="primary" plain size="small" style="margin-top:8px" @click="onIntervention('revise')">提交修订并继续</el-button>
            </div>

            <footer class="ra-composer">
              <div v-if="pendingWorkspaceRefs.length" class="ra-ref-chips">
                <span class="ra-ref-chips-label">本轮上下文</span>
                <el-tag
                  v-for="(r, i) in pendingWorkspaceRefs"
                  :key="r.rel_path + '-' + i"
                  closable
                  size="small"
                  type="primary"
                  effect="plain"
                  @close="removePendingRef(i)"
                >{{ r.kind === 'dir' ? '目录' : '文件' }} · {{ r.label }}</el-tag>
              </div>
              <el-input
                v-model="draft"
                type="textarea"
                :rows="3"
                resize="none"
                placeholder="输入问题或指令；普通对话点「发送」。深度研究请在右侧展示区勾选文献后点击「启动深度研究」。"
                :disabled="inputLocked"
                @keydown.enter.native.ctrl.exact.prevent="send"
              />
              <div class="ra-composer-actions">
                <span class="ra-hint">Ctrl+Enter 发送</span>
                <div class="ra-composer-btns">
                  <el-button size="small" :disabled="!taskId || taskStatus !== 'completed'" @click="onDownloadReport">下载报告</el-button>
                  <el-button type="primary" size="small" :disabled="inputLocked || !draft.trim()" @click="send">发送</el-button>
                </div>
              </div>
            </footer>
          </template>
        </main>

        <aside :class="['ra-col-right ra-surface', rightCollapsed && 'is-collapsed']">
          <div v-if="rightCollapsed" class="ra-rail-collapsed">
            <el-tooltip content="展开侧栏" placement="left">
              <el-button type="text" icon="el-icon-d-arrow-left" @click="rightCollapsed = false" />
            </el-tooltip>
          </div>
          <el-tabs v-else v-model="rightTab" class="ra-tabs" stretch>
            <el-tab-pane label="论文展示区" name="shelf">
              <div class="ra-tab-body">
                <template v-if="!currentSessionId">
                  <el-empty description="创建并进入会话后可使用展示区" :image-size="72" />
                </template>
                <template v-else>
                  <p class="ra-pane-intro">检索结果与手动添加的文献会出现在此。勾选条目，在下方填写研究问题后启动<strong>深度研究</strong>（独立六阶段流水线）。</p>
                  <div v-loading="paperShelfLoading" class="ra-shelf-list">
                    <el-empty v-if="!paperShelfItems.length && !paperShelfLoading" description="展示区暂无条目" :image-size="64" />
                    <el-checkbox-group v-model="selectedPaperIdsForDeep" class="ra-shelf-group">
                      <div v-for="it in paperShelfItems" :key="it.id" class="ra-shelf-row">
                        <el-checkbox :label="it.id" class="ra-shelf-cb">&nbsp;</el-checkbox>
                        <div class="ra-shelf-main">
                          <div class="ra-shelf-title">
                            {{ it.title }}
                            <el-tag size="mini" effect="plain">{{ shelfTierLabel(it.context_tier) }}</el-tag>
                            <el-tag v-if="it.source_kind === 'workspace_file'" size="mini" type="success" effect="plain">工作区</el-tag>
                            <el-tag v-else size="mini" type="warning" effect="plain">外链</el-tag>
                          </div>
                          <div v-if="it.abstract" class="ra-shelf-abs">{{ truncate(it.abstract, 160) }}</div>
                          <div class="ra-shelf-actions">
                            <el-button v-if="it.primary_url || it.external_jump_url" type="text" size="mini" @click.stop="openExternal(it)">打开链接</el-button>
                            <el-button type="text" size="mini" class="ra-danger-text" @click.stop="onDeleteShelfItem(it)">移除</el-button>
                          </div>
                        </div>
                      </div>
                    </el-checkbox-group>
                  </div>
                  <div class="ra-deep-actions">
                    <p class="ra-muted-tip">提示词取自中间对话区下方输入框（当前 {{ (draft || '').length }} 字）。已选 {{ selectedPaperIdsForDeep.length }} 条文献。</p>
                    <el-button
                      type="primary"
                      size="small"
                      icon="el-icon-magic-stick"
                      :loading="deepStarting"
                      :disabled="inputLocked || !draft.trim() || !selectedPaperIdsForDeep.length"
                      @click="startDeepResearch"
                    >启动深度研究</el-button>
                    <p v-if="!selectedPaperIdsForDeep.length" class="ra-muted-tip">请至少勾选一条展示区文献后再启动。</p>
                  </div>
                </template>
              </div>
            </el-tab-pane>

            <el-tab-pane label="工作区" name="ws">
              <div class="ra-tab-body">
                <p class="ra-pane-intro">勾选文件或目录，加入<strong>本轮对话上下文</strong>（随下一条「发送」提交）；仅文件可「加入展示区」。</p>
                <div class="ra-ws-head">
                  <el-breadcrumb separator-class="el-icon-arrow-right">
                    <el-breadcrumb-item>
                      <a href="javascript:;" @click="wsNavigate('')">根目录</a>
                    </el-breadcrumb-item>
                    <el-breadcrumb-item v-for="(seg, i) in wsBreadcrumbs" :key="'bc-' + i">
                      <a v-if="i < wsBreadcrumbs.length - 1" href="javascript:;" @click="wsNavigate(wsBreadcrumbs.slice(0, i + 1).join('/'))">{{ seg }}</a>
                      <span v-else>{{ seg }}</span>
                    </el-breadcrumb-item>
                  </el-breadcrumb>
                  <el-button size="mini" icon="el-icon-refresh" :loading="wsLoading" circle @click="wsRefresh" />
                </div>
                <div class="ra-ws-toolbar">
                  <el-button size="mini" type="primary" plain :disabled="!wsSelectedList.length" @click="addWsSelectionToPendingContext">附加选中到本轮</el-button>
                  <el-button size="mini" :disabled="!canAddShelfFromWs" @click="addWsFilesToShelf">加入展示区</el-button>
                  <el-button size="mini" icon="el-icon-folder-add" @click="wsMkdirDialogOpen">新建文件夹</el-button>
                </div>
                <div class="ra-ws-list" v-loading="wsLoading">
                  <p v-if="wsError" class="ra-error">{{ wsError }}</p>
                  <el-empty v-else-if="!wsLoading && !wsItems.length" description="此目录为空" :image-size="56" />
                  <div
                    v-for="item in wsItems"
                    :key="item.rel_path"
                    :class="['ra-ws-row', item.type === 'directory' && 'is-dir']"
                  >
                    <el-checkbox class="ra-ws-cb" :value="!!wsSelectedKeys[item.rel_path]" @input="v => setWsSelected(item, v)" @click.native.stop />
                    <div class="ra-ws-main" @click="item.type === 'directory' ? wsNavigate(item.rel_path) : null">
                      <i :class="[item.type === 'directory' ? 'el-icon-folder' : wsFileIcon(item.name), 'ra-ws-ico']" />
                      <span class="ra-ws-name">{{ item.name }}</span>
                      <span v-if="item.type === 'file'" class="ra-ws-size">{{ wsFormatSize(item.size) }}</span>
                    </div>
                    <div class="ra-ws-ops">
                      <el-button v-if="item.type === 'file'" type="text" size="mini" icon="el-icon-download" @click.stop="wsDownload(item)" />
                      <el-button type="text" size="mini" icon="el-icon-delete" class="ra-danger-text" @click.stop="wsDeleteConfirm(item)" />
                    </div>
                  </div>
                </div>
                <div class="ra-ws-upload">
                  <el-upload action="" :http-request="wsUploadHandler" :show-file-list="false" multiple :disabled="wsUploading">
                    <el-button size="mini" icon="el-icon-upload2" :loading="wsUploading">上传到此目录</el-button>
                  </el-upload>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane label="执行看板" name="board" :disabled="!showExecutionBoard">
              <div class="ra-tab-body ra-board-wrap">
                <div class="ra-current-card">
                  <p><strong>阶段：</strong>{{ currentStatus.phaseLabel }}</p>
                  <p><strong>子任务：</strong>{{ currentStatus.subtaskTitle }}</p>
                  <p><strong>轮次：</strong>{{ currentStatus.roundLabel }}</p>
                  <p><strong>最近动作：</strong>{{ currentStatus.recentAction }}</p>
                </div>

                <div v-if="displayedHistorySteps.length" class="ra-board-section">
                  <div class="ra-board-section-hd">
                    <strong>执行历史</strong>
                    <el-button v-if="shouldCollapseHistory" type="text" size="mini" @click="historyExpanded = !historyExpanded">
                      {{ historyExpanded ? '收起' : `展开（${steps.length}）` }}
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
                        <el-button type="text" size="mini" @click="toggleStepExpand(s.seq)">{{ stepExpanded[s.seq] ? '收起' : '详情' }}</el-button>
                      </div>
                      <div v-if="stepExpanded[s.seq]" class="ra-detail">
                        <p v-for="(line, lineIdx) in getStepDisplayLines(s)" :key="`${s.seq}-${lineIdx}`">{{ line }}</p>
                      </div>
                    </li>
                  </ul>
                </div>

                <div v-if="hasPlannerContent" class="ra-board-section">
                  <strong>方案与决策</strong>
                  <div v-if="plannerAlternatives.length" class="ra-plan-list">
                    <div v-for="item in plannerAlternatives" :key="item.plan_id" class="ra-plan-item">
                      <div class="ra-plan-title">
                        {{ item.title || item.plan_id }}
                        <el-tag v-if="deciderDecision.selected_plan_id && deciderDecision.selected_plan_id === item.plan_id" size="mini" type="success">已选</el-tag>
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

                <div v-if="subtaskProgressList.length" class="ra-board-section">
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

                <div v-if="reflectorConclusions.length" class="ra-board-section">
                  <strong>反思结论</strong>
                  <ul class="ra-subtask-list">
                    <li v-for="(item, idx) in reflectorConclusions.slice(-6)" :key="`${item.subtask_id || 'x'}-${idx}`" class="ra-subtask-item">
                      <div class="ra-subtask-title">{{ item.subtask_title || item.subtask_id || '未命名' }}</div>
                      <p class="ra-muted-line">轮次：{{ item.round || '-' }} · 继续优化：{{ item.needs_optimization === 'yes' ? '是' : '否' }}</p>
                      <p class="ra-muted-line">原因：{{ item.reason || '无' }}</p>
                    </li>
                  </ul>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </aside>
      </div>
    </div>

    <el-dialog title="新建文件夹" :visible.sync="wsMkdirDialog" width="320px" append-to-body @open="wsMkdirName = ''">
      <el-input v-model="wsMkdirName" placeholder="支持多级，如 papers/2026" maxlength="120" show-word-limit @keyup.enter.native="wsMkdir" />
      <span slot="footer">
        <el-button @click="wsMkdirDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!wsMkdirName.trim()" @click="wsMkdir">创建</el-button>
      </span>
    </el-dialog>
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
  createSession,
  updateSessionTitle,
  downloadTaskReport,
  createDeepResearchTask,
  listPaperShelf,
  addPaperShelfFromWorkspace,
  deletePaperShelfItem
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
      leftCollapsed: false,
      rightCollapsed: false,
      rightTab: 'shelf',
      messages: [],
      steps: [],
      taskId: null,
      taskStatus: '',
      taskOrchestrator: '',
      intervention: null,
      resultBody: null,
      taskProgress: 0,
      draft: '',
      reviseDraft: '',
      pollTimer: null,
      stepExpanded: {},
      historyExpanded: false,
      collapseAfterSteps: 12,
      pollFailureCount: 0,
      pollInFlight: false,
      autoFollowMessages: true,
      showScrollToBottom: false,
      reloadBusy: false,
      creatingSession: false,
      deepStarting: false,
      paperShelfItems: [],
      paperShelfLoading: false,
      selectedPaperIdsForDeep: [],
      pendingWorkspaceRefs: [],
      wsPath: '',
      wsItems: [],
      wsLoading: false,
      wsError: '',
      wsUploading: false,
      wsUploadActiveCount: 0,
      wsMkdirDialog: false,
      wsMkdirName: '',
      wsSelectedKeys: {}
    }
  },
  computed: {
    hasRouteSession () {
      return Boolean(this.$route.params.sessionId)
    },
    taskStatusLabel () {
      if (!this.taskStatus) return '无进行中任务'
      const map = { pending: '排队中', running: '执行中', pending_action: '待确认', completed: '已完成', failed: '失败', cancelled: '已取消' }
      return map[this.taskStatus] || this.taskStatus
    },
    taskStatusTagType () {
      if (this.taskStatus === 'completed') return 'success'
      if (this.taskStatus === 'failed') return 'danger'
      if (this.taskStatus === 'pending_action') return 'warning'
      if (this.taskStatus === 'running' || this.taskStatus === 'pending') return ''
      return 'info'
    },
    taskOrchestratorLabel () {
      const o = (this.taskOrchestrator || '').trim()
      if (o === 'deep_research') return '深度研究'
      if (o === 'basic') return '智能编排'
      if (o === 'workspace') return '工作区子任务'
      return o
    },
    isTaskActive () {
      return this.isTaskActiveStatus(this.taskStatus)
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
        return { subtask_id: subtaskId, title: item && item.title ? item.title : '', goal: item && item.goal ? item.goal : '', state }
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
    wsBreadcrumbs () {
      if (!this.wsPath) return []
      return this.wsPath.split('/').filter(Boolean)
    },
    wsSelectedList () {
      return Object.keys(this.wsSelectedKeys || {}).filter(k => this.wsSelectedKeys[k])
    },
    canAddShelfFromWs () {
      if (!this.currentSessionId || !this.wsSelectedList.length) return false
      return this.wsSelectedList.some((rel) => {
        const it = this.wsItems.find(i => i.rel_path === rel)
        return it && it.type === 'file'
      })
    }
  },
  watch: {
    '$route.params.sessionId' () {
      this.bootstrap()
    },
    steps () {
      if (!this.shouldCollapseHistory) this.historyExpanded = false
    },
    currentSessionId (id) {
      if (id) this.loadPaperShelf()
      else {
        this.paperShelfItems = []
        this.selectedPaperIdsForDeep = []
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
    truncate (s, n) {
      const t = (s || '').trim()
      if (t.length <= n) return t
      return t.slice(0, n) + '…'
    },
    shelfTierLabel (tier) {
      const m = {
        abstract_only: '摘要',
        link_only: '链接',
        full_text_available: '全文',
        workspace_opaque: '工作区'
      }
      return m[tier] || tier || ''
    },
    userRefsFromMeta (msg) {
      if (!msg || msg.role !== 'user') return []
      const meta = msg.metadata
      if (!meta || typeof meta !== 'object') return []
      const refs = meta.workspace_refs
      return Array.isArray(refs) ? refs : []
    },
    setWsSelected (item, checked) {
      this.$set(this.wsSelectedKeys, item.rel_path, Boolean(checked))
    },
    addWsSelectionToPendingContext () {
      const next = [...this.pendingWorkspaceRefs]
      const byPath = new Set(next.map(r => r.rel_path))
      for (const rel of this.wsSelectedList) {
        const item = this.wsItems.find(i => i.rel_path === rel)
        if (!item) continue
        const kind = item.type === 'directory' ? 'dir' : 'file'
        if (byPath.has(rel)) continue
        byPath.add(rel)
        next.push({ kind, rel_path: rel, label: item.name || rel })
      }
      this.pendingWorkspaceRefs = next
      this.$message.success('已加入本轮上下文，发送消息时生效')
    },
    async addWsFilesToShelf () {
      if (!this.currentSessionId) {
        this.$message.warning('请先创建并进入会话')
        return
      }
      const files = this.wsSelectedList
        .map(rel => this.wsItems.find(i => i.rel_path === rel))
        .filter(it => it && it.type === 'file')
      if (!files.length) {
        this.$message.warning('请仅勾选文件加入展示区')
        return
      }
      let ok = 0
      for (const f of files) {
        try {
          await addPaperShelfFromWorkspace(this.currentSessionId, f.rel_path)
          ok += 1
        } catch (e) {
          this.$message.error(this.apiErrorMessage(e, '加入展示区失败'))
        }
      }
      if (ok) {
        this.$message.success(`已添加 ${ok} 个文件到展示区`)
        await this.loadPaperShelf()
      }
    },
    removePendingRef (index) {
      this.pendingWorkspaceRefs.splice(index, 1)
    },
    openExternal (it) {
      const u = it.external_jump_url || it.primary_url
      if (u) window.open(u, '_blank', 'noopener,noreferrer')
    },
    async loadPaperShelf () {
      if (!this.currentSessionId) return
      this.paperShelfLoading = true
      try {
        const res = await listPaperShelf(this.currentSessionId)
        this.paperShelfItems = res.data.items || []
      } catch (e) {
        this.paperShelfItems = []
        this.$message.error(this.apiErrorMessage(e, '加载展示区失败'))
      } finally {
        this.paperShelfLoading = false
      }
    },
    async onDeleteShelfItem (it) {
      if (!this.currentSessionId || !it.id) return
      try {
        await this.$confirm('从展示区移除此条目？', '确认', { type: 'warning' })
      } catch (e) {
        return
      }
      try {
        await deletePaperShelfItem(this.currentSessionId, it.id)
        this.selectedPaperIdsForDeep = this.selectedPaperIdsForDeep.filter(x => x !== it.id)
        await this.loadPaperShelf()
      } catch (e) {
        this.$message.error(this.apiErrorMessage(e, '删除失败'))
      }
    },
    async startDeepResearch () {
      const content = this.draft.trim()
      if (!this.currentSessionId) {
        this.$message.warning('请先进入会话')
        return
      }
      if (!content) {
        this.$message.warning('请先在主输入框填写研究问题')
        return
      }
      if (!this.selectedPaperIdsForDeep.length) {
        this.$message.warning('请勾选至少一条展示区文献')
        return
      }
      this.deepStarting = true
      try {
        const res = await createDeepResearchTask({
          session_id: this.currentSessionId,
          content,
          selected_papers: [...this.selectedPaperIdsForDeep]
        })
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        this.taskOrchestrator = 'deep_research'
        this.taskProgress = 0
        this.draft = ''
        this.selectedPaperIdsForDeep = []
        await this.reload()
        await this.loadSessionList()
        await this.loadPaperShelf()
        this.syncPoll()
        this.rightTab = 'board'
      } catch (e) {
        this.$message.error(this.apiErrorMessage(e, '启动深度研究失败'))
      } finally {
        this.deepStarting = false
      }
    },
    async startBlankSession () {
      this.creatingSession = true
      try {
        const res = await createSession({ title: '新会话' })
        const sid = res.data.session_id
        this.$router.push({ path: `/research-agent/session/${sid}` })
      } catch (e) {
        this.$message.error(this.apiErrorMessage(e, '创建会话失败'))
      } finally {
        this.creatingSession = false
      }
    },
    async onManualRefresh () {
      this.reloadBusy = true
      try {
        await this.loadSessionList()
        if (this.currentSessionId) {
          await this.reload()
          await this.loadPaperShelf()
        }
        await this.wsRefresh()
      } finally {
        this.reloadBusy = false
      }
    },
    isTaskActiveStatus (status = this.taskStatus) {
      const s = String(status || '').trim()
      return s === 'pending' || s === 'running' || s === 'pending_action'
    },
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
        this.sessionTitle = ''
        this.messages = []
        this.steps = []
        this.taskId = null
        this.taskStatus = ''
        this.taskOrchestrator = ''
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
      await this.loadPaperShelf()
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
    parseStepMeta (step) {
      const lines = this.extractStepLines(step)
      let subtaskTitle = ''
      let roundLabel = ''
      lines.forEach((line) => {
        if (line.startsWith('子任务：')) subtaskTitle = line.replace('子任务：', '').trim()
        else if (line.startsWith('轮次：')) roundLabel = line.replace('轮次：', '').trim()
        else if (line.startsWith('当前轮次：')) roundLabel = line.replace('当前轮次：', '').trim()
      })
      return { subtaskTitle, roundLabel }
    },
    detectRunningSubtaskTitle () {
      if (!this.currentStep) return ''
      return this.parseStepMeta(this.currentStep).subtaskTitle || ''
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
        if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(text)
        else {
          const ta = document.createElement('textarea')
          ta.value = text
          ta.style.position = 'fixed'
          ta.style.opacity = '0'
          document.body.appendChild(ta)
          ta.select()
          document.execCommand('copy')
          document.body.removeChild(ta)
        }
        this.$message.success('已复制')
      } catch (e) {
        this.$message.error('复制失败')
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
      await this.startBlankSession()
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
        if (e !== 'cancel' && e !== 'close') this.$message.error('重命名失败')
      }
    },
    applyTaskPayload (at) {
      if (!at) {
        this.taskId = null
        this.taskStatus = ''
        this.taskOrchestrator = ''
        this.taskProgress = 0
        this.steps = []
        this.intervention = null
        this.resultBody = null
        return
      }
      this.taskId = at.task_id
      this.taskStatus = at.status
      this.taskProgress = at.progress || 0
      this.steps = at.steps || []
      this.intervention = at.intervention
      this.resultBody = at.result
      this.taskOrchestrator = at.orchestrator || this.taskOrchestrator
    },
    async reload () {
      const sid = this.$route.params.sessionId
      if (!sid) return
      try {
        const wasTaskActive = this.isTaskActiveStatus()
        const res = await getSession(sid)
        const d = res.data
        this.currentSessionId = d.session_id
        this.sessionTitle = d.title
        this.messages = d.messages || []
        const at = d.active_task || d.latest_task
        this.applyTaskPayload(at)
        if (wasTaskActive && !this.isTaskActiveStatus()) this.wsRefresh()
        this.$nextTick(() => this.scrollMsg(true))
        if (this.isTaskActiveStatus()) this.syncPoll()
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
      const threshold = 32
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
        const wasTaskActive = this.isTaskActiveStatus()
        const prevMsgCount = (this.messages || []).length
        const sRes = await getSession(this.currentSessionId)
        const s = sRes.data || {}
        this.sessionTitle = s.title || this.sessionTitle
        this.messages = s.messages || []
        const at = s.active_task || s.latest_task
        this.applyTaskPayload(at)
        const needTaskDetail = this.taskId && (this.taskStatus === 'running' || this.taskStatus === 'pending_action' || this.taskStatus === 'pending')
        if (needTaskDetail) {
          try {
            const tRes = await getTask(this.taskId)
            const t = tRes.data || {}
            this.applyTaskPayload(t)
          } catch (e) {}
        }
        if (wasTaskActive && !this.isTaskActiveStatus()) {
          this.wsRefresh()
          await this.loadPaperShelf()
        }
        if ((this.messages || []).length !== prevMsgCount) {
          this.$nextTick(() => this.scrollMsg())
          if (!this.isTaskActiveStatus()) this.stopPoll()
          return
        }
        this.$nextTick(() => this.scrollMsg())
        if (!this.isTaskActiveStatus()) this.stopPoll()
      } finally {
        this.pollInFlight = false
      }
    },
    syncPoll () {
      this.stopPoll()
      if (!this.currentSessionId) return
      if (!this.isTaskActiveStatus()) return
      this.pollFailureCount = 0
      this.pollTick().catch(() => {})
      this.pollTimer = setInterval(async () => {
        try {
          await this.pollTick()
          this.pollFailureCount = 0
        } catch (e) {
          this.pollFailureCount += 1
          if (this.pollFailureCount >= 6) {
            this.$message.warning('自动刷新失败，请手动刷新页面')
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
      const workspaceRefs = this.pendingWorkspaceRefs.length
        ? this.pendingWorkspaceRefs.map(r => ({ kind: r.kind, rel_path: r.rel_path, label: r.label }))
        : undefined
      const meta = {}
      if (workspaceRefs) {
        // eslint-disable-next-line camelcase
        meta.workspace_refs = workspaceRefs
      }
      this.messages = [...this.messages, {
        role: 'user',
        content,
        metadata: meta
      }]
      this.$nextTick(() => this.scrollMsg())
      this.draft = ''
      const refsToSend = workspaceRefs
      if (refsToSend) this.pendingWorkspaceRefs = []
      try {
        let res
        if (!this.currentSessionId) {
          const extra = {}
          if (refsToSend) {
            // eslint-disable-next-line camelcase
            extra.workspace_refs = refsToSend
          }
          res = await createSessionWithFirstMessage(content, '新会话', extra)
          const newSessionId = res.data.session_id
          this.currentSessionId = newSessionId
          this.$router.push({ path: `/research-agent/session/${newSessionId}` })
        } else {
          const body = { content }
          if (refsToSend) {
            // eslint-disable-next-line camelcase
            body.workspace_refs = refsToSend
          }
          res = await postMessage(this.currentSessionId, body)
        }
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        this.taskOrchestrator = 'basic'
        this.taskProgress = 0
        const ackMessage = '已收到请求，任务已启动。'
        const tail = this.messages[this.messages.length - 1]
        if (!tail || tail.role !== 'assistant' || tail.content !== ackMessage) {
          this.messages = [...this.messages, { role: 'assistant', content: ackMessage }]
          this.$nextTick(() => this.scrollMsg())
        }
        await this.pollTick()
        await this.loadSessionList()
        await this.loadPaperShelf()
        this.syncPoll()
      } catch (e) {
        this.messages = this.messages.filter((m, idx, arr) => !(idx === arr.length - 1 && m.role === 'user' && m.content === content))
        if (refsToSend) this.pendingWorkspaceRefs = refsToSend
        this.$message.error(this.apiErrorMessage(e, '发送失败'))
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
    async wsNavigate (relPath) {
      this.wsPath = relPath || ''
      this.wsSelectedKeys = {}
      await this.wsRefresh()
    },
    async wsDownload (item) {
      try {
        await downloadWorkspaceFile(item.rel_path, item.name)
      } catch (e) {
        this.$message.error('下载失败：' + ((e && e.message) || ''))
      }
    },
    wsDeleteConfirm (item) {
      const label = item.type === 'directory' ? `目录「${item.name}」` : `文件「${item.name}」`
      const hint = item.type === 'directory' ? '（须为空目录）' : ''
      this.$confirm(`确定删除${label}？${hint}`, '删除确认', { type: 'warning' }).then(() => this.wsDelete(item)).catch(() => {})
    },
    async wsDelete (item) {
      try {
        await deleteWorkspacePath(item.rel_path)
        this.$message.success(`已删除 ${item.name}`)
        this.$set(this.wsSelectedKeys, item.rel_path, false)
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('删除失败：' + ((e && e.message) || ''))
      }
    },
    async wsUploadHandler ({ file }) {
      this.wsUploadActiveCount += 1
      this.wsUploading = true
      try {
        const data = await uploadWorkspaceFiles([file], this.wsPath)
        const uploaded = data && Array.isArray(data.uploaded) ? data.uploaded[0] : null
        const savedName = uploaded && uploaded.name ? uploaded.name : file.name
        this.$message.success(`已上传 ${file.name}${savedName !== file.name ? ' → ' + savedName : ''}`)
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('上传失败：' + ((e && e.message) || ''))
      } finally {
        this.wsUploadActiveCount = Math.max(0, this.wsUploadActiveCount - 1)
        this.wsUploading = this.wsUploadActiveCount > 0
      }
    },
    wsMkdirDialogOpen () {
      this.wsMkdirName = ''
      this.wsMkdirDialog = true
    },
    async wsMkdir () {
      const name = this.wsMkdirName.trim()
      if (!name) return
      const fullPath = this.wsPath ? `${this.wsPath}/${name}` : name
      try {
        await mkdirWorkspace(fullPath)
        this.$message.success('目录已创建')
        this.wsMkdirDialog = false
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('创建失败：' + ((e && e.message) || ''))
      }
    },
    wsFileIcon (name) {
      const ext = (name || '').split('.').pop().toLowerCase()
      const map = { pdf: 'el-icon-document', md: 'el-icon-tickets', txt: 'el-icon-tickets', png: 'el-icon-picture', jpg: 'el-icon-picture' }
      return map[ext] || 'el-icon-document'
    },
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
.ra-shell {
  position: relative;
  min-height: calc(100vh - 72px);
  padding: 72px 12px 20px;
  text-align: left;
  overflow-x: hidden;
}
.ra-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: linear-gradient(165deg, #e8f0ff 0%, #f5f9ff 35%, #fafbff 70%, #ffffff 100%);
  opacity: 0.95;
}
.ra-inner {
  position: relative;
  z-index: 1;
  max-width: 1480px;
  margin: 0 auto;
}
.ra-surface {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(210, 225, 255, 0.85);
  border-radius: 14px;
  box-shadow: 0 8px 28px rgba(64, 120, 200, 0.08);
  backdrop-filter: blur(6px);
}
.ra-surface-2 {
  background: rgba(255, 251, 240, 0.95);
  border: 1px solid #f5dab1;
  border-radius: 12px;
}
.ra-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.ra-toolbar-main {
  flex: 1;
  min-width: 0;
}
.ra-h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: #1a2b4a;
  letter-spacing: 0.02em;
}
.ra-toolbar-meta {
  margin: 6px 0 0;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #6b7c93;
}
.ra-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}
.ra-toolbar-chips {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ra-toolbar-progress {
  margin-top: 10px;
  max-width: 520px;
}
.ra-toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.ra-icon-text {
  padding: 0 4px;
}
.ra-grid {
  display: flex;
  gap: 12px;
  align-items: stretch;
  min-height: calc(100vh - 200px);
}
.ra-col-left {
  flex: 0 0 260px;
  width: 260px;
  max-width: 260px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  transition: flex-basis 0.2s ease, width 0.2s ease, max-width 0.2s ease, padding 0.2s ease;
}
.ra-col-left.is-collapsed {
  flex: 0 0 56px;
  width: 56px;
  max-width: 56px;
  padding: 8px 6px;
}
.ra-col-left.is-collapsed .ra-side-scroll,
.ra-col-left.is-collapsed .ra-side-head-title {
  display: none;
}
.ra-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.ra-side-head-title {
  font-weight: 600;
  font-size: 14px;
  color: #2c3e50;
}
.ra-side-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: 2px;
}
.ra-side-card {
  border-radius: 10px;
  padding: 10px 10px;
  margin-bottom: 8px;
  border: 1px solid #e8edf7;
  cursor: pointer;
  background: #fbfdff;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.ra-side-card:hover {
  border-color: #c5d9ff;
  box-shadow: 0 2px 10px rgba(64, 158, 255, 0.12);
}
.ra-side-card.is-active {
  border-color: #409eff;
  background: linear-gradient(135deg, #ecf5ff 0%, #f7fbff 100%);
}
.ra-side-card-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ra-side-card-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.ra-muted-tip {
  font-size: 12px;
  color: #a0aec0;
  margin: 8px 0 0;
  line-height: 1.45;
}
.ra-col-center {
  flex: 1;
  min-width: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.ra-welcome {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 20px;
}
.ra-welcome-card {
  max-width: 520px;
  text-align: center;
  padding: 28px 24px;
  border-radius: 16px;
  border: 1px solid #e0ebff;
  background: linear-gradient(180deg, #ffffff 0%, #f6f9ff 100%);
  box-shadow: 0 12px 40px rgba(41, 94, 180, 0.1);
}
.ra-welcome-card h2 {
  margin: 0 0 12px;
  font-size: 1.35rem;
  color: #1a2b4a;
}
.ra-welcome-desc {
  margin: 0 0 20px;
  font-size: 14px;
  line-height: 1.65;
  color: #5a6b82;
  text-align: left;
}
.ra-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 16px 8px;
}
.ra-msg-row {
  display: flex;
  margin-bottom: 14px;
}
.ra-msg-row.is-user {
  justify-content: flex-end;
}
.ra-msg-row.is-assistant {
  justify-content: flex-start;
}
.ra-msg-bubble {
  max-width: 82%;
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
.ra-msg-bubble.is-user {
  background: linear-gradient(135deg, #e3f0ff 0%, #f0f7ff 100%);
  border: 1px solid #cfe6ff;
}
.ra-msg-bubble.is-assistant {
  background: #f8fafc;
  border: 1px solid #ebeef5;
}
.ra-msg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.ra-msg-role {
  font-size: 12px;
  color: #909399;
}
.ra-msg-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.ra-md-inline {
  font-size: 14px;
  line-height: 1.65;
  color: #303133;
}
.ra-md-inline >>> p {
  margin: 0.45em 0;
}
.ra-md-inline >>> pre {
  background: #f6f8fa;
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
}
.ra-report-lead {
  margin: 0 0 8px;
  font-size: 13px;
  color: #606266;
}
.ra-report-card {
  border: 1px solid #e4e7ed;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}
.ra-report-card-hd {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}
.ra-scroll-fab {
  position: sticky;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  margin: 4px auto 8px;
  display: table;
}
.ra-intervention {
  margin: 0 16px 12px;
  padding: 14px;
}
.ra-int-summary {
  margin: 8px 0;
  color: #303133;
  font-size: 14px;
}
.ra-int-risk {
  color: #e6a23c;
  font-size: 13px;
}
.ra-int-actions {
  margin: 8px 0;
  display: flex;
  gap: 8px;
}
.ra-composer {
  border-top: 1px solid #e8edf7;
  padding: 12px 16px 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.5) 0%, #fff 40%);
}
.ra-ref-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.ra-ref-chips-label {
  font-size: 12px;
  color: #909399;
}
.ra-composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
.ra-hint {
  font-size: 12px;
  color: #a0aec0;
}
.ra-composer-btns {
  display: flex;
  gap: 10px;
}
.ra-col-right {
  flex: 0 0 380px;
  width: 380px;
  max-width: 380px;
  padding: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: flex-basis 0.2s ease, width 0.2s ease, max-width 0.2s ease;
}
.ra-col-right.is-collapsed {
  flex: 0 0 44px;
  width: 44px;
  max-width: 44px;
  padding: 8px 4px;
  align-items: center;
}
.ra-rail-collapsed {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 8px;
}
.ra-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 4px 8px 8px;
}
.ra-tabs >>> .el-tabs__content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.ra-tabs >>> .el-tab-pane {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.ra-tab-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px 12px;
  min-height: 0;
}
.ra-pane-intro {
  font-size: 12px;
  line-height: 1.55;
  color: #6b7c93;
  margin: 0 0 10px;
}
.ra-shelf-list {
  min-height: 120px;
}
.ra-shelf-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.ra-shelf-row {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid #edf2f7;
  background: #fbfdff;
}
.ra-shelf-cb {
  margin-top: 2px;
}
.ra-shelf-main {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.ra-shelf-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.ra-shelf-abs {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.45;
}
.ra-shelf-actions {
  margin-top: 8px;
  display: flex;
  gap: 4px;
}
.ra-deep-actions {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed #e4e7ed;
}
.ra-ws-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.ra-ws-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.ra-ws-list {
  border: 1px solid #edf2f7;
  border-radius: 10px;
  max-height: 320px;
  overflow-y: auto;
  background: #fbfdff;
}
.ra-ws-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid #f0f3fa;
  font-size: 13px;
}
.ra-ws-row:last-child {
  border-bottom: none;
}
.ra-ws-row.is-dir .ra-ws-name {
  color: #409eff;
  cursor: pointer;
}
.ra-ws-cb {
  flex-shrink: 0;
}
.ra-ws-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: default;
}
.ra-ws-row.is-dir .ra-ws-main {
  cursor: pointer;
}
.ra-ws-ico {
  color: #909399;
}
.ra-ws-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.ra-ws-size {
  font-size: 11px;
  color: #c0c4cc;
  flex-shrink: 0;
}
.ra-ws-ops {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}
.ra-ws-upload {
  margin-top: 10px;
}
.ra-board-wrap {
  padding-bottom: 20px;
}
.ra-current-card {
  border-radius: 10px;
  padding: 10px 12px;
  background: linear-gradient(135deg, #f0f7ff 0%, #fafcff 100%);
  border: 1px solid #d9ecff;
  margin-bottom: 12px;
  font-size: 13px;
}
.ra-current-card p {
  margin: 6px 0;
}
.ra-board-section {
  margin-bottom: 14px;
}
.ra-board-section-hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.ra-step-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.ra-step-item {
  padding: 10px 0;
  border-bottom: 1px solid #eef1f6;
}
.ra-step-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.ra-ts {
  display: block;
  font-size: 11px;
  color: #909399;
  margin-bottom: 4px;
}
.ra-phase {
  font-size: 11px;
  color: #a0aec0;
}
.ra-detail {
  font-size: 12px;
  color: #606266;
  margin-top: 6px;
}
.ra-plan-list,
.ra-subtask-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
}
.ra-plan-item,
.ra-subtask-item {
  border: 1px solid #edf2f7;
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 6px;
  background: #fff;
}
.ra-plan-title,
.ra-subtask-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 13px;
}
.ra-muted-line {
  margin: 6px 0 0;
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
.ra-decision-meta p {
  margin: 6px 0;
  font-size: 12px;
}
.ra-error {
  padding: 12px;
  color: #f56c6c;
  font-size: 13px;
}
.ra-danger-text {
  color: #f56c6c !important;
}
@media (max-width: 960px) {
  .ra-grid {
    flex-direction: column;
  }
  .ra-col-left,
  .ra-col-right {
    flex: 1 1 auto;
    width: 100%;
    max-width: none;
    max-height: 320px;
  }
}
</style>
