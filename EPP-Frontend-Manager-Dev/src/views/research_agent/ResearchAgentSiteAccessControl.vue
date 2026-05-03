<template>
    <div class="site-access-page">
        <div class="overview-grid">
            <el-card class="metric-card" shadow="hover">
                <template #header>策略模式</template>
                <div class="metric-value">{{ policy.mode || 'blacklist' }}</div>
                <div class="metric-sub">version: {{ policy.policy_version || 1 }}</div>
            </el-card>
            <el-card class="metric-card" shadow="hover">
                <template #header>规则总数</template>
                <div class="metric-value">{{ stats.rules.total || 0 }}</div>
                <div class="metric-sub">启用 {{ stats.rules.enabled || 0 }}</div>
            </el-card>
            <el-card class="metric-card" shadow="hover">
                <template #header>拦截事件</template>
                <div class="metric-value danger">{{ stats.events.blocked || 0 }}</div>
                <div class="metric-sub">放行 {{ stats.events.allowed || 0 }}</div>
            </el-card>
        </div>

        <el-card class="section-card" shadow="never">
            <template #header>访问策略</template>
            <div class="policy-row">
                <el-select v-model="policyForm.mode" style="width: 180px">
                    <el-option label="白名单模式" value="whitelist" />
                    <el-option label="黑名单模式" value="blacklist" />
                </el-select>
                <el-input
                    v-model.trim="policyForm.description"
                    placeholder="策略说明（可选）"
                    style="max-width: 420px"
                    clearable
                />
                <el-button type="primary" :loading="policySaving" @click="savePolicy">保存策略</el-button>
                <el-button @click="refreshAll">刷新</el-button>
            </div>
            <div class="policy-tip">
                {{ policy.mode === 'whitelist' ? '白名单模式：仅命中 allow 规则时放行。' : '黑名单模式：命中 deny 规则拦截，其他默认放行。' }}
            </div>
        </el-card>

        <el-card class="section-card" shadow="never">
            <template #header>规则维护</template>
            <div class="toolbar">
                <div class="toolbar-left">
                    <el-input
                        v-model.trim="ruleFilters.keyword"
                        clearable
                        placeholder="按域名规则搜索"
                        style="width: 220px"
                        @keyup.enter="fetchRules"
                    />
                    <el-select v-model="ruleFilters.ruleType" clearable placeholder="规则类型" style="width: 140px">
                        <el-option label="allow" value="allow" />
                        <el-option label="deny" value="deny" />
                    </el-select>
                    <el-select v-model="ruleFilters.matchType" clearable placeholder="匹配类型" style="width: 140px">
                        <el-option label="exact" value="exact" />
                        <el-option label="suffix" value="suffix" />
                        <el-option label="wildcard" value="wildcard" />
                    </el-select>
                    <el-select v-model="ruleFilters.enabled" clearable placeholder="启用状态" style="width: 130px">
                        <el-option label="启用" value="true" />
                        <el-option label="停用" value="false" />
                    </el-select>
                    <el-button type="primary" @click="fetchRules">查询</el-button>
                    <el-button @click="resetRuleFilters">重置</el-button>
                </div>
                <el-button type="primary" @click="openCreateRule">新增规则</el-button>
            </div>

            <el-table
                :data="rules"
                v-loading="rulesLoading"
                stripe
                style="width: 100%"
                :header-cell-style="{ 'text-align': 'center' }"
                :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
            >
                <el-table-column label="ID" width="80" prop="rule_id" />
                <el-table-column label="类型" width="100">
                    <template #default="{ row }">
                        <el-tag :type="row.rule_type === 'deny' ? 'danger' : 'success'" effect="plain">{{ row.rule_type }}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="匹配方式" width="110" prop="match_type" />
                <el-table-column label="规则" min-width="220" prop="pattern" />
                <el-table-column label="优先级" width="100" prop="priority" />
                <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                        <el-tag :type="row.is_enabled ? 'success' : 'info'" effect="plain">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="描述" min-width="180" prop="description" />
                <el-table-column label="更新人" width="120" prop="updated_by" />
                <el-table-column label="操作" width="180" fixed="right">
                    <template #default="{ row }">
                        <el-button link type="primary" @click="openEditRule(row)">编辑</el-button>
                        <el-button link type="danger" @click="handleDeleteRule(row)">删除</el-button>
                    </template>
                </el-table-column>
                <template #empty>
                    <el-empty description="暂无站点访问规则" />
                </template>
            </el-table>
        </el-card>

        <el-card class="section-card" shadow="never">
            <template #header>命中事件</template>
            <div class="toolbar">
                <div class="toolbar-left">
                    <el-input
                        v-model.trim="eventFilters.targetDomain"
                        clearable
                        style="width: 240px"
                        placeholder="按目标域名筛选"
                        @keyup.enter="handleSearchEvents"
                    />
                    <el-select v-model="eventFilters.status" clearable style="width: 130px" placeholder="状态">
                        <el-option label="rejected" value="rejected" />
                        <el-option label="succeeded" value="succeeded" />
                        <el-option label="allowed" value="allowed" />
                    </el-select>
                    <el-select v-model="eventFilters.toolType" clearable style="width: 130px" placeholder="工具">
                        <el-option label="web_search" value="web_search" />
                        <el-option label="local_file" value="local_file" />
                    </el-select>
                    <el-button type="primary" @click="handleSearchEvents">查询</el-button>
                    <el-button @click="resetEventFilters">重置</el-button>
                </div>
            </div>

            <el-table
                :data="events"
                v-loading="eventsLoading"
                stripe
                style="width: 100%"
                :header-cell-style="{ 'text-align': 'center' }"
                :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
            >
                <el-table-column label="时间" min-width="180" prop="occurred_at" />
                <el-table-column label="用户" min-width="130">
                    <template #default="{ row }">{{ row.user_name || row.user_id || '—' }}</template>
                </el-table-column>
                <el-table-column label="任务ID" min-width="160">
                    <template #default="{ row }">{{ shortId(row.task_id) }}</template>
                </el-table-column>
                <el-table-column label="域名" min-width="180" prop="target_domain" />
                <el-table-column label="工具" width="110" prop="tool_type" />
                <el-table-column label="状态" width="110">
                    <template #default="{ row }">
                        <el-tag :type="eventStatusTag(row.status)" effect="plain">{{ row.status || '—' }}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="命中规则" min-width="220" prop="rule_hit" />
                <el-table-column label="策略版本" width="120" prop="policy_version" />
            </el-table>

            <el-pagination
                class="pagination"
                v-model:current-page="eventPage"
                v-model:page-size="eventPageSize"
                :page-sizes="[10, 20, 50]"
                layout="total, sizes, prev, pager, next, jumper"
                :total="eventTotal"
            />
        </el-card>

        <el-dialog v-model="ruleDialogVisible" :title="ruleEditMode ? '编辑规则' : '新增规则'" width="560px" @closed="resetRuleForm">
            <el-form :model="ruleForm" :rules="ruleFormRules" ref="ruleFormRef" label-width="92px">
                <el-form-item label="规则类型" prop="rule_type">
                    <el-select v-model="ruleForm.rule_type" style="width: 100%">
                        <el-option label="allow" value="allow" />
                        <el-option label="deny" value="deny" />
                    </el-select>
                </el-form-item>
                <el-form-item label="匹配类型" prop="match_type">
                    <el-select v-model="ruleForm.match_type" style="width: 100%">
                        <el-option label="exact" value="exact" />
                        <el-option label="suffix" value="suffix" />
                        <el-option label="wildcard" value="wildcard" />
                    </el-select>
                </el-form-item>
                <el-form-item label="规则内容" prop="pattern">
                    <el-input v-model.trim="ruleForm.pattern" placeholder="如 example.com 或 *.edu.cn" />
                </el-form-item>
                <el-form-item label="优先级" prop="priority">
                    <el-input-number v-model="ruleForm.priority" :min="1" :max="9999" style="width: 100%" />
                </el-form-item>
                <el-form-item label="启用状态">
                    <el-switch v-model="ruleForm.is_enabled" />
                </el-form-item>
                <el-form-item label="描述">
                    <el-input v-model.trim="ruleForm.description" type="textarea" :rows="2" placeholder="可选" />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="ruleDialogVisible = false">取消</el-button>
                <el-button type="primary" :loading="ruleSubmitting" @click="submitRule">保存</el-button>
            </template>
        </el-dialog>
    </div>
</template>

<script>
import { ElMessage, ElMessageBox } from 'element-plus'
import {
    createSiteAccessRule,
    deleteSiteAccessRule,
    getSiteAccessEvents,
    getSiteAccessPolicy,
    getSiteAccessRules,
    getSiteAccessStats,
    updateSiteAccessPolicy,
    updateSiteAccessRule
} from '@/api/research_agent_site_access.js'

export default {
    data() {
        return {
            policy: {},
            policyForm: { mode: 'blacklist', description: '' },
            policySaving: false,

            stats: {
                rules: {},
                events: {}
            },

            rules: [],
            rulesLoading: false,
            ruleFilters: {
                keyword: '',
                ruleType: '',
                matchType: '',
                enabled: ''
            },
            ruleDialogVisible: false,
            ruleEditMode: false,
            ruleSubmitting: false,
            ruleForm: {
                rule_id: null,
                rule_type: 'allow',
                match_type: 'suffix',
                pattern: '',
                priority: 100,
                is_enabled: true,
                description: ''
            },
            ruleFormRules: {
                rule_type: [{ required: true, message: '请选择规则类型', trigger: 'change' }],
                match_type: [{ required: true, message: '请选择匹配类型', trigger: 'change' }],
                pattern: [{ required: true, message: '请填写规则内容', trigger: 'blur' }],
                priority: [{ required: true, message: '请填写优先级', trigger: 'blur' }]
            },

            events: [],
            eventsLoading: false,
            eventTotal: 0,
            eventPage: 1,
            eventPageSize: 20,
            eventFilters: {
                targetDomain: '',
                status: '',
                toolType: ''
            }
        }
    },
    watch: {
        eventPage() {
            this.fetchEvents()
        },
        eventPageSize() {
            if (this.eventPage !== 1) {
                this.eventPage = 1
                return
            }
            this.fetchEvents()
        }
    },
    created() {
        this.refreshAll()
    },
    methods: {
        extractErrorMessage(err, fallback) {
            const responseData = err?.response?.data || {}
            const errorField = responseData.error
            if (typeof errorField === 'string' && errorField.trim()) {
                return errorField.trim()
            }
            if (errorField && typeof errorField === 'object') {
                const code = String(errorField.code || '').trim()
                const message = String(errorField.message || errorField.detail || '').trim()
                if (message && code) return `${message} (${code})`
                if (message) return message
                if (code) return `${fallback} (${code})`
            }
            const message = [responseData.message, responseData.detail, err?.message]
                .map((item) => (typeof item === 'string' ? item.trim() : ''))
                .find(Boolean)
            if (message) return message
            const status = err?.response?.status
            if (status) return `${fallback}（HTTP ${status}）`
            return fallback
        },
        async refreshAll() {
            await Promise.all([this.fetchPolicy(), this.fetchStats(), this.fetchRules(), this.fetchEvents()])
        },
        async fetchPolicy() {
            await getSiteAccessPolicy()
                .then((res) => {
                    this.policy = res.data.policy || {}
                    this.policyForm.mode = this.policy.mode || 'blacklist'
                    this.policyForm.description = this.policy.description || ''
                })
                .catch((err) => {
                    ElMessage.error(this.extractErrorMessage(err, '获取策略失败'))
                })
        },
        async savePolicy() {
            this.policySaving = true
            await updateSiteAccessPolicy(this.policyForm)
                .then((res) => {
                    this.policy = res.data.policy || {}
                    ElMessage.success('策略保存成功')
                })
                .catch((err) => {
                    ElMessage.error(this.extractErrorMessage(err, '保存策略失败'))
                })
            this.policySaving = false
            this.fetchStats()
        },
        async fetchStats() {
            await getSiteAccessStats()
                .then((res) => {
                    this.stats = {
                        rules: res.data.rules || {},
                        events: res.data.events || {}
                    }
                    this.policy = res.data.policy || this.policy
                })
                .catch((err) => {
                    ElMessage.error(this.extractErrorMessage(err, '获取统计失败'))
                })
        },
        buildRuleParams() {
            const params = {}
            if (this.ruleFilters.keyword) params.keyword = this.ruleFilters.keyword
            if (this.ruleFilters.ruleType) params.rule_type = this.ruleFilters.ruleType
            if (this.ruleFilters.matchType) params.match_type = this.ruleFilters.matchType
            if (this.ruleFilters.enabled) params.is_enabled = this.ruleFilters.enabled
            return params
        },
        async fetchRules() {
            this.rulesLoading = true
            await getSiteAccessRules(this.buildRuleParams())
                .then((res) => {
                    this.rules = res.data.rules || []
                })
                .catch((err) => {
                    ElMessage.error(this.extractErrorMessage(err, '获取规则失败'))
                })
            this.rulesLoading = false
        },
        resetRuleFilters() {
            this.ruleFilters = {
                keyword: '',
                ruleType: '',
                matchType: '',
                enabled: ''
            }
            this.fetchRules()
        },
        openCreateRule() {
            this.ruleEditMode = false
            this.ruleDialogVisible = true
        },
        openEditRule(row) {
            this.ruleEditMode = true
            this.ruleForm = {
                rule_id: row.rule_id,
                rule_type: row.rule_type,
                match_type: row.match_type,
                pattern: row.pattern,
                priority: row.priority,
                is_enabled: row.is_enabled,
                description: row.description || ''
            }
            this.ruleDialogVisible = true
        },
        async submitRule() {
            await this.$refs.ruleFormRef.validate()
            this.ruleSubmitting = true
            const payload = {
                rule_type: this.ruleForm.rule_type,
                match_type: this.ruleForm.match_type,
                pattern: this.ruleForm.pattern,
                priority: this.ruleForm.priority,
                is_enabled: this.ruleForm.is_enabled,
                description: this.ruleForm.description
            }
            const req = this.ruleEditMode
                ? updateSiteAccessRule(this.ruleForm.rule_id, payload)
                : createSiteAccessRule(payload)
            await req
                .then(() => {
                    ElMessage.success(this.ruleEditMode ? '规则更新成功' : '规则创建成功')
                    this.ruleDialogVisible = false
                    this.fetchRules()
                    this.fetchStats()
                })
                .catch((err) => {
                    ElMessage.error(this.extractErrorMessage(err, '保存规则失败'))
                })
            this.ruleSubmitting = false
        },
        resetRuleForm() {
            this.ruleForm = {
                rule_id: null,
                rule_type: 'allow',
                match_type: 'suffix',
                pattern: '',
                priority: 100,
                is_enabled: true,
                description: ''
            }
            this.$refs.ruleFormRef?.clearValidate()
        },
        handleDeleteRule(row) {
            ElMessageBox.confirm(`确认删除规则 #${row.rule_id} ？`, '删除确认', {
                type: 'warning',
                confirmButtonText: '删除',
                cancelButtonText: '取消'
            })
                .then(() => deleteSiteAccessRule(row.rule_id))
                .then(() => {
                    ElMessage.success('规则已删除')
                    this.fetchRules()
                    this.fetchStats()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(this.extractErrorMessage(err, '删除失败'))
                })
        },
        buildEventParams() {
            const params = {
                page_num: this.eventPage,
                page_size: this.eventPageSize
            }
            if (this.eventFilters.targetDomain) params.target_domain = this.eventFilters.targetDomain
            if (this.eventFilters.status) params.status = this.eventFilters.status
            if (this.eventFilters.toolType) params.tool_type = this.eventFilters.toolType
            return params
        },
        async fetchEvents() {
            this.eventsLoading = true
            await getSiteAccessEvents(this.buildEventParams())
                .then((res) => {
                    this.events = res.data.items || []
                    this.eventTotal = res.data.total || 0
                })
                .catch((err) => {
                    ElMessage.error(this.extractErrorMessage(err, '获取命中事件失败'))
                })
            this.eventsLoading = false
        },
        handleSearchEvents() {
            if (this.eventPage !== 1) {
                this.eventPage = 1
                return
            }
            this.fetchEvents()
        },
        resetEventFilters() {
            this.eventFilters = {
                targetDomain: '',
                status: '',
                toolType: ''
            }
            this.handleSearchEvents()
        },
        shortId(value) {
            const text = String(value || '').trim()
            if (!text) return '—'
            return text.length > 12 ? `${text.slice(0, 12)}...` : text
        },
        eventStatusTag(status) {
            const val = String(status || '').toLowerCase()
            if (val === 'rejected' || val === 'failed') return 'danger'
            if (val === 'allowed' || val === 'succeeded') return 'success'
            return 'info'
        }
    }
}
</script>

<style lang="scss" scoped>
.site-access-page {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 14px;
}
.overview-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(180px, 1fr));
    gap: 12px;
}
.metric-card {
    .metric-value {
        font-size: 28px;
        font-weight: 700;
        color: #303133;
        &.danger {
            color: #f56c6c;
        }
    }
    .metric-sub {
        margin-top: 6px;
        color: #909399;
        font-size: 12px;
    }
}
.section-card {
    width: 100%;
}
.policy-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
}
.policy-tip {
    margin-top: 8px;
    color: #909399;
    font-size: 12px;
}
.toolbar {
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 12px;
    .toolbar-left {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
    }
}
.pagination {
    margin-top: 14px;
    display: flex;
    justify-content: flex-end;
}
@media (max-width: 980px) {
    .overview-grid {
        grid-template-columns: 1fr;
    }
}
</style>
