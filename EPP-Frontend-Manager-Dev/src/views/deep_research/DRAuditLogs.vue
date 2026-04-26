<template>
    <div class="audit-logs-container">
        <div class="filter-bar">
            <el-input
                v-model="filters.adminKeyword"
                placeholder="操作管理员（姓名/ID）"
                clearable
                style="width: 200px"
                @keyup.enter="handleSearch"
            />
            <el-select v-model="filters.action" placeholder="操作类型" clearable style="width: 180px">
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
            <el-table-column label="操作管理员" width="150">
                <template #default="{ row }">{{ row.admin_name || row.admin || '—' }}</template>
            </el-table-column>
            <el-table-column label="任务ID" width="130">
                <template #default="{ row }">
                    <el-tooltip :content="row.task_id" placement="top">
                        <span class="mono-text">{{ row.task_id?.slice(0, 8) }}...</span>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="操作类型" width="140">
                <template #default="{ row }">
                    <el-tag :type="actionTagType(row.action)" size="small" effect="plain">
                        {{ row.action_label || actionLabel(row.action) }}
                    </el-tag>
                </template>
            </el-table-column>
            <el-table-column label="操作原因" min-width="240">
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
    force_stop: { label: '强制中断', type: 'danger' },
    suppress_output: { label: '屏蔽输出', type: 'warning' },
    unsuppress_output: { label: '恢复输出', type: 'success' },
    view_trace: { label: '查看轨迹', type: 'info' },
    auto_violation: { label: '自动违规命中', type: 'danger' }
}

const UUID_PATTERN = /^[0-9a-fA-F-]{32,36}$/

export default {
    data() {
        return {
            isLoading: false,
            logs: [],
            total: 0,
            currentPage: 1,
            pageSize: 25,
            filters: { adminKeyword: '', action: '', dateRange: [] },
            actionOptions: Object.entries(ACTION_MAP).map(([value, v]) => ({ value, label: v.label }))
        }
    },
    watch: {
        currentPage() {
            this.fetchLogs()
        },
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
            if (this.filters.adminKeyword) {
                if (UUID_PATTERN.test(this.filters.adminKeyword)) params.admin_id = this.filters.adminKeyword
                else params.admin_name = this.filters.adminKeyword
            }
            if (this.filters.action) params.action = this.filters.action
            if (this.filters.dateRange && this.filters.dateRange.length === 2) {
                params.date_from = this.filters.dateRange[0]
                params.date_to = this.filters.dateRange[1]
            }
            await getGlobalAuditLogs(params)
                .then((res) => {
                    this.logs = res.data.logs || []
                    this.total = res.data.total || 0
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
            this.filters = { adminKeyword: '', action: '', dateRange: [] }
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
