<template>
  <div>
    <el-row>
      <el-col :span="24">
        <h1 class='reportTitle'>翻译结果</h1>
      </el-col>
    </el-row>
    <el-row>
      <el-col :span="24">
        <el-card class="table-card">
          <el-table :data="displayedTranslations" v-loading="loading" style="width: 100%; min-height: 420px;" :default-sort="{prop: 'date', order: 'descending'}">
            <el-table-column prop="title" label="翻译标题" align="center">
              <template slot-scope="scope">
                <el-link
                  class="report-link"
                  :underline="false"
                  :disabled="scope.row.status !== 'done' || !scope.row.path"
                  @click="scope.row.status === 'done' && scope.row.path && downloadTranslation(scope.row.path)"
                  type="primary">
                  {{ scope.row.title }}
                </el-link>
              </template>
            </el-table-column>
            <el-table-column prop="date" label="生成时间" align="center" sortable></el-table-column>
            <el-table-column prop="glossary_name" label="术语表" align="center">
              <template slot-scope="scope">
                {{ scope.row.glossary_name || '无' }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" align="center">
              <template slot-scope="scope">
                <el-tag :type="getStatusTagType(scope.row.status)">
                  {{ getStatusText(scope.row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" align="center">
              <template slot-scope="scope">
                <el-button type="primary" size="small" icon="el-icon-delete" @click="deleteTranslation(scope.row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
    <el-pagination
      v-if="totalPages > 1"
      background
      style="margin-top: 10px;"
      @current-change="changePage"
      :current-page="currentPage"
      :page-size="itemsPerPage"
      layout="prev, pager, next"
      :total="totalRecords">
    </el-pagination>
  </div>
</template>

<script>
import { fetchTranslations, deleteTranslation } from '@/request/userRequest.js'

export default {
  data () {
    return {
      translations: [],
      currentPage: 1,
      itemsPerPage: 6,
      loading: true
    }
  },
  computed: {
    totalPages () {
      return Math.ceil(this.translations.length / this.itemsPerPage)
    },
    totalRecords () {
      return this.translations.length
    },
    displayedTranslations () {
      const start = (this.currentPage - 1) * this.itemsPerPage
      const end = start + this.itemsPerPage
      return this.translations.slice(start, end)
    }
  },
  methods: {
    async fetchTranslations () {
      try {
        const res = (await fetchTranslations()).data
        this.translations = res.data || []
        this.translations.sort((a, b) => new Date(b.date) - new Date(a.date))
        this.loading = false
      } catch (error) {
        console.error('fetchTranslations error:', error)
        this.loading = false
      }
    },
    changePage (page) {
      this.currentPage = page
    },
    downloadTranslation (url) {
      window.open(url, '_blank')
    },
    getStatusText (status) {
      switch (status) {
      case 'working':
        return '翻译中…'
      case 'done':
        return '翻译完成'
      case 'fail':
        return '翻译失败'
      default:
        return '未知'
      }
    },
    getStatusTagType (status) {
      switch (status) {
      case 'working':
        return 'info'
      case 'done':
        return 'success'
      case 'fail':
        return 'danger'
      default:
        return ''
      }
    },
    async deleteTranslation (id) {
      try {
        await deleteTranslation(id)
        this.$notify({
          title: '成功',
          message: '删除翻译结果成功！',
          type: 'success'
        })
        this.fetchTranslations()
      } catch (error) {
        console.error('deleteTranslation error:', error)
        this.$notify({
          title: '错误',
          message: error.message || '删除失败，请稍后重试。',
          type: 'error'
        })
      }
    }
  },
  mounted () {
    this.fetchTranslations()
  }
}
</script>

<style scoped>
.reportTitle {
  font-size: 30px;
  font-weight: bold;
  margin-bottom: 20px;
  color: rgb(18, 19, 18);
}
.table-card {
  border-radius: 12px;
}
.report-link {
  color: #409EFE;
  text-decoration: none;
}
.report-link:hover {
  opacity: 0.8;
  text-decoration: none;
}
</style>
