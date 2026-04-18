<template>
    <div class="paper-manage-container">
        <div class="collapse-title">
            <el-icon><i-ep-Histogram /></el-icon>
            <span class="collapse-title-text">用户在线时段统计</span>
        </div>
        <div class="chart-box" style="height: 45vh; margin-bottom: 3vh">
            <div class="chart-box-title" style="flex: 2"><span>用户在线时段统计</span></div>
            <div id="userOnlineChart" class="chart-box-content"></div>
        </div>
    </div>
</template>

<script>
import { ElMessage } from 'element-plus'
import { getVisitTime } from '@/api/hot'
import { getCurrentInstance } from 'vue'

export default {
    name: 'UserTimeTable',
    data() {
        return {
            dates: [],
            morning: [],
            noon: [],
            afternoon: [],
            evening: []
        }
    },
    async mounted() {
        let internalInstance = getCurrentInstance()
        let echarts = internalInstance.appContext.config.globalProperties.$echarts

        const userOnlineChart = echarts.init(document.getElementById('userOnlineChart'))

        const option = {
            title: {
                text: '最近30天用户在线人数 ',
                left: 'center'
            },
            tooltip: {
                trigger: 'axis',
                axisPointer: {
                    type: 'shadow'
                }
            },
            toolbox: {
                feature: {
                    dataView: { show: true, readOnly: false },
                    magicType: { show: true, type: ['line', 'bar'] },
                    restore: { show: true },
                    saveAsImage: { show: true }
                }
            },
            legend: {
                top: '10%',
                data: ['早上', '中午', '下午', '晚上']
            },
            grid: {
                top: '20%',
                left: '3%',
                right: '4%',
                bottom: '3%',
                containLabel: true
            },
            xAxis: {
                type: 'category',
                data: [] // 日期
            },
            yAxis: {
                type: 'value',
                name: '在线人数'
            },
            series: [
                {
                    name: '早上',
                    type: 'bar',
                    stack: '总量',
                    emphasis: { focus: 'series' },
                    data: []
                },
                {
                    name: '中午',
                    type: 'bar',
                    stack: '总量',
                    emphasis: { focus: 'series' },
                    data: []
                },
                {
                    name: '下午',
                    type: 'bar',
                    stack: '总量',
                    emphasis: { focus: 'series' },
                    data: []
                },
                {
                    name: '晚上',
                    type: 'bar',
                    stack: '总量',
                    emphasis: { focus: 'series' },
                    data: []
                }
            ]
        }
        option.xAxis.data = this.dates
        option.series[0].data = this.morning
        option.series[1].data = this.noon
        option.series[2].data = this.afternoon
        option.series[3].data = this.evening
        await getVisitTime()
            .then((response) => {
                const rawData = response.data
                // 遍历原始数据
                rawData.data.forEach((entry) => {
                    this.dates.push(entry.date)
                    this.morning.push(entry.visits[0])
                    this.noon.push(entry.visits[1])
                    this.afternoon.push(entry.visits[2])
                    this.evening.push(entry.visits[3])
                })
                // 设置到图表 option
                option.xAxis.data = this.dates
                option.series[0].data = this.morning
                option.series[1].data = this.noon
                option.series[2].data = this.afternoon
                option.series[3].data = this.evening
            })
            .catch((error) => {
                ElMessage.error(error.response?.data?.message || '加载失败')
            })

        userOnlineChart.setOption(option)
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
