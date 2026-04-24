<template>
    <el-collapse v-model="isClsActive">
        <el-collapse-item name="1">
            <template #title>
                <div class="collapse-title">
                    <el-icon><i-ep-Monitor /></el-icon>
                    <span class="collapse-title-text">Deep Research 管理</span>
                </div>
            </template>
            <el-menu :default-active="$route.path" class="menu" mode="horizontal" :ellipsis="false" router>
                <el-menu-item class="menu-content" index="/deep-research/tasks">任务监控</el-menu-item>
                <el-menu-item class="menu-content" index="/deep-research/archive">任务归档</el-menu-item>
                <el-menu-item class="menu-content" index="/deep-research/compliance">合规审计</el-menu-item>
                <el-menu-item class="menu-content" index="/deep-research/audit-logs">审计日志</el-menu-item>
            </el-menu>
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
.menu {
    margin: 0 10px;
    .menu-content {
        font-weight: bold;
        color: #909399;
    }
}
</style>
