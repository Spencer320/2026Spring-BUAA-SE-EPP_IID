<template>
    <div class="stats-container">
        <!-- 概览卡片区 -->
        <div class="overview-section">
            <div class="section-header">
                <el-icon><i-ep-DataAnalysis /></el-icon>
                <span>今日访问概览</span>
                <el-button size="small" text @click="fetchStats" style="margin-left: 12px">
                    <el-icon><i-ep-Refresh /></el-icon>刷新
                </el-button>
            </div>
            <div class="stat-cards" v-loading="statsLoading">
                <div class="stat-card" v-for="item in statCards" :key="item.feature">
                    <div class="stat-card-label">{{ item.label }}</div>
                    <div class="stat-card-row">
                        <div class="stat-card-item">
                            <span class="stat-card-num total">{{ item.total }}</span>
                            <span class="stat-card-sub">总调用</span>
                        </div>
                        <div class="stat-card-divider"></div>
                        <div class="stat-card-item">
                            <span class="stat-card-num allowed">{{ item.allowed }}</span>
                            <span class="stat-card-sub">已放行</span>
                        </div>
                        <div class="stat-card-divider"></div>
                        <div class="stat-card-item">
                            <span class="stat-card-num rejected">{{ item.rejected }}</span>
                            <span class="stat-card-sub">已拒绝</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="active-rules-tip" v-if="activeRules !== null">
                当前启用规则数：<strong>{{ activeRules }}</strong> 条
            </div>
        </div>

        <!-- 用户访问排行 -->
        <div class="ranking-section">
            <div class="section-header">
                <el-icon><i-ep-Trophy /></el-icon>
                <span>用户访问排行</span>
                <el-select
                    v-model="rankingFeature"
                    placeholder="全部功能"
                    clearable
                    size="small"
                    style="width: 180px; margin-left: 12px"
                    @change="fetchRanking"
                >
                    <el-option v-for="opt in featureOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
                <el-button size="small" text @click="fetchRanking" style="margin-left: 6px">
                    <el-icon><i-ep-Refresh /></el-icon>
                </el-button>
            </div>

            <el-table
                :data="ranking"
                stripe
                v-loading="rankingLoading"
                style="width: 100%; border-top: 1px solid #edebeb; font-size: 14px"
                size="default"
                :header-cell-style="{ 'text-align': 'center' }"
                :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
            >
                <el-table-column label="排名" width="70" type="index" />
                <el-table-column label="用户名" width="140">
                    <template #default="{ row }">
                        <span class="username-link" @click="handleViewUserDetail(row)">{{ row.username }}</span>
                    </template>
                </el-table-column>
                <el-table-column label="用户ID" width="130">
                    <template #default="{ row }">
                        <el-tooltip :content="row.user_id" placement="top">
                            <span class="id-text">{{ row.user_id.slice(0, 8) }}...</span>
                        </el-tooltip>
                    </template>
                </el-table-column>
                <el-table-column label="调用次数" prop="total" sortable width="110" />
                <el-table-column label="被拒次数" prop="rejected" sortable width="110">
                    <template #default="{ row }">
                        <span :style="{ color: row.rejected > 0 ? '#f56c6c' : 'inherit' }">{{ row.rejected }}</span>
                    </template>
                </el-table-column>
                <el-table-column label="操作" width="120">
                    <template #default="{ row }">
                        <el-button size="small" type="primary" plain @click="handleViewUserDetail(row)"
                            >配额详情</el-button
                        >
                    </template>
                </el-table-column>
                <template #empty>
                    <el-empty description="暂无数据" />
                </template>
            </el-table>
        </div>

        <!-- 用户配额详情弹窗 -->
        <el-dialog v-model="detailVisible" :title="`用户配额详情 — ${detailUser.username}`" width="600px">
            <div v-loading="detailLoading">
                <div class="detail-user-info">
                    <span>用户ID：{{ detailUser.user_id }}</span>
                </div>
                <el-table :data="detailUser.features" style="width: 100%; margin-top: 12px" size="default" stripe>
                    <el-table-column label="功能" min-width="160">
                        <template #default="{ row }">
                            <el-tag size="small">{{ getFeatureLabel(row.feature) }}</el-tag>
                        </template>
                    </el-table-column>
                    <el-table-column label="窗口" width="80" prop="window">
                        <template #default="{ row }">{{ getWindowLabel(row.window) }}</template>
                    </el-table-column>
                    <el-table-column label="上限" width="80">
                        <template #default="{ row }">
                            <span v-if="row.limit === -1" style="color: #67c23a">不限</span>
                            <span v-else>{{ row.limit }}</span>
                        </template>
                    </el-table-column>
                    <el-table-column label="已用" width="80" prop="used" />
                    <el-table-column label="剩余" width="80">
                        <template #default="{ row }">
                            <span v-if="row.limit === -1">—</span>
                            <span :style="{ color: row.remaining <= 1 ? '#f56c6c' : '#67c23a' }" v-else>
                                {{ row.remaining }}
                            </span>
                        </template>
                    </el-table-column>
                    <el-table-column label="特殊配额" width="100">
                        <template #default="{ row }">
                            <el-tag v-if="row.override_applied" type="warning" size="small">已覆盖</el-tag>
                            <el-tag v-else type="info" size="small">全局规则</el-tag>
                        </template>
                    </el-table-column>
                </el-table>
            </div>
            <template #footer>
                <el-button @click="detailVisible = false">关闭</el-button>
            </template>
        </el-dialog>
    </div>
</template>

<script>
import { getGlobalStats, getUserStatsRanking, getUserStatsDetail } from '@/api/access_frequency.js'
import { ElMessage } from 'element-plus'

const FEATURE_OPTIONS = [
    { value: 'deep_research', label: 'Deep Research 任务' },
    { value: 'ai_chat', label: 'AI 对话' },
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
            statsLoading: false,
            rankingLoading: false,
            detailLoading: false,
            activeRules: null,
            statCards: [],
            featureOptions: FEATURE_OPTIONS,
            rankingFeature: '',
            ranking: [],
            detailVisible: false,
            detailUser: { username: '', user_id: '', features: [] }
        }
    },
    created() {
        this.fetchStats()
        this.fetchRanking()
    },
    methods: {
        async fetchStats() {
            this.statsLoading = true
            await getGlobalStats()
                .then((res) => {
                    const today = res.data.today || {}
                    this.activeRules = res.data.active_rules ?? null
                    this.statCards = FEATURE_OPTIONS.map((opt) => ({
                        feature: opt.value,
                        label: opt.label,
                        total: today[opt.value]?.total ?? 0,
                        allowed: today[opt.value]?.allowed ?? 0,
                        rejected: today[opt.value]?.rejected ?? 0
                    }))
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取统计数据失败')
                })
            this.statsLoading = false
        },
        async fetchRanking() {
            this.rankingLoading = true
            const params = {}
            if (this.rankingFeature) params.feature = this.rankingFeature
            await getUserStatsRanking(params)
                .then((res) => {
                    this.ranking = res.data.items || []
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取排行数据失败')
                })
            this.rankingLoading = false
        },
        async handleViewUserDetail(row) {
            this.detailUser = { username: row.username, user_id: row.user_id, features: [] }
            this.detailVisible = true
            this.detailLoading = true
            await getUserStatsDetail(row.user_id)
                .then((res) => {
                    this.detailUser = {
                        username: res.data.username || row.username,
                        user_id: res.data.user_id || row.user_id,
                        features: res.data.features || []
                    }
                })
                .catch((err) => {
                    ElMessage.error(err.response?.data?.message || '获取用户配额详情失败')
                })
            this.detailLoading = false
        },
        getFeatureLabel(feature) {
            return FEATURE_OPTIONS.find((o) => o.value === feature)?.label || feature
        },
        getWindowLabel(window) {
            return WINDOW_OPTIONS.find((o) => o.value === window)?.label || window
        }
    }
}
</script>

<style lang="scss" scoped>
.stats-container {
    width: 100%;
}
.section-header {
    display: flex;
    align-items: center;
    font-size: 15px;
    font-weight: bold;
    color: rgb(0, 0, 0, 0.65);
    margin-bottom: 12px;
    .el-icon {
        margin-right: 6px;
    }
}
.overview-section {
    margin-bottom: 24px;
}
.stat-cards {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    min-height: 90px;
}
.stat-card {
    flex: 1;
    min-width: 200px;
    border: 1px solid #ebeef5;
    border-radius: 6px;
    padding: 14px 16px;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
    .stat-card-label {
        font-size: 13px;
        color: #606266;
        margin-bottom: 10px;
        font-weight: bold;
    }
    .stat-card-row {
        display: flex;
        align-items: center;
        justify-content: space-around;
    }
    .stat-card-item {
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    .stat-card-divider {
        width: 1px;
        height: 32px;
        background: #ebeef5;
    }
    .stat-card-num {
        font-size: 22px;
        font-weight: bold;
        &.total {
            color: #409eff;
        }
        &.allowed {
            color: #67c23a;
        }
        &.rejected {
            color: #f56c6c;
        }
    }
    .stat-card-sub {
        font-size: 11px;
        color: #909399;
        margin-top: 2px;
    }
}
.active-rules-tip {
    margin-top: 10px;
    font-size: 13px;
    color: #606266;
}
.ranking-section {
    margin-top: 8px;
}
.username-link {
    color: #409eff;
    cursor: pointer;
    &:hover {
        text-decoration: underline;
    }
}
.id-text {
    font-family: monospace;
    font-size: 13px;
    color: #909399;
}
.detail-user-info {
    font-size: 13px;
    color: #606266;
    margin-bottom: 4px;
}
</style>
