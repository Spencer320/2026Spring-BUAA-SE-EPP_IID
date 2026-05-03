<template>
    <div class="concurrency-container">
        <div class="overview-row" v-loading="statsLoading">
            <div class="overview-card">
                <div class="overview-label">当前运行任务</div>
                <div class="overview-value running">{{ stats.running_count ?? 0 }}</div>
            </div>
            <div class="overview-card">
                <div class="overview-label">当前排队任务</div>
                <div class="overview-value queued">{{ stats.queued_count ?? 0 }}</div>
            </div>
            <div class="overview-card">
                <div class="overview-label">并发覆盖用户数</div>
                <div class="overview-value">{{ stats.override_count ?? 0 }}</div>
            </div>
            <div class="overview-card">
                <div class="overview-label">规则状态</div>
                <div class="overview-value">
                    <el-tag :type="activeRule?.is_enabled ? 'success' : 'info'">
                        {{ activeRule?.is_enabled ? '启用' : '未启用' }}
                    </el-tag>
                </div>
                <div class="overview-sub">
                    全局并发上限：{{ activeRule?.max_global_running ?? '-' }} | 用户并发上限：{{
                        activeRule?.max_user_running ?? '-'
                    }}
                </div>
            </div>
            <el-button text @click="fetchStats">
                <el-icon><i-ep-Refresh /></el-icon>刷新
            </el-button>
        </div>

        <el-card shadow="never">
            <template #header>
                <div class="card-header">
                    <span>全局并发规则</span>
                    <el-button type="primary" @click="openRuleCreate">
                        <el-icon><i-ep-Plus /></el-icon>新增规则
                    </el-button>
                </div>
            </template>
            <el-table
                :data="rules"
                stripe
                v-loading="rulesLoading"
                :header-cell-style="{ 'text-align': 'center' }"
                :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
            >
                <el-table-column label="功能" min-width="180">
                    <template #default="{ row }">
                        <el-tag>{{ row.feature_label || getFeatureLabel(row.feature) }}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="全局并发上限" width="150">
                    <template #default="{ row }">
                        <span v-if="row.max_global_running === -1" style="color: #67c23a">不限制</span>
                        <span v-else>{{ row.max_global_running }}</span>
                    </template>
                </el-table-column>
                <el-table-column label="用户并发上限" width="150">
                    <template #default="{ row }">
                        <span v-if="row.max_user_running === -1" style="color: #67c23a">不限制</span>
                        <span v-else>{{ row.max_user_running }}</span>
                    </template>
                </el-table-column>
                <el-table-column label="状态" width="110">
                    <template #default="{ row }">
                        <el-switch v-model="row.is_enabled" @change="handleRuleToggle(row)" />
                    </template>
                </el-table-column>
                <el-table-column label="描述" min-width="200" prop="description" />
                <el-table-column label="操作" width="160" fixed="right">
                    <template #default="{ row }">
                        <el-button circle plain type="primary" @click="openRuleEdit(row)">
                            <el-icon><i-ep-Edit /></el-icon>
                        </el-button>
                        <el-button circle plain type="danger" @click="deleteRule(row)">
                            <el-icon><i-ep-Delete /></el-icon>
                        </el-button>
                    </template>
                </el-table-column>
                <template #empty>
                    <el-empty description="暂无并发规则" />
                </template>
            </el-table>
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
            <template #header>
                <div class="card-header">
                    <span>用户并发覆盖</span>
                    <div class="toolbar">
                        <el-input
                            v-model="overrideFilters.keyword"
                            placeholder="用户名 / 用户ID 搜索"
                            clearable
                            style="width: 220px"
                            @keyup.enter="fetchOverrides"
                        />
                        <el-select v-model="overrideFilters.feature" clearable style="width: 180px" placeholder="功能">
                            <el-option
                                v-for="opt in featureOptions"
                                :key="opt.value"
                                :label="opt.label"
                                :value="opt.value"
                            />
                        </el-select>
                        <el-button type="primary" @click="fetchOverrides">查询</el-button>
                        <el-button @click="resetOverrideFilters">重置</el-button>
                        <el-button type="primary" @click="openOverrideCreate">
                            <el-icon><i-ep-Plus /></el-icon>新增覆盖
                        </el-button>
                    </div>
                </div>
            </template>

            <el-table
                :data="overrides"
                stripe
                v-loading="overridesLoading"
                :header-cell-style="{ 'text-align': 'center' }"
                :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
            >
                <el-table-column label="用户名" width="140">
                    <template #default="{ row }">
                        <el-tooltip :content="row.user_id" placement="top">
                            <span style="color: #409eff">{{ row.username }}</span>
                        </el-tooltip>
                    </template>
                </el-table-column>
                <el-table-column label="功能" min-width="180">
                    <template #default="{ row }">
                        <el-tag>{{ row.feature_label || getFeatureLabel(row.feature) }}</el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="用户并发上限" width="140">
                    <template #default="{ row }">
                        <span v-if="row.max_user_running === -1" style="color: #67c23a">不限制</span>
                        <span v-else>{{ row.max_user_running }}</span>
                    </template>
                </el-table-column>
                <el-table-column label="备注" min-width="180" prop="reason" />
                <el-table-column label="操作" width="100" fixed="right">
                    <template #default="{ row }">
                        <el-button circle plain type="danger" @click="deleteOverride(row)">
                            <el-icon><i-ep-Delete /></el-icon>
                        </el-button>
                    </template>
                </el-table-column>
                <template #empty>
                    <el-empty description="暂无并发覆盖配置" />
                </template>
            </el-table>
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
            <template #header>用户并发 Top</template>
            <div class="dual-table">
                <div class="table-col">
                    <div class="sub-title">运行中 Top10</div>
                    <el-table :data="stats.top_running_users || []" size="small" stripe>
                        <el-table-column type="index" width="60" label="#" />
                        <el-table-column prop="username" label="用户名" />
                        <el-table-column prop="running_count" label="运行中" width="100" />
                    </el-table>
                </div>
                <div class="table-col">
                    <div class="sub-title">排队中 Top10</div>
                    <el-table :data="stats.top_queued_users || []" size="small" stripe>
                        <el-table-column type="index" width="60" label="#" />
                        <el-table-column prop="username" label="用户名" />
                        <el-table-column prop="queued_count" label="排队中" width="100" />
                    </el-table>
                </div>
            </div>
        </el-card>

        <el-dialog
            v-model="ruleDialogVisible"
            :title="ruleEditMode ? '编辑并发规则' : '新增并发规则'"
            width="520px"
            @closed="resetRuleForm"
        >
            <el-form :model="ruleForm" :rules="ruleRules" ref="ruleFormRef" label-width="130px">
                <el-form-item label="功能类型" prop="feature">
                    <el-select v-model="ruleForm.feature" :disabled="ruleEditMode" style="width: 100%">
                        <el-option
                            v-for="opt in availableRuleFeatures"
                            :key="opt.value"
                            :label="opt.label"
                            :value="opt.value"
                        />
                    </el-select>
                </el-form-item>
                <el-form-item label="全局并发上限" prop="max_global_running">
                    <el-input-number v-model="ruleForm.max_global_running" :min="-1" :max="9999" style="width: 100%" />
                    <div class="form-hint">-1 表示不限制</div>
                </el-form-item>
                <el-form-item label="用户并发上限" prop="max_user_running">
                    <el-input-number v-model="ruleForm.max_user_running" :min="-1" :max="9999" style="width: 100%" />
                    <div class="form-hint">-1 表示不限制</div>
                </el-form-item>
                <el-form-item label="启用状态">
                    <el-switch v-model="ruleForm.is_enabled" />
                </el-form-item>
                <el-form-item label="描述">
                    <el-input v-model="ruleForm.description" type="textarea" :rows="2" />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="ruleDialogVisible = false">取消</el-button>
                <el-button type="primary" :loading="ruleSubmitting" @click="submitRule">确定</el-button>
            </template>
        </el-dialog>

        <el-dialog v-model="overrideDialogVisible" title="新增并发覆盖" width="520px" @closed="resetOverrideForm">
            <el-form :model="overrideForm" :rules="overrideRules" ref="overrideFormRef" label-width="120px">
                <el-form-item label="选择用户" prop="user_id">
                    <el-select
                        v-model="overrideForm.user_id"
                        filterable
                        remote
                        reserve-keyword
                        placeholder="输入用户名搜索"
                        :remote-method="searchUsers"
                        :loading="userSearchLoading"
                        style="width: 100%"
                        @change="onUserSelect"
                    >
                        <el-option
                            v-for="item in userOptions"
                            :key="item.user_id"
                            :label="item.username"
                            :value="item.user_id"
                        >
                            <div class="user-option">
                                <span>{{ item.username }}</span>
                                <span class="user-id">{{ item.user_id }}</span>
                            </div>
                        </el-option>
                    </el-select>
                </el-form-item>
                <el-form-item label="功能类型" prop="feature">
                    <el-select v-model="overrideForm.feature" style="width: 100%">
                        <el-option
                            v-for="opt in featureOptions"
                            :key="opt.value"
                            :label="opt.label"
                            :value="opt.value"
                        />
                    </el-select>
                </el-form-item>
                <el-form-item label="用户并发上限" prop="max_user_running">
                    <el-input-number
                        v-model="overrideForm.max_user_running"
                        :min="-1"
                        :max="9999"
                        style="width: 100%"
                    />
                    <div class="form-hint">-1 表示不限制</div>
                </el-form-item>
                <el-form-item label="备注">
                    <el-input v-model="overrideForm.reason" type="textarea" :rows="2" />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="overrideDialogVisible = false">取消</el-button>
                <el-button type="primary" :loading="overrideSubmitting" @click="submitOverride">确定</el-button>
            </template>
        </el-dialog>
    </div>
</template>

<script>
import {
    getConcurrencyRuleList,
    createConcurrencyRule,
    updateConcurrencyRule,
    deleteConcurrencyRule,
    getConcurrencyOverrideList,
    upsertConcurrencyOverride,
    deleteConcurrencyOverride,
    getConcurrencyStats
} from '@/api/access_frequency.js'
import { getUserList } from '@/api/user.js'
import { ElMessage, ElMessageBox } from 'element-plus'

const FEATURE_OPTIONS = [
    { value: 'deep_research', label: 'Deep Research 任务' },
    { value: 'ai_chat', label: 'AI 对话（研读/调研助手）' },
    { value: 'summary', label: '综述报告生成' },
    { value: 'export', label: '报告批量导出' }
]

export default {
    data() {
        return {
            featureOptions: FEATURE_OPTIONS,
            rules: [],
            rulesLoading: false,
            statsLoading: false,
            overridesLoading: false,
            stats: {},

            ruleDialogVisible: false,
            ruleEditMode: false,
            ruleSubmitting: false,
            ruleForm: {
                rule_id: null,
                feature: '',
                max_global_running: 3,
                max_user_running: 1,
                is_enabled: true,
                description: ''
            },
            ruleRules: {
                feature: [{ required: true, message: '请选择功能类型', trigger: 'change' }],
                max_global_running: [{ required: true, message: '请填写全局并发上限', trigger: 'blur' }],
                max_user_running: [{ required: true, message: '请填写用户并发上限', trigger: 'blur' }]
            },

            overrides: [],
            overrideFilters: { keyword: '', feature: 'deep_research' },
            overrideDialogVisible: false,
            overrideSubmitting: false,
            overrideForm: {
                user_id: '',
                selected_username: '',
                feature: 'deep_research',
                max_user_running: 1,
                reason: ''
            },
            overrideRules: {
                user_id: [{ required: true, message: '请选择用户', trigger: 'change' }],
                feature: [{ required: true, message: '请选择功能类型', trigger: 'change' }],
                max_user_running: [{ required: true, message: '请填写并发上限', trigger: 'blur' }]
            },
            userSearchLoading: false,
            userOptions: []
        }
    },
    computed: {
        availableRuleFeatures() {
            if (this.ruleEditMode) return this.featureOptions
            const used = this.rules.map((r) => r.feature)
            return this.featureOptions.filter((opt) => !used.includes(opt.value))
        },
        activeRule() {
            return this.rules.find((r) => r.feature === 'deep_research') || this.rules[0] || null
        }
    },
    created() {
        this.fetchAll()
    },
    methods: {
        async fetchAll() {
            await Promise.all([this.fetchRules(), this.fetchOverrides(), this.fetchStats()])
        },
        async fetchRules() {
            this.rulesLoading = true
            await getConcurrencyRuleList()
                .then((res) => {
                    this.rules = res.data.rules || []
                })
                .catch((err) => ElMessage.error(err.response?.data?.error || '获取并发规则失败'))
            this.rulesLoading = false
        },
        async fetchOverrides() {
            this.overridesLoading = true
            const params = {}
            if (this.overrideFilters.keyword) params.keyword = this.overrideFilters.keyword
            if (this.overrideFilters.feature) params.feature = this.overrideFilters.feature
            await getConcurrencyOverrideList(params)
                .then((res) => {
                    this.overrides = res.data.overrides || []
                })
                .catch((err) => ElMessage.error(err.response?.data?.error || '获取并发覆盖失败'))
            this.overridesLoading = false
        },
        async fetchStats() {
            this.statsLoading = true
            const params = {}
            if (this.overrideFilters.feature) params.feature = this.overrideFilters.feature
            await getConcurrencyStats(params)
                .then((res) => {
                    this.stats = res.data || {}
                })
                .catch((err) => ElMessage.error(err.response?.data?.error || '获取并发统计失败'))
            this.statsLoading = false
        },
        getFeatureLabel(feature) {
            return FEATURE_OPTIONS.find((item) => item.value === feature)?.label || feature
        },
        openRuleCreate() {
            this.ruleEditMode = false
            this.ruleDialogVisible = true
        },
        openRuleEdit(row) {
            this.ruleEditMode = true
            this.ruleForm = {
                rule_id: row.rule_id,
                feature: row.feature,
                max_global_running: row.max_global_running,
                max_user_running: row.max_user_running,
                is_enabled: row.is_enabled,
                description: row.description || ''
            }
            this.ruleDialogVisible = true
        },
        async handleRuleToggle(row) {
            await updateConcurrencyRule(row.rule_id, { is_enabled: row.is_enabled })
                .then(() => {
                    ElMessage.success(row.is_enabled ? '规则已启用' : '规则已禁用')
                    this.fetchStats()
                })
                .catch((err) => {
                    row.is_enabled = !row.is_enabled
                    ElMessage.error(err.response?.data?.error || '状态切换失败')
                })
        },
        async submitRule() {
            await this.$refs.ruleFormRef.validate()
            this.ruleSubmitting = true
            const payload = {
                feature: this.ruleForm.feature,
                max_global_running: this.ruleForm.max_global_running,
                max_user_running: this.ruleForm.max_user_running,
                is_enabled: this.ruleForm.is_enabled,
                description: this.ruleForm.description
            }
            const req = this.ruleEditMode
                ? updateConcurrencyRule(this.ruleForm.rule_id, payload)
                : createConcurrencyRule(payload)
            await req
                .then(() => {
                    ElMessage.success(this.ruleEditMode ? '并发规则已更新' : '并发规则已创建')
                    this.ruleDialogVisible = false
                    this.fetchRules()
                    this.fetchStats()
                })
                .catch((err) => ElMessage.error(err.response?.data?.error || '保存并发规则失败'))
            this.ruleSubmitting = false
        },
        deleteRule(row) {
            ElMessageBox.confirm(`确定删除「${this.getFeatureLabel(row.feature)}」并发规则吗？`, '删除确认', {
                type: 'warning',
                confirmButtonText: '删除',
                cancelButtonText: '取消'
            })
                .then(() => deleteConcurrencyRule(row.rule_id))
                .then(() => {
                    ElMessage.success('并发规则已删除')
                    this.fetchRules()
                    this.fetchStats()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(err.response?.data?.error || '删除失败')
                })
        },
        resetRuleForm() {
            this.ruleForm = {
                rule_id: null,
                feature: '',
                max_global_running: 3,
                max_user_running: 1,
                is_enabled: true,
                description: ''
            }
            this.$refs.ruleFormRef?.clearValidate()
        },
        resetOverrideFilters() {
            this.overrideFilters = { keyword: '', feature: 'deep_research' }
            this.fetchOverrides()
            this.fetchStats()
        },
        openOverrideCreate() {
            this.overrideDialogVisible = true
        },
        async searchUsers(keyword) {
            if (!keyword) {
                this.userOptions = []
                return
            }
            this.userSearchLoading = true
            await getUserList({ keyword, page_num: 1, page_size: 20 })
                .then((res) => {
                    this.userOptions = res.data.users || []
                })
                .catch(() => {
                    this.userOptions = []
                })
            this.userSearchLoading = false
        },
        onUserSelect(userId) {
            const selected = this.userOptions.find((item) => item.user_id === userId)
            this.overrideForm.selected_username = selected?.username || ''
        },
        async submitOverride() {
            await this.$refs.overrideFormRef.validate()
            this.overrideSubmitting = true
            const payload = {
                user_id: this.overrideForm.user_id,
                feature: this.overrideForm.feature,
                max_user_running: this.overrideForm.max_user_running,
                reason: this.overrideForm.reason
            }
            await upsertConcurrencyOverride(payload)
                .then(() => {
                    ElMessage.success('并发覆盖已保存')
                    this.overrideDialogVisible = false
                    this.fetchOverrides()
                    this.fetchStats()
                })
                .catch((err) => ElMessage.error(err.response?.data?.error || '保存并发覆盖失败'))
            this.overrideSubmitting = false
        },
        deleteOverride(row) {
            ElMessageBox.confirm(
                `确定删除用户「${row.username}」的并发覆盖吗？删除后将恢复全局并发规则。`,
                '删除确认',
                { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
            )
                .then(() => deleteConcurrencyOverride(row.override_id))
                .then(() => {
                    ElMessage.success('并发覆盖已删除')
                    this.fetchOverrides()
                    this.fetchStats()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(err.response?.data?.error || '删除失败')
                })
        },
        resetOverrideForm() {
            this.overrideForm = {
                user_id: '',
                selected_username: '',
                feature: 'deep_research',
                max_user_running: 1,
                reason: ''
            }
            this.userOptions = []
            this.$refs.overrideFormRef?.clearValidate()
        }
    }
}
</script>

<style lang="scss" scoped>
.concurrency-container {
    width: 100%;
}

.overview-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 14px;
    align-items: stretch;
}

.overview-card {
    min-width: 180px;
    flex: 1;
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 12px;
    .overview-label {
        color: #909399;
        font-size: 12px;
        margin-bottom: 8px;
    }
    .overview-value {
        font-size: 24px;
        font-weight: 700;
        color: #303133;
        &.running {
            color: #67c23a;
        }
        &.queued {
            color: #e6a23c;
        }
    }
    .overview-sub {
        margin-top: 6px;
        font-size: 12px;
        color: #606266;
    }
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    .toolbar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
    }
}

.dual-table {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
}

.sub-title {
    font-size: 13px;
    color: #606266;
    font-weight: 600;
    margin-bottom: 8px;
}

.user-option {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    .user-id {
        color: #909399;
        font-size: 11px;
        font-family: monospace;
    }
}

.form-hint {
    margin-top: 4px;
    font-size: 12px;
    color: #909399;
}

@media (max-width: 1024px) {
    .dual-table {
        grid-template-columns: 1fr;
    }
}
</style>
