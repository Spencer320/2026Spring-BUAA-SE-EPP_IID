<template>
  <div class="ra-home">
    <header class="ra-header">
      <div class="ra-header-row">
        <h1>科研智能助手会话管理</h1>
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
    </header>
    <el-table :data="items" stripe style="width: 100%; max-width: 960px; margin: 24px auto;">
      <el-table-column label="标题" min-width="260">
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
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="updated_at" label="更新时间" width="200" />
      <el-table-column label="操作" width="150" align="center">
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
  methods: {
    async load () {
      try {
        const res = await listSessions({ page: 1, page_size: 50 })
        this.items = res.data.items || []
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
  background: linear-gradient(180deg, #f6f8fc 0%, #fff 40%);
  text-align: left;
}
.ra-header {
  max-width: 960px;
  margin: 0 auto;
}
.ra-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ra-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ra-header h1 {
  margin: 0 0 8px;
  font-size: 2rem;
  color: #1a1a2e;
}
.ra-title-cell {
  display: flex;
  align-items: center;
}
.ra-title-text {
  margin-left: 8px;
}
.ra-rename-btn {
  margin-left: 4px;
}
.ra-delete-btn {
  color: #f56c6c;
  margin-left: 6px;
}
</style>
