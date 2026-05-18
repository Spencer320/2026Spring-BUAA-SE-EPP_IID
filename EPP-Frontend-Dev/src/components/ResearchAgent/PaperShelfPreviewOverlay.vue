<template>
  <transition name="ra-sp-slide">
    <div
      v-if="visible"
      class="ra-shelf-preview-root"
      @click.self="close"
    >
      <div
        class="ra-shelf-preview-panel"
        :class="panelClass"
        :style="{ width: widthPx + 'px' }"
        role="dialog"
        aria-modal="true"
        aria-label="文献预览"
        @click.stop
      >
        <div
          class="ra-sp-resize-handle"
          title="拖动调整宽度"
          @pointerdown.prevent="onResizeStart"
          @mousedown.prevent="onResizeStart"
        />
        <div class="ra-sp-head">
          <span class="ra-sp-title" :title="title">{{ truncate(title, 48) }}</span>
          <el-tooltip content="关闭预览" placement="bottom">
            <el-button type="text" size="mini" icon="el-icon-close" circle @click="close" />
          </el-tooltip>
        </div>
        <div v-loading="loading" class="ra-sp-body">
          <template v-if="mode === 'pdf' && blobUrl">
            <iframe class="ra-sp-iframe" title="PDF 预览" :src="blobUrl" />
          </template>
          <div v-else-if="mode === 'markdown' && html" class="ra-sp-scroll ra-md-inline" v-html="html" />
          <pre v-else-if="mode === 'text'" class="ra-sp-scroll ra-sp-pre">{{ text }}</pre>
          <div v-else-if="mode === 'image' && blobUrl" class="ra-sp-img-wrap">
            <img class="ra-sp-img" alt="预览" :src="blobUrl" />
          </div>
          <div v-else-if="mode === 'download_only'" class="ra-sp-scroll ra-sp-fallback">
            <el-alert type="info" :closable="false" show-icon :title="downloadTitle" :description="hint || '此类文件不适合在浏览器内嵌预览，请下载后用本地应用打开。'" />
            <el-button v-if="workspaceRel" type="primary" size="small" plain style="margin-top:12px" icon="el-icon-download" @click="download">下载文件</el-button>
          </div>
          <div v-else-if="mode === 'external'" class="ra-sp-scroll ra-sp-fallback">
            <el-alert type="warning" :closable="false" show-icon title="外链文献" description="受跨域与安全策略限制，无法在应用内嵌预览 PDF 或网页。请使用下方按钮在浏览器新标签中打开。" />
            <p v-if="abstractText" class="ra-sp-abs">{{ truncate(abstractText, 1200) }}</p>
            <el-button v-if="externalUrl" type="primary" size="small" style="margin-top:12px" @click="openExternal">在新标签打开</el-button>
          </div>
          <div v-else-if="mode === 'error'" class="ra-sp-scroll ra-sp-fallback">
            <el-alert type="error" :closable="false" show-icon :title="error || '加载失败'" />
            <el-button size="small" style="margin-top:12px" @click="retry">重试</el-button>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<script>
import MarkdownIt from 'markdown-it'
import { downloadWorkspaceFile, fetchWorkspaceFileBlob } from '@/views/ResearchAgent/workspaceApi.js'

const md = new MarkdownIt({ breaks: true, linkify: true })
const TEXT_MAX_BYTES = 512 * 1024
const WIDTH_STORAGE_KEY = 'ra_shelf_preview_w'

export default {
  name: 'PaperShelfPreviewOverlay',
  props: {
    panelClass: { type: String, default: '' }
  },
  data () {
    return {
      visible: false,
      item: null,
      loading: false,
      title: '',
      mode: '',
      blobUrl: '',
      text: '',
      html: '',
      hint: '',
      error: '',
      widthPx: 680,
      resizeTeardownFn: null
    }
  },
  computed: {
    workspaceRel () {
      return this.item && this.item.workspace_rel_path ? String(this.item.workspace_rel_path) : ''
    },
    externalUrl () {
      if (!this.item) return ''
      return String(this.item.external_jump_url || this.item.primary_url || '').trim()
    },
    abstractText () {
      return this.item && this.item.abstract ? String(this.item.abstract) : ''
    },
    downloadTitle () {
      const raw = this.item && this.item.file_extension ? String(this.item.file_extension).trim() : ''
      if (!raw) return '该文件需下载后查看'
      const pretty = raw.startsWith('.') ? raw : `.${raw}`
      return `「${pretty}」格式需下载后查看`
    }
  },
  created () {
    try {
      const w = parseInt(localStorage.getItem(WIDTH_STORAGE_KEY), 10)
      if (w >= 320 && w <= 1600) this.widthPx = w
    } catch (e) {
      /* ignore */
    }
  },
  beforeDestroy () {
    this.close()
  },
  methods: {
    truncate (s, n) {
      const t = String(s || '')
      return t.length > n ? t.slice(0, n) + '…' : t
    },
    apiError (e, fallback) {
      const data = e && e.response && e.response.data
      return (data && (data.message || data.error)) || (e && e.message) || fallback
    },
    isPreviewingItem (it) {
      return Boolean(this.visible && this.item && it && this.item.id === it.id)
    },
    async open (it, opts = {}) {
      if (!it || !it.id) return
      if (!opts.force && this.isPreviewingItem(it)) {
        this.close()
        return
      }
      this.revokeBlob()
      this.visible = true
      this.item = it
      this.title = it.title || '预览'
      this.mode = ''
      this.text = ''
      this.html = ''
      this.error = ''
      this.hint = it.hint ? String(it.hint) : ''
      this.loading = false

      if (it.source_kind !== 'workspace_file' || !it.workspace_rel_path) {
        this.mode = 'external'
        return
      }

      const openMode = it.open_mode || 'download_only'
      if (openMode === 'download_only') {
        this.mode = 'download_only'
        return
      }

      this.loading = true
      try {
        const blob = await fetchWorkspaceFileBlob(it.workspace_rel_path)
        if (openMode === 'pdf_viewer') {
          const pdfBlob =
            blob.type && blob.type !== 'application/octet-stream'
              ? blob
              : new Blob([blob], { type: 'application/pdf' })
          this.blobUrl = URL.createObjectURL(pdfBlob)
          this.mode = 'pdf'
        } else if (openMode === 'image_preview') {
          const imgBlob =
            blob.type && blob.type.startsWith('image/')
              ? blob
              : new Blob([blob], { type: this.guessImageMime(it.workspace_rel_path) })
          this.blobUrl = URL.createObjectURL(imgBlob)
          this.mode = 'image'
        } else if (openMode === 'text_preview') {
          const slice = blob.size > TEXT_MAX_BYTES ? blob.slice(0, TEXT_MAX_BYTES) : blob
          const buf = await slice.arrayBuffer()
          const dec = new TextDecoder('utf-8', { fatal: false })
          let content = dec.decode(buf)
          if (blob.size > TEXT_MAX_BYTES) {
            content += '\n\n…（仅显示前 512 KB，完整内容请下载）'
          }
          this.text = content
          const ext = String(it.file_extension || '').toLowerCase()
          if (ext === '.md' || ext === '.markdown') {
            this.html = md.render(content)
            this.mode = 'markdown'
          } else {
            this.mode = 'text'
          }
        } else {
          this.mode = 'download_only'
        }
      } catch (e) {
        this.error = this.apiError(e, '加载预览失败')
        this.mode = 'error'
      } finally {
        this.loading = false
      }
    },
    close () {
      this.clearResizeListeners()
      this.revokeBlob()
      this.visible = false
      this.item = null
      this.mode = ''
      this.title = ''
      this.text = ''
      this.html = ''
      this.hint = ''
      this.error = ''
      this.loading = false
      this.$emit('close')
    },
    retry () {
      if (this.item) this.open(this.item, { force: true })
    },
    download () {
      const p = this.workspaceRel
      if (!p) return
      const name = p.split('/').filter(Boolean).pop() || 'file'
      downloadWorkspaceFile(p, name).catch(e => this.$message.error(this.apiError(e, '下载失败')))
    },
    openExternal () {
      const u = this.externalUrl
      if (u) window.open(u, '_blank', 'noopener,noreferrer')
    },
    revokeBlob () {
      if (this.blobUrl) {
        try {
          URL.revokeObjectURL(this.blobUrl)
        } catch (e) {
          /* ignore */
        }
        this.blobUrl = ''
      }
    },
    guessImageMime (relPath) {
      const ext = String(relPath.split('.').pop() || '').toLowerCase()
      const map = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp' }
      return map[ext] || 'application/octet-stream'
    },
    clearResizeListeners () {
      if (typeof this.resizeTeardownFn === 'function') {
        this.resizeTeardownFn()
        this.resizeTeardownFn = null
      }
    },
    onResizeStart (e) {
      if (e.type === 'mousedown' && typeof window.PointerEvent !== 'undefined') return
      if (e.button !== undefined && e.button !== 0) return
      this.clearResizeListeners()
      const handle = e.currentTarget
      const maxW = Math.max(320, Math.min(1600, Math.floor(window.innerWidth * 0.96)))
      const minW = 320
      const startX = e.clientX
      const startW = this.widthPx
      const applyWidth = (clientX) => {
        let w = startW + (clientX - startX)
        if (w < minW) w = minW
        if (w > maxW) w = maxW
        this.widthPx = w
      }
      let pointerId = null
      let usePointerCapture = false
      if (typeof e.pointerId === 'number' && handle.setPointerCapture) {
        pointerId = e.pointerId
        try {
          handle.setPointerCapture(pointerId)
          usePointerCapture = true
        } catch (err) {
          pointerId = null
        }
      }
      const onMove = (ev) => {
        if (usePointerCapture && ev.pointerId !== pointerId) return
        applyWidth(ev.clientX)
      }
      const onEnd = (ev) => {
        if (this.resizeTeardownFn !== onEnd) return
        if (usePointerCapture && ev && typeof ev.pointerId === 'number' && ev.pointerId !== pointerId) return
        this.resizeTeardownFn = null
        if (usePointerCapture) {
          handle.removeEventListener('pointermove', onMove)
          handle.removeEventListener('pointerup', onEnd)
          handle.removeEventListener('pointercancel', onEnd)
          if (pointerId != null) {
            try { handle.releasePointerCapture(pointerId) } catch (err) { /* ignore */ }
          }
        } else {
          document.removeEventListener('mousemove', onMove, true)
          document.removeEventListener('mouseup', onEnd, true)
          window.removeEventListener('blur', onEnd)
        }
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        try {
          localStorage.setItem(WIDTH_STORAGE_KEY, String(this.widthPx))
        } catch (err) {
          /* ignore */
        }
      }
      this.resizeTeardownFn = onEnd
      if (usePointerCapture) {
        handle.addEventListener('pointermove', onMove)
        handle.addEventListener('pointerup', onEnd)
        handle.addEventListener('pointercancel', onEnd)
      } else {
        document.addEventListener('mousemove', onMove, true)
        document.addEventListener('mouseup', onEnd, true)
        window.addEventListener('blur', onEnd)
      }
      document.body.style.cursor = 'ew-resize'
      document.body.style.userSelect = 'none'
    }
  }
}
</script>

<style scoped>
.ra-shelf-preview-root {
  position: absolute;
  inset: 0;
  z-index: 34;
  background: rgba(15, 23, 42, 0.14);
}
.ra-shelf-preview-panel {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  box-sizing: border-box;
  padding: 8px 14px 10px 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  box-shadow: 10px 0 36px rgba(0, 0, 0, 0.18);
  border-radius: 0 12px 12px 0;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(210, 225, 255, 0.85);
}
.ra-sp-resize-handle {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 10px;
  z-index: 6;
  cursor: ew-resize;
  background: transparent;
}
.ra-sp-resize-handle:hover {
  background: rgba(64, 158, 255, 0.14);
}
.ra-sp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
  margin-bottom: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e8edf7;
}
.ra-sp-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a2b4a;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ra-sp-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ra-sp-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.ra-sp-iframe {
  flex: 1;
  min-height: 360px;
  width: 100%;
  border: none;
  border-radius: 8px;
  background: #f5f7fa;
}
.ra-sp-pre {
  margin: 0;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #edf2f7;
}
.ra-sp-img-wrap {
  flex: 1;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  background: #0f172a08;
  border-radius: 8px;
}
.ra-sp-img {
  max-width: 100%;
  max-height: min(78vh, 900px);
  object-fit: contain;
}
.ra-sp-fallback {
  padding: 4px 2px 8px;
}
.ra-sp-abs {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
}
.ra-md-inline >>> p {
  margin: 0.45em 0;
}
.ra-md-inline >>> pre {
  background: #f6f8fa;
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
}
.ra-sp-slide-enter-active,
.ra-sp-slide-leave-active {
  transition: opacity 0.22s ease;
}
.ra-sp-slide-enter-active .ra-shelf-preview-panel,
.ra-sp-slide-leave-active .ra-shelf-preview-panel,
.ra-sp-slide-enter-to .ra-shelf-preview-panel {
  transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1);
}
.ra-sp-slide-enter,
.ra-sp-slide-leave-to {
  opacity: 0;
}
.ra-sp-slide-enter .ra-shelf-preview-panel,
.ra-sp-slide-leave-to .ra-shelf-preview-panel {
  transform: translateX(-100%);
}
.ra-sp-slide-enter-to .ra-shelf-preview-panel {
  transform: translateX(0);
}
</style>
