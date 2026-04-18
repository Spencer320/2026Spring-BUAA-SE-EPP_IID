<template>
  <div class="ra-session">
    <header class="ra-top">
      <div>
        <h1>科研智能助手</h1>
        <p class="ra-meta">{{ sessionTitle }} · {{ taskStatusLabel }}</p>
      </div>
      <div>
        <el-button size="small" @click="$router.push({ name: 'ResearchAgentHome' })">返回列表</el-button>
      </div>
    </header>

    <div class="ra-layout">
      <aside class="ra-sidebar">
        <h3>任务步骤</h3>
        <ul v-if="steps.length" class="ra-step-list">
          <li v-for="s in steps" :key="s.seq" class="ra-step-item">
            <span class="ra-ts">{{ s.ts }}</span>
            <strong>{{ s.title }}</strong>
            <div class="ra-phase">{{ s.phase }}</div>
            <div class="ra-detail">{{ s.detail }}</div>
          </li>
        </ul>
        <p v-else class="ra-muted">尚无步骤，发送指令后可见</p>
      </aside>

      <main class="ra-main">
        <div class="ra-messages" ref="msgBox">
          <div
            v-for="(m, idx) in messages"
            :key="idx"
            :class="['ra-bubble', m.role === 'user' ? 'is-user' : 'is-assistant']"
          >
            <span class="ra-role">{{ m.role === 'user' ? '我' : '助手' }}</span>
            <div class="ra-content" v-html="formatMsg(m.content)"></div>
          </div>
        </div>

        <el-card v-if="resultHtml" class="ra-result" shadow="never">
          <div slot="header">成果（Markdown）</div>
          <div class="ra-md" v-html="resultHtml"></div>
        </el-card>

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
          <el-button type="primary" :disabled="inputLocked || !draft.trim()" @click="send">发送</el-button>
        </footer>
      </main>
    </div>
  </div>
</template>

<script>
import MarkdownIt from 'markdown-it'
import { getSession, postMessage, postIntervention, getTask } from './researchAgentApi.js'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])
const md = new MarkdownIt({ breaks: true, linkify: true })

export default {
  name: 'ResearchAgentSession',
  data () {
    return {
      sessionTitle: '',
      messages: [],
      steps: [],
      taskId: null,
      taskStatus: '',
      intervention: null,
      resultBody: null,
      draft: '',
      reviseDraft: '',
      pollTimer: null
    }
  },
  computed: {
    taskStatusLabel () {
      return this.taskStatus ? `任务：${this.taskStatus}` : '无活跃任务'
    },
    resultHtml () {
      if (!this.resultBody || !this.resultBody.body) return ''
      return md.render(this.resultBody.body)
    },
    interventionVisible () {
      return this.taskStatus === 'waiting_user' && this.intervention
    },
    inputLocked () {
      if (!this.taskStatus) return false
      return !TERMINAL.has(this.taskStatus)
    }
  },
  watch: {
    '$route.params.sessionId' () {
      this.reload()
    }
  },
  created () {
    this.reload()
  },
  beforeDestroy () {
    this.stopPoll()
  },
  methods: {
    formatMsg (text) {
      return md.render(text || '')
    },
    async reload () {
      const sid = this.$route.params.sessionId
      if (!sid) return
      try {
        const res = await getSession(sid)
        const d = res.data
        this.sessionTitle = d.title
        this.messages = d.messages || []
        const at = d.active_task
        if (at) {
          this.taskId = at.task_id
          this.taskStatus = at.status
          this.steps = at.steps || []
          this.intervention = at.intervention
          this.resultBody = at.result
        } else {
          this.taskId = null
          this.taskStatus = ''
          this.steps = []
          this.intervention = null
          this.resultBody = null
        }
        this.$nextTick(() => this.scrollMsg())
        this.syncPoll()
      } catch (e) {
        this.$message.error('加载会话失败')
        this.$router.push({ name: 'ResearchAgentHome' })
      }
    },
    scrollMsg () {
      const el = this.$refs.msgBox
      if (el) el.scrollTop = el.scrollHeight
    },
    syncPoll () {
      this.stopPoll()
      const need = this.taskId && (this.taskStatus === 'running' || this.taskStatus === 'waiting_user' || this.taskStatus === 'pending')
      if (!need) return
      this.pollTimer = setInterval(async () => {
        try {
          const res = await getTask(this.taskId)
          const t = res.data
          this.taskStatus = t.status
          this.steps = t.steps || []
          this.intervention = t.intervention
          this.resultBody = t.result
          if (TERMINAL.has(t.status)) {
            this.stopPoll()
            await this.reload()
          }
        } catch (e) {
          this.stopPoll()
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
      const sid = this.$route.params.sessionId
      this.draft = ''
      try {
        const res = await postMessage(sid, content)
        this.taskId = res.data.task_id
        this.taskStatus = res.data.status || 'pending'
        await this.reload()
        this.syncPoll()
      } catch (e) {
        const msg = (e.response && e.response.data && e.response.data.err) || '发送失败'
        this.$message.error(msg)
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
        const msg = (e.response && e.response.data && e.response.data.err) || '提交失败'
        this.$message.error(msg)
      }
    }
  }
}
</script>

<style scoped>
.ra-session {
  min-height: 100vh;
  padding: 16px;
  background: #f0f2f5;
  text-align: left;
}
.ra-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  max-width: 1200px;
  margin: 0 auto 16px;
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
}
.ra-layout {
  display: flex;
  max-width: 1200px;
  margin: 0 auto;
  gap: 16px;
  align-items: flex-start;
}
.ra-sidebar {
  width: 280px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.ra-sidebar h3 {
  margin: 0 0 12px;
  font-size: 1rem;
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
  min-height: 480px;
}
.ra-messages {
  flex: 1;
  max-height: 360px;
  overflow-y: auto;
  margin-bottom: 12px;
}
.ra-bubble {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  text-align: left;
}
.ra-bubble.is-user {
  background: #ecf5ff;
  margin-left: 48px;
}
.ra-bubble.is-assistant {
  background: #f4f4f5;
  margin-right: 48px;
}
.ra-role {
  font-size: 0.75rem;
  color: #909399;
}
.ra-content {
  margin-top: 4px;
  font-size: 0.95rem;
}
.ra-content >>> p {
  margin: 0.4em 0;
}
.ra-result {
  margin-bottom: 12px;
  text-align: left;
}
.ra-md {
  text-align: left;
  line-height: 1.6;
}
.ra-md >>> h1 {
  font-size: 1.25rem;
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
