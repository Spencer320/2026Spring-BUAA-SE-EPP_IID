<template>
    <div>
        <div style="width: 100%">
            <el-collapse v-model="isClsActive">
                <el-collapse-item name="1">
                    <template #title>
                        <div class="collapse-title">
                            <el-icon><i-ep-management /></el-icon>
                            <span class="collapse-title-text">热门关键词</span>
                        </div>
                    </template>
                    <HotKeywords />
                </el-collapse-item>
            </el-collapse>
        </div>
    </div>
    <UserTimeTable />
    <HotPaper />
</template>

<script>
import HotKeywords from './HotKeywords.vue'
import HotPaper from './HotPaper.vue'
import UserTimeTable from './UserTimeTable.vue'
export default {
    components: {
        HotKeywords,
        HotPaper,
        UserTimeTable
    },
    data() {
        return {
            isClsActive: '1'
        }
    }
}
</script>

<style lang="scss" scoped>
.collapse-title {
    display: flex;
    align-items: center;
    font-weight: bold;
    color: rgb(0, 0, 0, 0.6);
    font-size: 16px;
    padding: 10px;
    .collapse-title-text {
        margin-left: 10px;
    }
}
</style>
