<template>
  <div class="ra-shell">
    <div class="ra-bg" aria-hidden="true" />
    <div class="ra-inner">
      <header class="ra-toolbar ra-surface">
        <div class="ra-toolbar-main">
          <div class="ra-toolbar-titles">
            <h1 class="ra-h1">科研助手</h1>
            <p class="ra-toolbar-meta">
              <span class="ra-ellipsis">{{ sessionTitleDisplay }}</span>
              <el-button
                v-if="persistedSessionId"
                type="text"
                icon="el-icon-edit"
                class="ra-icon-text"
                @click="onRenameTitle"
              />
            </p>
            <p v-if="showSessionHint" class="ra-toolbar-hint">发送首条普通对话，或将工作区文件「加入展示区」，将自动创建并绑定会话。</p>
          </div>
          <div v-if="persistedSessionId || taskId" class="ra-toolbar-chips">
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
          <el-tooltip :content="rightCollapsed ? '展开侧栏' : '收起侧栏'" placement="bottom">
            <el-button circle size="small" :icon="rightCollapsed ? 'el-icon-d-arrow-left' : 'el-icon-d-arrow-right'" @click="rightCollapsed = !rightCollapsed" />
          </el-tooltip>
          <el-button size="small" plain @click="goManage">会话管理</el-button>
        </div>
      </header>

      <div ref="raBody" class="ra-body">
        <div class="ra-grid">
        <aside :class="['ra-col-left ra-surface', leftCollapsed && 'is-collapsed']">
          <div class="ra-side-head" :class="{ 'is-collapsed': leftCollapsed }">
            <el-tooltip :content="leftCollapsed ? '展开会话列表' : '收起会话列表'" placement="bottom">
              <el-button
                class="ra-side-collapse-btn"
                circle
                size="mini"
                :icon="leftCollapsed ? 'el-icon-s-unfold' : 'el-icon-s-fold'"
                @click="leftCollapsed = !leftCollapsed"
              />
            </el-tooltip>
            <span v-show="!leftCollapsed" class="ra-side-head-title">历史会话</span>
            <el-tooltip content="新建空白会话" placement="right">
              <el-button type="primary" size="mini" icon="el-icon-plus" circle :loading="creatingSession" @click="createAndOpenSession" />
            </el-tooltip>
          </div>
          <div v-show="!leftCollapsed" class="ra-side-scroll">
            <div
              v-for="s in displayedSessionItems"
              :key="s.session_id"
              :class="['ra-side-card', (s.session_id === persistedSessionId) ? 'is-active' : '']"
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
          <div class="ra-center-stack">
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
                :rows="5"
                resize="none"
                placeholder="输入问题或指令，Ctrl+Enter 发送（尚未落库会话时，首条发送将自动创建会话）。"
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
          </div>
        </main>

        <aside :class="['ra-col-right ra-surface', rightCollapsed && 'is-collapsed']">
          <div v-if="rightCollapsed" class="ra-rail-collapsed">
            <el-tooltip content="展开侧栏" placement="left">
              <el-button type="text" icon="el-icon-d-arrow-left" @click="rightCollapsed = false" />
            </el-tooltip>
          </div>
          <el-tabs v-else v-model="rightTab" class="ra-tabs" stretch>
            <el-tab-pane label="论文展示区" name="shelf">
              <div class="ra-tab-body ra-shelf-tab">
                <template v-if="!persistedSessionId">
                  <el-empty description="尚未落库会话：发送首条普通对话，或在工作区将文件「加入展示区」，将自动创建会话并启用文献展示。" :image-size="72" />
                </template>
                <template v-else>
                  <p class="ra-pane-intro">检索结果与手动添加的文献列表如下。点击条目标题区域可预览（工作区文件支持 PDF / 文本 / 图片等）；勾选后，在下方填写提示词并点击<strong>启动深度研究</strong>。</p>
                  <div v-loading="paperShelfLoading" class="ra-shelf-list">
                    <el-empty v-if="!paperShelfItems.length && !paperShelfLoading" description="展示区暂无条目" :image-size="64" />
                    <el-checkbox-group v-model="selectedPaperIdsForDeep" class="ra-shelf-group">
                      <div
                        v-for="it in paperShelfItems"
                        :key="it.id"
                        :class="['ra-shelf-row', shelfPreviewItem && shelfPreviewItem.id === it.id && shelfPreviewOpen && 'is-preview-active']"
                      >
                        <el-checkbox :label="it.id" class="ra-shelf-cb">&nbsp;</el-checkbox>
                        <div class="ra-shelf-main" title="点击预览" @click="openShelfPreview(it)">
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
                  <div class="ra-deep-panel">
                    <div class="ra-deep-panel-hd">深度研究</div>
                    <el-input
                      v-model="deepDraft"
                      type="textarea"
                      :rows="5"
                      resize="none"
                      placeholder="在此填写深度研究提示词（独立于中间普通对话输入框）"
                      :disabled="inputLocked"
                    />
                    <div class="ra-deep-panel-actions">
                      <el-button
                        type="primary"
                        size="small"
                        icon="el-icon-magic-stick"
                        :loading="deepStarting"
                        :disabled="inputLocked || !deepDraft.trim() || !selectedPaperIdsForDeep.length"
                        @click="startDeepResearch"
                      >启动深度研究</el-button>
                      <span class="ra-muted-tip ra-deep-meta">已选文献 {{ selectedPaperIdsForDeep.length }} 条</span>
                    </div>
                    <p v-if="!selectedPaperIdsForDeep.length" class="ra-muted-tip">请在上方的展示区列表中勾选至少一条文献。</p>
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
                  <el-button size="mini" :disabled="!wsSelectedItems.length" @click="wsOpenTransferDialog('copy')">复制到…</el-button>
                  <el-button size="mini" :disabled="!wsSelectedItems.length" @click="wsOpenTransferDialog('move')">移动到…</el-button>
                  <el-button size="mini" :disabled="!wsSelectedItems.length" @click="wsStageClipboard('cut')">剪切</el-button>
                  <el-button size="mini" :disabled="!wsCanPaste" @click="wsPasteIntoCurrent">粘贴</el-button>
                  <el-button size="mini" plain :disabled="!wsSelectedItems.length" @click="wsClearSelection">清空已选</el-button>
                  <el-button size="mini" icon="el-icon-folder-add" @click="wsMkdirDialogOpen">新建文件夹</el-button>
                </div>
                <div v-if="wsSelectedSummary" class="ra-ws-selection">
                  <div class="ra-ws-selection-head">
                    <span class="ra-ws-selection-title">{{ wsSelectedSummary }}</span>
                    <el-button type="text" size="mini" @click="wsClearSelection">清空</el-button>
                  </div>
                  <div class="ra-ws-selection-tags">
                    <el-tag
                      v-for="item in wsSelectedPreviewItems"
                      :key="'sel-' + item.rel_path"
                      closable
                      size="mini"
                      type="success"
                      effect="plain"
                      @close="wsRemoveSelected(item.rel_path)"
                    >{{ item.type === 'directory' ? '目录' : '文件' }} · {{ item.label }}</el-tag>
                    <span v-if="wsSelectedItems.length > wsSelectedPreviewItems.length" class="ra-muted-tip ra-ws-selection-more">
                      还有 {{ wsSelectedItems.length - wsSelectedPreviewItems.length }} 项
                    </span>
                  </div>
                </div>
                <p v-if="wsClipboardSummary" class="ra-muted-tip ra-ws-clipboard">{{ wsClipboardSummary }}</p>
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
                      <el-dropdown trigger="click" @command="cmd => wsHandleRowAction(cmd, item)">
                        <el-button type="text" size="mini" class="ra-ws-more-btn" icon="el-icon-more" @click.stop>
                          操作
                        </el-button>
                        <el-dropdown-menu slot="dropdown">
                          <el-dropdown-item v-if="item.type === 'file'" command="download">下载</el-dropdown-item>
                          <el-dropdown-item command="copy_to">复制到…</el-dropdown-item>
                          <el-dropdown-item command="move_to">移动到…</el-dropdown-item>
                          <el-dropdown-item command="copy">复制</el-dropdown-item>
                          <el-dropdown-item command="cut">剪切</el-dropdown-item>
                          <el-dropdown-item v-if="wsIsZipFile(item)" command="extract">解压</el-dropdown-item>
                          <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                        </el-dropdown-menu>
                      </el-dropdown>
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

      <transition name="ra-sp-slide">
        <div
          v-if="shelfPreviewOpen"
          class="ra-shelf-preview-root"
          @click.self="closeShelfPreview"
        >
          <div
            class="ra-shelf-preview-panel ra-surface"
            :style="{ width: shelfPreviewWidthPx + 'px' }"
            role="dialog"
            aria-modal="true"
            aria-label="文献预览"
            @click.stop
          >
            <div
              class="ra-sp-resize-handle"
              title="拖动调整宽度"
              @pointerdown.prevent="onShelfPreviewResizeStart"
              @mousedown.prevent="onShelfPreviewResizeStart"
            />
            <div class="ra-sp-head">
              <span class="ra-sp-title" :title="shelfPreviewTitle">{{ truncate(shelfPreviewTitle, 48) }}</span>
              <el-tooltip content="关闭预览" placement="bottom">
                <el-button type="text" size="mini" icon="el-icon-close" circle @click="closeShelfPreview" />
              </el-tooltip>
            </div>
            <div v-loading="shelfPreviewLoading" class="ra-sp-body">
              <template v-if="shelfPreviewMode === 'pdf' && shelfPreviewBlobUrl">
                <iframe class="ra-sp-iframe" title="PDF 预览" :src="shelfPreviewBlobUrl" />
              </template>
              <div v-else-if="shelfPreviewMode === 'markdown' && shelfPreviewHtml" class="ra-sp-scroll ra-md-inline" v-html="shelfPreviewHtml" />
              <pre v-else-if="shelfPreviewMode === 'text'" class="ra-sp-scroll ra-sp-pre">{{ shelfPreviewText }}</pre>
              <div v-else-if="shelfPreviewMode === 'image' && shelfPreviewBlobUrl" class="ra-sp-img-wrap">
                <img class="ra-sp-img" alt="预览" :src="shelfPreviewBlobUrl" />
              </div>
              <div v-else-if="shelfPreviewMode === 'download_only'" class="ra-sp-scroll ra-sp-fallback">
                <el-alert type="info" :closable="false" show-icon :title="shelfPreviewDownloadTitle" :description="shelfPreviewHint || '此类文件不适合在浏览器内嵌预览，请下载后用本地应用打开。'" />
                <el-button v-if="shelfPreviewWorkspaceRel" type="primary" size="small" plain style="margin-top:12px" icon="el-icon-download" @click="shelfPreviewDownload">下载文件</el-button>
              </div>
              <div v-else-if="shelfPreviewMode === 'external'" class="ra-sp-scroll ra-sp-fallback">
                <el-alert type="warning" :closable="false" show-icon title="外链文献" description="受跨域与安全策略限制，无法在应用内嵌预览 PDF 或网页。请使用下方按钮在浏览器新标签中打开。" />
                <p v-if="shelfPreviewAbstract" class="ra-sp-abs">{{ truncate(shelfPreviewAbstract, 1200) }}</p>
                <el-button v-if="shelfPreviewExternalUrl" type="primary" size="small" style="margin-top:12px" @click="shelfPreviewOpenExternal">在新标签打开</el-button>
              </div>
              <div v-else-if="shelfPreviewMode === 'error'" class="ra-sp-scroll ra-sp-fallback">
                <el-alert type="error" :closable="false" show-icon :title="shelfPreviewError || '加载失败'" />
                <el-button size="small" style="margin-top:12px" @click="shelfPreviewRetry">重试</el-button>
              </div>
            </div>
          </div>
        </div>
      </transition>
      </div>
    </div>

    <el-dialog title="新建文件夹" :visible.sync="wsMkdirDialog" width="320px" append-to-body @open="wsMkdirName = ''">
      <el-input v-model="wsMkdirName" placeholder="支持多级，如 papers/2026" maxlength="120" show-word-limit @keyup.enter.native="wsMkdir" />
      <span slot="footer">
        <el-button @click="wsMkdirDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!wsMkdirName.trim()" @click="wsMkdir">创建</el-button>
      </span>
    </el-dialog>
    <el-dialog :title="wsTransferDialogTitle" :visible.sync="wsTransferDialog" width="420px" append-to-body>
      <p class="ra-muted-tip">目标目录默认为当前浏览目录；可填写工作区相对路径，目标目录需已存在，同名冲突会被拦截。</p>
      <div class="ra-ws-transfer-summary">
        <strong>待{{ wsTransferMode === 'move' ? '移动' : '复制' }}</strong>
        <span>{{ wsTransferItemsSummary }}</span>
      </div>
      <el-input
        v-model="wsTransferTargetPath"
        placeholder="目标目录，相对工作区根；留空表示根目录"
        maxlength="512"
        show-word-limit
        @keyup.enter.native="wsSubmitTransfer"
      />
      <span slot="footer">
        <el-button @click="wsTransferDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!wsTransferItems.length" @click="wsSubmitTransfer">执行</el-button>
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
  fetchWorkspaceFileBlob,
  uploadWorkspaceFiles,
  deleteWorkspacePath,
  mkdirWorkspace,
  copyWorkspacePath,
  moveWorkspacePath,
  extractWorkspaceArchive
} from './workspaceApi.js'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])
const md = new MarkdownIt({ breaks: true, linkify: true })
const REPORT_MESSAGE_PREFIX = '[[RA_REPORT]]\n'
const SHELF_PREVIEW_TEXT_MAX_BYTES = 512 * 1024

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
      deepDraft: '',
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
      lastWorkspaceSyncDuringTaskTs: 0,
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
      wsSelectedMap: {},
      wsClipboard: null,
      wsTransferDialog: false,
      wsTransferMode: 'copy',
      wsTransferItems: [],
      wsTransferTargetPath: '',
      shelfPreviewOpen: false,
      shelfPreviewLoading: false,
      shelfPreviewTitle: '',
      shelfPreviewMode: '',
      shelfPreviewBlobUrl: '',
      shelfPreviewText: '',
      shelfPreviewHtml: '',
      shelfPreviewHint: '',
      shelfPreviewError: '',
      shelfPreviewItem: null,
      shelfPreviewWidthPx: 680
    }
  },
  computed: {
    persistedSessionId () {
      return this.$route.params.sessionId || this.currentSessionId || ''
    },
    sessionTitleDisplay () {
      if (this.persistedSessionId) return this.sessionTitle || '新会话'
      return '尚未创建会话'
    },
    showSessionHint () {
      return !this.persistedSessionId
    },
    shelfPreviewWorkspaceRel () {
      const it = this.shelfPreviewItem
      return it && it.workspace_rel_path ? String(it.workspace_rel_path) : ''
    },
    shelfPreviewExternalUrl () {
      const it = this.shelfPreviewItem
      if (!it) return ''
      return String(it.external_jump_url || it.primary_url || '').trim()
    },
    shelfPreviewAbstract () {
      const it = this.shelfPreviewItem
      return it && it.abstract ? String(it.abstract) : ''
    },
    shelfPreviewDownloadTitle () {
      const it = this.shelfPreviewItem
      const raw = it && it.file_extension ? String(it.file_extension).trim() : ''
      if (!raw) return '该文件需下载后查看'
      const pretty = raw.startsWith('.') ? raw : `.${raw}`
      return `「${pretty}」格式需下载后查看`
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
    wsSelectedKeys () {
      const out = {}
      for (const item of this.wsItems) {
        if (this.wsSelectedMap[item.rel_path]) out[item.rel_path] = true
      }
      return out
    },
    wsSelectedList () {
      return Object.keys(this.wsSelectedMap || {}).filter(k => this.wsSelectedMap[k])
    },
    wsSelectedItems () {
      return this.wsSelectedList
        .map(rel => this.wsSelectedMap[rel])
        .filter(Boolean)
    },
    canAddShelfFromWs () {
      if (!this.wsSelectedList.length) return false
      return this.wsSelectedItems.some(it => it && it.type === 'file')
    },
    wsCanPaste () {
      const clip = this.wsClipboard
      return Boolean(clip && clip.mode && Array.isArray(clip.items) && clip.items.length)
    },
    wsClipboardSummary () {
      const clip = this.wsClipboard
      if (!clip || !Array.isArray(clip.items) || !clip.items.length) return ''
      const modeLabel = clip.mode === 'cut' ? '已剪切' : '已复制'
      const names = clip.items.map(item => item.name || item.rel_path).slice(0, 3).join('、')
      const extra = clip.items.length > 3 ? ` 等 ${clip.items.length} 项` : ''
      return `${modeLabel}：${names}${extra}，可切换目录后粘贴到当前目录。`
    },
    wsTransferDialogTitle () {
      return this.wsTransferMode === 'move' ? '移动到…' : '复制到…'
    },
    wsTransferItemsSummary () {
      if (!this.wsTransferItems.length) return '无'
      const names = this.wsTransferItems.map(item => item.name || item.rel_path).slice(0, 3).join('、')
      if (this.wsTransferItems.length > 3) return `${names} 等 ${this.wsTransferItems.length} 项`
      return names
    },
    wsSelectedSummary () {
      if (!this.wsSelectedItems.length) return ''
      return `已勾选 ${this.wsSelectedItems.length} 项，可切换目录继续追加后统一操作。`
    },
    wsSelectedPreviewItems () {
      return this.wsSelectedItems.slice(0, 6).map(item => ({
        rel_path: item.rel_path,
        type: item.type,
        label: item.name || item.rel_path
      }))
    }
  },
  watch: {
    '$route.params.sessionId' () {
      this.closeShelfPreview()
      this.bootstrap()
    },
    steps () {
      if (!this.shouldCollapseHistory) this.historyExpanded = false
    },
    currentSessionId (id) {
      if (id) this.loadPaperShelf()
      else if (!this.$route.params.sessionId) {
        this.paperShelfItems = []
        this.selectedPaperIdsForDeep = []
      }
    }
  },
  created () {
    try {
      const w = parseInt(localStorage.getItem('ra_shelf_preview_w'), 10)
      if (w >= 320 && w <= 1600) this.shelfPreviewWidthPx = w
    } catch (e) {
      /* ignore */
    }
    this.bootstrap()
    this.wsRefresh()
  },
  beforeDestroy () {
    this.stopPoll()
    this.closeShelfPreview()
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
      if (!item || !item.rel_path) return
      if (checked) {
        this.$set(this.wsSelectedMap, item.rel_path, {
          rel_path: item.rel_path,
          name: item.name,
          type: item.type,
          size: item.size
        })
        this.$message.success(`已勾选 ${this.wsSelectedList.length} 项`)
      } else {
        this.$delete(this.wsSelectedMap, item.rel_path)
        this.$message.info(`已勾选 ${this.wsSelectedList.length} 项`)
      }
    },
    wsRemoveSelected (relPath) {
      if (!relPath) return
      this.$delete(this.wsSelectedMap, relPath)
      this.$message.info(`已勾选 ${this.wsSelectedList.length} 项`)
    },
    wsClearSelection () {
      if (!this.wsSelectedList.length) return
      this.wsSelectedMap = {}
      this.$message.success('已清空所有勾选项')
    },
    wsItemName (item) {
      return (item && (item.name || item.rel_path)) || ''
    },
    wsIsZipFile (item) {
      if (!item || item.type !== 'file') return false
      return /\.zip$/i.test(String(item.name || item.rel_path || ''))
    },
    wsNormalizeTargetDir (path) {
      return String(path || '').trim().replace(/^\/+/, '').replace(/\\/g, '/')
    },
    wsTransferItemsFromArg (item) {
      if (item) return [item]
      return this.wsSelectedItems
    },
    wsStageClipboard (mode, item = null) {
      const items = this.wsTransferItemsFromArg(item)
      if (!items.length) {
        this.$message.warning('请先选择文件或目录')
        return
      }
      this.wsClipboard = {
        mode,
        items: items.map((entry) => ({
          rel_path: entry.rel_path,
          name: entry.name,
          type: entry.type
        }))
      }
      this.$message.success(mode === 'cut' ? '已加入剪切板，可切换目录后粘贴' : '已加入复制列表，可切换目录后粘贴')
    },
    wsHandleRowAction (command, item) {
      if (!item) return
      if (command === 'download') {
        this.wsDownload(item)
        return
      }
      if (command === 'copy_to') {
        this.wsOpenTransferDialog('copy', item)
        return
      }
      if (command === 'move_to') {
        this.wsOpenTransferDialog('move', item)
        return
      }
      if (command === 'copy') {
        this.wsStageClipboard('copy', item)
        return
      }
      if (command === 'cut') {
        this.wsStageClipboard('cut', item)
        return
      }
      if (command === 'extract') {
        this.wsExtractArchive(item)
        return
      }
      if (command === 'delete') {
        this.wsDeleteConfirm(item)
      }
    },
    wsOpenTransferDialog (mode, item = null) {
      const items = this.wsTransferItemsFromArg(item)
      if (!items.length) {
        this.$message.warning('请先选择文件或目录')
        return
      }
      this.wsTransferMode = mode
      this.wsTransferItems = items.map((entry) => ({
        rel_path: entry.rel_path,
        name: entry.name,
        type: entry.type
      }))
      this.wsTransferTargetPath = this.wsPath || ''
      this.wsTransferDialog = true
    },
    async wsExecuteTransfer (mode, items, targetDir, { fromPaste = false } = {}) {
      const normalizedTarget = this.wsNormalizeTargetDir(targetDir)
      const action = mode === 'move' ? moveWorkspacePath : copyWorkspacePath
      for (const item of items) {
        const dst = normalizedTarget
        try {
          await action(item.rel_path, dst)
        } catch (e) {
          this.$message.error(this.apiErrorMessage(e, mode === 'move' ? '移动失败' : '复制失败'))
          return false
        }
      }
      const label = mode === 'move' ? '移动' : '复制'
      this.$message.success(`${label}成功，共 ${items.length} 项`)
      if (mode === 'move' || fromPaste) {
        items.forEach(item => this.$delete(this.wsSelectedMap, item.rel_path))
      }
      if (fromPaste && this.wsClipboard && this.wsClipboard.mode === 'cut') {
        this.wsClipboard = null
      }
      await this.wsRefresh()
      return true
    },
    async wsSubmitTransfer () {
      const ok = await this.wsExecuteTransfer(this.wsTransferMode, this.wsTransferItems, this.wsTransferTargetPath)
      if (ok) {
        this.wsTransferDialog = false
        this.wsTransferItems = []
      }
    },
    async wsPasteIntoCurrent () {
      if (!this.wsCanPaste) return
      const clip = this.wsClipboard
      const mode = clip.mode === 'cut' ? 'move' : 'copy'
      await this.wsExecuteTransfer(mode, clip.items, this.wsPath || '', { fromPaste: true })
    },
    async wsExtractArchive (item) {
      if (!this.wsIsZipFile(item)) return
      try {
        await this.$confirm(`确定原地解压「${this.wsItemName(item)}」？`, '解压确认', { type: 'warning' })
      } catch (e) {
        return
      }
      try {
        const data = await extractWorkspaceArchive(item.rel_path)
        this.$message.success(`已解压 ${this.wsItemName(item)}，共 ${data.extracted_count || 0} 项`)
        await this.wsRefresh()
      } catch (e) {
        this.$message.error('解压失败：' + ((e && e.message) || ''))
      }
    },
    addWsSelectionToPendingContext () {
      const next = [...this.pendingWorkspaceRefs]
      const byPath = new Set(next.map(r => r.rel_path))
      for (const rel of this.wsSelectedList) {
        const item = this.wsSelectedMap[rel]
        if (!item) continue
        const kind = item.type === 'directory' ? 'dir' : 'file'
        if (byPath.has(rel)) continue
        byPath.add(rel)
        next.push({ kind, rel_path: rel, label: item.name || rel })
      }
      this.pendingWorkspaceRefs = next
      this.$message.success('已加入本轮上下文，发送消息时生效')
    },
    async ensurePersistedSession () {
      const rid = this.$route.params.sessionId
      if (rid) {
        if (!this.currentSessionId) this.currentSessionId = rid
        return rid
      }
      if (this.currentSessionId) return this.currentSessionId
      const res = await createSession({ title: '新会话' })
      const id = res.data.session_id
      await this.$router.push({ path: `/research-agent/session/${id}` })
      await this.$nextTick()
      return this.$route.params.sessionId || id
    },
    async addWsFilesToShelf () {
      const files = this.wsSelectedItems
        .filter(it => it && it.type === 'file')
      if (!files.length) {
        this.$message.warning('请仅勾选文件加入展示区')
        return
      }
      let sid
      try {
        sid = await this.ensurePersistedSession()
      } catch (e) {
        this.$message.error(this.apiErrorMessage(e, '创建会话失败'))
        return
      }
      let ok = 0
      for (const f of files) {
        try {
          await addPaperShelfFromWorkspace(sid, f.rel_path)
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
    revokeShelfPreviewBlob () {
      if (this.shelfPreviewBlobUrl) {
        try {
          URL.revokeObjectURL(this.shelfPreviewBlobUrl)
        } catch (e) {
          /* ignore */
        }
        this.shelfPreviewBlobUrl = ''
      }
    },
    closeShelfPreview () {
      this._shelfPreviewClearResizeListeners()
      this.revokeShelfPreviewBlob()
      this.shelfPreviewOpen = false
      this.shelfPreviewLoading = false
      this.shelfPreviewItem = null
      this.shelfPreviewMode = ''
      this.shelfPreviewTitle = ''
      this.shelfPreviewText = ''
      this.shelfPreviewHtml = ''
      this.shelfPreviewHint = ''
      this.shelfPreviewError = ''
    },
    _shelfPreviewClearResizeListeners () {
      if (typeof this._shelfPreviewResizeTeardown === 'function') {
        this._shelfPreviewResizeTeardown()
        this._shelfPreviewResizeTeardown = null
      }
    },
    onShelfPreviewResizeStart (e) {
      if (e.type === 'mousedown' && typeof window.PointerEvent !== 'undefined') {
        return
      }
      if (e.button !== undefined && e.button !== 0) {
        return
      }

      this._shelfPreviewClearResizeListeners()

      const handle = e.currentTarget
      const el = this.$refs.raBody
      const rect = el && el.getBoundingClientRect ? el.getBoundingClientRect() : null
      const avail = rect && rect.width ? rect.width : window.innerWidth
      const maxW = Math.max(320, Math.min(1600, Math.floor(avail * 0.96)))
      const minW = 320
      const startX = e.clientX
      const startW = this.shelfPreviewWidthPx

      const applyWidth = (clientX) => {
        let w = startW + (clientX - startX)
        if (w < minW) w = minW
        if (w > maxW) w = maxW
        this.shelfPreviewWidthPx = w
      }

      let pointerId = null
      let usePointerCapture = false
      if (typeof e.pointerId === 'number' && handle.setPointerCapture) {
        pointerId = e.pointerId
        try {
          handle.setPointerCapture(pointerId)
          usePointerCapture = true
        } catch (err) {
          pointerId = null
          usePointerCapture = false
        }
      }

      const onMove = (ev) => {
        if (usePointerCapture) {
          if (ev.pointerId !== pointerId) {
            return
          }
        }
        applyWidth(ev.clientX)
      }

      const onEnd = (ev) => {
        if (this._shelfPreviewResizeTeardown !== onEnd) {
          return
        }
        if (usePointerCapture && ev && typeof ev.pointerId === 'number' && ev.pointerId !== pointerId) {
          return
        }
        this._shelfPreviewResizeTeardown = null
        if (usePointerCapture) {
          handle.removeEventListener('pointermove', onMove)
          handle.removeEventListener('pointerup', onEnd)
          handle.removeEventListener('pointercancel', onEnd)
          handle.removeEventListener('lostpointercapture', onLostCapture)
          if (pointerId != null) {
            try {
              handle.releasePointerCapture(pointerId)
            } catch (err) {
              /* ignore */
            }
          }
        } else {
          document.removeEventListener('mousemove', onMove, true)
          document.removeEventListener('mouseup', onEnd, true)
          window.removeEventListener('blur', onEnd)
        }
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        try {
          localStorage.setItem('ra_shelf_preview_w', String(this.shelfPreviewWidthPx))
        } catch (err) {
          /* ignore */
        }
      }

      const onLostCapture = (ev) => {
        if (ev.pointerId === pointerId) {
          onEnd(ev)
        }
      }

      this._shelfPreviewResizeTeardown = onEnd

      if (usePointerCapture) {
        handle.addEventListener('pointermove', onMove)
        handle.addEventListener('pointerup', onEnd)
        handle.addEventListener('pointercancel', onEnd)
        handle.addEventListener('lostpointercapture', onLostCapture)
      } else {
        document.addEventListener('mousemove', onMove, true)
        document.addEventListener('mouseup', onEnd, true)
        window.addEventListener('blur', onEnd)
      }

      document.body.style.cursor = 'ew-resize'
      document.body.style.userSelect = 'none'
    },
    shelfPreviewGuessImageMime (relPath) {
      const ext = String(relPath.split('.').pop() || '').toLowerCase()
      const map = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp' }
      return map[ext] || 'application/octet-stream'
    },
    async openShelfPreview (it, opts = {}) {
      if (!it || !it.id) return
      if (!opts.force && this.shelfPreviewOpen && this.shelfPreviewItem && this.shelfPreviewItem.id === it.id) {
        this.closeShelfPreview()
        return
      }
      this.revokeShelfPreviewBlob()
      this.shelfPreviewOpen = true
      this.shelfPreviewItem = it
      this.shelfPreviewTitle = it.title || '预览'
      this.shelfPreviewMode = ''
      this.shelfPreviewText = ''
      this.shelfPreviewHtml = ''
      this.shelfPreviewError = ''
      this.shelfPreviewHint = it.hint ? String(it.hint) : ''
      this.shelfPreviewLoading = false

      if (it.source_kind !== 'workspace_file' || !it.workspace_rel_path) {
        this.shelfPreviewMode = 'external'
        return
      }

      const mode = it.open_mode || 'download_only'
      if (mode === 'download_only') {
        this.shelfPreviewMode = 'download_only'
        return
      }

      this.shelfPreviewLoading = true
      try {
        const blob = await fetchWorkspaceFileBlob(it.workspace_rel_path)
        if (mode === 'pdf_viewer') {
          const pdfBlob =
            blob.type && blob.type !== 'application/octet-stream'
              ? blob
              : new Blob([blob], { type: 'application/pdf' })
          this.shelfPreviewBlobUrl = URL.createObjectURL(pdfBlob)
          this.shelfPreviewMode = 'pdf'
        } else if (mode === 'image_preview') {
          const imgBlob =
            blob.type && blob.type.startsWith('image/')
              ? blob
              : new Blob([blob], { type: this.shelfPreviewGuessImageMime(it.workspace_rel_path) })
          this.shelfPreviewBlobUrl = URL.createObjectURL(imgBlob)
          this.shelfPreviewMode = 'image'
        } else if (mode === 'text_preview') {
          const slice =
            blob.size > SHELF_PREVIEW_TEXT_MAX_BYTES ? blob.slice(0, SHELF_PREVIEW_TEXT_MAX_BYTES) : blob
          const buf = await slice.arrayBuffer()
          const dec = new TextDecoder('utf-8', { fatal: false })
          let text = dec.decode(buf)
          if (blob.size > SHELF_PREVIEW_TEXT_MAX_BYTES) {
            text += '\n\n…（仅显示前 512 KB，完整内容请下载）'
          }
          this.shelfPreviewText = text
          const ext = String(it.file_extension || '').toLowerCase()
          if (ext === '.md' || ext === '.markdown') {
            this.shelfPreviewHtml = md.render(text)
            this.shelfPreviewMode = 'markdown'
          } else {
            this.shelfPreviewMode = 'text'
          }
        } else {
          this.shelfPreviewMode = 'download_only'
        }
      } catch (e) {
        this.shelfPreviewError = this.apiErrorMessage(e, '加载预览失败')
        this.shelfPreviewMode = 'error'
      } finally {
        this.shelfPreviewLoading = false
      }
    },
    shelfPreviewRetry () {
      const it = this.shelfPreviewItem
      if (it) this.openShelfPreview(it, { force: true })
    },
    shelfPreviewDownload () {
      const p = this.shelfPreviewWorkspaceRel
      if (!p) return
      const name = p.split('/').filter(Boolean).pop() || 'file'
      downloadWorkspaceFile(p, name).catch(e => this.$message.error(this.apiErrorMessage(e, '下载失败')))
    },
    shelfPreviewOpenExternal () {
      const u = this.shelfPreviewExternalUrl
      if (u) window.open(u, '_blank', 'noopener,noreferrer')
    },
    async loadPaperShelf () {
      const sid = this.persistedSessionId
      if (!sid) return
      this.paperShelfLoading = true
      try {
        const res = await listPaperShelf(sid)
        this.paperShelfItems = res.data.items || []
      } catch (e) {
        this.paperShelfItems = []
        this.$message.error(this.apiErrorMessage(e, '加载展示区失败'))
      } finally {
        this.paperShelfLoading = false
      }
    },
    async onDeleteShelfItem (it) {
      const sid = this.persistedSessionId
      if (!sid || !it.id) return
      try {
        await this.$confirm('从展示区移除此条目？', '确认', { type: 'warning' })
      } catch (e) {
        return
      }
      try {
        await deletePaperShelfItem(sid, it.id)
        if (this.shelfPreviewItem && this.shelfPreviewItem.id === it.id) {
          this.closeShelfPreview()
        }
        this.selectedPaperIdsForDeep = this.selectedPaperIdsForDeep.filter(x => x !== it.id)
        await this.loadPaperShelf()
      } catch (e) {
        this.$message.error(this.apiErrorMessage(e, '删除失败'))
      }
    },
    async startDeepResearch () {
      const content = this.deepDraft.trim()
      if (!content) {
        this.$message.warning('请填写深度研究提示词')
        return
      }
      if (!this.selectedPaperIdsForDeep.length) {
        this.$message.warning('请勾选至少一条展示区文献')
        return
      }
      let sid = this.persistedSessionId
      if (!sid) {
        try {
          sid = await this.ensurePersistedSession()
        } catch (e) {
          this.$message.error(this.apiErrorMessage(e, '无法创建会话'))
          return
        }
      }
      this.deepStarting = true
      try {
        /* eslint-disable camelcase */
        const res = await createDeepResearchTask({
          session_id: sid,
          content,
          selected_papers: [...this.selectedPaperIdsForDeep]
        })
        /* eslint-enable camelcase */
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        this.taskOrchestrator = 'deep_research'
        this.taskProgress = 0
        this.deepDraft = ''
        this.selectedPaperIdsForDeep = []
        const newSid = res.data.session_id
        if (newSid && newSid !== this.$route.params.sessionId) {
          await this.$router.push({ path: `/research-agent/session/${newSid}` })
          await this.$nextTick()
        }
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
        if (this.persistedSessionId) {
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
        this.lastWorkspaceSyncDuringTaskTs = 0
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
      const sid = this.persistedSessionId
      if (!sid) return
      try {
        const res = await this.$prompt('请输入新的会话标题', '重命名会话', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          inputValue: this.sessionTitle || '',
          inputValidator: (val) => !!(val && val.trim()),
          inputErrorMessage: '标题不能为空'
        })
        const nextTitle = (res.value || '').trim()
        await updateSessionTitle(sid, nextTitle)
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
      const sid = this.persistedSessionId
      if (!sid) return
      if (!this.currentSessionId) this.currentSessionId = sid
      if (this.pollInFlight) return
      this.pollInFlight = true
      try {
        const wasTaskActive = this.isTaskActiveStatus()
        const prevMsgCount = (this.messages || []).length
        const sRes = await getSession(sid)
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
        const nowTaskActive = this.isTaskActiveStatus()
        if (!wasTaskActive && nowTaskActive) {
          this.wsRefresh()
          this.lastWorkspaceSyncDuringTaskTs = Date.now()
        } else if (nowTaskActive) {
          const now = Date.now()
          if (now - this.lastWorkspaceSyncDuringTaskTs >= 5000) {
            this.lastWorkspaceSyncDuringTaskTs = now
            this.wsRefresh()
          }
        }
        if (wasTaskActive && !nowTaskActive) {
          this.lastWorkspaceSyncDuringTaskTs = 0
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
      if (!this.persistedSessionId) return
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
        if (!this.persistedSessionId) {
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
          res = await postMessage(this.persistedSessionId, body)
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
        this.$delete(this.wsSelectedMap, item.rel_path)
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
  height: calc(100vh - 64px);
  max-height: calc(100vh - 64px);
  padding: 64px 12px 2px;
  text-align: left;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
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
  max-width: 1680px;
  margin: 0 auto;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
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
  padding: 10px 14px;
  margin-bottom: 8px;
  flex-shrink: 0;
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
.ra-toolbar-hint {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: #909399;
  max-width: 560px;
}
.ra-icon-text {
  padding: 0 4px;
}
.ra-grid {
  display: flex;
  gap: 10px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.ra-body {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ra-shelf-preview-root {
  position: absolute;
  inset: 0;
  z-index: 34;
  background: rgba(15, 23, 42, 0.14);
}
.ra-shelf-preview-panel {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  box-sizing: border-box;
  padding: 8px 14px 10px 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  box-shadow: 10px 0 36px rgba(0, 0, 0, 0.18);
  border-radius: 0 12px 12px 0;
}
.ra-sp-resize-handle {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 10px;
  z-index: 6;
  cursor: ew-resize;
  background: transparent;
  border-radius: 0 12px 12px 0;
}
.ra-sp-resize-handle:hover {
  background: rgba(64, 158, 255, 0.14);
}
.ra-sp-slide-enter-active,
.ra-sp-slide-leave-active {
  transition: opacity 0.22s ease;
}
.ra-sp-slide-enter-active .ra-shelf-preview-panel,
.ra-sp-slide-leave-active .ra-shelf-preview-panel,
.ra-sp-slide-enter-to .ra-shelf-preview-panel {
  transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1);
}
.ra-sp-slide-enter,
.ra-sp-slide-leave-to {
  opacity: 0;
}
.ra-sp-slide-enter .ra-shelf-preview-panel,
.ra-sp-slide-leave-to .ra-shelf-preview-panel {
  transform: translateX(-100%);
}
.ra-sp-slide-enter-to .ra-shelf-preview-panel {
  transform: translateX(0);
}
.ra-sp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
  margin-bottom: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e8edf7;
}
.ra-sp-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a2b4a;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ra-sp-body {
  flex: 1;
  min-height: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ra-sp-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}
.ra-sp-iframe {
  flex: 1;
  min-height: 360px;
  width: 100%;
  border: none;
  border-radius: 8px;
  background: #f5f7fa;
}
.ra-sp-pre {
  margin: 0;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #edf2f7;
}
.ra-sp-img-wrap {
  flex: 1;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  background: #0f172a08;
  border-radius: 8px;
}
.ra-sp-img {
  max-width: 100%;
  max-height: min(78vh, 900px);
  object-fit: contain;
  border-radius: 6px;
}
.ra-sp-fallback {
  padding: 4px 2px 8px;
}
.ra-sp-abs {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
}
.ra-shelf-row.is-preview-active {
  border-color: #b3d8ff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.25);
  background: linear-gradient(135deg, #f0f7ff 0%, #fbfdff 100%);
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
.ra-side-head.is-collapsed {
  flex-direction: column;
  justify-content: flex-start;
  align-items: center;
  gap: 10px;
}
.ra-side-collapse-btn {
  flex-shrink: 0;
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
  /* 中间栏占满左右栏之间的剩余空间，并保证最窄不低于可读宽度 */
  flex: 1 1 600px;
  min-width: 540px;
  padding: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.ra-center-stack {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  /* 对话正文区固定可读宽度，居中；与气泡 max-width 配合，避免「随短句变窄」 */
  width: 100%;
  max-width: 920px;
  margin-left: auto;
  margin-right: auto;
  box-sizing: border-box;
}
.ra-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 18px 18px 10px;
  -webkit-overflow-scrolling: touch;
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
  box-sizing: border-box;
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
.ra-msg-bubble.is-user {
  max-width: 88%;
  width: fit-content;
  background: linear-gradient(135deg, #e3f0ff 0%, #f0f7ff 100%);
  border: 1px solid #cfe6ff;
}
.ra-msg-bubble.is-assistant {
  width: 100%;
  max-width: 100%;
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
.ra-md-inline >>> h1,
.ra-md-inline >>> h2,
.ra-md-inline >>> h3 {
  font-weight: 650;
  color: #1a2b4a;
  line-height: 1.35;
  margin: 0.65em 0 0.4em;
}
.ra-md-inline >>> h1 {
  font-size: 1.15rem;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 0.25em;
}
.ra-md-inline >>> h2 {
  font-size: 1.05rem;
}
.ra-md-inline >>> h3 {
  font-size: 1rem;
  font-weight: 600;
  color: #303133;
}
.ra-md-inline >>> ul,
.ra-md-inline >>> ol {
  margin: 0.4em 0;
  padding-left: 1.2em;
}
.ra-md-inline >>> blockquote {
  margin: 0.5em 0;
  padding: 0.35em 0.75em;
  border-left: 3px solid #dcdfe6;
  color: #606266;
  background: #f8f9fb;
  font-size: 13px;
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
  flex-shrink: 0;
  align-self: center;
  margin: 6px auto 8px;
  z-index: 2;
}
.ra-intervention {
  flex-shrink: 0;
  margin: 0 16px 10px;
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
  flex-shrink: 0;
  border-top: 1px solid #e8edf7;
  padding: 14px 18px 16px;
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
  flex: 0 0 460px;
  width: 460px;
  max-width: 460px;
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
  padding: 8px 4px 4px;
  min-height: 0;
}
.ra-shelf-tab {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.ra-deep-panel {
  flex-shrink: 0;
  margin-top: 12px;
  margin-bottom: 0;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid #d9e8ff;
  background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%);
}
.ra-deep-panel-hd {
  font-size: 13px;
  font-weight: 600;
  color: #1a2b4a;
  margin-bottom: 8px;
}
.ra-deep-panel-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}
.ra-deep-meta {
  margin: 0;
}
.ra-pane-intro {
  font-size: 12px;
  line-height: 1.55;
  color: #6b7c93;
  margin: 0 0 10px;
}
.ra-shelf-list {
  flex: 1;
  min-height: 80px;
  overflow-y: auto;
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
.ra-ws-clipboard {
  margin: 0 0 8px;
}
.ra-ws-selection {
  margin: 0 0 10px;
  padding: 8px 10px;
  border: 1px solid #d9ecff;
  border-radius: 10px;
  background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%);
}
.ra-ws-selection-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.ra-ws-selection-title {
  font-size: 12px;
  color: #4a5d77;
  line-height: 1.5;
}
.ra-ws-selection-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ra-ws-selection-more {
  align-self: center;
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
  gap: 10px;
  padding: 9px 12px;
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
  gap: 10px;
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
  white-space: nowrap;
}
.ra-ws-ops {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 54px;
}
.ra-ws-more-btn {
  color: #5b6b81;
  padding: 0 2px;
}
.ra-ws-more-btn:hover,
.ra-ws-more-btn:focus {
  color: #409eff;
}
.ra-ws-upload {
  margin-top: 10px;
}
.ra-ws-transfer-summary {
  margin: 10px 0 12px;
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}
.ra-ws-transfer-summary strong {
  color: #303133;
  margin-right: 6px;
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
  .ra-col-center {
    flex: 1 1 auto;
    min-width: 0;
    max-width: none;
  }
  .ra-center-stack {
    max-width: none;
    margin-left: 0;
    margin-right: 0;
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
