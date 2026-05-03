<template>
    <el-card class="hot-keywords-card">
        <template #header>
            <span>🔥 热门关键词</span>
        </template>

        <el-skeleton :loading="loading" animated>
            <template #default>
                <el-empty v-if="keywords.length === 0" description="暂无关键词" />
                <ul v-else class="hot-keywords-list">
                    <li v-for="(item, i) in keywords" :key="item.keyword" class="keyword-item">
                        <span class="index">{{ i + 1 }}.</span>
                        <span class="keyword">{{ item.keyword }}</span>
                    </li>
                </ul>
            </template>
        </el-skeleton>
    </el-card>
</template>

<script>
import { getHotKeywords } from '@/api/hot'
import { ElMessage } from 'element-plus'

export default {
    name: 'HotKeywords',
    data() {
        return {
            keywords: [],
            loading: false
        }
    },
    created() {
        this.fetchKeywords()
    },
    methods: {
        async fetchKeywords() {
            this.loading = true
            try {
                const res = await getHotKeywords()
                if (res.data?.data) {
                    this.keywords = res.data.data.sort((a, b) => b.index - a.index)
                } else {
                    ElMessage.warning(res.data?.message || '未获取到关键词数据')
                }
            } catch (err) {
                ElMessage.error(err?.response?.data?.error || '获取关键词失败')
            } finally {
                this.loading = false
            }
        }
    }
}
</script>

<style scoped>
.hot-keywords-card {
    width: 100%;
    max-width: 400px;
    margin: 0 auto;
    border-radius: 12px;
    font-weight: bold;
    color: rgb(0, 0, 0, 0.6);
    font-size: 16px;
    padding: 10px;
}
.hot-keywords-list {
    list-style: none;
    padding: 0;
    margin: 0;
}
.keyword-item {
    display: flex;
    align-items: center;
    padding: 6px 0;
    font-size: 16px;
}
.index {
    width: 24px;
    font-weight: bold;
    color: #f56c6c;
}
.keyword {
    margin-left: 8px;
    color: #409eff;
}
</style>
