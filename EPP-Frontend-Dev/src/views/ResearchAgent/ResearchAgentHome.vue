<template>
  <div class="ra-home">
    <header class="ra-header ra-card">
      <div class="ra-header-row">
        <div>
          <h1>科研智能助手会话管理</h1>
          <p class="ra-subtitle">统一管理历史会话、重命名与批量清理</p>
        </div>
        <div class="ra-header-actions">
          <el-button
            v-if="!batchMode"
            size="small"
            type="danger"
            plain
            @click="enterBatchMode"
          >
            批量删除
          </el-button>
          <template v-else>
            <el-button size="small" type="primary" plain @click="toggleSelectAll">
              {{ allSelected ? '全不选' : '全选' }}
            </el-button>
            <el-button size="small" @click="cancelBatchMode">取消</el-button>
            <el-button
              size="small"
              type="danger"
              :disabled="!selectedSessionIds.length"
              @click="confirmBatchDelete"
            >
              确认删除
            </el-button>
          </template>
          <el-button size="small" @click="$router.push('/research-agent')">返回</el-button>
        </div>
      </div>
      <div class="ra-metrics">
        <span class="ra-metric">会话总数：{{ items.length }}</span>
        <span v-if="batchMode" class="ra-metric ra-metric-active">已勾选：{{ selectedSessionIds.length }}</span>
      </div>
    </header>
    <section class="ra-table-wrap ra-card">
      <el-table :data="items" stripe>
        <el-table-column label="标题" min-width="280">
          <template slot-scope="scope">
            <div class="ra-title-cell">
              <el-checkbox
                v-if="batchMode"
                :value="isSelected(scope.row.session_id)"
                @change="toggleSelected(scope.row.session_id, $event)"
              />
              <span class="ra-title-text">{{ scope.row.title }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="updated_at" label="更新时间" width="210" />
        <el-table-column label="操作" width="170" align="center">
          <template slot-scope="scope">
            <el-tooltip content="进入会话" placement="top">
              <el-button type="text" icon="el-icon-right" :disabled="batchMode" @click="goSession(scope.row.session_id)" />
            </el-tooltip>
            <el-tooltip content="重命名会话" placement="top">
              <el-button
                type="text"
                icon="el-icon-edit"
                class="ra-rename-btn"
                :disabled="batchMode"
                @click="onRenameSession(scope.row)"
              />
            </el-tooltip>
            <el-tooltip content="删除会话" placement="top">
              <el-button
                type="text"
                icon="el-icon-delete"
                class="ra-delete-btn"
                :disabled="batchMode"
                @click="onDeleteSession(scope.row.session_id)"
              />
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script>
import { listSessions, deleteSession, updateSessionTitle, batchDeleteSessions } from './researchAgentApi.js'

export default {
  name: 'ResearchAgentHome',
  data () {
    return {
      items: [],
      batchMode: false,
      selectedSessionIds: []
    }
  },
  created () {
    this.load()
  },
  computed: {
    allSelected () {
      if (!this.items.length) return false
      return this.selectedSessionIds.length === this.items.length
    }
  },
  methods: {
    async load () {
      try {
        const res = await listSessions({ page: 1, page_size: 50 })
        this.items = res.data.items || []
        const validIds = new Set(this.items.map(item => item.session_id))
        this.selectedSessionIds = this.selectedSessionIds.filter(id => validIds.has(id))
      } catch (e) {
        this.$message.error('加载会话列表失败')
      }
    },
    goSession (sessionId) {
      this.$router.push({ path: `/research-agent/session/${sessionId}` })
    },
    enterBatchMode () {
      this.batchMode = true
      this.selectedSessionIds = []
    },
    cancelBatchMode () {
      this.batchMode = false
      this.selectedSessionIds = []
    },
    toggleSelectAll () {
      if (!this.items.length) {
        this.selectedSessionIds = []
        return
      }
      this.selectedSessionIds = this.allSelected
        ? []
        : this.items.map(item => item.session_id)
    },
    isSelected (sessionId) {
      return this.selectedSessionIds.includes(sessionId)
    },
    toggleSelected (sessionId, checked) {
      if (checked) {
        if (!this.selectedSessionIds.includes(sessionId)) {
          this.selectedSessionIds.push(sessionId)
        }
        return
      }
      this.selectedSessionIds = this.selectedSessionIds.filter(id => id !== sessionId)
    },
    confirmBatchDelete () {
      const count = this.selectedSessionIds.length
      if (!count) return
      this.$confirm(`将删除 ${count} 个会话，此操作不可撤回`, '确认批量删除', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        await batchDeleteSessions(this.selectedSessionIds)
        this.$message.success(`已删除 ${count} 个会话`)
        this.cancelBatchMode()
        this.load()
      }).catch((e) => {
        if (e !== 'cancel' && e !== 'close') {
          this.$message.error('批量删除失败')
        }
      })
    },
    async onRenameSession (row) {
      try {
        const res = await this.$prompt('请输入新的会话标题', '重命名会话', {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          inputValue: row.title || '',
          inputValidator: (val) => !!(val && val.trim()),
          inputErrorMessage: '标题不能为空'
        })
        const nextTitle = (res.value || '').trim()
        await updateSessionTitle(row.session_id, nextTitle)
        this.$message.success('标题已更新')
        this.load()
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') {
          this.$message.error('重命名失败')
        }
      }
    },
    onDeleteSession (sessionId) {
      this.$confirm('将删除会话，此操作不可撤回', '确认删除', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }).then(async () => {
        await deleteSession(sessionId)
        this.$message.success('会话已删除')
        this.load()
      }).catch((e) => {
        if (e !== 'cancel' && e !== 'close') {
          this.$message.error('删除会话失败')
        }
      })
    }
  }
}
</script>

<style scoped>
.ra-home {
  min-height: 100vh;
  padding: 84px 16px 48px;
  background: linear-gradient(180deg, #eef4ff 0%, #f8fbff 38%, #fff 100%);
  text-align: left;
}
.ra-header {
  max-width: 960px;
  margin: 0 auto 18px;
}
.ra-card {
  border: 1px solid #dbe8ff;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 4px 14px rgba(64, 158, 255, 0.08);
  padding: 14px 16px;
}
.ra-header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.ra-header-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.ra-header h1 {
  margin: 0;
  font-size: 1.35rem;
  color: #1f2d3d;
}
.ra-subtitle {
  margin: 6px 0 0;
  color: #7b8aa0;
  font-size: 13px;
}
.ra-metrics {
  margin-top: 10px;
  display: flex;
  gap: 10px;
}
.ra-metric {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  color: #5f6b7a;
  background: #f3f7ff;
  border: 1px solid #e0ebff;
}
.ra-metric-active {
  color: #2f71ff;
  background: #edf4ff;
  border-color: #c8ddff;
}
.ra-table-wrap {
  max-width: 960px;
  margin: 0 auto;
}
.ra-table-wrap >>> .el-table {
  border-radius: 10px;
  overflow: hidden;
}
.ra-title-cell {
  display: flex;
  align-items: center;
}
.ra-title-text {
  margin-left: 8px;
}
.ra-title-link {
  padding: 0;
  border: none;
  background: transparent;
  color: #409eff;
  cursor: pointer;
  text-align: left;
  font: inherit;
}
.ra-title-link:hover {
  text-decoration: underline;
}
.ra-title-link.is-disabled {
  color: #909399;
  cursor: not-allowed;
}
.ra-rename-btn {
  margin-left: 4px;
}
.ra-delete-btn {
  color: #f56c6c;
  margin-left: 6px;
}
</style>
