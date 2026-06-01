<template>
  <div class="pdf-iframe-wrapper" v-if="iframeUrl">
    <iframe
      ref="pdfIframe"
      :src="iframeUrl"
      width="100%"
      height="100%"
      frameborder="0"
      @load="onIframeLoad"
    ></iframe>
    <div v-if="!iframeLoaded" class="loading-overlay">加载中...</div>
  </div>
</template>

<script>
export default {
  name: 'PDFViewer',
  props: {
    pdfUrl: {
      type: String,
      required: true
    }
  },
  data () {
    return {
      iframeLoaded: false,
      annotationTimer: null,
      annotations: null // 保存拿到的笔记
    }
  },
  computed: {
    iframeUrl () {
      if (!this.pdfUrl) return ''
      return `/static/web/viewer.html?file=${encodeURIComponent(this.pdfUrl)}`
    }
  },
  methods: {
    onIframeLoad () {
      this.iframeLoaded = true
      // iframe 加载完成后，监听 postMessage
      window.addEventListener('message', this.handleMessage, false)
    },
    handleMessage (event) {
      if (event.data) {
        console.log('接收到的消息:', event.data)
        if (event.data.type === 'ANNOTATIONS_DATA') {
          console.log('收到注释数据:', event.data.data)
          if (this.annotationTimer) {
            clearTimeout(this.annotationTimer)
            this.annotationTimer = null
          }
          this.annotations = event.data.data
          this.$emit('annotations-ready', this.annotations)
        }
      }
    },
    // 主动请求获取注释
    getAnnotations () {
      try {
        if (this.annotationTimer) {
          clearTimeout(this.annotationTimer)
        }
        this.annotationTimer = setTimeout(() => {
          this.annotationTimer = null
          this.$emit('annotations-ready', [])
        }, 3000)
        const iframe = this.$refs.pdfIframe
        if (iframe && iframe.contentWindow) {
          // 在请求前判断是否已加载完成
          if (!this.iframeLoaded) {
            return
          }
          iframe.contentWindow.postMessage({ type: 'GET_ANNOTATIONS' }, '*')
        }
      } catch (error) {
        console.error('postMessage 错误:', error)
        if (this.annotationTimer) {
          clearTimeout(this.annotationTimer)
          this.annotationTimer = null
        }
        this.$emit('annotations-ready', [])
      }
    },
    // 向 iframe 发送注释数据（恢复）
    loadAnnotations (annotationsData) {
      try {
        const iframe = this.$refs.pdfIframe
        if (iframe && iframe.contentWindow) {
          iframe.contentWindow.postMessage({ type: 'LOAD_ANNOTATIONS', data: annotationsData }, '*')
        }
      } catch (error) {
        console.error('postMessage 错误:', error)
      }
    }
  },
  beforeDestroy () {
    if (this.annotationTimer) {
      clearTimeout(this.annotationTimer)
      this.annotationTimer = null
    }
    window.removeEventListener('message', this.handleMessage)
  }
}
</script>

<style scoped>
.pdf-iframe-wrapper {
  position: relative;
  width: 100%;
  height: calc(100vh - 60px);
  overflow: hidden;
}

.pdf-iframe-wrapper iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: none;
}

.loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(255,255,255,0.8);
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
