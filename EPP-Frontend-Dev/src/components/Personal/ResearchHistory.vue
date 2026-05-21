<template>
  <div class="research-history">
    <div v-loading="loading" class="history-container">
      <!-- 统计头部 -->
      <div class="history-header">
        <div class="header-title">
          <i class="el-icon-reading" />
          <span>深度研究历史</span>
          <span class="history-count">共 {{ sessions.length }} 条记录</span>
        </div>
        <el-button
          size="small"
          type="text"
          icon="el-icon-refresh"
          :loading="loading"
          @click="loadHistory"
        >
          刷新
        </el-button>
      </div>

      <!-- 历史列表 -->
      <div class="history-list">
        <div
          v-for="session in sessions"
          :key="session.session_id"
          class="history-card"
          :class="{ 'is-expanded': expanded[session.session_id] }"
        >
          <!-- 卡片头部 -->
          <div class="card-header" @click="toggleExpand(session.session_id)">
            <div class="header-left">
              <i :class="expanded[session.session_id] ? 'el-icon-arrow-down' : 'el-icon-arrow-right'" class="expand-icon" />
              <div class="session-info">
                <div class="session-title">{{ session.displayTitle || session.title || '深度研究会话' }}</div>
                <div class="session-time">
                  <i class="el-icon-time" />
                  {{ formatDateTime(session.updated_at) }}
                </div>
              </div>
            </div>
            <div class="header-right" @click.stop>
              <el-badge :value="session.citations ? session.citations.length : 0" :hidden="!session.citations || session.citations.length === 0" class="paper-badge">
                <el-button
                  type="text"
                  size="small"
                  class="paper-count-btn"
                  @click="toggleExpand(session.session_id)"
                >
                  <i class="el-icon-document" />
                  <span v-if="session.citations && session.citations.length">{{ session.citations.length }}篇参考</span>
                  <span v-else>暂无参考</span>
                </el-button>
              </el-badge>
              <el-popconfirm
                title="确定删除此会话吗？"
                @confirm="deleteSession(session.session_id)"
              >
                <el-button
                  slot="reference"
                  type="text"
                  size="small"
                  class="delete-btn"
                  icon="el-icon-delete"
                />
              </el-popconfirm>
            </div>
          </div>

          <!-- 卡片内容（展开后显示参考来源列表） -->
          <transition name="expand">
            <div v-if="expanded[session.session_id]" class="card-content">
              <!-- 参考来源列表 -->
              <div v-if="session.citations && session.citations.length" class="papers-section">
                <div class="papers-header">
                  <span>📚 参考来源（{{ session.citations.length }}篇）</span>
                </div>
                <div class="papers-list">
                  <div
                    v-for="(citation, idx) in getDisplayCitations(session)"
                    :key="citation.url || idx"
                    class="paper-item"
                    @click="openCitationLink(citation.url)"
                  >
                    <div class="paper-icon">
                      <i class="el-icon-document" />
                    </div>
                    <div class="paper-info">
                      <div class="paper-title">{{ truncate(citation.title || '未命名论文', 80) }}</div>
                    </div>
                  </div>
                  <!-- 展开全部按钮 -->
                  <div v-if="session.citations.length > 3 && !session.showAllCitations" class="more-papers-btn">
                    <el-button type="text" size="small" @click.stop="toggleShowAllCitations(session.session_id)">
                      <i class="el-icon-arrow-down" />
                      展开全部 {{ session.citations.length }} 篇参考来源
                    </el-button>
                  </div>
                  <!-- 收起按钮 -->
                  <div v-if="session.showAllCitations" class="more-papers-btn">
                    <el-button type="text" size="small" @click.stop="toggleShowAllCitations(session.session_id)">
                      <i class="el-icon-arrow-up" />
                      收起
                    </el-button>
                  </div>
                </div>
              </div>
              <div v-else class="empty-papers">
                <i class="el-icon-info" />
                <span>暂无参考来源</span>
              </div>

              <!-- 底部操作 - 只保留继续对话按钮 -->
              <div class="card-footer">
                <el-button
                  type="primary"
                  size="small"
                  plain
                  icon="el-icon-chat-dot-round"
                  @click="goToSession(session.session_id)"
                >
                  继续对话
                </el-button>
              </div>
            </div>
          </transition>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && sessions.length === 0" class="empty-history">
        <div class="empty-icon">
          <i class="el-icon-reading" />
        </div>
        <p>暂无深度研究历史</p>
        <p class="empty-hint">在深度研究页面开始你的第一次深度研究吧</p>
        <el-button type="primary" size="small" @click="goToDeepResearch">前往深度研究</el-button>
      </div>
    </div>
  </div>
</template>

<script>
/* eslint-disable */ 
import { listSessions, deleteSession, getSession } from '@/views/ResearchAgent/researchAgentApi.js'

export default {
  name: 'ResearchHistory',
  data() {
    return {
      loading: false,
      sessions: [],
      expanded: {},
      citationsCache: {}
    }
  },
  mounted() {
    this.loadHistory()
  },
  methods: {
    async loadHistory() {
      this.loading = true
      try {
        const res = await listSessions({ page: 1, page_size: 50 })
        let allSessions = res.data.items || []
        const deepSessions = allSessions.filter(s => {
          return s.title && (
            s.title.includes('深度研究') || 
            s.title.includes('Deep Research') ||
            s.title !== '新会话'
          )
        })
        
        this.sessions = []
        for (const session of deepSessions) {
          const citations = await this.loadCitationsForSession(session.session_id)
          let displayTitle = session.title
          if (displayTitle === '深度研究会话' || displayTitle === '新会话') {
            displayTitle = session.title
          }
          this.sessions.push({
            ...session,
            displayTitle: displayTitle,
            citations: citations,
            showAllCitations: false
          })
        }
      } catch (e) {
        console.error('加载历史失败', e)
        this.$message.error('加载历史失败')
      } finally {
        this.loading = false
      }
    },

    async loadCitationsForSession(sessionId) {
      if (this.citationsCache[sessionId]) {
        return this.citationsCache[sessionId]
      }
      try {
        const res = await getSession(sessionId)
        const sessionData = res.data
        const at = sessionData.active_task || sessionData.latest_task
        const citations = (at && at.result && at.result.citations) || []
        this.citationsCache[sessionId] = citations
        return citations
      } catch (e) {
        console.error(`加载会话 ${sessionId} 参考来源失败`, e)
        return []
      }
    },

    toggleExpand(sessionId) {
      this.$set(this.expanded, sessionId, !this.expanded[sessionId])
    },

    toggleShowAllCitations(sessionId) {
      const session = this.sessions.find(s => s.session_id === sessionId)
      if (session) {
        session.showAllCitations = !session.showAllCitations
        this.$forceUpdate()
      }
    },

    getDisplayCitations(session) {
      if (session.showAllCitations) {
        return session.citations
      }
      return (session.citations || []).slice(0, 3)
    },

    openCitationLink(url) {
      if (url) {
        window.open(url, '_blank')
      } else {
        this.$message.info('该参考来源暂无链接')
      }
    },

    goToSession(sessionId) {
      // 使用路由跳转并传递 session_id 参数，确保深度研究页面能加载对应会话
      this.$router.push({
        path: '/deep-research',
        query: { session_id: sessionId }
      })
    },

    goToDeepResearch() {
      this.$router.push('/deep-research')
    },

    async deleteSession(sessionId) {
      try {
        await deleteSession(sessionId)
        this.$message.success('删除成功')
        this.sessions = this.sessions.filter(s => s.session_id !== sessionId)
        delete this.citationsCache[sessionId]
        delete this.expanded[sessionId]
      } catch (e) {
        console.error('删除失败', e)
        this.$message.error('删除失败')
      }
    },

    formatDateTime(dateStr) {
      if (!dateStr) return ''
      const date = new Date(dateStr)
      const year = date.getFullYear()
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hours = String(date.getHours()).padStart(2, '0')
      const minutes = String(date.getMinutes()).padStart(2, '0')
      const seconds = String(date.getSeconds()).padStart(2, '0')
      return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
    },

    truncate(text, maxLength) {
      if (!text) return ''
      if (text.length <= maxLength) return text
      return text.slice(0, maxLength) + '...'
    }
  }
}
</script>

<style scoped>
.research-history {
  padding: 20px;
  min-height: 500px;
}

.history-container {
  max-width: 1000px;
  margin: 0 auto;
}

/* 头部 */
.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid #e8e8e8;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.header-title i {
  font-size: 24px;
  color: #409eff;
}

.history-count {
  font-size: 13px;
  font-weight: normal;
  color: #909399;
  background: #f5f7fa;
  padding: 2px 10px;
  border-radius: 20px;
}

/* 卡片 */
.history-card {
  background: white;
  border-radius: 16px;
  margin-bottom: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  transition: all 0.3s ease;
  overflow: hidden;
}

.history-card:hover {
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
}

.history-card.is-expanded {
  box-shadow: 0 4px 20px rgba(64, 158, 255, 0.12);
}

/* 卡片头部 */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  cursor: pointer;
  transition: background 0.2s;
}

.card-header:hover {
  background: #f8f9fa;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.expand-icon {
  font-size: 14px;
  color: #909399;
  transition: transform 0.2s;
}

.session-info {
  flex: 1;
}

.session-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}

.session-time {
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: center;
  gap: 4px;
}

.session-time i {
  font-size: 12px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.paper-badge >>> .el-badge__content {
  background-color: #409eff;
}

.paper-count-btn {
  color: #606266;
  display: flex;
  align-items: center;
  gap: 6px;
}

.paper-count-btn:hover {
  color: #409eff;
}

.delete-btn {
  color: #f56c6c;
}

.delete-btn:hover {
  color: #f56c6c;
  background: rgba(245, 108, 108, 0.1);
}

/* 卡片内容 */
.card-content {
  border-top: 1px solid #f0f0f0;
  padding: 16px 20px;
  background: #fafbfc;
}

.papers-section {
  margin-bottom: 16px;
}

.papers-header {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 500;
  color: #606266;
}

.papers-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.paper-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  background: white;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid #f0f0f0;
}

.paper-item:hover {
  border-color: #409eff;
  background: #f5faff;
  transform: translateX(4px);
}

.paper-icon {
  width: 32px;
  height: 32px;
  background: #f5f7fa;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  flex-shrink: 0;
}

.paper-info {
  flex: 1;
  min-width: 0;
}

.paper-title {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  line-height: 1.4;
  word-break: break-word;
}

.more-papers-btn {
  text-align: center;
  padding: 8px 0 4px;
}

.empty-papers {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: #c0c4cc;
  font-size: 13px;
  background: white;
  border-radius: 10px;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid #e8e8e8;
  margin-top: 8px;
}

/* 展开动画 */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
}

.expand-enter,
.expand-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* 空状态 */
.empty-history {
  text-align: center;
  padding: 60px 20px;
  background: white;
  border-radius: 16px;
}

.empty-icon {
  font-size: 64px;
  color: #c0c4cc;
  margin-bottom: 16px;
}

.empty-history p {
  color: #909399;
  margin: 8px 0;
}

.empty-hint {
  font-size: 13px;
  color: #c0c4cc;
  margin-bottom: 20px;
}

/* 响应式 */
@media (max-width: 768px) {
  .research-history {
    padding: 12px;
  }
  
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  
  .header-right {
    width: 100%;
    justify-content: flex-end;
  }
  
  .paper-item {
    flex-direction: column;
  }
  
  .paper-icon {
    display: none;
  }
}
</style>