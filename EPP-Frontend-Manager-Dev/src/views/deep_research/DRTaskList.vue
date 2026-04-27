<template>
    <div class="task-list-container">
        <div class="stats-row" v-loading="statsLoading">
            <div class="stat-card" v-for="card in statCards" :key="card.key">
                <div class="stat-card-value" :style="{ color: card.color }">{{ card.value }}</div>
                <div class="stat-card-label">{{ card.label }}</div>
            </div>
        </div>

        <div class="filter-bar">
            <div class="filter-left">
                <el-tag v-if="isFixedStatusView" type="info" effect="plain">状态：{{ fixedStatusLabels }}</el-tag>
                <el-select
                    v-else
                    v-model="filters.statusList"
                    multiple
                    collapse-tags
                    placeholder="状态筛选（可多选）"
                    clearable
                    style="width: 220px"
                >
                    <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
                <el-input
                    v-model="filters.userKeyword"
                    placeholder="用户名 / 用户ID"
                    clearable
                    style="width: 180px"
                    @keyup.enter="handleSearch"
                />
                <el-input
                    v-model="filters.queryKeyword"
                    placeholder="研究问题关键词"
                    clearable
                    style="width: 190px"
                    @keyup.enter="handleSearch"
                />
                <el-date-picker
                    v-model="filters.dateRange"
                    type="daterange"
                    range-separator="至"
                    start-placeholder="开始日期"
                    end-placeholder="结束日期"
                    format="YYYY-MM-DD"
                    value-format="YYYY-MM-DD"
                    style="width: 240px"
                />
                <el-button type="primary" @click="handleSearch">
                    <el-icon><i-ep-Search /></el-icon>搜索
                </el-button>
                <el-button @click="handleReset">重置</el-button>
            </div>
            <div class="filter-right">
                <span class="refresh-label">自动刷新(5s)</span>
                <el-switch v-model="autoRefresh" @change="handleAutoRefreshChange" />
                <el-button text style="margin-left: 8px" @click="fetchAll" :loading="isLoading">
                    <el-icon><i-ep-Refresh /></el-icon>
                </el-button>
            </div>
        </div>

        <el-table
            :data="taskList"
            stripe
            v-loading="isLoading"
            style="width: 100%; border-top: 1px solid #edebeb; font-size: 14px"
            size="default"
            :header-cell-style="{ 'text-align': 'center' }"
            :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
        >
            <el-table-column label="任务ID" width="130">
                <template #default="{ row }">
                    <el-tooltip :content="row.task_id" placement="top">
                        <span class="mono-text">{{ row.task_id.slice(0, 8) }}...</span>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="用户名" width="110">
                <template #default="{ row }">
                    <el-button text size="small" @click="filterByUser(row)">{{ row.username }}</el-button>
                </template>
            </el-table-column>
            <el-table-column label="研究问题" min-width="180">
                <template #default="{ row }">
                    <el-tooltip :content="row.query" placement="top" :show-after="300">
                        <div class="query-cell">{{ row.query }}</div>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
                <template #default="{ row }">
                    <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="阶段/进度" width="130">
                <template #default="{ row }">
                    <template v-if="row.status === 'running'">
                        <el-tag
                            :color="phaseColor(row.current_phase)"
                            effect="dark"
                            size="small"
                            style="margin-bottom: 4px"
                        >
                            {{ phaseLabel(row.current_phase) }}
                        </el-tag>
                        <el-progress :percentage="row.progress ?? 0" :stroke-width="5" />
                    </template>
                    <span v-else style="color: #909399">—</span>
                </template>
            </el-table-column>
            <el-table-column label="风险" width="120">
                <template #default="{ row }">
                    <el-tag v-if="row.status === 'violation_pending'" type="danger" size="small">待处理</el-tag>
                    <el-tag v-else-if="row.violation_count > 0" type="warning" size="small">
                        命中 {{ row.violation_count }}
                    </el-tag>
                    <span v-else style="color: #909399">—</span>
                </template>
            </el-table-column>
            <el-table-column label="Token" width="100">
                <template #default="{ row }">
                    <span :style="{ color: row.token_used_total > 50000 ? '#f56c6c' : 'inherit' }">
                        {{ formatToken(row.token_used_total) }}
                    </span>
                </template>
            </el-table-column>
            <el-table-column label="输出" width="90">
                <template #default="{ row }">
                    <el-tag v-if="row.output_suppressed" type="danger" size="small">已屏蔽</el-tag>
                    <el-tag v-else type="success" size="small">正常</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="创建时间" width="160" prop="created_at" />
            <el-table-column label="操作" width="220" fixed="right">
                <template #default="{ row }">
                    <el-button size="small" plain @click="openDetail(row)">详情</el-button>
                    <el-button size="small" plain @click="openTrace(row)">轨迹</el-button>
                    <el-button
                        v-if="['running', 'queued', 'violation_pending', 'needs_review'].includes(row.status)"
                        size="small"
                        type="danger"
                        plain
                        @click="handleForceStop(row)"
                        >中断</el-button
                    >
                    <el-button
                        v-else-if="
                            ['completed', 'violation_pending', 'needs_review'].includes(row.status) &&
                            !row.output_suppressed
                        "
                        size="small"
                        type="warning"
                        plain
                        @click="handleSuppress(row)"
                        >屏蔽</el-button
                    >
                    <el-button
                        v-else-if="row.output_suppressed"
                        size="small"
                        type="success"
                        plain
                        @click="handleUnsuppress(row)"
                        >恢复</el-button
                    >
                </template>
            </el-table-column>
            <template #empty>
                <el-empty :description="emptyDescription" />
            </template>
        </el-table>

        <el-pagination
            class="pagination"
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50, 100]"
            layout="total, sizes, prev, pager, next, jumper"
            :total="total"
        />

        <DRTaskDetailDrawer
            ref="detailDrawer"
            :task-id="detailTaskId"
            @view-trace="openTraceById"
            @action-done="fetchAll"
        />
        <DRTraceDrawer ref="traceDrawer" :task-id="traceTaskId" />
    </div>
</template>

<script>
import { getDRStats, getDRTaskList, forceStopTask, suppressOutput, unsuppressOutput } from '@/api/deep_research.js'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import DRTaskDetailDrawer from './DRTaskDetailDrawer.vue'
import DRTraceDrawer from './DRTraceDrawer.vue'
import { DR_PHASE_CONFIG, DR_STATUS_MAP } from '@/views/deep_research/dr_constants.js'

const UUID_PATTERN = /^[0-9a-fA-F-]{32,36}$/

export default {
    components: { DRTaskDetailDrawer, DRTraceDrawer },
    props: {
        fixedStatusList: {
            type: Array,
            default: () => []
        }
    },
    data() {
        const initialStatusList = Array.isArray(this.fixedStatusList) ? [...this.fixedStatusList] : []
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
                statusList: initialStatusList,
                userKeyword: '',
                queryKeyword: '',
                dateRange: []
            },
            knownViolationTaskIds: new Set(),
            detailTaskId: '',
            traceTaskId: '',
            statusOptions: Object.entries(DR_STATUS_MAP).map(([value, v]) => ({ value, label: v.label }))
        }
    },
    computed: {
        isFixedStatusView() {
            return this.fixedStatusList.length > 0
        },
        fixedStatusLabels() {
            return this.fixedStatusList.map((status) => this.statusLabel(status)).join(' / ')
        },
        emptyDescription() {
            return this.isFixedStatusView ? '暂无符合条件的任务' : '暂无任务记录'
        },
        statCards() {
            return [
                { key: 'running', label: '执行中', value: this.stats.running_count ?? 0, color: '#E6A23C' },
                { key: 'queued', label: '排队中', value: this.stats.queued_count ?? 0, color: '#409EFF' },
                { key: 'today', label: '今日任务', value: this.stats.today_total ?? 0, color: '#303133' },
                { key: 'completed', label: '今日完成', value: this.stats.today_completed ?? 0, color: '#67C23A' },
                { key: 'failed', label: '今日失败', value: this.stats.today_failed ?? 0, color: '#F56C6C' },
                {
                    key: 'violation_pending',
                    label: '违规待处理',
                    value: this.stats.violation_pending_count ?? 0,
                    color: '#F56C6C'
                },
                {
                    key: 'needs_review',
                    label: '待人工复核',
                    value: this.stats.needs_review_count ?? 0,
                    color: '#E6A23C'
                },
                {
                    key: 'archived',
                    label: '已归档总数',
                    value: this.stats.archived_count ?? 0,
                    color: '#909399'
                },
                {
                    key: 'token',
                    label: '今日Token',
                    value: this.formatToken(this.stats.today_token_total ?? 0),
                    color: '#606266'
                },
                {
                    key: 'suppressed',
                    label: '已屏蔽报告',
                    value: this.stats.suppressed_count ?? 0,
                    color: '#F56C6C'
                }
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
        async fetchAll() {
            await Promise.all([this.fetchStats(), this.fetchTaskList()])
        },
        async fetchStats() {
            this.statsLoading = true
            await getDRStats()
                .then((res) => {
                    this.stats = res.data || {}
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取统计数据失败')
                })
            this.statsLoading = false
        },
        async fetchTaskList() {
            if (this.isLoading) return
            this.isLoading = true
            const params = { page_num: this.currentPage, page_size: this.pageSize }
            const statusList = this.isFixedStatusView ? this.fixedStatusList : this.filters.statusList

            if (statusList.length > 0) params.status = statusList.join(',')
            if (this.filters.userKeyword) {
                if (UUID_PATTERN.test(this.filters.userKeyword)) params.user_id = this.filters.userKeyword
                else params.username = this.filters.userKeyword
            }
            if (this.filters.queryKeyword) params.keyword = this.filters.queryKeyword
            if (this.filters.dateRange && this.filters.dateRange.length === 2) {
                params.date_from = this.filters.dateRange[0]
                params.date_to = this.filters.dateRange[1]
            }

            await getDRTaskList(params)
                .then((res) => {
                    const items = res.data.items || []
                    this.taskList = items
                    this.total = res.data.total || 0
                    this.notifyViolationTasks(items)
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取任务列表失败')
                })
            this.isLoading = false
        },
        notifyViolationTasks(items) {
            for (const task of items) {
                if (task.status !== 'violation_pending') continue
                if (this.knownViolationTaskIds.has(task.task_id)) continue
                this.knownViolationTaskIds.add(task.task_id)
                ElNotification({
                    title: '合规预警',
                    message: `任务 ${task.task_id.slice(0, 8)} 命中安全红线，状态已标记为“违规待处理”`,
                    type: 'warning',
                    duration: 6000
                })
            }
        },
        handleSearch() {
            this.currentPage = 1
            this.fetchAll()
        },
        handleReset() {
            this.filters = {
                statusList: this.isFixedStatusView ? [...this.fixedStatusList] : [],
                userKeyword: '',
                queryKeyword: '',
                dateRange: []
            }
            this.currentPage = 1
            this.fetchAll()
        },
        filterByUser(row) {
            this.filters.userKeyword = row.user_id || row.username || ''
            this.handleSearch()
        },
        handleAutoRefreshChange(val) {
            if (val) {
                this.refreshTimer = setInterval(() => {
                    this.fetchAll()
                }, 5000)
            } else {
                this.stopAutoRefresh()
            }
        },
        stopAutoRefresh() {
            if (this.refreshTimer) {
                clearInterval(this.refreshTimer)
                this.refreshTimer = null
            }
        },
        openDetail(row) {
            this.detailTaskId = row.task_id
            this.$refs.detailDrawer.open()
        },
        openTrace(row) {
            this.traceTaskId = row.task_id
            this.$refs.traceDrawer.open()
        },
        openTraceById(taskId) {
            this.traceTaskId = taskId
            this.$refs.traceDrawer.open()
        },
        handleForceStop(row) {
            ElMessageBox.prompt('请填写强制中断原因', '强制中断确认', {
                confirmButtonText: '确认中断',
                cancelButtonText: '取消',
                inputPlaceholder: '例如：任务资源消耗异常，已超时',
                inputValidator: (val) => !!val || '原因不能为空',
                type: 'warning'
            })
                .then(({ value }) => forceStopTask(row.task_id, { reason: value }))
                .then(() => {
                    ElMessage.success('中断指令已发送')
                    this.fetchAll()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '操作失败')
                })
        },
        handleSuppress(row) {
            ElMessageBox.prompt('请填写屏蔽原因', '屏蔽报告输出', {
                confirmButtonText: '确认屏蔽',
                cancelButtonText: '取消',
                inputPlaceholder: '例如：报告内容涉及不当信息，临时屏蔽待人工复核',
                inputValidator: (val) => !!val || '原因不能为空',
                type: 'warning'
            })
                .then(({ value }) => suppressOutput(row.task_id, { reason: value }))
                .then(() => {
                    ElMessage.success('报告已屏蔽')
                    this.fetchAll()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '操作失败')
                })
        },
        handleUnsuppress(row) {
            ElMessageBox.confirm('确定恢复该任务报告的访问权限吗？', '恢复报告输出', {
                confirmButtonText: '确认恢复',
                cancelButtonText: '取消',
                type: 'info'
            })
                .then(() => unsuppressOutput(row.task_id, {}))
                .then(() => {
                    ElMessage.success('报告输出已恢复')
                    this.fetchAll()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '操作失败')
                })
        },
        statusLabel(status) {
            return DR_STATUS_MAP[status]?.label || status || '—'
        },
        statusTagType(status) {
            return DR_STATUS_MAP[status]?.type || 'info'
        },
        phaseLabel(phase) {
            return DR_PHASE_CONFIG[phase]?.label || phase || '—'
        },
        phaseColor(phase) {
            return DR_PHASE_CONFIG[phase]?.color || '#909399'
        },
        formatToken(num) {
            if (!num && num !== 0) return '0'
            if (num >= 10000) return `${(num / 10000).toFixed(1)}万`
            return num.toString()
        }
    }
}
</script>

<style lang="scss" scoped>
.task-list-container {
    width: 100%;
}

.stats-row {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 16px;
    min-height: 70px;
}
.stat-card {
    flex: 1;
    min-width: 90px;
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 10px 12px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    .stat-card-value {
        font-size: 22px;
        font-weight: bold;
        line-height: 1.2;
    }
    .stat-card-label {
        font-size: 12px;
        color: #909399;
        margin-top: 4px;
    }
}

.filter-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
    flex-wrap: wrap;
    gap: 8px;
    .filter-left {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
    }
    .filter-right {
        display: flex;
        align-items: center;
        gap: 4px;
        .refresh-label {
            font-size: 13px;
            color: #606266;
        }
    }
}

.query-cell {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 200px;
    text-align: left;
}

.mono-text {
    font-family: monospace;
    font-size: 12px;
    color: #606266;
    cursor: default;
}

.pagination {
    height: 10vh;
    display: flex;
    align-items: center;
    justify-content: flex-end;
}
</style>
