<template>
    <div>
        <el-row type="flex" justify="center">
            <el-col :span="20">
                <!-- 论文部分 -->
                <el-container class="box" style="margin-top: 60px;">
                    <el-row class="header">
                        {{ paper.title }}
                    </el-row>
                    <el-row>
                        <p><strong>作者:</strong> {{ paper.authors }}</p>
                    </el-row>
                    <el-row style="margin-top: 10px;">
                        <el-col :span="24">
                            <div style="width: 90%; margin: auto; text-align: left;">
                                <p><strong>摘要:</strong> {{ paper.abstract }}</p>
                            </div>
                        </el-col>
                    </el-row>
                    <el-row class="buttons">
                        <el-button type="text" @click="likePaper">
                            <i :class="liked ? 'fas' : 'far'" class="fa-thumbs-up"></i>
                            {{ paper.like_count }}
                        </el-button>
                        <el-button type="text" @click="collectPaper">
                            <i :class="collected ? 'el-icon-star-on' : 'el-icon-star-off'"></i>
                            {{ paper.collect_count }}
                        </el-button>
                        <el-button type="text" icon="el-icon-chat-dot-round" @click="showCommentModal = true">{{ comments.length }}</el-button>
                        <el-button type="text" icon="el-icon-download" @click="downloadPaper">下载</el-button>
                        <router-link :to="{name: 'paper-reader', params: { paper_id: paper.paper_id }}" tag="button" class="el-button el-button--text">
                            <i class="el-icon-view"></i> 在线研读
                        </router-link>

                        <!-- 文献翻译按钮 -->
                        <el-button type="text" @click="openTranslateModal">
                          <i class="fas fa-language" style="margin-right: 4px;"></i> 文献翻译
                        </el-button>

                        <!-- 翻译对话框 -->
                        <el-dialog title="文献翻译" :visible.sync="showTranslateModal" width="550px">
                          <el-form v-if="!loadingTranslation" label-width="100px" class="translate-form">
                            <!-- 术语表选择 -->
                            <el-form-item label="术语表">
                              <div class="glossary-select-wrapper">
                                <el-select
                                  v-model="selectedGlossaryId"
                                  placeholder="请选择术语表..."
                                  clearable
                                  class="glossary-select"
                                >
                                  <el-option
                                    v-for="item in glossaryList"
                                    :key="item.id"
                                    :label="item.name"
                                    :value="item.id"
                                  />
                                </el-select>
                                <el-button
                                  type="text"
                                  v-if="selectedGlossaryId"
                                  class="view-detail-btn"
                                  @click="openGlossaryDetail"
                                >
                                  查看详情
                                </el-button>
                              </div>
                            </el-form-item>

                            <!-- 启用重用 -->
                            <el-form-item label="启用重用" class="reuse-trans-form">
                              <el-tooltip
                                content="如果该文献已用相同术语表翻译过，将直接返回结果"
                                placement="right"
                              >
                                <el-switch v-model="reuseTranslation" />
                              </el-tooltip>
                            </el-form-item>
                          </el-form>

                          <div v-if="loadingTranslation" style="text-align: center; padding: 30px;">
                            <el-spinner type="fading-circle"></el-spinner>
                            <p style="margin-top: 10px;">正在翻译，请稍候...</p>
                          </div>

                          <div slot="footer" class="dialog-footer" v-if="!loadingTranslation">
                            <el-button @click="showTranslateModal = false">取 消</el-button>
                            <el-button type="primary" @click="translatePaper">开始翻译</el-button>
                          </div>

                          <!-- 翻译结果展示 -->
                          <div v-if="translationResult && !loadingTranslation" class="translation-result-container">
                            <el-alert
                              title="翻译完成！点击下方链接下载"
                              type="success"
                              show-icon
                            ></el-alert>

                            <div class="translation-buttons">
                              <el-link :href="translationResult.path" target="_blank" type="primary">
                                下载翻译文件
                              </el-link>
                              <el-tooltip content="重新生成翻译" placement="right">
                                <el-button type="text" @click="regenerateTranslation()">
                                  重新生成
                                </el-button>
                              </el-tooltip>
                            </div>
                          </div>

                        </el-dialog>

                        <!-- 术语表详情弹窗 -->
                        <el-dialog
                          title="术语表详情"
                          :visible.sync="glossaryDetailVisible"
                          width="600px"
                          class="glossary-detail-dialog">
                          <div v-if="glossaryDetail">
                            <el-divider content-position="center">
                              <span style="font-size: 18px; font-weight: bold;">{{ glossaryDetail.name }}</span>
                            </el-divider>
                            <el-table
                              :data="glossaryDetail.terms"
                              border
                              style="width: 100%; margin-top: 40px; max-height: 400px; overflow-y: auto;">
                              <el-table-column prop="en" label="英文术语" width="240" />
                              <el-table-column prop="zh" label="中文翻译" />
                            </el-table>
                          </div>
                          <span slot="footer" class="dialog-footer">
                            <el-button @click="glossaryDetailVisible = false">关闭</el-button>
                          </span>
                        </el-dialog>

                        <el-link type="primary" :href="paper.original_url" icon="el-icon-link"
                            style="margin-left: 10px;">原文链接</el-link>
                        <router-link :to="{name: 'paper-annotations', params: { paper_id: paper.paper_id }}" tag="button" class="el-button el-button--text" style="margin-left: 20px;">
                            <i class="el-icon-share"></i> 公开批注
                        </router-link>
                    </el-row>
                </el-container>

                <!-- 评分部分 -->
                <el-container class="box">
                    <el-row>
                        <el-col :span="8" style="justify-content: center; text-align: center">
                            <el-rate v-model="paper.score" disabled show-score text-color="#ff9900">
                            </el-rate>
                            <p>{{ paper.score_count }} 个评分</p>
                        </el-col>
                        <el-col :span="8">
                            <el-button type="text" icon="el-icon-edit-outline"
                                @click="showScoreModal = true">我要评分</el-button>
                        </el-col>
                        <el-dialog title="我要评分" :visible.sync="showScoreModal" width="50%" @close="showScoreModal = false">
                            <el-form>
                                <el-form-item>
                                    <el-rate v-model="newScore"></el-rate>
                                </el-form-item>
                            </el-form>
                            <span slot="footer">
                                <el-button @click="showScoreModal = false">取 消</el-button>
                                <el-button type="primary" @click="submitScore">评 分</el-button>
                            </span>
                        </el-dialog>
                    </el-row>
                </el-container>

                <!-- 评论区 -->
                <el-container class="box" style="margin-top: 20px">
                    <!-- 评论弹窗 -->
                    <el-dialog title="发表评论" :visible.sync="showCommentModal" width="50%" @close="closeCommentModal">
                        <el-form>
                            <el-form-item>
                                <el-input type="textarea" placeholder="添加评论..." v-model="newComment" autosize>
                                </el-input>
                            </el-form-item>
                        </el-form>
                        <span slot="footer">
                            <el-button @click="showCommentModal = false">取 消</el-button>
                            <el-button type="primary" @click="submitComment1(1)">发 送</el-button>
                        </span>
                    </el-dialog>
                    <el-divider>评论区</el-divider>
                    <div class="comments">
                        <div v-if="comments.length > 0">
                            <!-- 一级评论 -->
                            <div v-for="comment in comments" :key="comment.comment_id" class="comment-item">
                                <el-row>
                                    <el-col :span="2">
                                        <img :src="fullURL(comment.user_image)" alt="user avatar" class="avatar">
                                    </el-col>
                                    <el-col :span="22">
                                        <div class="comment-content">
                                            <div style="font-weight: bold;">{{ comment.username }}</div>
                                            <div class="text">{{ comment.text }}</div>
                                            <div class="my-footer">
                                                <span class="date">{{ comment.date }}</span>
                                                <span class="actions">
                                                    <el-button type="text" @click="likeComment(comment.comment_id, 1)">
                                                        <i :class="comment.user_liked ? 'fas' : 'far'" class="fa-thumbs-up"></i>
                                                        {{ comment.like_count }}
                                                    </el-button>
                                                    <el-button type="text" icon="el-icon-chat-dot-round"
                                                        @click="toggleReplyInput(comment.comment_id)">回复</el-button>
                                                    <el-button type="text" icon="el-icon-warning-outline"
                                                        @click="reportComment(comment.comment_id, 1)">举报</el-button>
                                                    <el-button type="text" :icon="showRepliesCommentId === comment.comment_id ? 'el-icon-arrow-up' : 'el-icon-arrow-down'" v-show="comment.second_len > 0"
                                                        @click="fetchComments2(comment.comment_id)">共 {{ comment.second_len }} 条回复</el-button>
                                                </span>
                                            </div>
                                        </div>
                                        <!-- 回复评论的框 -->
                                        <div style="display: flex; margin-bottom: 5px;">
                                            <el-input v-if="showReplyInput == comment.comment_id" type="textarea" v-model="newComment" placeholder="请输入回复内容..." rows="1"></el-input>
                                            <el-button v-if="showReplyInput == comment.comment_id" type="primary" size="small" @click="submitComment2(comment.comment_id)">发送</el-button>
                                        </div>
                                    </el-col>
                                </el-row>

                                <!-- 二级评论部分 -->
                                <div v-show="showRepliesCommentId === comment.comment_id">
                                    <div v-if="secondLevelComments.length > 0">
                                        <div v-for="comment2 in secondLevelComments" :key="comment2.comment_id"
                                            class="comment-item">
                                            <el-row>
                                                <el-col :span="2" :offset="2">
                                                    <img :src="fullURL(comment2.user_image)" alt="user avatar"
                                                        class="avatar">
                                                </el-col>
                                                <el-col :span="20">
                                                    <div class="comment-content">
                                                        <div style="font-weight: bold;">{{ comment2.username }}</div>
                                                        <div class="text">
                                                            <!-- 后续加上跳转到用户个人中心的功能 -->
                                                            <router-link v-if="comment2.to_username"
                                                                :to="{ name: '', params: { username: comment2.to_username } }">
                                                                @{{ comment2.to_username }}
                                                            </router-link>
                                                            {{ comment2.text }}
                                                        </div>
                                                        <div class="my-footer">
                                                            <span class="date">{{ comment2.date }}</span>
                                                            <span class="actions">
                                                                <el-button type="text" @click="likeComment(comment2.comment_id, 2)">
                                                                    <i :class="comment2.user_liked ? 'fas' : 'far'" class="fa-thumbs-up"></i>
                                                                    {{ comment2.like_count }}
                                                                </el-button>
                                                                <el-button type="text" icon="el-icon-chat-dot-round"
                                                                    @click="toggleReplyInput(comment2.comment_id)">回复</el-button>
                                                                <el-button type="text" icon="el-icon-warning-outline"
                                                                    @click="reportComment(comment2.comment_id, 2)">举报</el-button>
                                                            </span>
                                                        </div>
                                                    </div>
                                                    <!-- 回复评论的框 -->
                                                    <div style="display: flex; margin-bottom: 5px;">
                                                        <el-input v-if="showReplyInput == comment2.comment_id" type="textarea" v-model="newComment" placeholder="请输入回复内容..." rows="1"></el-input>
                                                        <el-button v-if="showReplyInput == comment2.comment_id" type="primary" size="small" @click="submitComment3(comment.comment_id, comment2.comment_id)">发送</el-button>
                                                    </div>
                                                </el-col>
                                            </el-row>
                                        </div>
                                    </div>
                                    <p v-else>暂无评论</p>
                                </div>
                            </div>
                        </div>
                        <p v-else>暂无评论</p>
                    </div>
                </el-container>
            </el-col>
        </el-row>
        <report-modal :showReportModal="showReportModal" :commentId="reportedCommentId"
        :commentLevel="reportedCommentLevel" @close-report-modal="showReportModal = false"></report-modal>
    </div>
</template>

<script>
import request from '@/request/request'
import ReportModal from './ReportModal.vue'
export default {
  props: {
    paper_id: {
      type: String,
      required: true
    }
  },
  components: {
    'report-modal': ReportModal
  },
  computed: {
  },
  data () {
    return {
      paper: {},
      liked: false,
      collected: false,
      scored: false,
      showTranslateModal: false, // translation
      glossaryList: [],
      selectedGlossaryId: null,
      glossaryDetailVisible: false,
      glossaryDetail: null,
      reuseTranslation: true, // 默认启用重用
      historyTranslationMessage: '', // 提示用户是否已有翻译
      translationResult: null, // translation
      loadingTranslation: false, // 控制翻译按钮的 loading 状态,
      pollingTimer: null, // 用于保存 setInterval 的引用
      newComment: '',
      comments: [],
      showCommentModal: false,
      newScore: 0,
      showScoreModal: false,
      showRepliesCommentId: null,
      showReplyInput: null, // 显示回复二级评论的输入框
      secondLevelComments: [],
      showReportModal: false,
      reportedCommentId: '',
      reportedCommentLevel: 0
    }
  },
  created () {
    this.paper_id = this.$route.params.paper_id
    this.fetchPaperInfo()
    this.fetchComments1()
    this.fetchUserPaperInfo()
  },
  methods: {
    fullURL (url) {
      return this.$BASE_URL + url
    },
    fetchUserPaperInfo () {
      request.get('/getUserPaperInfo?paper_id=' + this.paper_id)
        .then((response) => {
          this.liked = response.data.liked
          this.collected = response.data.collected
          this.scored = response.data.score !== 0
          this.newScore = response.data.score
        })
        .catch((error) => {
          console.error('Error', error)
        })
    },
    fetchPaperInfo () {
      console.log('传递过来的paper id:', this.paper_id)
      // 向后端传送id，返回论文结果
      //   console.log('url is...' + this.$BASE_API_URL + '/getPaperInfo?paper_id=' + this.paper_id)
      request.get('/getPaperInfo?paper_id=' + this.paper_id)
        .then((response) => {
          console.log('paper info is ...')
          this.paper = response.data
          console.log(this.paper)
        })
        .catch((error) => {
          console.error('Error:', error)
        })
    },
    fetchComments1 () {
      // 向后端传送id，返回论文结果
      request.get('/getComment1?paper_id=' + this.paper_id)
        .then((response) => {
          console.log('一级评论 ...')
          this.comments = response.data.comments
          console.log(this.comments)
        })
        .catch((error) => {
          console.error('Error:', error)
        })
    },
    likePaper () {
      request.post('/userLikePaper', { 'paper_id': this.paper_id })
        .then(() => {
          this.liked = !this.liked
          this.liked ? this.paper.like_count++ : this.paper.like_count--
        })
        .catch((error) => {
          console.error('点赞操作失败:', error)
          this.$message({
            message: '点赞操作失败',
            type: 'error'
          })
        })
    },
    collectPaper () {
      request.post('/collectPaper', { 'paper_id': this.paper_id })
        .then(() => {
          this.collected = !this.collected
          this.collected ? this.paper.collect_count++ : this.paper.collect_count--
        })
        .catch((error) => {
          console.error('收藏操作失败:', error)
          this.$message({
            message: '收藏操作失败',
            type: 'error'
          })
        })
    },
    downloadPaper () {
      // 实现下载功能
      request.post('/batchDownload', {'paper_id_list': [this.paper_id]})
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
    },
    likeComment (commentId, commentLevel) {
      request.post('/likeComment', { 'comment_level': commentLevel, 'comment_id': commentId })
        .then((response) => {
          let comment
          if (commentLevel === 1) {
            comment = this.comments.find(c => c.comment_id === commentId)
          } else if (commentLevel === 2) {
            comment = this.secondLevelComments.find(c => c.comment_id === commentId)
          }
          if (comment) {
            comment.user_liked = !comment.user_liked
            comment.user_liked ? comment.like_count++ : comment.like_count--
          }
        })
        .catch((error) => {
          console.error('点赞操作失败:', error)
          this.$message({
            message: '点赞操作失败',
            type: 'error'
          })
        })
    },
    reportComment (commentId, commentLevel) {
      this.reportedCommentId = commentId
      this.reportedCommentLevel = commentLevel
      this.showReportModal = true
    },
    closeCommentModal () {
      this.showCommentModal = false // 关闭对话框
      this.newComment = ''
    },
    submitComment1 () {
      console.log('评论级别', 1)
      console.log('提交的评论内容：', this.newComment)
      let isSuccessful = false
      request.post('/commentPaper', {'paper_id': this.paper_id, 'comment_level': 1, 'comment': this.newComment})
        .then((response) => {
          isSuccessful = true
        })
        .catch((error) => {
          console.error('Error : ', error)
          isSuccessful = false
        })
        .finally(() => {
          this.newComment = ''
          this.showCommentModal = false
          window.location.reload()
          if (isSuccessful) {
            this.$message({
              message: '评论成功',
              type: 'success'
            })
          } else {
            this.$message({
              message: '评论失败',
              type: 'error'
            })
          }
        })
    },
    openTranslateModal () {
      this.showTranslateModal = true
      this.fetchGlossaryList()
      this.translationResult = null
      this.historyTranslationMessage = '' // 清除提示信息
    },

    fetchGlossaryList () {
      request.get('/translate/glossaries', {
        paper_id: this.paper_id
      }).then((response) => {
        this.glossaryList = response.data.data || []
        this.selectedGlossaryId = null
      }).catch((error) => {
        console.error('获取术语表失败:', error)
        this.$message({
          message: '获取术语表失败',
          type: 'error'
        })
      })
    },

    openGlossaryDetail () {
      if (!this.selectedGlossaryId) return
      request.get(`/translate/glossary?glossary_id=${this.selectedGlossaryId}`)
        .then((res) => {
          const { name, data, error } = res.data
          if (error) {
            this.$message.error(error)
            return
          }
          this.glossaryDetail = {
            name,
            terms: data
          }
          this.glossaryDetailVisible = true
        })
        .catch((err) => {
          console.error('获取术语详情失败:', err)
          this.$message.error('获取术语详情失败')
        })
    },
    translatePaper () {
      this.loadingTranslation = true
      this.translationResult = null

      request.post(`/article/translate?id=${this.paper_id}`, {
        // file_type: 0,
        glossary_id: this.selectedGlossaryId,
        reuse: this.reuseTranslation
      }).then((response) => {
        const taskId = response.data.id
        this.pollTranslationStatus(taskId)
      }).catch((error) => {
        console.error('翻译启动失败:', error)
        this.$message({
          message: '翻译启动失败',
          type: 'error'
        })
        this.loadingTranslation = false
      })
    },
    pollTranslationStatus (taskId) {
      this.pollingTimer = setInterval(() => {
        request.get(`/translate/status?id=${taskId}`)
          .then((res) => {
            const status = res.data.status
            if (status === 'done') {
              clearInterval(this.pollingTimer)
              this.pollingTimer = null
              this.translationResult = {
                id: taskId,
                path: res.data.url
              }
              this.$message({ message: '翻译完成', type: 'success' })
              this.loadingTranslation = false
            } else if (status === 'fail') {
              clearInterval(this.pollingTimer)
              this.pollingTimer = null
              this.$message({ message: res.data.error || '翻译失败', type: 'error' })
              this.loadingTranslation = false
            }
          })
          .catch((err) => {
            console.error('查询翻译状态失败:', err)
            clearInterval(this.pollingTimer)
            this.pollingTimer = null
            this.$message({ message: '查询翻译状态失败', type: 'error' })
            this.loadingTranslation = false
          })
      }, 3000)
    },
    regenerateTranslation () {
      this.loadingTranslation = true
      this.translationResult = null

      request.post(`/article/translate?id=${this.paper_id}`, {
        // file_type: 0,
        glossary_id: this.selectedGlossaryId,
        reuse: this.reuseTranslation
      }).then((response) => {
        const taskId = response.data.id
        this.pollTranslationStatus(taskId)
      }).catch((error) => {
        console.error('重新翻译失败:', error)
        this.$message({
          message: '重新翻译失败',
          type: 'error'
        })
        this.loadingTranslation = false
      })
    },
    submitComment2 (level1CommentId) {
      console.log('1级评论', this.level1CommentId)
      console.log('提交的评论内容：', this.newComment)
      request.post('/commentPaper', {
        'paper_id': this.paper_id,
        'comment_level': 2,
        'level1_comment_id': level1CommentId,
        'comment': this.newComment
      })
        .then((response) => {
          this.$message({
            message: '评论成功',
            type: 'success'
          })
        })
        .catch((error) => {
          console.error('Error : ', error)
          this.$message({
            message: '评论失败',
            type: 'error'
          })
        })
        .finally(() => {
          this.newComment = ''
          // window.location.reload()
        })
    },
    submitComment3 (level1CommentId, level2CommentId) {
      console.log('评论级别', 3)
      console.log('提交的评论内容：', this.newComment)
      request.post('/commentPaper', {
        'paper_id': this.paper_id,
        'comment_level': 2,
        'level1_comment_id': level1CommentId,
        'reply_comment_id': level2CommentId,
        'comment': this.newComment
      })
        .then((response) => {
          this.$message({
            message: '评论成功',
            type: 'success'
          })
        })
        .catch((error) => {
          console.error('Error : ', error)
          this.$message({
            message: '评论失败',
            type: 'error'
          })
        })
        .finally(() => {
          this.newComment = ''
          // window.location.reload()
        })
    },
    submitScore () {
      console.log('提交的评分内容：', this.newScore)
      if (this.scored) {
        this.$message({
          message: '暂不支持修改评分哦～',
          type: 'error'
        })
        return
      }
      // 这里可以添加评论提交的逻辑
      request.post('/userScoring', {'paper_id': this.paper_id, 'score': this.newScore})
        .then((response) => {
          if (response.status === 200) {
            this.$message({
              message: '评分成功',
              type: 'success'
            })
          }
        })
        .catch((error) => {
          console.error('评分失败', error)
          this.$message({
            message: '评分失败',
            type: 'error'
          })
        })
        .finally(() => {
          this.showScoreModal = false // 关闭对话框
          window.location.reload()
        })
    },
    fetchComments2 (commentId) {
      if (this.showRepliesCommentId === commentId) {
        this.showRepliesCommentId = null
        return
      }
      console.log('second level comment id is ' + commentId)
      const url = '/getComment2?paper_id=' + this.paper_id + '&comment1_id=' + commentId
      request.get(url)
        .then((response) => {
          this.secondLevelComments = response.data.comments
          console.log(response.data.message)
          console.log('二级评论：', response.data.comments)
          this.showRepliesCommentId = commentId
        })
        .catch((error) => {
          console.error('Error:', error)
        })
    },
    toggleReplyInput (commentId) {
      if (this.showReplyInput === commentId) {
        this.showReplyInput = null
      } else {
        this.showReplyInput = commentId
      }
    }
  },

  watch: {
    showTranslateModal (val) {
      if (!val && this.pollingTimer) {
        clearInterval(this.pollingTimer)
        this.pollingTimer = null
      }
    }
  },
  beforeDestroy () {
    if (this.pollingTimer) {
      clearInterval(this.pollingTimer)
      this.pollingTimer = null
    }
  }
}
</script>

<style scoped>
.header {
    font-size: 40px;
    text-align: center;
}

.buttons {
    margin-left: 20px;
    justify-content: flex-start;
}

.reuse-trans-form {
  margin-bottom: 5px;
}

.buttons >>> .el-button {
  margin-right: 10px;
}

.glossary-detail-dialog >>> .el-dialog__body {
  padding-top: 5px;
}

.translate-form .glossary-select-wrapper {
  display: flex;
  align-items: center;
}

.glossary-select {
  flex: 1;
}

.view-detail-btn {
  margin-left: 12px;
  white-space: nowrap;
  font-size: 14px;
}

.translation-result-container {
  margin-top: 20px;
}

.translation-buttons {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 100px; /* 设置两个按钮之间的适当间距 */
  margin-top: 20px;
}

.translation-buttons el-link {
  font-size: 16px;
}

.translation-buttons el-button {
  font-size: 14px;
}

.dialog-footer {
  margin-top: 0px; /* 减少顶部间距 */
}

p {
    word-wrap: break-word;
    /* 允许单词在必要时断行 */
}

.avatar {
    width: 50%;
    aspect-ratio: 1 / 1;
    border-radius: 50%;
    overflow: hidden;   /* 超出容器的图片部分会被隐藏 */
    object-fit: cover;  /* 图片会覆盖整个容器，且内容会被裁剪以适应 */
}

.comment-content {
    text-align: left;
}

.text {
    margin-top: 5px;
}

.my-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.date {
    font-size: 0.85rem;
    color: #666;
}

.actions {
    display: flex;
    align-items: center;
}
</style>
