<template>
  <el-col style="overflow: hidden; height: 100vh" v-loading="loading" element-loading-text="正在搜索…🔍">
    <div v-if="loading && limitedLoadingHints.length > 0" class="loading-hints-container"
        style="position: fixed; bottom: 250px; left: 50%; transform: translateX(-50%);
                background: rgba(255, 255, 255, 0.9);
                padding: 10px 20px; border-radius: 5px;
                box-shadow: 0 0 8px rgba(0,0,0,0.2);
                max-height: 150px; overflow-y: auto;
                color: #409eff; font-size: 16px; z-index: 3000;">
      <div v-for="(hint, index) in limitedLoadingHints" :key="index" style="white-space: nowrap; display: flex; align-items: center; gap: 6px;">
        <span>{{ hint.text }}</span>
        <span v-if="hint.done" style="color: green;">✅</span>
        <span v-else style="color: orange; animation: spin 1s linear infinite;">🔄</span>
      </div>
    </div>

    <el-col :span="16" style="margin-top: 80px;" type="flex">
      <el-row>
        <el-col :span="22" :offset="1" style="display: flex; align-items: center;">
          <el-switch v-model="isDialogSearch" active-text="语义匹配" inactive-text="精确匹配">
          </el-switch>
          <div style="width: 80%;">
            <search-input :searchType="isDialogSearch ? 'dialogue' : 'string'"
            :searchContent.sync="defaultSearchContent"/>
          </div>
        </el-col>
      </el-row>
      <el-row>
        <el-col :span="4" style="margin-top: 15px;">
          <el-col :span="18" :offset="6">
            <!-- 侧边栏 -->
            <div class="filter-cond">
              <el-button type="text" @click="filterByYear(0)"
                :class="filterYear === 0 ? 'clicked-button' : 'normal-button'">时间不限</el-button>
            </div>
            <div class="filter-cond">
              <el-button type="text" @click="filterByYear(2024)"
                :class="filterYear === 2024 ? 'clicked-button' : 'normal-button'">2024年以来</el-button>
            </div>
            <div class="filter-cond">
              <el-button type="text" @click="filterByYear(2022)"
                :class="filterYear === 2022 ? 'clicked-button' : 'normal-button'">2022年以来</el-button>
            </div>
            <div class="filter-cond">
              <el-button type="text" @click="filterByYear(2020)"
                :class="filterYear === 2020 ? 'clicked-button' : 'normal-button'">2020年以来</el-button>
            </div>
            <el-divider></el-divider>
            <div class="filter-cond">
              <el-button type="text" @click="sortPapers('')"
                :class="sortOrder === '' ? 'clicked-button' : 'normal-button'">默认排序</el-button>
            </div>
            <div class="filter-cond">
              <el-button type="text" @click="sortPapers('asc')"
                :class="sortOrder === 'asc' ? 'clicked-button' : 'normal-button'">按时间升序</el-button>
            </div>
            <div class="filter-cond">
              <el-button type="text" @click="sortPapers('desc')"
                :class="sortOrder === 'desc' ? 'clicked-button' : 'normal-button'">按时间降序</el-button>
            </div>
            <el-divider></el-divider>
            <el-form label-position="top">
              <el-form-item>
                <el-select v-model="filterSubclass" placeholder="所有类别" @change="applyFilter">
                  <el-option label="所有类别" value=""></el-option>
                  <el-option label="边缘检测" value="边缘检测"></el-option>
                  <el-option label="目标检测" value="目标检测"></el-option>
                  <el-option label="图像分类" value="图像分类"></el-option>
                  <el-option label="图像去噪" value="图像去噪"></el-option>
                  <el-option label="图像分割" value="图像分割"></el-option>
                  <el-option label="人脸识别" value="人脸识别"></el-option>
                  <el-option label="姿态估计" value="姿态估计"></el-option>
                  <el-option label="动作识别" value="动作识别"></el-option>
                  <el-option label="人群计数" value="人群计数"></el-option>
                  <el-option label="医学影像" value="医学影像"></el-option>
                  <el-option label="三维重建" value="三维重建"></el-option>
                  <el-option label="对抗样本攻击" value="对抗样本攻击"></el-option>
                </el-select>
              </el-form-item>
            </el-form>
            <el-divider></el-divider>
          </el-col>
        </el-col>
        <el-col :span="20">
          <el-main>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                共检索出 {{ filteredPapers.length }} 篇论文
                <div>
                  <el-button type="success" icon="el-icon-download" @click="downloadPapers" size="small">
                    下载文献
                  </el-button>
                  <el-button type="primary" icon="el-icon-document-copy" @click="generateSummaryReport" size="small">
                    生成综述
                  </el-button>
                </div>
              </div>

              <div class="papers-container" v-if="papers && papers.length > 0">
                <div v-for="paper in filteredPapers" :key="paper.paper_id" style="margin-top: 30px;">
                  <div class="columns is-mobile">
                    <div class="column is-narrow checkbox">
                      <el-checkbox
                        v-model="checkedPapers[paper.paper_id]"
                        @change="handleCheckboxChange(paper.paper_id)">
                      </el-checkbox>
                    </div>
                    <paper-card :paper="paper" />
                  </div>
                </div>
              </div>
              <div v-else-if="papers && papers.length == 0">
                <img
                  src="@/assets/userAvatar/ybw.jpg"
                  alt=""
                  width="30%"
                  height="30%"
                  style="border-radius: 50%; margin-top: 3rem;">
                <img src="@/assets/前面的区域以后再来探索吧.jpg" alt="">
              </div>
            <el-backtop :visibility-height="100"></el-backtop>
          </el-main>
        </el-col>
      </el-row>
    </el-col>
    <el-col :span="8" style="height: 100vh; position: sticky; top: 55px">
      <ai-assistant v-if="aiReply.length > 0" :aiReply="aiReply" :paperIds="paperIds" :searchRecordID="searchRecordID"
        :restoreHistory="restoreHistory" @find-paper="searchPaperByAssistant" />
    </el-col>
  </el-col>
</template>

<script>
import request from '@/request/request'
import SearchAssistant from './SearchAssistant.vue'
import PaperCard from './PaperCard.vue'
import SearchInput from './SearchInput.vue'
import { EventBus } from '@/main.js'

export default {
  components: {
    'ai-assistant': SearchAssistant,
    'paper-card': PaperCard,
    'search-input': SearchInput
  },
  props: ['searchForm'],
  watch: {
    '$route.query.search_content' (newContent) {
      this.defaultSearchContent = newContent
      this.startSearch()
    }
  },
  data () {
    return {
      papers: null,
      filteredPapers: [],
      checkedPapers: {},
      selectedPapers: [],
      filterYear: 0,
      sortOrder: '',
      filterSubclass: '',
      isDialogSearch: true,
      defaultSearchContent: '',

      loading: false,
      loadingHint: '正在搜索...',
      loadingHints: [], // 保存所有的 loading 提示

      aiReply: [],
      paperIds: [],
      searchRecordID: '',
      restoreHistory: false
    }
  },
  computed: {
    limitedLoadingHints () {
    // 如果 loadingHints 长度超过5，只显示最后5条，否则全部显示
      if (this.loadingHints.length > 5) {
        return this.loadingHints.slice(-5)
      } else {
        return this.loadingHints
      }
    }
  },
  methods: {
    filterByYear (year) {
      this.filterYear = year
      this.applyFilter()
    },
    sortPapers (sortOrder) {
      this.sortOrder = sortOrder
      this.applyFilter()
    },
    applyFilter () {
      let results = this.papers.slice()
      if (this.sortOrder === 'asc') {
        results.sort((a, b) => {
          const dateA = new Date(a.publication_date)
          const dateB = new Date(b.publication_date)
          return dateA - dateB // 升序排序
        })
      } else if (this.sortOrder === 'desc') {
        results.sort((a, b) => {
          const dateA = new Date(a.publication_date)
          const dateB = new Date(b.publication_date)
          return dateB - dateA // 降序排序
        })
      } else {
        console.log('default order:', this.papers)
        results = this.papers
      }
      results = results.filter(paper => {
        const year = new Date(paper.publication_date).getFullYear()
        console.log(year)
        return year >= this.filterYear
      })
      if (this.filterSubclass.length > 0) {
        results = results.filter(paper => {
          return paper.sub_classes.includes(this.filterSubclass)
        })
      }
      this.filteredPapers = results
      console.log('filter papers: ', this.filteredPapers)
    },
    async startSearch () {
      this.loadingHint = ''
      this.loadingHints = []
      this.loading = true
      this.defaultSearchContent = this.$route.query.search_content || this.defaultSearchContent
      try {
        const type = this.isDialogSearch ? 'dialogue' : 'string'
        const res = await request.post('/v2/search/vectorQuery', {
          search_content: this.defaultSearchContent,
          search_type: type
        })
        this.searchRecordID = res.data.data.search_record_id
        console.log('获取到的 searchRecordID:', this.searchRecordID)
        this.pollStatus()
      } catch (error) {
        this.loading = false
        this.$message.error('搜索接口调用失败')
      }
    },
    async pollStatus () {
      try {
        const statusRes = await request.get(
          `/v2/search/status?search_record_id=${this.searchRecordID}`
        )
        const data = statusRes.data.data
        if (data.type === 'hint') {
          const content = data.content
          const lastHint = this.loadingHints.length > 0 ? this.loadingHints[this.loadingHints.length - 1] : null
          if (!lastHint || lastHint.text !== content) {
            // 如果当前content和最后一条不一样，说明最后一条完成了
            if (lastHint) {
              lastHint.done = true
            }
            // 添加新条目，done为false，表示正在进行中
            this.loadingHints.push({ text: content, done: false })
          } else {
            // 如果和最后一条一样，说明还是同一个提示，保持done为false
            // 可以不做操作，也可以确认lastHint.done = false
            lastHint.done = false
          }
          this.loadingHint = content
          setTimeout(() => this.pollStatus(), 500)
        } else if (data.type === 'success') {
          // 搜索完成，把所有 loadingHints 标记 done = true
          this.loadingHints = this.loadingHints.map(hint => ({
            ...hint,
            done: true
          }))
          await this.fetchResult()
          this.$message.success('搜索完成')
          this.loading = false
        } else {
          this.loading = false
          this.$message.error('搜索状态异常')
        }
      } catch (error) {
        this.loading = false
        console.error('轮询状态出错', error)
      }
    },
    async fetchResult () {
      try {
        const resultRes = await request.get(`/v2/search/result?search_record_id=${this.searchRecordID}`)
        this.papers = resultRes.data.data.paper_infos
        this.aiReply = [{ sender: 'ai', text: resultRes.data.data.ai_reply, loading: false, type: 'dialog' }]
        this.paperIds = this.papers.map(p => p.paper_id)
        this.applyFilter()
        this.initializeCheckboxes()
      } catch (error) {
        console.error('获取结果失败', error)
      } finally {
        this.loading = false
      }
    },
    async fetchPapersFromHistory () {
      console.log('search record ID: ', this.$route.query.searchRecordID)
      await request.get('/search/restoreSearchRecord?search_record_id=' + this.$route.query.searchRecordID)
        .then((response) => {
          this.papers = response.data.paper_infos
          console.log('历史记录的论文', this.papers)
          this.defaultSearchContent = response.data.conversation[0].content
          console.log('first message is ', this.defaultSearchContent)
          for (const message of response.data.conversation) {
            const sender = message.role === 'user' ? 'user' : 'ai'
            this.aiReply.push({ sender: sender, text: message.content, loading: false, type: 'dialog' })
          }
          // console.log('历史记录对话信息 ', this.aiReply)
          this.paperIds = this.papers.map(paper => paper.paper_id)
          this.restoreHistory = true
        })
        .catch((error) => {
          console.error('恢复历史记录失败: ', error)
        })
    },
    handleCheckboxChange (paperId) {
      const index = this.selectedPapers.indexOf(paperId)
      if (index > -1) {
        // 如果已存在，则移除
        this.selectedPapers.splice(index, 1)
      } else {
        // 如果不存在，则添加
        this.selectedPapers.push(paperId)
      }
    },
    resetCheckboxes () {
      Object.keys(this.checkedPapers).forEach(key => {
        this.checkedPapers[key] = false
      })
    },
    initializeCheckboxes () {
      this.papers.forEach(paper => {
        this.$set(this.checkedPapers, paper.paper_id, false)
      })
    },
    generateSummaryReport () {
      const selectedPaperIds = Object.keys(this.checkedPapers).filter(key => this.checkedPapers[key])
      console.log('选中的论文ID:', selectedPaperIds)
      EventBus.$emit('generate-review', selectedPaperIds)
      // if (this.selectedPapers.length === 0) {
      //   this.$message({
      //     message: '请选择论文',
      //     type: 'warning'
      //   })
      //   return
      // }
      // console.log('选中的论文:', this.selectedPapers)
      // request.post('/summary/generateSummaryReport', { 'paper_id_list': this.selectedPapers }, { timeout: 300000 })
      //   .then((response) => {
      //     if (response.status === 200) {
      //       this.$message({
      //         message: '正在生成综述报告',
      //         type: 'success'
      //       })
      //       this.getSummaryReportStatus(response.data.report_id)
      //     }
      //   })
      //   .catch((error) => {
      //     console.error('综述报告生成失败:', error)
      //     this.$message({
      //       message: '综述报告生成失败',
      //       type: 'error'
      //     })
      //   })
      // this.selectedPapers = []
      // this.resetCheckboxes()
    },
    getSummaryReportStatus (reportID) {
      console.log('报告ID是', reportID)
      let intervalID = setInterval(() => {
        request.get('/summary/getSummaryStatus?report_id=' + reportID)
          .then(response => {
            if (response.data.status === '生成成功') {
              this.$message({
                message: '综述报告已生成，请在个人中心查看',
                type: 'success'
              })
              clearInterval(intervalID) // 停止轮询
            }
          })
          .catch(error => {
            console.error('查询状态失败:', error)
            clearInterval(this.intervalID) // 错误时停止轮询
          })
      }, 1000) // 每秒查询一次
    },
    downloadPapers () {
      if (this.selectedPapers.length === 0) {
        this.$message({
          message: '请选择论文',
          type: 'warning'
        })
      }
      request.post('/batchDownload', { 'paper_id_list': this.selectedPapers })
        .then((response) => {
          this.$message({
            message: '开始下载！',
            type: 'success'
          })
          const zipUrl = this.$BASE_URL + response.data.zip_url
          const link = document.createElement('a')
          link.href = zipUrl
          link.download = 'papers.zip'
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)
          this.selectedPapers = []
        })
        .catch((error) => {
          console.error('Error:', error)
        })
      this.selectedPapers = []
      this.resetCheckboxes()
    },
    searchPaperByAssistant (papers) {
      console.log('循征之后的论文', papers)
      this.papers = papers
      this.applyFilter()
      const paperIDs = papers.map(paper => paper.paper_id)
      request.post('/search/changeRecordPapers', { search_record_id: this.searchRecordID, paper_id_list: paperIDs })
        .then((response) => {
          console.log(response.status)
          if (response.status === 200) {
            console.log('论文循征成功, ', response.data.msg)
          }
        })
        .catch((error) => {
          console.error('论文循征失败, ', error)
        })
    }
  },
  async mounted () {
    if (this.$route.query.searchRecordID) {
      this.searchRecordID = this.$route.query.searchRecordID
      await this.fetchPapersFromHistory()
      this.applyFilter()
      this.initializeCheckboxes()
    } else {
      this.isDialogSearch = this.$route.query.searchType === 'dialogue'
      await this.startSearch()
    }
  }
}
</script>

<style scoped>
.filter-cond {
  display: flex;
  justify-content: flex-start;
}

.normal-button {
  color: black;
  font-weight: normal !important;
}

.clicked-button {
  color: #409EFE;
  font-weight: normal !important;
  font-size: 16px;
}

.checkbox {
  margin-left: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.papers-container {
  height: 83vh;
  overflow-y: auto;
}

/* 对话式检索部分 */
.el-header {
  text-align: center;
  padding: 20px;
}

.chat-content {
  background: rgb(233, 242, 251);
}

.el-footer {
  background: rgb(233, 242, 251);
  display: flex;
  align-items: center;
  height: 100%;
  margin: 0;
}

.my-message {
  background-color: #acd1f7;
  color: white;
  text-align: right;
}

.other-message {
  background-color: white;
  color: black;
  text-align: left;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
