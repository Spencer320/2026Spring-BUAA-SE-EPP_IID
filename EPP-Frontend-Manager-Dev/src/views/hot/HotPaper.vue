<template>
    <div class="paper-manage-container">
        <div class="collapse-title">
            <el-icon><i-ep-management /></el-icon>
            <span class="collapse-title-text">热门文献</span>
        </div>
        <!-- 表格内容 -->
        <div class="paper-manage-table">
            <el-table
                :data="paperData"
                stripe
                style="width: 94%; border-top: 1px solid #edebeb; font-size: 15px"
                size="large"
                v-loading="isLoading"
                :header-cell-style="{ 'text-align': 'center' }"
                :cell-style="{ 'text-align': 'center' }"
                :default-sort="{ prop: 'publication_date', order: 'descending' }"
            >
                <el-table-column label="序号" width="100" type="index"></el-table-column>
                <el-table-column label="标题">
                    <template v-slot="scope">
                        <el-tooltip class="item" effect="light" :content="scope.row.title" placement="bottom">
                            <div class="text-left" style="color: #409efe; cursor: pointer">
                                {{ scope.row.title }}
                            </div>
                        </el-tooltip>
                    </template>
                </el-table-column>
                <el-table-column label="操作" width="80">
                    <template v-slot="scope">
                        <el-button circle plain type="success" @click="handleView(scope.row)">
                            <el-icon><i-ep-view></i-ep-view></el-icon>
                        </el-button>
                    </template>
                </el-table-column>
                <template v-slot:empty>
                    <el-empty description="没有数据" />
                </template>
            </el-table>
        </div>
        <!-- 论文概述 -->
        <el-dialog v-model="paperOutline.visible" width="60vw">
            <PaperOutline :paperID="paperOutline.paperID"></PaperOutline>
        </el-dialog>
        <!-- 分页组件 -->
    </div>
</template>

<script>
import { getHotPapers } from '@/api/hot'
import PaperOutline from '../paper/PaperOutline.vue'
import { ElMessage } from 'element-plus'

export default {
    name: 'HotPaper',
    components: {
        PaperOutline
    },
    data() {
        return {
            paperOutline: {
                visible: false,
                paperID: ''
            },
            paperData: [
                {
                    id: '',
                    title: ''
                }
            ],
            isLoading: false
        }
    },
    methods: {
        handleView(item) {
            this.$nextTick(() => {
                this.paperOutline.visible = true
                this.paperOutline.paperID = item.id
            })
        },
        async fetchPapers() {
            this.isLoading = true
            await getHotPapers()
                .then((response) => {
                    this.paperData = response.data.data
                })
                .catch((error) => {
                    ElMessage.error(error.response.data.message)
                })
            this.isLoading = false
        }
    },
    created() {
        this.fetchPapers()
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
.number-box {
    float: left;
    width: 22%;
    height: 14vh;
    margin-left: 1%;
    margin-right: 1%;
    margin-bottom: 2%;
    margin-top: 1%;
    box-shadow: 0px 0px 3px 1px rgba(0, 0, 0, 0.2);
    .number-box-icon {
        float: left;
        width: 35%;
        height: 100%;
        margin-left: 5%;
    }

    .number-box-content {
        float: right;
        width: 60%;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;

        .number-box-title {
            flex: 2;
            font-size: 20px;
            font-weight: bold;
            padding: 5%;
            border-bottom: 1px solid black;
        }
        .number-box-digit {
            flex: 3;
            margin-top: 5%;
            font-weight: 500;
            font-size: 21px;
        }
    }
}
.chart-box {
    width: 94%;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    box-shadow: 0px 0px 3px 1px rgba(0, 0, 0, 0.2);
    .chart-box-title {
        display: flex;
        justify-content: center;
        align-items: center;
        span {
            font-size: 20px;
            font-weight: bold;
        }
    }
    .chart-box-content {
        flex: 8;
        width: 95%;
    }
}
.paper-manage-container {
    margin-top: 2vh;
    background-color: white;
    overflow: hidden;
    .paper-manage-search {
        float: right;
        height: 8vh;
        line-height: 8vh;
        padding: 0 3%;
    }
    .paper-manage-table {
        display: flex;
        justify-content: center;
        width: 100%;
    }
    .paper-manage-pagination {
        height: 10vh;
        margin-right: 3%;
        float: right;
    }
}
.text-left {
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>
