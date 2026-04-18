<template>
    <div class="report-manage-table">
        <!-- 表格内容 -->
        <el-table
            :data="reportData"
            stripe
            style="width: 96%; border-top: 1px solid #edebeb; font-size: 15px; margin: 0 auto"
            size="large"
            v-loading="isLoading"
            :header-cell-style="{ 'text-align': 'center' }"
            :cell-style="{ 'text-align': 'center', 'vertical-align': 'middle' }"
            :default-sort="{ prop: 'date', order: 'descending' }"
        >
            <el-table-column label="序号" width="100" type="index"></el-table-column>
            <el-table-column label="时间" width="200">
                <template v-slot="scope">
                    <div class="table-text">
                        {{ scope.row.author_date }}
                    </div>
                </template>
            </el-table-column>
            <el-table-column label="用户" width="150">
                <template v-slot="scope">
                    <div class="table-text">
                        {{ scope.row.author_name }}
                    </div>
                </template>
            </el-table-column>
            <el-table-column label="类型">
                <template v-slot="scope">
                    <div class="table-text">
                        {{ scope.row.type }}
                    </div>
                </template>
            </el-table-column>
            <el-table-column label="已恢复评论">
                <template v-slot="scope">
                    <div class="table-text">
                        {{ scope.row.comment_content }}
                    </div>
                </template>
            </el-table-column>
            <el-table-column label="评论等级">
                <template v-slot="scope">
                    <div class="table-text">
                        {{ scope.row.comment_level }}
                    </div>
                </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
                <template v-slot="scope">
                    <el-button circle plain type="success" @click="handleCancel(scope.row)"> 撤销 </el-button>
                </template>
            </el-table-column>
            <template v-slot:empty>
                <el-empty description="没有数据" />
            </template>
        </el-table>
    </div>
</template>

<script>
import { getDeletedReportList, cancelRevertedReport } from '@/api/system_report'
import { ElMessage } from 'element-plus'

export default {
    data() {
        return {
            isLoading: false,
            reportData: []
        }
    },
    methods: {
        async handleCancel(item) {
            await cancelRevertedReport(item.id, item.type)
                .then(() => {
                    this.fetchSystemReport()
                    ElMessage.success('恢复成功！')
                })
                .catch(() => ElMessage.error('无法恢复！'))
        },
        async fetchSystemReport() {
            this.isLoading = true
            await getDeletedReportList()
                .then((response) => {
                    this.reportData = []
                    response.data.data.forEach((item) => {
                        if (item.reverted) {
                            this.reportData.push(item)
                        }
                    })
                })
                .catch(() => {
                    ElMessage.error('无法获取评论删除列表！')
                })
            this.isLoading = false
        }
    },
    created() {
        this.fetchSystemReport() // 初始化列表
    }
}
</script>

<style lang="scss" scoped>
.report-manage-table {
    width: 100%;
    .report-manage-search {
        float: right;
        height: 8vh;
        line-height: 8vh;
        padding: 0 3%;
    }
    .report-manage-pagination {
        height: 10vh;
        margin-right: 2%;
        float: right;
    }
}

.table-text {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>
