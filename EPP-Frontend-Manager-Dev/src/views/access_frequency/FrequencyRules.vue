<template>
    <div class="rules-container">
        <!-- 操作区 -->
        <div class="toolbar">
            <el-button type="primary" @click="handleOpenCreate">
                <el-icon><i-ep-Plus /></el-icon>新增规则
            </el-button>
        </div>

        <!-- 规则表格 -->
        <el-table
            :data="rules"
            stripe
            v-loading="isLoading"
            style="width: 100%; border-top: 1px solid #edebeb; font-size: 15px"
            size="large"
            :header-cell-style="{ 'text-align': 'center' }"
            :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
        >
            <el-table-column label="功能名称" min-width="160">
                <template #default="{ row }">
                    <el-tag>{{ row.feature_label || getFeatureLabel(row.feature) }}</el-tag>
                </template>
            </el-table-column>
            <el-table-column label="时间窗口" width="110">
                <template #default="{ row }">
                    {{ row.window_label || getWindowLabel(row.window) }}
                </template>
            </el-table-column>
            <el-table-column label="配额上限" width="130">
                <template #default="{ row }">
                    <span v-if="row.max_count === -1" style="color: #67c23a">不限制</span>
                    <span v-else>{{ formatQuota(row.max_count, row.feature) }}</span>
                </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
                <template #default="{ row }">
                    <el-switch
                        v-model="row.is_enabled"
                        @change="handleToggle(row)"
                        active-text="启用"
                        inactive-text="禁用"
                    />
                </template>
            </el-table-column>
            <el-table-column label="描述" min-width="180" prop="description" />
            <el-table-column label="最后修改时间" width="180">
                <template #default="{ row }">
                    {{ formatDateTime(row.updated_at) }}
                </template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right">
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
                <el-empty description="暂无频次规则" />
            </template>
        </el-table>

        <!-- 新增/编辑 对话框 -->
        <el-dialog
            v-model="dialogVisible"
            :title="isEditMode ? '编辑规则' : '新增规则'"
            width="480px"
            @closed="resetForm"
        >
            <el-form :model="formData" :rules="formRules" ref="ruleFormRef" label-width="100px">
                <el-form-item label="功能类型" prop="feature">
                    <el-select
                        v-model="formData.feature"
                        placeholder="请选择功能"
                        :disabled="isEditMode"
                        style="width: 100%"
                    >
                        <el-option
                            v-for="opt in availableFeatureOptions"
                            :key="opt.value"
                            :label="opt.label"
                            :value="opt.value"
                        />
                    </el-select>
                </el-form-item>
                <el-form-item label="时间窗口" prop="window">
                    <el-select v-model="formData.window" style="width: 100%">
                        <el-option
                            v-for="opt in windowOptions"
                            :key="opt.value"
                            :label="opt.label"
                            :value="opt.value"
                        />
                    </el-select>
                </el-form-item>
                <el-form-item :label="quotaLimitFormLabel" prop="max_count">
                    <el-input-number
                        v-model="formData.max_count"
                        :min="-1"
                        :max="formData.feature === 'research_assistant' ? 999999999 : 99999"
                        style="width: 100%"
                    />
                    <div class="form-hint">{{ quotaLimitHint }}</div>
                </el-form-item>
                <el-form-item label="是否启用">
                    <el-switch v-model="formData.is_enabled" active-text="启用" inactive-text="禁用" />
                </el-form-item>
                <el-form-item label="备注说明">
                    <el-input
                        v-model="formData.description"
                        type="textarea"
                        :rows="2"
                        placeholder="可选，填写规则用途说明"
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
import { getRuleList, createRule, updateRule, deleteRule } from '@/api/access_frequency.js'
import { FEATURE_OPTIONS, WINDOW_OPTIONS, getFeatureMeta, quotaLimitLabel } from '@/constants/accessFrequency.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatDateTime, getApiErrorMessage } from '@/utils/adminView.js'

export default {
    data() {
        return {
            rules: [],
            isLoading: false,
            dialogVisible: false,
            isEditMode: false,
            submitting: false,
            featureOptions: FEATURE_OPTIONS,
            windowOptions: WINDOW_OPTIONS,
            formData: {
                rule_id: null,
                feature: '',
                window: 'daily',
                max_count: 10,
                is_enabled: true,
                description: ''
            },
            formRules: {
                feature: [{ required: true, message: '请选择功能类型', trigger: 'change' }],
                window: [{ required: true, message: '请选择时间窗口', trigger: 'change' }],
                max_count: [{ required: true, message: '请输入上限次数', trigger: 'blur' }]
            }
        }
    },
    computed: {
        availableFeatureOptions() {
            if (this.isEditMode) return this.featureOptions
            const usedFeatures = this.rules.map((r) => r.feature)
            return this.featureOptions.filter((opt) => !usedFeatures.includes(opt.value))
        },
        quotaLimitFormLabel() {
            return this.formData.feature ? quotaLimitLabel(this.formData.feature) : '配额上限'
        },
        quotaLimitHint() {
            const meta = getFeatureMeta(this.formData.feature)
            if (meta.quotaMode === 'tokens') {
                return '-1 表示不限制 Token；科研助手按每轮对话累计 LLM Token 统计'
            }
            return '-1 表示不限制；深度研究按创建任务次数统计'
        }
    },
    created() {
        this.fetchRules()
    },
    methods: {
        formatDateTime,
        async fetchRules() {
            this.isLoading = true
            try {
                const res = await getRuleList()
                this.rules = res.data.rules || []
            } catch (err) {
                ElMessage.error(getApiErrorMessage(err, '获取规则列表失败'))
            } finally {
                this.isLoading = false
            }
        },
        getFeatureLabel(feature) {
            return FEATURE_OPTIONS.find((o) => o.value === feature)?.label || feature
        },
        getWindowLabel(window) {
            return WINDOW_OPTIONS.find((o) => o.value === window)?.label || window
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
                rule_id: row.rule_id,
                feature: row.feature,
                window: row.window,
                max_count: row.max_count,
                is_enabled: row.is_enabled,
                description: row.description
            }
            this.dialogVisible = true
        },
        async handleToggle(row) {
            try {
                await updateRule(row.rule_id, { is_enabled: row.is_enabled })
                ElMessage.success(row.is_enabled ? '规则已启用' : '规则已禁用')
            } catch (err) {
                row.is_enabled = !row.is_enabled
                ElMessage.error(getApiErrorMessage(err, '操作失败'))
            }
        },
        handleDelete(row) {
            ElMessageBox.confirm(`确定删除「${this.getFeatureLabel(row.feature)}」的频次规则吗？`, '删除确认', {
                confirmButtonText: '删除',
                cancelButtonText: '取消',
                type: 'warning'
            })
                .then(() => deleteRule(row.rule_id))
                .then(() => {
                    ElMessage.success('规则已删除')
                    this.fetchRules()
                })
                .catch((err) => {
                    if (err !== 'cancel') ElMessage.error(getApiErrorMessage(err, '删除失败'))
                })
        },
        async handleSubmit() {
            await this.$refs.ruleFormRef.validate()
            this.submitting = true
            const payload = {
                feature: this.formData.feature,
                window: this.formData.window,
                max_count: this.formData.max_count,
                is_enabled: this.formData.is_enabled,
                description: this.formData.description
            }
            const request = this.isEditMode ? updateRule(this.formData.rule_id, payload) : createRule(payload)
            try {
                await request
                ElMessage.success(this.isEditMode ? '规则已更新' : '规则已创建')
                this.dialogVisible = false
                this.fetchRules()
            } catch (err) {
                ElMessage.error(getApiErrorMessage(err, '操作失败'))
            } finally {
                this.submitting = false
            }
        },
        resetForm() {
            this.formData = {
                rule_id: null,
                feature: '',
                window: 'daily',
                max_count: 10,
                is_enabled: true,
                description: ''
            }
            this.$refs.ruleFormRef?.clearValidate()
        }
    }
}
</script>

<style lang="scss" scoped>
.rules-container {
    width: 100%;
}
.toolbar {
    display: flex;
    justify-content: flex-end;
    padding: 8px 0 12px;
}
.form-hint {
    font-size: 12px;
    color: #909399;
    margin-top: 4px;
}
</style>
