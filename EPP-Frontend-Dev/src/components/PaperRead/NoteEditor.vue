<template>
  <div class="note-editor-wrapper">
    <div class="note-editor-card">
      <div class="note-editor-header">
        <h3>📝 文本笔记</h3>
        <p class="note-tip">支持 Markdown 编写、保存 👍</p>
      </div>
      <div id="vditor" class="vditor-container"></div>
    </div>
  </div>
</template>

<script>
import Vditor from 'vditor'
import 'vditor/dist/index.css'

export default {
  name: 'NoteEditor',
  data () {
    return {
      vditor: null,
      content: '# 欢迎使用 EPP 文本笔记😊\n\n你可以使用 Markdown 来进行编写😎。'
    }
  },
  mounted () {
    this.vditor = new Vditor('vditor', {
      height: '100%',
      toolbar: [
        { name: 'emoji', tipPosition: 's' },
        { name: 'headings', tipPosition: 's' },
        { name: 'bold', tipPosition: 's' },
        { name: 'italic', tipPosition: 's' },
        { name: 'strike', tipPosition: 's' },
        { name: 'link', tipPosition: 's' },
        '|',
        { name: 'list', tipPosition: 's' },
        { name: 'ordered-list', tipPosition: 's' },
        { name: 'check', tipPosition: 's' },
        { name: 'outdent', tipPosition: 's' },
        { name: 'indent', tipPosition: 's' },
        '|',
        { name: 'quote', tipPosition: 's' },
        { name: 'line', tipPosition: 's' },
        { name: 'code', tipPosition: 's' },
        { name: 'inline-code', tipPosition: 's' },
        { name: 'insert-before', tipPosition: 's' },
        { name: 'insert-after', tipPosition: 's' },
        '|',
        'table',
        '|',
        'undo',
        'redo',
        '|',
        'fullscreen',
        'edit-mode',
        {
          name: 'more',
          toolbar: [
            'both',
            'code-theme',
            'content-theme',
            'export',
            'outline',
            'preview',
            'devtools',
            'help'
          ]
        }
      ],
      toolbarConfig: {
        pin: true
      },
      cache: {
        enable: false
      },
      mode: 'ir', // 可选：sv | ir | wysiwyg
      value: this.content,
      input: (value) => {
        // 每次内容变化时同步到 data
        this.content = value
      }
    })
  },
  methods: {
    getNoteContent () {
      // 获取 Markdown 内容
      return this.vditor.getValue()
    },
    setNoteContent (markdown) {
      this.vditor.setValue(markdown)
    }
  }
}
</script>

<style>
.note-editor-wrapper {
  padding: 5px;
  height: 100%;
  box-sizing: border-box;
  background: #f5f7fa;
  display: flex;
  flex-direction: column;
}

.note-editor-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  padding: 16px;
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.note-editor-header {
  margin-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 10px;
}

.note-editor-header h3 {
  margin: 0;
  font-weight: 600;
  font-size: 24px;
}

.note-tip {
  font-size: 13px;
  color: #999;
  margin-top: 5px;
}

.vditor-container {
  flex: 1;
  overflow: hidden;
}

.vditor .vditor-content {
  text-align: justify !important;
}
</style>
