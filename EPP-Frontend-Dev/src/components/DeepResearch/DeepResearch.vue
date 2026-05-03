<template>
  <div class="deep-research-container">
    <!-- 步骤 1: 研究需求输入 -->
    <div v-if="step === 1" class="input-container">
      <h3 class="section-title">Deep Research深度研究</h3>
      <p class="description">
        本功能针对复杂科研课题提供超越普通对话问答的深度分析能力，通过"多轮规划-检索-阅读-反思"的深度逻辑闭环，
        模拟AI科学家的研究路径，深挖文献之间的底层关联，形成具备严密论证与详尽溯源的结构化长篇调研报告。
      </p>

      <el-form label-position="top" class="requirement-form">
        <el-form-item label="研究需求">
          <el-input
            type="textarea"
            :rows="5"
            placeholder="请输入您的深度研究需求（例：基于当前文献，分析XX技术的研究现状、存在的争议及未来发展趋势，要求结合文献中的实验数据进行论证）"
            v-model="researchRequirement"
          ></el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="startResearch" :loading="loading" :disabled="!researchRequirement.trim()">
            开始深度研究
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 步骤 2: 研究处理进度 -->
    <div v-else-if="step === 2" class="progress-container">
      <h3 class="section-title">深度研究正在进行中</h3>
      <el-steps :active="activeStep" finish-status="success" class="research-steps">
        <el-step title="任务拆解" description="将研究需求拆解为多个子任务"></el-step>
        <el-step title="文献检索" description="检索相关文献片段"></el-step>
        <el-step title="内容分析" description="阅读分析文献核心内容"></el-step>
        <el-step title="关联梳理" description="梳理文献间底层关联"></el-step>
        <el-step title="论证推导" description="进行严密的论证推导"></el-step>
        <el-step title="报告生成" description="生成深度研究报告"></el-step>
      </el-steps>

      <div class="progress-info">
        <el-progress :percentage="progressPercentage" :stroke-width="18"></el-progress>
        <p class="progress-text">{{ progressText }}</p>
      </div>
    </div>

    <!-- 步骤 3: 研究结果展示 -->
    <div v-else-if="step === 3" class="result-container">
      <div class="result-header">
        <h3 class="section-title">深度研究报告</h3>
        <div class="action-buttons">
          <el-button type="primary" size="small" @click="exportPDF">
            <i class="fas fa-file-pdf"></i> 导出PDF
          </el-button>
          <el-button type="success" size="small" @click="exportMarkdown">
            <i class="fas fa-file-alt"></i> 导出Markdown
          </el-button>
        </div>
      </div>

      <div class="report-content">
        <div class="report-panel">
          <div v-html="renderedReport" class="markdown-body"></div>
        </div>

        <div class="interaction-panel">
          <div class="follow-up-section">
            <h4>继续追问</h4>
            <el-input
              type="textarea"
              :rows="3"
              placeholder="请输入您的追问内容..."
              v-model="followUpQuestion"
            ></el-input>
            <el-button
              type="primary"
              @click="submitFollowUpQuestion"
              :loading="followUpLoading"
              :disabled="!followUpQuestion.trim()"
              style="margin-top: 10px;"
            >
              提交问题
            </el-button>
          </div>

          <div class="recommended-questions">
            <h4>推荐问题</h4>
            <p v-if="recommendedQuestions.length === 0 && !loadingRecommendedQuestions" class="no-questions">
              正在准备推荐问题...
            </p>
            <el-tag
              v-for="(question, index) in recommendedQuestions"
              :key="index"
              @click="selectRecommendedQuestion(question)"
              class="question-tag"
              effect="plain"
            >
              {{ question }}
            </el-tag>
            <div v-if="loadingRecommendedQuestions" class="loading-questions">
              <i class="el-icon-loading"></i> 加载中...
            </div>
          </div>

          <div class="section-detail">
            <h4>重新生成局部内容</h4>
            <el-select
              v-model="selectedSection"
              placeholder="选择需要详细展开的部分"
              style="width: 100%; margin-bottom: 10px;"
            >
              <el-option
                v-for="section in extractedSections"
                :key="section"
                :label="section"
                :value="section"
              ></el-option>
            </el-select>
            <el-button
              type="primary"
              @click="generateDetailedSection"
              :loading="sectionDetailLoading"
              :disabled="!selectedSection"
            >
              生成详细内容
            </el-button>
          </div>
        </div>
      </div>

      <div v-if="followUpAnswer" class="follow-up-answer">
        <h4>回答</h4>
        <div v-html="renderedFollowUpAnswer" class="markdown-body"></div>
      </div>

      <div v-if="detailedSectionContent" class="detailed-section">
        <h4>《{{ selectedSection }}》的详细内容</h4>
        <div v-html="renderedDetailedSection" class="markdown-body"></div>
      </div>
    </div>

    <!-- 步骤 4: 错误状态 -->
    <div v-else-if="step === 4" class="error-container">
      <h3 class="section-title">研究过程中出现错误</h3>
      <el-alert
        title="深度研究失败"
        type="error"
        :description="errorMessage"
        show-icon
      ></el-alert>
      <div class="error-actions">
        <el-button type="primary" @click="resetResearch">重新开始</el-button>
      </div>
    </div>
  </div>
</template>

<script>
import {
  startDeepResearch,
  getDeepResearchStatus,
  continueDeepResearch,
  generateLocalSection,
  getRecommendedQuestions
} from '@/request/deepResearchRequest'
import markdownIt from 'markdown-it'
import html2pdf from 'html2pdf.js'
import FileSaver from 'file-saver'
import '@/assets/markdown.css'

export default {
  name: 'DeepResearch',
  props: {
    summaryReportId: {
      type: String,
      required: true
    }
  },
  data () {
    return {
      step: 1, // 1: 输入, 2: 进度, 3: 结果, 4: 错误
      researchRequirement: '',
      loading: false,
      recordId: null,
      statusPollingInterval: null,
      activeStep: 0, // 进度步骤
      progressPercentage: 0,
      progressText: '正在准备研究...',
      reportContent: '',
      followUpQuestion: '',
      followUpAnswer: '',
      followUpLoading: false,
      recommendedQuestions: [],
      loadingRecommendedQuestions: false,
      selectedSection: '',
      extractedSections: [],
      detailedSectionContent: '',
      sectionDetailLoading: false,
      errorMessage: '',
      md: null
    }
  },
  created () {
    this.md = markdownIt({
      html: true,
      linkify: true,
      typographer: true,
      highlight: function (str, lang) {
        if (lang && window.hljs && window.hljs.getLanguage(lang)) {
          try {
            return '<pre class="hljs"><code>' + window.hljs.highlight(str, { language: lang }).value + '</code></pre>'
          } catch (__) {}
        }
        return '<pre class="hljs"><code>' + this.md.utils.escapeHtml(str) + '</code></pre>'
      }
    })
  },
  computed: {
    renderedReport () {
      return this.reportContent ? this.md.render(this.reportContent) : ''
    },
    renderedFollowUpAnswer () {
      return this.followUpAnswer ? this.md.render(this.followUpAnswer) : ''
    },
    renderedDetailedSection () {
      return this.detailedSectionContent ? this.md.render(this.detailedSectionContent) : ''
    }
  },
  methods: {
    async startResearch () {
      if (!this.researchRequirement.trim()) {
        this.$message.warning('请输入研究需求')
        return
      }

      this.loading = true
      try {
        const response = await startDeepResearch({
          summary_report_id: this.summaryReportId,
          research_requirement: this.researchRequirement
        })

        this.recordId = response.data.record_id
        this.step = 2 // 进入进度页面
        this.startStatusPolling() // 开始轮询状态
      } catch (error) {
        console.error('开始深度研究失败:', error)
        this.errorMessage = (error.response && error.response.data && error.response.data.msg) || '开始研究失败，请稍后重试'
        this.step = 4 // 错误状态
      } finally {
        this.loading = false
      }
    },

    startStatusPolling () {
      // 每3秒轮询一次状态
      this.statusPollingInterval = setInterval(async () => {
        try {
          const response = await getDeepResearchStatus({ record_id: this.recordId })
          const { status, progress, reportContent, error } = response.data

          // 更新进度信息
          this.updateProgress(progress)

          // 处理不同状态
          if (status === 2) { // COMPLETED
            clearInterval(this.statusPollingInterval)
            this.reportContent = reportContent
            this.extractSections() // 提取报告中的章节
            this.step = 3 // 进入结果页面
            this.loadRecommendedQuestions() // 加载推荐问题
          } else if (status === 3) { // FAILED
            clearInterval(this.statusPollingInterval)
            this.errorMessage = error || '研究过程中出现错误'
            this.step = 4 // 错误状态
          }
        } catch (error) {
          console.error('获取研究状态失败:', error)
        }
      }, 3000)
    },

    updateProgress (progress) {
      // 根据进度文本更新步骤和百分比
      if (progress.includes('任务拆解')) {
        this.activeStep = 0
        this.progressPercentage = 15
      } else if (progress.includes('检索相关文献片段')) {
        this.activeStep = 1
        this.progressPercentage = 30
      } else if (progress.includes('阅读分析文献核心内容')) {
        this.activeStep = 2
        this.progressPercentage = 45
      } else if (progress.includes('梳理文献间底层关联')) {
        this.activeStep = 3
        this.progressPercentage = 60
      } else if (progress.includes('论证推导')) {
        this.activeStep = 4
        this.progressPercentage = 75
      } else if (progress.includes('生成深度研究报告')) {
        this.activeStep = 5
        this.progressPercentage = 90
      }

      this.progressText = progress
    },

    extractSections () {
      // 提取报告中的章节标题（## 或 ### 开头的行）
      if (!this.reportContent) return

      const lines = this.reportContent.split('\n')
      const sections = []

      lines.forEach(line => {
        if (line.startsWith('## ') || line.startsWith('### ')) {
          const section = line.replace(/^#+\s+/, '').trim()
          if (section && !sections.includes(section)) {
            sections.push(section)
          }
        }
      })

      this.extractedSections = sections
    },

    async submitFollowUpQuestion () {
      if (!this.followUpQuestion.trim()) {
        this.$message.warning('请输入问题内容')
        return
      }

      this.followUpLoading = true
      try {
        const response = await continueDeepResearch({
          record_id: this.recordId,
          question: this.followUpQuestion
        })

        this.followUpAnswer = response.data.answer
        this.followUpQuestion = '' // 清空输入框
      } catch (error) {
        console.error('追问失败:', error)
        this.$message.error('提交问题失败，请稍后重试')
      } finally {
        this.followUpLoading = false
      }
    },

    async loadRecommendedQuestions () {
      this.loadingRecommendedQuestions = true
      try {
        const response = await getRecommendedQuestions({ record_id: this.recordId })
        this.recommendedQuestions = response.data.questions || []
      } catch (error) {
        console.error('获取推荐问题失败:', error)
        this.$message.error('加载推荐问题失败')
      } finally {
        this.loadingRecommendedQuestions = false
      }
    },

    selectRecommendedQuestion (question) {
      this.followUpQuestion = question
    },

    async generateDetailedSection () {
      if (!this.selectedSection) {
        this.$message.warning('请选择需要详细展开的部分')
        return
      }

      this.sectionDetailLoading = true
      try {
        const response = await generateLocalSection({
          record_id: this.recordId,
          section: this.selectedSection
        })

        this.detailedSectionContent = response.data.detailed_content
      } catch (error) {
        console.error('生成详细内容失败:', error)
        this.$message.error('生成详细内容失败，请稍后重试')
      } finally {
        this.sectionDetailLoading = false
      }
    },

    exportPDF () {
      // 创建一个完整的HTML内容用于导出
      const content = document.createElement('div')
      content.innerHTML = this.renderedReport

      // 使用html2pdf导出
      const opt = {
        margin: 10,
        filename: `深度研究报告_${new Date().toLocaleDateString()}.pdf`,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2 },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
      }

      html2pdf().from(content).set(opt).save()
    },

    exportMarkdown () {
      const blob = new Blob([this.reportContent], { type: 'text/markdown;charset=utf-8' })
      FileSaver.saveAs(blob, `深度研究报告_${new Date().toLocaleDateString()}.md`)
    },

    resetResearch () {
      // 重置所有状态，返回步骤1
      this.step = 1
      this.researchRequirement = ''
      this.loading = false
      this.recordId = null
      this.activeStep = 0
      this.progressPercentage = 0
      this.progressText = '正在准备研究...'
      this.reportContent = ''
      this.followUpQuestion = ''
      this.followUpAnswer = ''
      this.recommendedQuestions = []
      this.selectedSection = ''
      this.extractedSections = []
      this.detailedSectionContent = ''
      this.errorMessage = ''

      if (this.statusPollingInterval) {
        clearInterval(this.statusPollingInterval)
      }
    }
  },
  beforeDestroy () {
    // 清除轮询
    if (this.statusPollingInterval) {
      clearInterval(this.statusPollingInterval)
    }
  }
}
</script>

<style scoped>
.deep-research-container {
  height: 100%;
  overflow-y: auto;
  padding: 20px;
}

.section-title {
  font-size: 22px;
  margin-bottom: 20px;
  color: #303133;
  font-weight: 600;
}

.description {
  color: #606266;
  margin-bottom: 20px;
  line-height: 1.6;
}

.input-container {
  max-width: 800px;
  margin: 0 auto;
}

.requirement-form {
  background-color: #f9f9f9;
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}

.research-steps {
  margin-bottom: 30px;
}

.progress-container {
  max-width: 800px;
  margin: 0 auto;
  text-align: center;
}

.progress-info {
  margin-top: 40px;
}

.progress-text {
  margin-top: 15px;
  font-size: 16px;
  color: #409EFF;
}

.result-container {
  height: 100%;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.action-buttons {
  display: flex;
  gap: 10px;
}

.report-content {
  display: flex;
  height: calc(100% - 100px);
  gap: 20px;
  margin-bottom: 20px;
}

.report-panel {
  flex: 2;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 20px;
  overflow-y: auto;
  background-color: white;
  max-height: 600px;
}

.interaction-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.follow-up-section,
.recommended-questions,
.section-detail {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 15px;
  background-color: white;
}

.follow-up-section h4,
.recommended-questions h4,
.section-detail h4 {
  margin-top: 0;
  margin-bottom: 15px;
  font-size: 16px;
  color: #303133;
}

.question-tag {
  margin: 5px;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}

.follow-up-answer,
.detailed-section {
  margin-top: 20px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 20px;
  background-color: white;
}

.follow-up-answer h4,
.detailed-section h4 {
  margin-top: 0;
  margin-bottom: 15px;
  font-size: 16px;
  color: #303133;
}

.error-container {
  max-width: 600px;
  margin: 0 auto;
  text-align: center;
}

.error-actions {
  margin-top: 20px;
}

.loading-questions {
  text-align: center;
  color: #909399;
  padding: 10px 0;
}

.no-questions {
  text-align: center;
  color: #909399;
}

/* 覆盖markdown样式 */
/deep/ .markdown-body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  word-wrap: break-word;
}

/deep/ .markdown-body h1 {
  font-size: 1.8em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

/deep/ .markdown-body h2 {
  font-size: 1.5em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
}

/deep/ .markdown-body h3 {
  font-size: 1.25em;
}

/deep/ .markdown-body h4 {
  font-size: 1em;
}
</style>
