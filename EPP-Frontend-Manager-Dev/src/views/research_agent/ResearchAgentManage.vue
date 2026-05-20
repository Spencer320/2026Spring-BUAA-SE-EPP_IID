<template>
    <div class="run-manage-page">
        <el-alert
            title="科研助手任务管理"
            type="info"
            :closable="false"
            description="按 BasicOrchestratorRun 展示：一次科研助手编排对应一行；工作区 Agent 子运行计入该任务，展开行为链路可查看逐步审计。"
            style="margin-bottom: 12px"
        />

        <div class="stats-row" v-loading="statsLoading">
            <div class="stat-card" v-for="card in statCards" :key="card.key">
                <div class="stat-card-value" :style="{ color: card.color }">{{ card.value }}</div>
                <div class="stat-card-label">{{ card.label }}</div>
            </div>
        </div>

        <div class="toolbar">
            <el-input
                v-model.trim="filters.userKeyword"
                clearable
                style="width: 200px"
                placeholder="用户名 / 用户ID"
                @keyup.enter="handleSearch"
            />
            <el-input
                v-model.trim="filters.keyword"
                clearable
                style="width: 220px"
                placeholder="任务名 / 问题关键词"
                @keyup.enter="handleSearch"
            />
            <el-select
                v-model="filters.statusList"
                multiple
                collapse-tags
                clearable
                style="width: 220px"
                placeholder="状态"
            >
                <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
            <el-date-picker
                v-model="filters.dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始"
                end-placeholder="结束"
                value-format="YYYY-MM-DD"
                style="width: 240px"
            />
            <el-button type="primary" @click="handleSearch">查询</el-button>
            <el-button @click="handleReset">重置</el-button>
            <span class="refresh-label">自动刷新(10s)</span>
            <el-switch v-model="autoRefresh" @change="handleAutoRefreshChange" />
        </div>

        <el-table
            :data="taskList"
            v-loading="isLoading"
            stripe
            style="width: 100%; border-top: 1px solid #edebeb"
            :header-cell-style="{ 'text-align': 'center' }"
            :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
        >
            <el-table-column label="任务ID" width="120">
                <template #default="{ row }">
                    <el-tooltip :content="row.task_id" placement="top">
                        <span class="mono-text">{{ shortId(row.task_id) }}</span>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="用户" width="120" prop="user_name" />
            <el-table-column label="任务 / 问题" min-width="200">
                <template #default="{ row }">
                    <div class="ellipsis-cell">{{ row.query || row.task_name || '—' }}</div>
                </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
                <template #default="{ row }">
                    <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="进度" width="140">
                <template #default="{ row }">
                    <el-progress :percentage="row.progress ?? 0" :stroke-width="6" />
                </template>
            </el-table-column>
            <el-table-column label="Token 消耗" width="110">
                <template #default="{ row }">
                    <span v-if="row.token_usage != null" class="mono-text">{{ formatTokens(row.token_usage) }}</span>
                    <span v-else class="text-muted">—</span>
                </template>
            </el-table-column>
            <el-table-column label="子运行" width="90">
                <template #default="{ row }">{{ row.workspace_run_count ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="审计条数" width="100">
                <template #default="{ row }">
                    <span>{{ row.log_count ?? 0 }}</span>
                    <el-tag v-if="row.exception_count > 0" type="danger" size="small" style="margin-left: 4px">
                        {{ row.exception_count }} 异常
                    </el-tag>
                </template>
            </el-table-column>
            <el-table-column label="创建时间" width="170" prop="created_at" />
            <el-table-column label="操作" width="200" fixed="right">
                <template #default="{ row }">
                    <el-button type="primary" link @click="openChain(row.task_id)">行为链路</el-button>
                    <el-button v-if="canCancel(row)" type="danger" link @click="handleCancel(row)">取消</el-button>
                </template>
            </el-table-column>
            <template #empty>
                <el-empty description="暂无科研助手任务" />
            </template>
        </el-table>

        <el-pagination
            class="pagination"
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            :total="total"
        />

        <RunBehaviorChainDrawer ref="chainDrawer" scope="assistant" />
    </div>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAssistantStats, getAssistantTaskList, cancelAssistantTask } from '@/api/research_agent_manage.js'
import { RA_STATUS_MAP } from '@/views/deep_research/dr_constants.js'
import RunBehaviorChainDrawer from '@/components/research_agent/RunBehaviorChainDrawer.vue'

const ACTIVE = new Set(['pending', 'running', 'pending_action'])

export default {
    components: { RunBehaviorChainDrawer },
    data() {
        return {
            statsLoading: false,
            isLoading: false,
            stats: {},
            taskList: [],
            total: 0,
            currentPage: 1,
            pageSize: 20,
            autoRefresh: false,
            refreshTimer: null,
            filters: {
                userKeyword: '',
                keyword: '',
                statusList: [],
                dateRange: []
            },
            statusOptions: Object.entries(RA_STATUS_MAP).map(([value, v]) => ({ value, label: v.label }))
        }
    },
    computed: {
        statCards() {
            return [
                { key: 'running', label: '执行中', value: this.stats.running_count ?? 0, color: '#E6A23C' },
                { key: 'pending', label: '待启动', value: this.stats.pending_count ?? 0, color: '#409EFF' },
                { key: 'today', label: '今日任务', value: this.stats.today_total ?? 0, color: '#303133' },
                { key: 'completed', label: '今日完成', value: this.stats.today_completed ?? 0, color: '#67C23A' },
                { key: 'failed', label: '今日失败', value: this.stats.today_failed ?? 0, color: '#F56C6C' }
            ]
        }
    },
    watch: {
        currentPage() {
            this.fetchTaskList()
        },
        pageSize() {
            this.currentPage = 1
            this.fetchTaskList()
        }
    },
    created() {
        this.fetchAll()
    },
    beforeUnmount() {
        this.stopAutoRefresh()
    },
    methods: {
        shortId(id) {
            if (!id) return '—'
            return id.length <= 12 ? id : `${id.slice(0, 8)}...`
        },
        formatTokens(n) {
            const v = Number(n)
            if (!Number.isFinite(v)) return '—'
            return v.toLocaleString('zh-CN')
        },
        statusLabel(s) {
            return RA_STATUS_MAP[s]?.label || s || '—'
        },
        statusTagType(s) {
            return RA_STATUS_MAP[s]?.type || 'info'
        },
        canCancel(row) {
            return ACTIVE.has(row.status)
        },
        buildParams() {
            const params = { page_num: this.currentPage, page_size: this.pageSize }
            if (this.filters.statusList.length) params.status = this.filters.statusList.join(',')
            if (this.filters.userKeyword) {
                if (/^[0-9a-fA-F-]{32,36}$/.test(this.filters.userKeyword)) params.user_id = this.filters.userKeyword
                else params.username = this.filters.userKeyword
            }
            if (this.filters.keyword) params.keyword = this.filters.keyword
            if (this.filters.dateRange?.length === 2) {
                params.date_from = this.filters.dateRange[0]
                params.date_to = this.filters.dateRange[1]
            }
            return params
        },
        async fetchAll() {
            await Promise.all([this.fetchStats(), this.fetchTaskList()])
        },
        async fetchStats() {
            this.statsLoading = true
            await getAssistantStats()
                .then((res) => {
                    this.stats = res.data || {}
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.error || '获取统计失败')
                })
            this.statsLoading = false
        },
        async fetchTaskList() {
            this.isLoading = true
            await getAssistantTaskList(this.buildParams())
                .then((res) => {
                    this.taskList = res.data.items || []
                    this.total = res.data.total || 0
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.error || '获取任务列表失败')
                })
            this.isLoading = false
        },
        handleSearch() {
            this.currentPage = 1
            this.fetchAll()
        },
        handleReset() {
            this.filters = { userKeyword: '', keyword: '', statusList: [], dateRange: [] }
            this.handleSearch()
        },
        openChain(taskId) {
            this.$refs.chainDrawer.open(taskId)
        },
        async handleCancel(row) {
            await ElMessageBox.confirm(`确定取消任务 ${this.shortId(row.task_id)}？`, '取消任务', {
                type: 'warning'
            })
            await cancelAssistantTask(row.task_id)
                .then(() => {
                    ElMessage.success('已取消')
                    this.fetchAll()
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.error || '取消失败')
                })
        },
        handleAutoRefreshChange(val) {
            if (val) {
                this.refreshTimer = setInterval(() => this.fetchAll(), 10000)
            } else {
                this.stopAutoRefresh()
            }
        },
        stopAutoRefresh() {
            if (this.refreshTimer) {
                clearInterval(this.refreshTimer)
                this.refreshTimer = null
            }
        }
    }
}
</script>

<style lang="scss" scoped>
.run-manage-page {
    width: 100%;
}
.stats-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 12px;
}
.stat-card {
    min-width: 120px;
    padding: 12px 16px;
    background: #fafafa;
    border-radius: 8px;
    border: 1px solid #ebeef5;
}
.stat-card-value {
    font-size: 22px;
    font-weight: 600;
}
.stat-card-label {
    font-size: 13px;
    color: #909399;
    margin-top: 4px;
}
.toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
}
.refresh-label {
    font-size: 13px;
    color: #909399;
    margin-left: 8px;
}
.pagination {
    margin-top: 16px;
    justify-content: flex-end;
}
.mono-text {
    font-family: monospace;
    font-size: 12px;
}
.ellipsis-cell {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 280px;
    margin: 0 auto;
}
.text-muted {
    color: #c0c4cc;
}
</style>
