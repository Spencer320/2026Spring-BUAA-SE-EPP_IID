<template>
    <div class="behavior-audit-page">
        <div class="toolbar">
            <el-input
                v-model.trim="filters.userId"
                clearable
                style="width: 220px"
                placeholder="用户 ID"
                @keyup.enter="handleSearch"
            />
            <el-input
                v-model.trim="filters.taskId"
                clearable
                style="width: 260px"
                placeholder="任务 ID"
                @keyup.enter="handleSearch"
            />
            <el-input
                v-model.trim="filters.targetDomain"
                clearable
                style="width: 180px"
                placeholder="目标域名"
                @keyup.enter="handleSearch"
            />
            <el-select v-model="filters.operationType" clearable style="width: 170px" placeholder="操作类型">
                <el-option v-for="item in operationOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="filters.exceptionStatus" style="width: 140px" placeholder="异常状态">
                <el-option label="全部状态" value="all" />
                <el-option label="仅异常" value="true" />
                <el-option label="仅正常" value="false" />
            </el-select>
            <el-date-picker
                v-model="filters.dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                value-format="YYYY-MM-DD"
                format="YYYY-MM-DD"
                style="width: 240px"
            />
            <el-button type="primary" @click="handleSearch">
                <el-icon><i-ep-Search /></el-icon>查询
            </el-button>
            <el-button @click="handleReset">重置</el-button>
            <el-button type="success" plain @click="handleExport">
                <el-icon><i-ep-Download /></el-icon>导出结构化文档
            </el-button>
        </div>

        <el-table
            :data="logs"
            v-loading="isLoading"
            stripe
            size="default"
            style="width: 100%; border-top: 1px solid #ebeef5"
            :header-cell-style="{ 'text-align': 'center' }"
            :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
        >
            <el-table-column type="index" label="序号" width="70" />
            <el-table-column label="时间" min-width="180" prop="occurred_at" />
            <el-table-column label="用户ID" min-width="190">
                <template #default="{ row }">
                    <el-tooltip :content="row.user_id" placement="top">
                        <span class="mono-cell">{{ row.user_id }}</span>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="任务ID" min-width="190">
                <template #default="{ row }">
                    <el-tooltip :content="row.task_id" placement="top">
                        <span class="mono-cell">{{ shortTask(row.task_id) }}</span>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="目标域名" min-width="150" prop="target_domain" />
            <el-table-column label="操作类型" min-width="140" prop="operation_type" />
            <el-table-column label="状态码" width="100">
                <template #default="{ row }">{{ row.response_status ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="异常状态" width="110">
                <template #default="{ row }">
                    <el-tag :type="row.is_exception ? 'danger' : 'success'" size="small" effect="plain">
                        {{ row.is_exception ? '异常' : '正常' }}
                    </el-tag>
                </template>
            </el-table-column>
            <el-table-column label="异常说明" min-width="220">
                <template #default="{ row }">
                    <el-tooltip
                        v-if="row.exception_message && row.exception_message.length > 40"
                        :content="row.exception_message"
                        placement="top"
                    >
                        <div class="ellipsis-cell">{{ row.exception_message }}</div>
                    </el-tooltip>
                    <span v-else>{{ row.exception_message || '—' }}</span>
                </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
                <template #default="{ row }">
                    <el-button type="primary" link @click="openChain(row.task_id)">查看链路</el-button>
                </template>
            </el-table-column>
            <template #empty>
                <el-empty description="暂无行为审计日志" />
            </template>
        </el-table>

        <el-pagination
            class="pagination"
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next, jumper"
            :total="total"
        />

        <el-drawer
            v-model="chainVisible"
            title="任务行为链路"
            direction="rtl"
            size="55%"
            :destroy-on-close="true"
        >
            <div v-loading="chainLoading" class="chain-container">
                <el-descriptions v-if="chainTask.task_id" border :column="1" size="small">
                    <el-descriptions-item label="任务ID">{{ chainTask.task_id }}</el-descriptions-item>
                    <el-descriptions-item label="会话ID">{{ chainTask.session_id }}</el-descriptions-item>
                    <el-descriptions-item label="用户ID">{{ chainTask.user_id }}</el-descriptions-item>
                    <el-descriptions-item label="任务状态">{{ chainTask.status }}</el-descriptions-item>
                </el-descriptions>

                <el-timeline v-if="chainLogs.length > 0" style="margin-top: 16px">
                    <el-timeline-item
                        v-for="log in chainLogs"
                        :key="log.id"
                        :timestamp="log.occurred_at"
                        :type="log.is_exception ? 'danger' : 'primary'"
                    >
                        <div class="timeline-card">
                            <div class="timeline-title">
                                <el-tag size="small" effect="plain">{{ log.operation_type }}</el-tag>
                                <span class="timeline-domain">{{ log.target_domain || '—' }}</span>
                            </div>
                            <div class="timeline-detail">{{ log.trace_detail || '—' }}</div>
                            <div class="timeline-meta">
                                状态码：{{ log.response_status ?? '—' }} / 异常：{{ log.is_exception ? '是' : '否' }}
                            </div>
                        </div>
                    </el-timeline-item>
                </el-timeline>

                <el-empty v-else-if="!chainLoading" description="该任务暂无行为日志" />
            </div>
        </el-drawer>
    </div>
</template>

<script>
import { ElMessage } from 'element-plus'
import {
    exportResearchAgentBehaviorLogs,
    getResearchAgentBehaviorLogs,
    getResearchAgentTaskBehaviorChain
} from '@/api/research_agent_audit.js'

export default {
    data() {
        return {
            isLoading: false,
            logs: [],
            total: 0,
            currentPage: 1,
            pageSize: 20,
            filters: {
                userId: '',
                taskId: '',
                targetDomain: '',
                operationType: '',
                exceptionStatus: 'all',
                dateRange: []
            },
            operationOptions: [
                { label: 'outbound_get', value: 'outbound_get' },
                { label: 'http_request', value: 'http_request' },
                { label: 'navigate', value: 'navigate' },
                { label: 'click', value: 'click' },
                { label: 'extract', value: 'extract' }
            ],
            chainVisible: false,
            chainLoading: false,
            chainTask: {},
            chainLogs: []
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
        buildFilterParams() {
            const params = {
                page_num: this.currentPage,
                page_size: this.pageSize
            }
            if (this.filters.userId) params.user_id = this.filters.userId
            if (this.filters.taskId) params.task_id = this.filters.taskId
            if (this.filters.targetDomain) params.target_domain = this.filters.targetDomain
            if (this.filters.operationType) params.operation_type = this.filters.operationType
            if (this.filters.exceptionStatus) params.exception_status = this.filters.exceptionStatus
            if (this.filters.dateRange && this.filters.dateRange.length === 2) {
                params.date_from = this.filters.dateRange[0]
                params.date_to = this.filters.dateRange[1]
            }
            return params
        },
        async fetchLogs() {
            this.isLoading = true
            await getResearchAgentBehaviorLogs(this.buildFilterParams())
                .then((res) => {
                    this.logs = res.data.items || []
                    this.total = res.data.total || 0
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.error || '获取行为审计日志失败')
                })
            this.isLoading = false
        },
        handleSearch() {
            this.currentPage = 1
            this.fetchLogs()
        },
        handleReset() {
            this.filters = {
                userId: '',
                taskId: '',
                targetDomain: '',
                operationType: '',
                exceptionStatus: 'all',
                dateRange: []
            }
            this.currentPage = 1
            this.fetchLogs()
        },
        shortTask(taskId) {
            if (!taskId) return '—'
            return taskId.length <= 12 ? taskId : `${taskId.slice(0, 12)}...`
        },
        async openChain(taskId) {
            this.chainVisible = true
            this.chainLoading = true
            this.chainTask = {}
            this.chainLogs = []
            await getResearchAgentTaskBehaviorChain(taskId)
                .then((res) => {
                    this.chainTask = res.data.task || {}
                    this.chainLogs = res.data.logs || []
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.error || '获取任务链路失败')
                })
            this.chainLoading = false
        },
        async handleExport() {
            const params = this.buildFilterParams()
            delete params.page_num
            delete params.page_size
            await exportResearchAgentBehaviorLogs(params)
                .then((res) => {
                    const fileName = res.data.file_name || 'research-assistant-audit.md'
                    const content = res.data.content || ''
                    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
                    const link = document.createElement('a')
                    const href = URL.createObjectURL(blob)
                    link.href = href
                    link.download = fileName
                    document.body.appendChild(link)
                    link.click()
                    document.body.removeChild(link)
                    URL.revokeObjectURL(href)
                    ElMessage.success(`导出成功，共 ${res.data.count || 0} 条`)
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.error || '导出失败')
                })
        }
    }
}
</script>

<style lang="scss" scoped>
.behavior-audit-page {
    width: 100%;
}
.toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
}
.mono-cell {
    font-family: monospace;
    font-size: 12px;
}
.ellipsis-cell {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.pagination {
    margin-top: 14px;
    display: flex;
    justify-content: flex-end;
}
.chain-container {
    width: 100%;
}
.timeline-card {
    border: 1px solid #ebeef5;
    border-radius: 8px;
    padding: 10px 12px;
    background: #fff;
}
.timeline-title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}
.timeline-domain {
    color: #606266;
    font-size: 13px;
}
.timeline-detail {
    color: #303133;
    margin-bottom: 6px;
    word-break: break-word;
}
.timeline-meta {
    color: #909399;
    font-size: 12px;
}
</style>
