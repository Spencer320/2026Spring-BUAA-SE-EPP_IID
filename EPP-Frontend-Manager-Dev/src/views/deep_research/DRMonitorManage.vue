<template>
    <el-collapse v-model="isClsActive">
        <el-collapse-item name="1">
            <template #title>
                <div class="collapse-title">
                    <el-icon><i-ep-Monitor /></el-icon>
                    <span class="collapse-title-text">深度研究管理</span>
                </div>
            </template>
            <div style="padding: 10px"><router-view></router-view></div>
        </el-collapse-item>
    </el-collapse>
</template>

<script>
export default {
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
    color: rgb(0, 0, 0, 0.6);
    font-size: 16px;
    font-weight: bold;
    padding: 10px;
    .collapse-title-text {
        margin-left: 10px;
    }
}
</style>
