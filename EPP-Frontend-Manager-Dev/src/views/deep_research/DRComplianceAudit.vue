<template>
    <div class="compliance-container">
        <el-alert
            title="深度研究合规审计"
            type="warning"
            :closable="false"
            description="对 Deep Research 任务“规划-检索-阅读-反思”全生命周期及最终报告进行合规监控，支持强制中断和强制屏蔽。"
            style="margin-bottom: 12px"
        />
        <DRTaskList :fixed-status-list="['violation_pending', 'needs_review']" />
    </div>
</template>

<script>
import DRTaskList from './DRTaskList.vue'

export default {
    components: { DRTaskList }
}
</script>

<style scoped>
.compliance-container {
    width: 100%;
}
</style>
