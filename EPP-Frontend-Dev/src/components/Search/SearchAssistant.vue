<template>
  <div>
    <el-container style="height: calc(100vh - 50px);">
        <el-header>
          <h3>
            <i class="fas fa-search" style="margin-right: 8px;"></i>
            调研助手
          </h3>
        </el-header>

        <el-main class="chat-content">
            <div v-for="(message, index) in chatMessages" :key="index">
                <div v-if="message.sender === 'ai'" class="message-bubble left">
                    <div v-if="message.loading" class="my-loader">
                      <i class="el-icon-loading spinner-icon"></i>
                      <span class="loader-text">{{ message.progress }}</span>
                    </div>
                    <div v-else>
                        <p style="white-space: pre-wrap;">{{ message.text }}</p>
                        <div v-if="message.type === 'query'" style="margin-top: 10px;">
                          <div v-for="(paper, index) of papers" :key="index">
                            <paper-card :paper="paper" />
                          </div>
                        </div>
                        <el-button v-show="message.type === 'query' && answerFinished && index === chatMessages.length - 1"
                        type="text" @click="searchPaperByAssistant">
                          <i class="fas fa-compass"></i>
                          论文循征
                        </el-button>
                    </div>
                    <div v-if="message.type==='review' && !message.loading" class="mt-2">
                      <el-button size="mini" @click="continueReview(message)" :disabled="message.finished" class="continue-button">
                        <i class="el-icon-arrow-right"></i> 继续生成
                      </el-button>
                      <el-button size="mini" @click="openRegenerateDialog(message)" :disabled="message.finished" class="regenerate-button">
                        <i class="el-icon-refresh"></i> 重新生成
                      </el-button>
                    </div>
                </div>
                <div v-else class="message-bubble right">
                    <p style="word-wrap: break-word;">{{ message.text }}</p>
                </div>
            </div>
        </el-main>

        <el-footer>
          <el-input v-model="chatInput" placeholder="输入你的消息..." @keyup.enter.native="chatToAI" clearable></el-input>
          <el-button type="primary" @click="chatToAI">发送</el-button>
        </el-footer>
    </el-container>
    <el-dialog
      title="请输入重新生成意见"
      :visible.sync="showRegenerateDialog"
      append-to-body
      width="30%"
      :modal-append-to-body="false"
      class="centered-dialog"
    >
      <el-input
        type="textarea"
        v-model="regenerateFeedback"
        placeholder="请填写您的意见…"
        rows="4"
      />
      <span slot="footer" class="dialog-footer">
        <el-button @click="showRegenerateDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmRegenerate"
          >确定</el-button
        >
      </span>
    </el-dialog>
  </div>
</template>

<script>
import request from '@/request/request'
import PaperCard from './PaperCard.vue'
import { EventBus } from '@/main.js'
export default {
  components: {
    'paper-card': PaperCard
  },
  props: {
    paperIds: {
      type: Array,
      default: null
    },
    searchRecordID: {
      type: String,
      default: ''
    },
    aiReply: {
      type: Array,
      default: null
    },
    restoreHistory: {
      type: Boolean,
      default: false
    }
  },
  data () {
    return {
      chatInput: '',
      buttonCnt: 0,
      chatMessages: [],
      answerFinished: false,
      papers: [],
      showRegenerateDialog: false, // 控制 Dialog 显示
      regenerateFeedback: '', // 存用户输入的反馈
      pendingRegenerateMsg: null, // 保存正在重生成的消息对象
      localPaperIds: this.paperIds ? [...this.paperIds] : [], // 使用局部变量存储 paperIds
      currentSelectedPaperIds: [], // 用于保存当前选中的论文 ID
      reportId: ''
    }
  },
  created () {
    EventBus.$on('generate-review', this.generateReview)
    if (this.restoreHistory) {
      this.restoreDialogSearch()
    } else {
      this.createDialogStudy()
    }
  },
  beforeDestroy () {
    // 记得销毁绑定，防止内存泄漏
    EventBus.$off('generate-review', this.generateReview)
  },
  methods: {
    openRegenerateDialog (message) {
      this.pendingRegenerateMsg = message
      this.regenerateFeedback = '' // 清空上一次的输入
      this.showRegenerateDialog = true // 打开弹窗
    },

    // 弹窗里点击「确定」
    async confirmRegenerate () {
      this.showRegenerateDialog = false
      // 调用下面的真正重生成逻辑，并把 feedback 作为全局状态传入
      this.regenerateReview(this.pendingRegenerateMsg)
    },

    async fetchProgress (msg) {
      const { content, type } = await new Promise((resolve, reject) => {
        const requestStatus = () => {
          request
            .get(`/v2/summary/status?report_id=${this.reportId}`)
            .then(res => {
              const resData = res.data.data
              const content = resData.content
              const type = resData.type

              if (type === 'success') {
                msg.finished = true
                msg.loading = false
                msg.text = content
                resolve({ content, type })
              } else if (type === 'response') {
                msg.loading = false
                msg.finished = false
                msg.text = content
                resolve({ content, type })
              } else {
                msg.progress = content
                setTimeout(() => {
                  requestStatus()
                }, 500)
              }
            })
            .catch(err => {
              console.error('获取进度失败', err)
              reject(err)
            })
        }
        requestStatus()
      })
      // 等待轮询完成之后再打字 + 弹窗提示
      await this.typewriterEffect(msg, content)

      if (type === 'success') {
        this.$message({
          message: '综述报告已完成',
          type: 'success',
          duration: 3000
        })
      }
    },

    async generateReview (selectedPaperIds) {
      // push 一个占位的 loading 消息
      const msg = { sender: 'ai', text: 'AI正在生成综述报告…', loading: true, type: 'review', finished: false, progress: 'AI专家正在调用知识库1' }
      this.chatMessages.push(msg)
      this.currentSelectedPaperIds = selectedPaperIds // 保存当前选中的论文 ID
      try {
        const res = await request.post('/summary/generateSummaryReport', {
          paper_id_list: selectedPaperIds
        })
        this.reportId = res.data.report_id
        this.fetchProgress(msg)
      } catch (e) {
        msg.text = '生成失败，请重试'
        console.error(e)
      }
    },

    // ② “继续生成”：告诉后端从上次结束处再继续
    async continueReview () {
      // 1. 找到最后一条 AI 的 review 消息
      const lastMsg = this.chatMessages[this.chatMessages.length - 1]
      lastMsg.finished = false
      lastMsg.loading = true
      try {
        await request.post(`/v2/summary/response?report_id=${this.reportId}`, {
          type: 'continue',
          content: ''
        })
        lastMsg.text = ''
        lastMsg.progress = ''
        this.fetchProgress(lastMsg)
      } catch (err) {
        console.error('继续生成失败', err)
        lastMsg.text += '\n⚠ 继续生成失败，请重试'
      }
    },
    // ③ “重新生成”：丢给后端整段重来
    async regenerateReview (msg) {
      msg.progress = ''
      msg.text = ''
      msg.loading = true; msg.finished = false
      try {
        await request.post(`/v2/summary/response?report_id=${this.reportId}`, {
          type: 'regen',
          content: this.regenerateFeedback
        })
        this.fetchProgress(msg)
      } catch (e) {
        console.error(e)
      }
    },

    // 公共：打字机效果
    async typewriterEffect (msg, fullText, append = false) {
      if (!append) msg.text = ''
      for (let i = 0; i < fullText.length; i++) {
        msg.text += fullText.charAt(i)
        await this.delay(30)
      }
    },
    createDialogStudy () {
      this.localPaperIds = this.localPaperIds.slice(0, 5)
      for (const message of this.aiReply) {
        this.chatMessages.push(message)
      }
    },
    async queryDialogStatus (msg) {
      await new Promise((resolve, reject) => {
        const requestStatus = () => {
          request.get(`/v2/search/dialog/status?search_record_id=${this.searchRecordID}`).then((response) => {
            const content = response.data.data.content
            const type = response.data.data.type
            if (type === 'hint') {
              // Fixme: I want to display both the loading icon and the text
              msg.loading = false
              msg.text = content
              setTimeout(() => {
                requestStatus()
              }, 500)
            } else if (type === 'success') {
              msg.finished = true
              msg.loading = false
              msg.text = content
              resolve()
            } else {
              console.log('Bad response type:', type)
              reject(Error('Bad response type'))
            }
          }).catch(err => {
            console.error('获取进度失败', err)
            reject(err)
          })
        }
        requestStatus()
      })
      let answer = ''
      await request.get(`v2/search/dialog/result?search_record_id=${this.searchRecordID}`).then((response) => {
        msg.type = response.data.dialog_type
        console.log(msg.type)
        if (msg.type === 'query') {
          this.papers = response.data.papers
        }
        msg.loading = false
        msg.text = ''

        answer = response.data.content
      }).catch((error) => {
        console.log(error)
        answer = '遭遇了错误！'
      })

      this.answerFinished = false
      let cur = 0
      while (cur < answer.length) {
        msg.text += answer.charAt(cur)
        cur++
        await this.delay(50)
      }
      this.answerFinished = true
    },
    async chatToAI () {
      const chatMessage = this.chatInput.trim()
      if (!chatMessage) {
        this.$message({
          message: '请输入你的问题',
          type: 'warning'
        })
        return
      }
      this.chatMessages.push({sender: 'user', text: chatMessage, loading: false, type: 'dialog'})
      let loadingMessage = { sender: 'ai', text: 'AI正在思考...', loading: true, type: 'dialog' }
      this.chatMessages.push(loadingMessage)
      this.chatInput = ''
      try {
        console.log('search-record-id: ', this.searchRecordID)
        await request.post('/v2/search/dialogQuery', { 'message': chatMessage, 'paper_ids': this.localPaperIds, 'search_record_id': this.searchRecordID })
          .then((response) => {
            console.log(response.data)
          })
        await this.queryDialogStatus(loadingMessage)
      } catch (error) {
        const answer = '抱歉, 无法从AI获取回应。'
        console.error('Error:', error)
        loadingMessage.text = ''
        loadingMessage.loading = false
        this.answerFinished = false
        let cur = 0
        while (cur < answer.length) {
          loadingMessage.text += answer.charAt(cur)
          cur++
          await this.delay(50)
        }
        this.answerFinished = true
      }
    },
    createFakeData (loadingMessage) {
      loadingMessage.text = '以下为您找到几篇论文'
      loadingMessage.loading = false
      loadingMessage.type = 'query'
      this.answerFinished = true
      this.papers = [{
        'abstract': '  This document facilitates understanding of core concepts about uniform\nB-spline and its matrix representation.\n',
        'authors': 'Yi Zhou,',
        'citation_count': 39,
        'collect_count': 0,
        'comment_count': 0,
        'download_count': 635,
        'journal': null,
        'like_count': 0,
        'original_url': 'http://arxiv.org/abs/2309.15477v1',
        'paper_id': '04534e01-fea6-4676-adb0-3c9af9716dd2',
        'publication_date': 'Wed, 27 Sep 2023 00:00:00 GMT',
        'read_count': 516,
        'score': 0,
        'score_count': 0,
        'title': 'A Tutorial on Uniform B-Spline'
      }]
    },
    delay (ms) {
      return new Promise(resolve => setTimeout(resolve, ms))
    },
    // async regenerateAnswer () {
    //   console.log('regenerating...')
    //   const lastMessage = this.chatMessages[this.chatMessages.length - 1]
    //   lastMessage.text = 'AI正在思考...'
    //   lastMessage.loading = true
    //   this.answerFinished = false
    //   let answer = ''
    //   await request.post('/search/dialogQuery', { 'message': lastMessage, 'paper_ids': this.localPaperIds, 'search_record_id': this.searchRecordID })
    //     .then((response) => {
    //       answer = response.data.ai_reply
    //       lastMessage.text = ''
    //       lastMessage.loading = false
    //     })
    //     .catch((error) => {
    //       console.error('重新生成对话式检索结果失败: ', error)
    //       lastMessage.text = ''
    //       answer = '抱歉, 无法从AI获取回应。'
    //       lastMessage.loading = false
    //     })
    //   let cur = 0
    //   while (cur < answer.length) {
    //     lastMessage.text += answer.charAt(cur)
    //     cur++
    //     await this.delay(100)
    //   }
    //   this.answerFinished = true
    // },
    // createKB () {
    //   console.log('创建知识库的论文ids', this.paperIds)
    //   let firstMessage = this.chatMessages[this.chatMessages.length - 1]
    //   firstMessage.loading = true
    //   request.post('/search/rebuildKB', {'paper_id_list': this.paperIds})
    //     .then((response) => {
    //       this.kbId = response.data.kb_id
    //       firstMessage.loading = false
    //       this.$message({
    //         message: '创建知识库成功',
    //         type: 'success'
    //       })
    //     })
    //     .catch((error) => {
    //       console.error('创建知识库失败', error)
    //       firstMessage.loading = false
    //       this.$message({
    //         message: '创建知识库失败',
    //         type: 'error'
    //       })
    //     })
    // },
    searchPaperByAssistant () {
      this.$emit('find-paper', this.papers)
    },
    restoreDialogSearch () {
      for (const message of this.aiReply) {
        this.chatMessages.push(message)
      }
    }
  }

}
</script>

<style scoped>
.el-header {
  text-align: center;
  padding: 20px;
}

.chat-content {
  display: flex;
  flex-direction: column;
  align-items: stretch; /* 确保元素可以根据需要对齐到左边或右边 */
  background: rgb(233, 242, 251);
  width: 100%; /* 可以调整宽度以适应不同屏幕大小 */
}
.el-footer {
  background: rgb(233, 242, 251);
  display: flex;
  align-items: center;
  height: 100%;
  margin: 0;
}

.centered-dialog >>> .el-dialog__header {
  text-align: center;
}
.my-loader {
  position: relative;
  padding: 10px 20px;
}
.spinner-icon {
  animation: loadingRotate 1s linear infinite;
  margin-right: 8px;
  font-size: 18px;
  vertical-align: middle;
}
.loader-text {
  vertical-align: middle;
  font-size: 14px;
}
/* loading 动画（Element UI 默认） */
@keyframes loadingRotate {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
.message-bubble {
  position: relative;
  display: inline-block;
  padding: 10px 20px;
  border: 1px solid #ccc;
  margin: 5px 0;
  overflow-y: auto;
  text-align: left;
}

.message-bubble p {
    margin: 0;
}

.right {
  background-color: #007bff;
  color: white;
  border-color: #007bff;
  float: right;
  border-radius: 15px 0 15px 15px;
  clear: both;
  word-break: break-all;
}

.left {
  background-color: white;
  color: black;
  border-color: #ccc;
  float: left;
  clear: both;
  border-radius: 0 15px 15px 15px;
}

/* 继续生成按钮样式 */
.continue-button {
  background-color: #67c23a; /* 绿色 */
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  transition: background-color 0.3s ease;
}

.continue-button:hover {
  background-color: #85ce61;
}

.continue-button:disabled {
  background-color: #b3e19d;
  cursor: not-allowed;
}

/* 重新生成按钮样式 */
.regenerate-button {
  background-color: #409eff; /* 蓝色 */
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  transition: background-color 0.3s ease;
}

.regenerate-button:hover {
  background-color: #66b1ff;
}

.regenerate-button:disabled {
  background-color: #a0cfff;
  cursor: not-allowed;
}
</style>
