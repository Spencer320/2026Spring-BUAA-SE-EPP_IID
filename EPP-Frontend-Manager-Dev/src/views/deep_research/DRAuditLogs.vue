<template>
    <div class="audit-logs-container">
        <!-- 筛选区 -->
        <div class="filter-bar">
            <el-input
                v-model="filters.admin"
                placeholder="操作管理员"
                clearable
                style="width: 160px"
                @keyup.enter="handleSearch"
            />
            <el-select v-model="filters.action" placeholder="操作类型" clearable style="width: 160px">
                <el-option v-for="opt in actionOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
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

        <!-- 日志表格 -->
        <el-table
            :data="logs"
            stripe
            v-loading="isLoading"
            style="width: 100%; border-top: 1px solid #edebeb; font-size: 14px"
            size="default"
            :header-cell-style="{ 'text-align': 'center' }"
            :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
        >
            <el-table-column label="序号" width="70" type="index" />
            <el-table-column label="操作管理员" width="130">
                <template #default="{ row }">{{ row.admin_name || row.admin || '—' }}</template>
            </el-table-column>
            <el-table-column label="任务ID" width="130">
                <template #default="{ row }">
                    <el-tooltip :content="row.task_id" placement="top">
                        <span class="mono-text">{{ row.task_id?.slice(0, 8) }}...</span>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="操作类型" width="120">
                <template #default="{ row }">
                    <el-tag :type="actionTagType(row.action)" size="small" effect="plain">
                        {{ row.action_label || actionLabel(row.action) }}
                    </el-tag>
                </template>
            </el-table-column>
            <el-table-column label="操作原因" min-width="220">
                <template #default="{ row }">
                    <el-tooltip v-if="row.reason && row.reason.length > 40" :content="row.reason" placement="top">
                        <div class="reason-cell">{{ row.reason }}</div>
                    </el-tooltip>
                    <span v-else>{{ row.reason || '—' }}</span>
                </template>
            </el-table-column>
            <el-table-column label="操作时间" width="180" prop="created_at" sortable />
            <template #empty>
                <el-empty description="暂无审计记录" />
            </template>
        </el-table>

        <!-- 分页 -->
        <el-pagination
            class="pagination"
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 25, 50]"
            layout="total, sizes, prev, pager, next, jumper"
            :total="total"
        />
    </div>
</template>

<script>
import { getGlobalAuditLogs } from '@/api/deep_research.js'
import { ElMessage } from 'element-plus'

const ACTION_MAP = {
    force_stop:        { label: '强制中断', type: 'danger' },
    suppress_output:   { label: '屏蔽输出', type: 'warning' },
    unsuppress_output: { label: '恢复输出', type: 'success' },
    view_trace:        { label: '查看轨迹', type: 'info' }
}

export default {
    data() {
        return {
            isLoading: false,
            logs: [],
            total: 0,
            currentPage: 1,
            pageSize: 25,
            filters: { admin: '', action: '', dateRange: [] },
            actionOptions: Object.entries(ACTION_MAP).map(([value, v]) => ({ value, label: v.label }))
        }
    },
    watch: {
        currentPage() { this.fetchLogs() },
        pageSize() {
            this.currentPage = 1
            this.fetchLogs()
        }
    },
    created() {
        this.fetchLogs()
    },
    methods: {
        async fetchLogs() {
            this.isLoading = true
            const params = { page_num: this.currentPage, page_size: this.pageSize }
            if (this.filters.admin) params.admin = this.filters.admin
            if (this.filters.action) params.action = this.filters.action
            if (this.filters.dateRange && this.filters.dateRange.length === 2) {
                params.date_from = this.filters.dateRange[0]
                params.date_to = this.filters.dateRange[1]
            }
            await getGlobalAuditLogs(params)
                .then((res) => {
                    this.logs = res.data.logs || res.data.items || []
                    this.total = res.data.total || this.logs.length
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取审计日志失败')
                })
            this.isLoading = false
        },
        handleSearch() {
            this.currentPage = 1
            this.fetchLogs()
        },
        handleReset() {
            this.filters = { admin: '', action: '', dateRange: [] }
            this.currentPage = 1
            this.fetchLogs()
        },
        actionLabel(action) {
            return ACTION_MAP[action]?.label || action
        },
        actionTagType(action) {
            return ACTION_MAP[action]?.type || 'info'
        }
    }
}
</script>

<style lang="scss" scoped>
.audit-logs-container {
    width: 100%;
}
.filter-bar {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 12px;
    padding: 8px 0;
}
.mono-text {
    font-family: monospace;
    font-size: 12px;
    color: #606266;
    cursor: default;
}
.reason-cell {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 220px;
    text-align: left;
    cursor: pointer;
}
.pagination {
    height: 10vh;
    display: flex;
    align-items: center;
    justify-content: flex-end;
}
</style>
