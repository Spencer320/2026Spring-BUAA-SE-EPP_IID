<template>
  <el-row style="overflow: hidden; height: 100vh;">
    <!-- PDF 预览区 -->
    <el-col :span="16" style="margin-top: 60px;">
      <pdf-viewer
        v-if="pdfUrl"
        ref="pdfViewer"
        :pdfUrl="pdfUrl"
        @annotations-ready="onAnnotationsReady"
      />
    </el-col>
    <!-- 笔记按钮区域 -->
    <div class="floating-buttons">
      <el-button type="primary" @click="saveAnnotations" style="margin-bottom: 10px;">保存笔记</el-button>
      <el-button type="success" @click="loadSavedAnnotations">恢复笔记</el-button>
    </div>

    <el-col :span="8" style="margin-top: 60px; height: calc(100vh - 60px); overflow: hidden; display: flex; flex-direction: column;">
      <el-radio-group v-model="activePanel" style="margin-bottom: 10px;">
        <el-radio-button label="assistant">调研助手</el-radio-button>
        <el-radio-button label="note">文本笔记</el-radio-button>
      </el-radio-group>

      <div style="flex: 1; overflow-y: auto;">
        <!-- 调研助手 -->
        <read-assistant
          v-show="activePanel === 'assistant'"
          :paperID="paper_id"
          :fileReadingId="Number(fileReadingID)"
        />

        <!-- 笔记编辑器 -->
        <note-editor
          v-show="activePanel === 'note'"
          ref="noteEditor"
        />
      </div>
    </el-col>

    <!-- 保存笔记对话框 -->
    <el-dialog
      :visible.sync="saveDialogVisible"
      width="40%"
      :before-close="() => (saveDialogVisible = false)"
    >
      <span slot="title">
        <i class="el-icon-edit" style="margin-right: 6px;"></i>
        保存笔记
      </span>

      <el-form label-width="85px" label-position="left">
        <el-form-item label="笔记名称：">
          <el-input v-model="newNoteName" placeholder="请输入笔记名称..." />
        </el-form-item>
      </el-form>

      <div slot="footer" class="dialog-footer">
        <el-button @click="saveDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isSaving" @click="confirmSave">保存</el-button>
      </div>
    </el-dialog>

    <!-- 恢复笔记对话框 -->
    <el-dialog
      :visible.sync="loadDialogVisible"
      width="40%"
      @open="fetchAnnotationList"
      :before-close="() => (loadDialogVisible = false)"
    >
      <span slot="title">
        <i class="el-icon-folder-opened" style="margin-right: 6px;"></i>
        恢复笔记
      </span>

      <el-form label-width="85px" label-position="left">
        <el-form-item label="选择笔记：">
          <el-select v-model="selectedNoteName" placeholder="请选择要恢复的笔记..." style="width: 100%;">
            <el-option
              v-for="item in annotationList"
              :key="item.name"
              :label="item.name"
              :value="item.name"
            />
          </el-select>
        </el-form-item>
      </el-form>

      <div slot="footer" class="dialog-footer">
        <el-button @click="loadDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmLoad">恢复</el-button>
      </div>
    </el-dialog>

  </el-row>
</template>

<script>
import ReadAssistant from './ReadAssistant.vue'
import PdfViewer from './PdfViewer.vue'
import request from '@/request/request'
import { resolvePdfFileUrl } from '@/utils/resolvePdfFileUrl'
import NoteEditor from './NoteEditor.vue'
export default {
  components: {
    'read-assistant': ReadAssistant,
    'pdf-viewer': PdfViewer,
    'note-editor': NoteEditor
  },
  props: {
    paper_id: {
      type: String,
      default: ''
    }
  },
  data () {
    return {
      pdfUrl: '',
      fileReadingID: '', // 初始化为空，created 中获取
      activePanel: 'assistant', // 默认显示调研助手
      saveDialogVisible: false,
      loadDialogVisible: false,
      newNoteName: '',
      selectedNoteName: '',
      pendingSaveNoteName: '', // 用于保存时暂存名称
      isSaving: false, // 保存笔记时 loading
      pendingMarkdown: '', // 暂存 markdown
      annotationList: []
    }
  },
  computed: {
    pdfViewer () {
      return this.$refs.pdfViewer
    }
  },
  created () {
    this.fileReadingID = this.$route.query.fileReadingID || ''
    this.fetchPaperPDF()
  },
  methods: {
    fetchPaperPDF () {
      request.get('/study/getPaperPDF?paper_id=' + this.paper_id)
        .then((response) => {
          this.pdfUrl = resolvePdfFileUrl(response.data.local_url, this.$BASE_URL)
          // this.pdfUrl = '/static/example.pdf'
          console.log('论文PDF为', this.pdfUrl)
        })
        .catch((error) => {
          console.log('请求论文PDF失败 ', error)
        })
    },
    // 保存按钮：打开对话框
    saveAnnotations () {
      console.log('Clicked!')

      this.newNoteName = ''
      this.saveDialogVisible = true
    },
    // 用户点击“确认保存”
    confirmSave () {
      if (!this.newNoteName) {
        this.$message.warning('笔记名称不能为空')
        return
      }
      this.isSaving = true
      this.pendingSaveNoteName = this.newNoteName // 暂存名称

      // 获取 markdown 内容
      const markdownContent = this.$refs.noteEditor.getNoteContent()
      console.log('获得的 markdown 为：', markdownContent)
      this.pendingMarkdown = markdownContent

      this.$refs.pdfViewer.getAnnotations() // 向 iframe 请求数据
    },
    // 当子组件传回注释数据
    onAnnotationsReady (annotations) {
      const markdown = this.pendingMarkdown ? this.pendingMarkdown.trim() : ''
      const noAnnotations = !annotations || annotations.length === 0
      const noMarkdown = !markdown

      if (noAnnotations && noMarkdown) {
        this.$message.error('笔记内容为空，无法保存')
        this.isSaving = false
        return
      }

      request.post('/saveNote', {
        paper_id: this.paper_id,
        fileReadingID: this.fileReadingID,
        name: this.pendingSaveNoteName,
        annotations,
        markdown: this.pendingMarkdown // 发送 Markdown 一起保存
      }).then(() => {
        this.$message.success('保存成功')
        this.saveDialogVisible = false
      }).catch(() => {
        this.$message.error('保存失败')
      }).finally(() => {
        this.isSaving = false
      })
    },

    // 点击按钮：显示恢复对话框
    loadSavedAnnotations () {
      this.loadDialogVisible = true
    },
    fetchAnnotationList () {
      request.get('/listNotes', {
        params: {
          paper_id: this.paper_id,
          fileReadingID: this.fileReadingID
        }
      }).then(res => {
        this.annotationList = res.data.annotations || []
      }).catch(() => {
        this.$message.error('获取笔记列表失败')
      })
    },
    confirmLoad () {
      const selected = this.annotationList.find(a => a.name === this.selectedNoteName)
      if (!selected) {
        this.$message.warning('请选择一个有效的笔记')
        return
      }
      this.pdfViewer.loadAnnotations(selected.annotations)
      this.$refs.noteEditor.setNoteContent(selected.markdown || '')
      this.loadDialogVisible = false
      this.$message.success(`已加载笔记：${selected.name}`)
    }
  }
}
</script>

<style scoped>
.floating-buttons {
  position: fixed;
  bottom: 10px;
  left: 10px;
  z-index: 999;
  flex-direction: column;
}
</style>
