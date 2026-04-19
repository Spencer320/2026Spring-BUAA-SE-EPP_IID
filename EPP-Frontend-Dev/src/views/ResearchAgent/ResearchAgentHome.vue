<template>
  <div class="ra-home">
    <header class="ra-header">
      <h1>科研智能助手</h1>
      <p class="ra-sub">创建或进入会话，发送自然语言指令启动 Mock 调研任务</p>
      <el-button type="primary" :loading="creating" @click="onCreate">新建会话</el-button>
      <el-button @click="$router.push('/search')">返回文献调研</el-button>
    </header>
    <el-table :data="items" stripe style="width: 100%; max-width: 960px; margin: 24px auto;">
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="updated_at" label="更新时间" width="200" />
      <el-table-column label="操作" width="120">
        <template slot-scope="scope">
          <el-button type="text" @click="goSession(scope.row.session_id)">进入</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
import { listSessions, createSession } from './researchAgentApi.js'

export default {
  name: 'ResearchAgentHome',
  data () {
    return {
      items: [],
      creating: false
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
    async onCreate () {
      this.creating = true
      try {
        const res = await createSession({ title: '新会话' })
        const id = res.data.session_id
        this.$router.push({ name: 'ResearchAgentSession', params: { sessionId: id } })
      } catch (e) {
        this.$message.error('创建会话失败')
      } finally {
        this.creating = false
      }
    },
    goSession (sessionId) {
      this.$router.push({ name: 'ResearchAgentSession', params: { sessionId } })
    }
  }
}
</script>

<style scoped>
.ra-home {
  min-height: 100vh;
  padding: 24px 16px 48px;
  background: linear-gradient(180deg, #f6f8fc 0%, #fff 40%);
  text-align: left;
}
.ra-header {
  max-width: 960px;
  margin: 0 auto;
}
.ra-header h1 {
  margin: 0 0 8px;
  font-size: 1.5rem;
  color: #1a1a2e;
}
.ra-sub {
  margin: 0 0 16px;
  color: #606266;
  font-size: 0.95rem;
}
</style>
