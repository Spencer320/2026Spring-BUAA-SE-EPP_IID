<template>
    <el-collapse v-model="isClsActive">
        <el-collapse-item name="1">
            <template #title>
                <div class="collapse-title">
                    <el-icon><i-ep-Odometer /></el-icon>
                    <span class="collapse-title-text">访问频次控制</span>
                </div>
            </template>
            <el-menu :default-active="$route.path" class="menu" mode="horizontal" :ellipsis="false" router>
                <el-menu-item class="menu-content" index="/access-frequency/rules">规则配置</el-menu-item>
                <el-menu-item class="menu-content" index="/access-frequency/overrides">用户特殊配额</el-menu-item>
                <el-menu-item class="menu-content" index="/access-frequency/stats">访问统计</el-menu-item>
                <el-menu-item class="menu-content" index="/access-frequency/concurrency">并发限制</el-menu-item>
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
