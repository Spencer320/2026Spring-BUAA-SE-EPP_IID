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
            <el-table-column label="上限次数" width="110">
                <template #default="{ row }">
                    <span v-if="row.max_count === -1" style="color: #67c23a">不限制</span>
                    <span v-else>{{ row.max_count }} 次</span>
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
            <el-table-column label="最后更新" width="180" prop="updated_at" />
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
                    <el-select v-model="formData.feature" placeholder="请选择功能" :disabled="isEditMode" style="width: 100%">
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
                        <el-option v-for="opt in windowOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                    </el-select>
                </el-form-item>
                <el-form-item label="上限次数" prop="max_count">
                    <el-input-number
                        v-model="formData.max_count"
                        :min="-1"
                        :max="99999"
                        style="width: 100%"
                    />
                    <div class="form-hint">-1 表示不限制次数</div>
                </el-form-item>
                <el-form-item label="是否启用">
                    <el-switch v-model="formData.is_enabled" active-text="启用" inactive-text="禁用" />
                </el-form-item>
                <el-form-item label="备注说明">
                    <el-input v-model="formData.description" type="textarea" :rows="2" placeholder="可选，填写规则用途说明" />
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
import { ElMessage, ElMessageBox } from 'element-plus'

const FEATURE_OPTIONS = [
    { value: 'deep_research', label: 'Deep Research 任务' },
    { value: 'ai_chat', label: 'AI 对话（研读/调研助手）' },
    { value: 'summary', label: '综述报告生成' },
    { value: 'export', label: '报告批量导出' }
]

const WINDOW_OPTIONS = [
    { value: 'daily', label: '每日' },
    { value: 'weekly', label: '每周' },
    { value: 'monthly', label: '每月' }
]

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
        }
    },
    created() {
        this.fetchRules()
    },
    methods: {
        async fetchRules() {
            this.isLoading = true
            await getRuleList()
                .then((res) => {
                    this.rules = res.data.rules || []
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取规则列表失败')
                })
            this.isLoading = false
        },
        getFeatureLabel(feature) {
            return FEATURE_OPTIONS.find((o) => o.value === feature)?.label || feature
        },
        getWindowLabel(window) {
            return WINDOW_OPTIONS.find((o) => o.value === window)?.label || window
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
            await updateRule(row.rule_id, { is_enabled: row.is_enabled })
                .then(() => {
                    ElMessage.success(row.is_enabled ? '规则已启用' : '规则已禁用')
                })
                .catch((err) => {
                    row.is_enabled = !row.is_enabled
                    ElMessage.error(err.response?.data?.message || '操作失败')
                })
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
                    if (err !== 'cancel') ElMessage.error(err.response?.data?.message || '删除失败')
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
            await request
                .then(() => {
                    ElMessage.success(this.isEditMode ? '规则已更新' : '规则已创建')
                    this.dialogVisible = false
                    this.fetchRules()
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '操作失败')
                })
            this.submitting = false
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
