<template>
    <div class="run-manage-page">
        <el-alert
            title="深度研究任务管理"
            type="warning"
            :closable="false"
            description="按 AgentTask 展示：一次深度研究流水线对应一行；行为审计请在「行为链路」中查看逐步记录。"
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
            <el-table-column label="研究问题" min-width="200">
                <template #default="{ row }">
                    <div class="ellipsis-cell">{{ row.query || row.task_name || '—' }}</div>
                </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
                <template #default="{ row }">
                    <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="阶段 / 进度" width="150">
                <template #default="{ row }">
                    <template v-if="['running', 'pending_action', 'pending'].includes(row.status)">
                        <el-tag
                            v-if="row.current_phase"
                            :color="phaseColor(row.current_phase)"
                            effect="dark"
                            size="small"
                            style="margin-bottom: 4px"
                        >
                            {{ phaseLabel(row.current_phase) }}
                        </el-tag>
                        <el-progress :percentage="row.progress ?? 0" :stroke-width="6" />
                    </template>
                    <span v-else>—</span>
                </template>
            </el-table-column>
            <el-table-column label="审计条数" width="100">
                <template #default="{ row }">
                    <span>{{ row.log_count ?? 0 }}</span>
                    <el-tag v-if="row.exception_count > 0" type="danger" size="small" style="margin-left: 4px">
                        {{ row.exception_count }} 异常
                    </el-tag>
                </template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
                <template #default="{ row }">
                    {{ formatDateTime(row.created_at) }}
                </template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right">
                <template #default="{ row }">
                    <el-button type="primary" link @click="openDetail(row)">详情</el-button>
                    <el-button type="primary" link @click="openChain(row.task_id)">行为链路</el-button>
                    <el-button v-if="canCancel(row)" type="danger" link @click="handleCancel(row)">取消</el-button>
                </template>
            </el-table-column>
            <template #empty>
                <el-empty description="暂无深度研究任务" />
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

        <DRTaskDetailDrawer ref="detailDrawer" @action-done="fetchAll" />
        <RunBehaviorChainDrawer ref="chainDrawer" scope="deep-research" />
    </div>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDRStats, getDRTaskList, cancelDRTask } from '@/api/deep_research.js'
import { DR_PHASE_CONFIG, DR_STATUS_MAP } from '@/views/deep_research/dr_constants.js'
import DRTaskDetailDrawer from './DRTaskDetailDrawer.vue'
import RunBehaviorChainDrawer from '@/components/research_agent/RunBehaviorChainDrawer.vue'
import { formatDateTime, getApiErrorMessage } from '@/utils/adminView.js'

const ACTIVE = new Set(['pending', 'running', 'pending_action'])

export default {
    components: { DRTaskDetailDrawer, RunBehaviorChainDrawer },
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
            statusOptions: Object.entries(DR_STATUS_MAP).map(([value, v]) => ({ value, label: v.label }))
        }
    },
    computed: {
        statCards() {
            return [
                { key: 'running', label: '执行中', value: this.stats.running_count ?? 0, color: '#E6A23C' },
                { key: 'pending', label: '待启动', value: this.stats.pending_count ?? 0, color: '#409EFF' },
                { key: 'today', label: '今日任务', value: this.stats.today_total ?? 0, color: '#303133' },
                { key: 'completed', label: '今日完成', value: this.stats.today_completed ?? 0, color: '#67C23A' },
                { key: 'failed', label: '今日失败', value: this.stats.today_failed ?? 0, color: '#F56C6C' },
                { key: 'total', label: '任务总数', value: this.stats.total_count ?? 0, color: '#909399' }
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
        formatDateTime,
        shortId(id) {
            if (!id) return '—'
            return id.length <= 12 ? id : `${id.slice(0, 8)}...`
        },
        statusLabel(s) {
            return DR_STATUS_MAP[s]?.label || s || '—'
        },
        statusTagType(s) {
            return DR_STATUS_MAP[s]?.type || 'info'
        },
        phaseLabel(phase) {
            return DR_PHASE_CONFIG[phase]?.label || phase || '—'
        },
        phaseColor(phase) {
            return DR_PHASE_CONFIG[phase]?.color || '#909399'
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
            try {
                const res = await getDRStats()
                this.stats = res.data || {}
            } catch (err) {
                ElMessage.error(getApiErrorMessage(err, '获取统计失败'))
            } finally {
                this.statsLoading = false
            }
        },
        async fetchTaskList() {
            this.isLoading = true
            try {
                const res = await getDRTaskList(this.buildParams())
                this.taskList = res.data.items || []
                this.total = res.data.total || 0
            } catch (err) {
                ElMessage.error(getApiErrorMessage(err, '获取任务列表失败'))
            } finally {
                this.isLoading = false
            }
        },
        handleSearch() {
            this.currentPage = 1
            this.fetchAll()
        },
        handleReset() {
            this.filters = { userKeyword: '', keyword: '', statusList: [], dateRange: [] }
            this.handleSearch()
        },
        openDetail(row) {
            this.$refs.detailDrawer.open(row.task_id)
        },
        openChain(taskId) {
            this.$refs.chainDrawer.open(taskId)
        },
        async handleCancel(row) {
            await ElMessageBox.confirm(`确定取消任务 ${this.shortId(row.task_id)}？`, '取消任务', {
                type: 'warning'
            })
            try {
                await cancelDRTask(row.task_id)
                ElMessage.success('已取消')
                this.fetchAll()
            } catch (err) {
                ElMessage.error(getApiErrorMessage(err, '取消失败'))
            }
        },
        handleAutoRefreshChange(val) {
            if (val) {
                this.stopAutoRefresh()
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
    min-width: 110px;
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
</style>
