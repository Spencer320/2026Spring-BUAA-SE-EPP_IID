<template>
  <div style="padding: 10px;">
    <!-- 批注详情页 -->
    <div style="max-height: 800px;
             overflow-y: auto;
             padding-right: 10px;">
      <el-card
        v-for="(annotation, idx) in annotations"
        :key="annotation.id"
        class="annotation-comment"
        style="margin-bottom: 10px;"
      >
        <el-row>
          <!-- 头像列 -->
          <el-col :span="3" style="text-align: center;">
            <el-avatar :size="40" :src="annotation.author_avatar" style="box-shadow: 0 0 4px rgba(0,0,0,0.2);" />
          </el-col>

          <!-- 内容列 -->
          <el-col :span="21">
            <div style="text-align: justify; padding-left: 10px">{{ annotation.content }}</div>
            <div style="color: gray; font-size: 12px; text-align: right;">—— {{ annotation.author_name }}</div>

            <div style="text-align: right; margin-top: 10px;">
              <el-tooltip content="定位" placement="bottom">
                <el-button
                  type="text"
                  icon="el-icon-location"
                  @click="locate(idx)"
                />
              </el-tooltip>
              <el-tooltip content="收藏" placement="bottom">
                <el-button
                  type="text"
                  :icon="annotation.liked ? 'el-icon-star-on' : 'el-icon-star-off'"
                  @click="annotationToggleLike(idx)"
                />
              </el-tooltip>
              <el-tooltip content="评论" placement="bottom">
                <el-button
                  type="text"
                  icon="el-icon-edit"
                  @click="toggleCommentInput(idx)"
                />
              </el-tooltip>
            </div>

            <!-- 评论列表 -->
            <div v-if="annotation.comments && annotation.comment_count" style="margin-top: 10px;">
              <div
                v-for="(comment, i) in annotation.comments"
                :key="comment.id"
                style="padding: 5px 10px; border-radius: 4px; margin-bottom: 5px;"
              >
                <el-col :span="3" style="text-align: center;">
                  <el-avatar :size="32" :src="comment.author_avatar" />
                </el-col>
                <el-col :span="21" style="padding-left: 5px;">
                  <div style="text-align: justify;">{{ comment.content }}</div>
                  <div style="color: gray; font-size: 12px; text-align: right;">—— {{ comment.author_name }}</div>
                  <div style="text-align: right; margin-top: 10px;">
                    <!-- <el-tooltip content="comment收藏" placement="bottom">
                      <el-button
                        type="text"
                        :icon="comment.liked ? 'el-icon-star-on' : 'el-icon-star-off'"
                        size="mini"
                        @click.stop="toggleCommentLike(comment)"
                      />
                    </el-tooltip> -->
                  </div>
                  <div
                    v-if="comment.sub_comments && comment.sub_comment_count"
                    style="margin-left: 20px; margin-top: 10px;"
                  >
                    <div
                      v-for="(sub, j) in comment.sub_comments"
                      :key="j"
                      style="padding: 4px 8px; border-radius: 4px; margin-bottom: 6px;"
                    >
                      <el-col :span="3" style="text-align: center;">
                        <el-avatar :size="32" :src="sub.author_avatar"  />
                      </el-col>
                      <el-col :span="21" style="padding-left: 12px;">
                        <div style="text-align: justify;">{{ sub.content }}</div>
                        <div style="color: gray; font-size: 11px; text-align: right;">
                          — {{ sub.author_name }}
                        </div>
                      </el-col>
                    </div>
                  </div>

                  <!-- 二级评论输入框 -->
                  <div v-if="subCommentIndex === i" style="margin-left: 20px; margin-top: 6px;">
                    <el-input
                      v-model="subCommentInput"
                      placeholder="输入回复内容…"
                      size="small"
                      style="margin-bottom: 5px;"
                    />
                    <div style="text-align: right;">
                      <el-button type="primary" size="mini" @click="submitSubComment(idx, i)">发送</el-button>
                      <el-button type="info" size="mini" @click="subCommentIndex = null">取消</el-button>
                    </div>
                  </div>

                  <!-- “回复”按钮 (切换 replyIndex) -->
                  <div style="text-align: right; margin-top: 4px;">
                    <el-button type="text" size="mini" @click="subCommentIndex = i">回复</el-button>
                  </div>

                </el-col>

              </div>
            </div>

            <!-- 评论输入框 -->
            <div v-if="commentIndex === idx" style="margin-top: 10px;">
              <el-input
                v-model="commentInput"
                placeholder="输入评论内容…"
                size="small"
                style="margin-bottom: 5px;"
              />
              <div style="text-align: right;">
                <el-button type="primary" size="mini" @click="submitComment(idx)">发送</el-button>
                <el-button type="info" size="mini" @click="commentIndex = null">取消</el-button>
              </div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- 添加卡片 -->
      <el-card style="margin-bottom: 10px;">
        <template v-if="!showAddInDetail">
          <el-button type="primary" @click="startSelect">添加批注</el-button>
        </template>
        <template v-else>
          <el-input v-model="newAnnotation" placeholder="请输入批注内容…" style="margin-bottom: 10px;" />
          <el-button type="success" @click="addNewAnnotation">保存</el-button>
          <el-button type="info" @click="cancelAnnotation">取消</el-button>
        </template>
      </el-card>
    </div>
  </div>
</template>

<script>
export default {
  name: 'Annotations',
  props: {
    paper_id: {
      type: String,
      default: ''
    },
    annotations: {
      type: Array,
      default: () => []
    }
  },
  data () {
    return {
      loading: false, // 新增 loading 状态
      mode: 'list',
      showAddInList: false,
      showAddInDetail: false,
      newParagraphText: '',
      newCommentText: '',
      newDetailCommentText: '',
      newAnnotation: '',
      commentIndex: null,
      commentInput: '',
      subCommentIndex: null,
      subCommentInput: ''
    }
  },
  mounted () {
    // this.loading = true // 开始加载时显示 loading
    // fetchAnnotations(this.paper_id).then(response => {
    //   this.annotations = response.data
    //   console.log(this.annotations)
    //   this.loading = false // 完成后隐藏 loading
    // }).catch(err => {
    //   console.error('获取批注列表失败:', err)
    //   this.loading = false // 出现错误时也隐藏 loading
    // })
  },
  methods: {
    addNewAnnotation () {
      if (!this.newAnnotation) {
        this.$message({
          message: '请输入批注',
          type: 'warning'
        })
        return
      }
      this.$emit('save-annotation', this.newAnnotation)
      this.newAnnotation = ''
      this.showAddInDetail = false
    },
    annotationToggleLike (idx) {
      this.$emit('annotation-toggle-like', idx)
    },
    toggleCommentInput (index) {
      this.commentIndex = this.commentIndex === index ? null : index
    },
    submitComment (idx) {
      if (!this.commentInput) {
        this.$message.warning('请输入评论内容')
        return
      }
      const params = {
        idx: idx,
        content: this.commentInput
      }
      this.$emit('submit-comment', params)
      this.commentInput = ''
    },
    submitSubComment (annotationIdx, commentIdx) {
      if (!this.subCommentInput) {
        this.$message.warning('请输入评论内容')
        return
      }
      const params = {
        annotation_idx: annotationIdx,
        comment_idx: commentIdx,
        content: this.subCommentInput
      }
      this.$emit('submit-subcomment', params)
      this.subCommentInput = ''
    },
    startSelect () {
      this.showAddInDetail = true
      this.$emit('start-select')
    },
    cancelAnnotation () {
      this.showAddInDetail = false
      this.$emit('cancel-annotation')
    },
    locate (idx) {
      this.$emit('locate', idx)
    }
    // toggleCommentLike (comment) {
    //   comment.liked = !comment.liked
    // }
  }
}
</script>

<style scoped>
.el-loading-spinner {
  z-index: 9999;
}

.annotation-card:not(:last-child):hover {
  background: #f9f9f9;
  transition: background 0.3s;
}

.annotation-card {
  border-left: 4px solid #409EFF;
}

.annotation-comment {
  border-left: 4px solid #E6A23C;
  padding: 10px;
  transition: background 0.3s;
}

.annotation-comment:hover {
  background: #f9f9f9;
}

.el-button[type="text"] {
  padding: 0 8px;
}

</style>
