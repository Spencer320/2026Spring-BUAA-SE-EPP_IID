<template>
    <div class="overrides-container">
        <!-- 筛选 & 操作区 -->
        <div class="toolbar">
            <div class="filter-area">
                <el-input
                    v-model="filters.keyword"
                    placeholder="用户名搜索"
                    clearable
                    style="width: 180px"
                    @keyup.enter="handleSearch"
                />
                <el-select v-model="filters.feature" placeholder="全部功能" clearable style="width: 180px">
                    <el-option v-for="opt in featureOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
                <el-button type="primary" @click="handleSearch">搜索</el-button>
            </div>
            <el-button type="primary" @click="handleOpenCreate">
                <el-icon><i-ep-Plus /></el-icon>新增特殊配额
            </el-button>
        </div>

        <!-- 表格 -->
        <el-table
            :data="overrides"
            stripe
            v-loading="isLoading"
            style="width: 100%; border-top: 1px solid #edebeb; font-size: 15px"
            size="large"
            :header-cell-style="{ 'text-align': 'center' }"
            :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
        >
            <el-table-column label="序号" width="70" type="index" />
            <el-table-column label="用户名" width="140">
                <template #default="{ row }">
                    <el-tooltip :content="row.user_id" placement="top">
                        <span style="color: #409eff; cursor: pointer">{{ row.username }}</span>
                    </el-tooltip>
                </template>
            </el-table-column>
            <el-table-column label="功能类型" width="200">
                <template #default="{ row }">
                    <el-tag>{{ row.feature_label || getFeatureLabel(row.feature) }}</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="特殊配额" width="130">
                <template #default="{ row }">
                    <el-tag v-if="row.max_count === -1" type="success">无限制</el-tag>
                    <el-tag v-else-if="row.max_count === 0" type="danger">完全封禁</el-tag>
                    <span v-else>{{ formatQuota(row.max_count, row.feature) }}</span>
                </template>
            </el-table-column>
            <el-table-column label="备注原因" min-width="180" prop="reason" />
            <el-table-column label="创建时间" width="180" prop="created_at" />
            <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }">
                    <el-button circle plain type="primary" @click="handleOpenEdit(row)">
                        <el-icon><i-ep-Edit /></el-icon>
                    </el-button>
                    <el-button circle plain type="danger" @click="handleDelete(row)">
                        <el-icon><i-ep-Delete /></el-icon>
                    </el-button>
                </template>
            </el-table-column>
            <template #empty>
                <el-empty description="暂无用户特殊配额" />
            </template>
        </el-table>

        <!-- 新增对话框 -->
        <el-dialog
            v-model="dialogVisible"
            :title="isEditMode ? '编辑特殊配额' : '新增特殊配额'"
            width="500px"
            @closed="resetForm"
        >
            <el-form :model="formData" :rules="formRules" ref="overrideFormRef" label-width="90px">
                <el-form-item label="用户" prop="user_id">
                    <template v-if="isEditMode">
                        <el-input :model-value="formData.selectedUsername" disabled />
                        <div class="selected-hint">用户 ID：{{ formData.user_id }}</div>
                    </template>
                    <template v-else>
                        <el-select
                            v-model="formData.user_id"
                            filterable
                            remote
                            reserve-keyword
                            placeholder="输入用户名搜索"
                            :remote-method="remoteSearchUsers"
                            :loading="userSearchLoading"
                            style="width: 100%"
                            @change="handleUserSelected"
                        >
                            <el-option
                                v-for="user in userSearchResults"
                                :key="user.user_id"
                                :label="user.username"
                                :value="user.user_id"
                            >
                                <div class="user-option">
                                    <span class="user-option-name">{{ user.username }}</span>
                                    <span class="user-option-id">{{ user.user_id }}</span>
                                </div>
                            </el-option>
                        </el-select>
                        <div v-if="formData.selectedUsername" class="selected-hint">
                            已选用户：<strong>{{ formData.selectedUsername }}</strong>
                        </div>
                    </template>
                </el-form-item>

                <el-form-item label="功能类型" prop="feature">
                    <el-select
                        v-model="formData.feature"
                        placeholder="请选择功能"
                        style="width: 100%"
                        :disabled="isEditMode"
                    >
                        <el-option
                            v-for="opt in featureOptions"
                            :key="opt.value"
                            :label="opt.label"
                            :value="opt.value"
                        />
                    </el-select>
                </el-form-item>

                <el-form-item :label="overrideQuotaLabel" prop="max_count">
                    <el-input-number
                        v-model="formData.max_count"
                        :min="-1"
                        :max="formData.feature === 'research_assistant' ? 999999999 : 99999"
                        style="width: 180px"
                    />
                    <div class="form-hint">
                        <el-tag size="small" type="success" effect="plain">-1 = 不限制</el-tag>
                        <el-tag size="small" type="danger" effect="plain" style="margin-left: 6px">0 = 完全封禁</el-tag>
                        <el-tag size="small" effect="plain" style="margin-left: 6px">{{ overrideQuotaHint }}</el-tag>
                    </div>
                </el-form-item>

                <el-form-item label="备注原因">
                    <el-input
                        v-model="formData.reason"
                        type="textarea"
                        :rows="2"
                        placeholder="请填写设置原因（可选）"
                    />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="dialogVisible = false">取消</el-button>
                <el-button type="primary" @click="handleSubmit" :loading="submitting">确定</el-button>
            </template>
        </el-dialog>
    </div>
</template>

<script>
import { getOverrideList, upsertOverride, deleteOverride } from '@/api/access_frequency.js'
import { FEATURE_OPTIONS, getFeatureMeta, quotaLimitLabel } from '@/constants/accessFrequency.js'
import { getUserList } from '@/api/user.js'
import { ElMessage, ElMessageBox } from 'element-plus'

export default {
    data() {
        return {
            overrides: [],
            isLoading: false,
            filters: { keyword: '', feature: '' },
            featureOptions: FEATURE_OPTIONS,
            dialogVisible: false,
            isEditMode: false,
            submitting: false,
            userSearchLoading: false,
            userSearchResults: [],
            formData: {
                user_id: '',
                selectedUsername: '',
                feature: '',
                max_count: 10,
                reason: ''
            },
            formRules: {
                user_id: [{ required: true, message: '请搜索并选择用户', trigger: 'change' }],
                feature: [{ required: true, message: '请选择功能类型', trigger: 'change' }],
                max_count: [{ required: true, message: '请输入配额数值', trigger: 'blur' }]
            }
        }
    },
    computed: {
        overrideQuotaLabel() {
            return this.formData.feature ? quotaLimitLabel(this.formData.feature) : '特殊配额'
        },
        overrideQuotaHint() {
            const meta = getFeatureMeta(this.formData.feature)
            return meta.quotaMode === 'tokens' ? '正整数 = Token 上限' : '正整数 = 任务次数上限'
        }
    },
    created() {
        this.handleSearch()
    },
    methods: {
        async handleSearch() {
            this.isLoading = true
            const params = {}
            if (this.filters.keyword) params.keyword = this.filters.keyword
            if (this.filters.feature) params.feature = this.filters.feature
            await getOverrideList(params)
                .then((res) => {
                    this.overrides = res.data.overrides || []
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取配额覆盖列表失败')
                })
            this.isLoading = false
        },
        getFeatureLabel(feature) {
            return FEATURE_OPTIONS.find((o) => o.value === feature)?.label || feature
        },
        formatQuota(value, feature) {
            const meta = getFeatureMeta(feature)
            if (meta.quotaMode === 'tokens') {
                return `${Number(value).toLocaleString()} Token`
            }
            return `${value} 次`
        },
        handleOpenCreate() {
            this.isEditMode = false
            this.dialogVisible = true
        },
        handleOpenEdit(row) {
            this.isEditMode = true
            this.formData = {
                user_id: row.user_id,
                selectedUsername: row.username || '',
                feature: row.feature,
                max_count: row.max_count,
                reason: row.reason || ''
            }
            this.dialogVisible = true
        },
        async remoteSearchUsers(query) {
            if (!query) {
                this.userSearchResults = []
                return
            }
            this.userSearchLoading = true
            await getUserList({ keyword: query, page_num: 1, page_size: 20 })
                .then((res) => {
                    this.userSearchResults = res.data.users || []
                })
                .catch(() => {
                    this.userSearchResults = []
                })
            this.userSearchLoading = false
        },
        handleUserSelected(userId) {
            const user = this.userSearchResults.find((u) => u.user_id === userId)
            this.formData.selectedUsername = user?.username || ''
        },
        handleDelete(row) {
            ElMessageBox.confirm(
                `确定删除用户「${row.username}」对「${row.feature_label || this.getFeatureLabel(row.feature)}」的特殊配额吗？\n删除后将恢复全局默认规则。`,
                '删除特殊配额',
                { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
            )
                .then(() => deleteOverride(row.override_id))
                .then(() => {
                    ElMessage.success('已删除，该用户将恢复全局规则')
                    this.handleSearch()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '删除失败')
                })
        },
        async handleSubmit() {
            await this.$refs.overrideFormRef.validate()
            this.submitting = true
            const payload = {
                user_id: this.formData.user_id,
                feature: this.formData.feature,
                max_count: this.formData.max_count,
                reason: this.formData.reason
            }
            await upsertOverride(payload)
                .then(() => {
                    ElMessage.success(this.isEditMode ? '特殊配额已更新' : '特殊配额已保存')
                    this.dialogVisible = false
                    this.handleSearch()
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '操作失败')
                })
            this.submitting = false
        },
        resetForm() {
            this.isEditMode = false
            this.formData = { user_id: '', selectedUsername: '', feature: '', max_count: 10, reason: '' }
            this.userSearchResults = []
            this.$refs.overrideFormRef?.clearValidate()
        }
    }
}
</script>

<style lang="scss" scoped>
.overrides-container {
    width: 100%;
}
.toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0 12px;
    .filter-area {
        display: flex;
        gap: 10px;
        align-items: center;
    }
}
.user-option {
    display: flex;
    flex-direction: column;
    gap: 2px;
    .user-option-name {
        font-size: 14px;
        color: #303133;
    }
    .user-option-id {
        font-size: 11px;
        color: #909399;
        font-family: monospace;
    }
}
.selected-hint {
    font-size: 12px;
    color: #67c23a;
    margin-top: 4px;
}
.form-hint {
    margin-top: 6px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}
</style>
