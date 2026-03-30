<template>
    <el-row style="overflow: hidden; height: 100vh;">
      <el-col :span="15" style="margin-top: 60px;">
        <div id="pdf-viewer-container" style="width: 90%; height: 755px;"></div>
      </el-col>
      <el-col :span="9" style="margin-top: 60px; height: calc(100vh - 60px); overflow: hidden; display: flex; flex-direction: column;">
        <!-- 公开批注 -->
        <annotations
          :paper_id="paper_id"
          :annotations="annotations"
          @start-select="startSelect"
          @save-annotation="saveAnntation"
          @cancel-annotation="cancelAnnotation"
          @locate="locate"
          @annotation-toggle-like="annotationToggleLike"
          @submit-comment="annotationComment"
          @submit-subcomment="annotationSubComment"
        />
    </el-col>
    </el-row>
</template>

<script>
import request from '@/request/request'
import Annotations from './Annotations.vue'
import { addAnnotation, fetchAnnotations, fetchAnnotationComment, fetchAnnotationSubComment, annotationLike, annotationComment, annotationSubComment } from '@/request/userRequest'
export default {
  name: 'PdfAnnoations',
  components: {
    'annotations': Annotations
  },
  props: {
    paper_id: {
      type: String,
      default: ''
    }
  },
  data () {
    return {
      startSel: false,
      pdfUrl: '', // 用来显示的url
      fileReadingID: '',
      isSelecting: false, // 是否正在框选
      startX: 0, // 框选起始点的X坐标
      startY: 0, // 框选起始点的Y坐标
      selectionBox: null, // 保存框选区域的DOM元素
      annotations: [], // 保存用来显示的注释。初始等于下面，但是后续会根据筛选调整，保证论文和评论展示区都能只显示筛选后的注释
      pdfInstance: null, // PDF.js 实例
      containerOffsetTop: 0, // PDF 容器的顶部偏移
      containerOffsetLeft: 0, // PDF 容器的左侧偏移
      allPageNumbers: [], // 所有页面的页码
      pendingAnnotation: null, // 正在发表的批注内容
      isFetchPaperSuccess: false, // 是否获取成功
      isLoadPdfSuccess: false // 是否加载PDF成功
    }
  },
  async created () {
    this.loadPDFJS()
    this.fetchPaperPDF()
    this.fileReadingID = this.$route.query.fileReadingID
  },
  mounted () {
    // 一开始先不绑定 mousedown/mousemove/mouseup
    // 只绑定可能一直都需要的事件，比如 scroll
    // 监听 startSel 的变化
    this.$watch('startSel', (newVal) => {
      const container = document.getElementById('pdf-viewer-container')
      if (newVal) {
        // startSel 变 true，开始监听这三种事件
        container.addEventListener('mousedown', this.handleMouseDown)
        container.addEventListener('mousemove', this.handleMouseMove)
        container.addEventListener('mouseup', this.handleMouseUp)
      } else {
        // startSel 变 false，就移除监听
        container.removeEventListener('mousedown', this.handleMouseDown)
        container.removeEventListener('mousemove', this.handleMouseMove)
        container.removeEventListener('mouseup', this.handleMouseUp)
      }
    })
  },
  beforeUnmount () {
    // 组件卸载时，清理所有监听器
    const container = document.getElementById('pdf-viewer-container')
    container.removeEventListener('scroll', this.updateAnnotationsPosition)
    container.removeEventListener('mousedown', this.handleMouseDown)
    container.removeEventListener('mousemove', this.handleMouseMove)
    container.removeEventListener('mouseup', this.handleMouseUp)
  },
  methods: {
    fetchPaperPDF () {
      request.get('/study/getPaperPDF?paper_id=' + this.paper_id)
        .then((response) => {
          // this.pdfUrl = this.$BASE_URL + response.data.local_url
          this.pdfUrl = '/static/example.pdf'
          this.isFetchPaperSuccess = true
          if (this.isLoadPdfSuccess) {
            this.initPDFViewer()
          }
          console.log('论文PDF为', this.pdfUrl)
        })
        .catch((error) => {
          console.log('请求论文PDF失败 ', error)
        })
    },
    loadPDFJS () {
      const script = document.createElement('script')
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.10.377/pdf.min.js'
      script.onload = () => {
        console.log('PDF.js 加载成功') // 添加这行
        window.pdfjsLib.GlobalWorkerOptions.workerSrc =
          'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.10.377/pdf.worker.min.js'
        this.isLoadPdfSuccess = true // PDF.js加载成功
        if (this.isFetchPaperSuccess) {
          this.initPDFViewer()
        }
      }
      script.onerror = () => {
        console.error('PDF.js 加载失败') // 添加错误处理
      }
      document.head.appendChild(script)
    },
    // 初始化PDF查看器
    initPDFViewer () {
      if (!window.pdfjsLib) {
        console.error('PDF.js库未加载完成')
        return
      }

      const container = document.getElementById('pdf-viewer-container')
      container.innerHTML = '' // 清空容器
      container.style.position = 'relative' // 设为相对定位
      container.style.overflow = 'auto' // 添加滚动支持
      window.pdfjsLib.GlobalWorkerOptions.workerSrc =
        'https://cdn.jsdelivr.net/npm/pdfjs-dist@2.10.377/build/pdf.worker.min.js'

      // 2. 加载PDF文档（含中文支持配置）
      window.pdfjsLib.getDocument({
        url: this.pdfUrl,
        cMapUrl: 'https://cdn.jsdelivr.net/npm/pdfjs-dist@2.10.377/cmaps/', // 关键：中文CMAP
        cMapPacked: true,
        useSystemFonts: false, // 禁用系统字体回退
        disableFontFace: false // 启用@font-face
      }).promise
        .then(pdf => {
          this.pdfInstance = pdf
          this.renderAllPages(pdf, container)
          this.getAllInformation()
        })
        .catch(error => {
          // console.error('PDF加载失败:', error)
          // 友好错误提示（根据实际UI框架调整）
          if (error.name === 'MissingPDFException') {
            alert('PDF文件不存在或路径错误')
          } else if (error.name === 'InvalidPDFException') {
            alert('PDF文件已损坏')
          } else {
            // alert('PDF加载失败，请确保文件使用标准字体嵌入')
          }
        })
      // container.addEventListener('mousedown', this.handleMouseDown)
      // container.addEventListener('mousemove', this.handleMouseMove)
      // container.addEventListener('mouseup', this.handleMouseUp)
    },
    getAllInformation () {
      fetchAnnotations(this.paper_id).then(res => {
        const resData = res.data
        this.annotations.push(...resData)
        for (let i = 0; i < this.annotations.length; i++) {
          let pos = this.annotations[i].position
          this.renderAnnotation(pos.x, pos.y, pos.width, pos.height, pos.pageNum)
        }
        for (let i = 0; i < this.annotations.length; i++) {
          if (this.annotations[i].comment_count > 0) {
            this.annotations[i].comments = []
            fetchAnnotationComment(this.annotations[i].id).then(res => {
              const resData = res.data
              this.annotations[i].comments.push(...resData)
              for (let j = 0; j < this.annotations[i].comments.length; j++) {
                if (this.annotations[i].comments[j].sub_comment_count > 0) {
                  this.annotations[i].comments[j].sub_comments = []
                  fetchAnnotationSubComment(this.annotations[i].id, this.annotations[i].comments[j].id).then(res => {
                    const resData = res.data
                    this.annotations[i].comments[j].sub_comments.push(...resData)
                  })
                }
              }
            })
          }
        }
      })
    },
    // 渲染所有页面
    renderAllPages (pdf, container) {
      for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
        this.allPageNumbers.push(pageNum)
        pdf.getPage(pageNum).then(page => {
          const viewport = page.getViewport({ scale: 1.5 })
          const canvas = document.createElement('canvas')
          const context = canvas.getContext('2d')
          canvas.height = viewport.height
          canvas.width = viewport.width
          container.appendChild(canvas)
          page.render({ canvasContext: context, viewport: viewport })
          canvas.setAttribute('data-page-num', pageNum)
          canvas.addEventListener('click', this.handlePageClick)
        })
      }
    },
    handleMouseDown (event) {
      if (this.isSelecting) return
      this.isSelecting = true
      const container = document.getElementById('pdf-viewer-container')
      this.startX = event.clientX + container.scrollLeft // 修正 scrollLeft
      this.startY = event.clientY + container.scrollTop // 修正 scrollTop

      this.containerOffsetTop = container.getBoundingClientRect().top
      this.containerOffsetLeft = container.getBoundingClientRect().left

      this.selectionBox = document.createElement('div')
      this.selectionBox.style.position = 'absolute'
      this.selectionBox.style.border = '2px dashed blue'
      this.selectionBox.style.pointerEvents = 'none'
      this.selectionBox.style.zIndex = '1000'
      container.appendChild(this.selectionBox)
    },
    handleMouseMove (event) {
      if (!this.isSelecting) return
      const container = document.getElementById('pdf-viewer-container')

      const width = event.clientX + container.scrollLeft - this.startX
      const height = event.clientY + container.scrollTop - this.startY // 修正 scrollTop

      this.selectionBox.style.left = `${this.startX - this.containerOffsetLeft}px`
      this.selectionBox.style.top = `${this.startY - this.containerOffsetTop}px`
      this.selectionBox.style.width = `${Math.abs(width)}px`
      this.selectionBox.style.height = `${Math.abs(height)}px`
      // this.selectionBox.style.left = `${Math.round(this.startX - this.containerOffsetLeft)}px`
      // this.selectionBox.style.top = `${Math.round(this.startY - this.containerOffsetTop)}px`
      // this.selectionBox.style.width = `${Math.round(Math.abs(width))}px`
      // this.selectionBox.style.height = `${Math.round(Math.abs(height))}px`
    },
    handleMouseUp (event) {
      if (!this.isSelecting) return

      this.isSelecting = false
      const selectionRect = this.selectionBox.getBoundingClientRect()
      document.getElementById('pdf-viewer-container').removeChild(this.selectionBox)
      this.selectionBox = null

      // 下面以后可以设置，当框太小或者太靠近滚动条等明显不是为了框选的时候，就不框选了。也就是不执行下面那行代码。
      this.extractSelectedText(selectionRect)
    },
    isIntersecting (rect1, rect2) {
      return !(rect2.top > rect1.bottom ||
              rect2.right < rect1.left ||
              rect2.bottom < rect1.top ||
              rect2.left > rect1.right)
    },
    extractSelectedText (selectionRect) {
      const container = document.getElementById('pdf-viewer-container')
      // 下面的这些坐标是 可能带小数的。其中上方相对视口偏移this.containerOffsetTop = container.getBoundingClientRect().top是永远不变的。有啥用我也不知道。。前四个确定了显示的框位置。滚动那个是确定相对位置的。container我用了相对距离，大概是考虑了不同浏览器的显示问题，有没有用就不知道了。但这里根本没用到页数了。
      // alert('选中区域：宽度：' + selectionRect.width + ' 高度：' + selectionRect.height + ' 左上角X坐标：' + selectionRect.left + ' 左上角Y坐标：' + selectionRect.top + '上方相对视口偏移:' + this.containerOffsetTop + '上下滚动距离' + container.scrollTop)
      const canvasElements = container.getElementsByTagName('canvas')

      for (let canvas of canvasElements) {
        const pageNum = parseInt(canvas.getAttribute('data-page-num'))
        const canvasRect = canvas.getBoundingClientRect()

        if (this.isIntersecting(selectionRect, canvasRect)) {
          this.showAnnotation(selectionRect.left - canvasRect.left, selectionRect.top - canvasRect.top, selectionRect.width, selectionRect.height, pageNum)
          return
        }
      }
    },

    showAnnotation (x, y, width, height, pageNum) {
      if (this.pendingAnnotation != null) {
        this.removeAnnotation(this.pendingAnnotation.x, this.pendingAnnotation.y,
          this.pendingAnnotation.width, this.pendingAnnotation.height, this.pendingAnnotation.pageNum)
      }
      this.pendingAnnotation = { x, y, width, height, pageNum }
      this.renderAnnotation(x, y, width, height, pageNum)
    },

    renderAnnotation (x, y, width, height, pageNum) {
      // console.log(`x = ${x}, y = ${y}, width = ${width}, height = ${height}, pageNum = ${pageNum}`)
      const container = document.getElementById('pdf-viewer-container')
      const canvas = container.querySelector(`canvas[data-page-num="${pageNum}"]`)
      if (!canvas) return
      // 创建虚线框
      const annotationBox = document.createElement('div')
      annotationBox.classList.add('annotation-box')
      annotationBox.style.position = 'absolute'
      annotationBox.style.left = `${canvas.offsetLeft + x}px`
      annotationBox.style.top = `${canvas.offsetTop + y}px`
      annotationBox.style.width = `${width}px`
      annotationBox.style.height = `${height}px`
      annotationBox.style.border = '2px dashed rgba(0, 0, 255, 0.8)' // 蓝色虚线框
      annotationBox.style.pointerEvents = 'auto' // 让鼠标事件生效
      annotationBox.style.zIndex = '1000'
      annotationBox.setAttribute('data-page-num', pageNum)

      // 创建弹出注释框
      const tooltip = document.createElement('div')
      tooltip.classList.add('annotation-tooltip')
      tooltip.style.position = 'absolute'
      tooltip.style.left = `${canvas.offsetLeft + x}px`
      tooltip.style.top = `${canvas.offsetTop + y + height + 5}px` // 显示在框下方
      tooltip.style.backgroundColor = 'rgba(0, 0, 0, 0.8)'
      tooltip.style.color = 'white'
      tooltip.style.padding = '6px 10px'
      tooltip.style.borderRadius = '5px'
      tooltip.style.fontSize = '12px'
      tooltip.style.whiteSpace = 'nowrap'
      tooltip.style.display = 'none'
      tooltip.setAttribute('data-page-num', pageNum)
      // tooltip.innerHTML = comments.map(c => `• ${c}`).join('<br>') // 显示所有注释

      // **鼠标悬停时，找到所有重叠的注释**
      // annotationBox.addEventListener('mousemove', (event) => {
      //   // const overlappingComments = this.findOverlappingComments(x, y, width, height, pageNum)
      //   const overlappingComments = this.findOverlappingComments(event.clientX, event.clientY, pageNum)
      //   // tooltip.innerHTML = overlappingComments.map(c => `• ${c}`).join('<br>')
      //   tooltip.innerHTML = overlappingComments.map(c => `• ${c.userName}: ${c.comment}`).join('<br>')

      //   // **调整 tooltip 位置**
      //   tooltip.style.left = `${canvas.offsetLeft + x}px`
      //   tooltip.style.top = `${canvas.offsetTop + y + height + 5}px`
      //   tooltip.style.display = 'block'
      //   tooltip.style.textAlign = 'left'
      //   tooltip.style.whiteSpace = 'normal' // 允许换行
      //   tooltip.style.maxWidth = '400px' // 设置最大宽度
      // })

      // annotationBox.addEventListener('mouseleave', () => {
      //   tooltip.style.display = 'none'
      // })

      container.appendChild(annotationBox)
      container.appendChild(tooltip)
    },
    removeAnnotation (x, y, width, height, pageNum) {
      const container = document.getElementById('pdf-viewer-container')
      if (!container) return

      const canvas = container.querySelector(`canvas[data-page-num="${pageNum}"]`)
      if (!canvas) return

      // 计算元素应该出现的绝对位置
      const expectedLeft = canvas.offsetLeft + x
      const expectedTop = canvas.offsetTop + y
      const expectedTooltipTop = expectedTop + height + 5 // 对应tooltip位置

      // 查找匹配的注释框
      const annotations = container.querySelectorAll(`.annotation-box[data-page-num="${pageNum}"]`)
      annotations.forEach(annotation => {
        const annotationLeft = parseInt(annotation.style.left, 10)
        const annotationTop = parseInt(annotation.style.top, 10)
        const annotationWidth = parseInt(annotation.style.width, 10)
        const annotationHeight = parseInt(annotation.style.height, 10)

        // 允许1像素的舍入误差
        const positionMatches =
      Math.abs(annotationLeft - expectedLeft) <= 1 &&
      Math.abs(annotationTop - expectedTop) <= 1 &&
      Math.abs(annotationWidth - width) <= 1 &&
      Math.abs(annotationHeight - height) <= 1

        if (positionMatches) {
          // 删除注释框
          annotation.remove()

          // 查找关联的tooltip
          const tooltips = container.querySelectorAll(`.annotation-tooltip[data-page-num="${pageNum}"]`)
          tooltips.forEach(tooltip => {
            const tooltipLeft = parseInt(tooltip.style.left, 10)
            const tooltipTop = parseInt(tooltip.style.top, 10)

            if (
              Math.abs(tooltipLeft - expectedLeft) <= 1 &&
          Math.abs(tooltipTop - expectedTooltipTop) <= 1
            ) {
              tooltip.remove()
            }
          })
        }
      })
    },
    startSelect () {
      this.startSel = true
    },
    saveAnntation (content) {
      if (!this.pendingAnnotation) {
        this.$message({
          message: '请添加框选',
          type: 'warning'
        })
        return
      }
      const pos = {
        'x': this.pendingAnnotation.x,
        'y': this.pendingAnnotation.y,
        'width': this.pendingAnnotation.width,
        'height': this.pendingAnnotation.height,
        'pageNum': this.pendingAnnotation.pageNum
      }
      const name = localStorage.getItem('username')
      const avatar = localStorage.getItem('avatar')
      this.annotations.push({
        'id': '',
        'position': pos,
        'content': content,
        'date': '',
        'author_name': name,
        'author_avatar': avatar,
        'liked': false,
        'comment_count': 0
      })
      const params = {
        'position': pos,
        'content': {
          'id': '',
          'position': pos,
          'content': content,
          'date': '',
          'author_name': name,
          'author_avatar': avatar,
          'liked': false,
          'comment_count': 0
        }
      }
      addAnnotation(this.paper_id, params).then(res => {
        const resData = res.data
        this.annotations[this.annotations.length - 1].id = resData.id
        this.annotations[this.annotations.length - 1].date = resData.date
      })
      this.pendingAnnotation = null
      this.startSel = false
    },
    cancelAnnotation () {
      if (this.pendingAnnotation != null) {
        this.removeAnnotation(this.pendingAnnotation.x, this.pendingAnnotation.y,
          this.pendingAnnotation.width, this.pendingAnnotation.height, this.pendingAnnotation.pageNum)
      }
      if (this.startSel) {
        this.startSel = false
      }
    },
    scrollToAnnotation (x, y, width, height, pageNum) {
      const container = document.getElementById('pdf-viewer-container')
      if (!container) return

      // 1. 找到目标画布
      const canvas = container.querySelector(`canvas[data-page-num="${pageNum}"]`)
      if (!canvas) return

      // 3. 计算目标区域坐标（相对容器）
      const targetLeft = canvas.offsetLeft + x
      const targetTop = canvas.offsetTop + y

      // 4. 计算滚动位置（让目标区域居中）
      const targetCenterX = targetLeft + width / 2
      const targetCenterY = targetTop + height / 2

      // 滚动计算考虑容器可见区域
      const scrollLeft = targetCenterX - container.clientWidth / 2
      const scrollTop = targetCenterY - container.clientHeight / 2

      // 5. 平滑滚动到目标位置
      container.scrollTo({
        left: Math.max(0, scrollLeft),
        top: Math.max(0, scrollTop),
        behavior: 'smooth'
      })

      // 6. 高亮目标区域（可选）
      this.highlightAnnotation(x, y, width, height, pageNum)
    },

    // 高亮特定注释（可单独调用）
    highlightAnnotation (x, y, width, height, pageNum) {
      // 先清除所有高亮
      const existingHighlights = document.querySelectorAll('.annotation-highlight')
      existingHighlights.forEach(el => el.remove())

      // 创建高亮元素
      const container = document.getElementById('pdf-viewer-container')
      const canvas = container.querySelector(`canvas[data-page-num="${pageNum}"]`)

      const highlight = document.createElement('div')
      highlight.classList.add('annotation-highlight')
      highlight.style.cssText = `
    position: absolute;
    left: ${canvas.offsetLeft + x}px;
    top: ${canvas.offsetTop + y}px;
    width: ${width}px;
    height: ${height}px;
    background: rgba(255,215,0,0.3);
    border: 2px solid #ffd700;
    pointer-events: none;
    z-index: 1001;
    box-shadow: 0 0 8px rgba(255,215,0,0.5);
  `

      container.appendChild(highlight)

      // 5秒后自动移除高亮
      setTimeout(() => highlight.remove(), 2000)
    },
    locate (idx) {
      const pos = this.annotations[idx].position
      this.scrollToAnnotation(pos.x, pos.y, pos.width,
        pos.height, pos.pageNum)
    },
    annotationToggleLike (idx) {
      this.annotations[idx].liked = !this.annotations[idx].liked
      annotationLike(this.annotations[idx].id)
    },
    annotationComment (params) {
      const name = localStorage.getItem('username')
      const avatar = localStorage.getItem('avatar')
      let idx = params.idx
      let content = params.content
      const comment = {
        'id': '',
        'date': '',
        'author_name': name,
        'author_avatar': avatar,
        'content': content,
        'liked': false,
        'sub_comment_count': 0
      }
      if (!Array.isArray(this.annotations[idx].comments)) {
        this.annotations[idx].comments = []
      }
      this.annotations[idx].comments.push(comment)
      this.annotations[idx].comment_count += 1
      annotationComment(this.annotations[idx].id, {comment: content}).then(res => {
        const resData = res.data
        const l = this.annotations[idx].comment.length - 1
        this.annotations[idx].comments[l].id = resData.id
        this.annotations[idx].comments[l].date = resData.date
      })
    },
    annotationSubComment (params) {
      const name = localStorage.getItem('username')
      const avatar = localStorage.getItem('avatar')
      let annotationIdx = params.annotation_idx
      let commentIdx = params.comment_idx
      let content = params.content
      const comment = {
        'id': '',
        'date': '',
        'author_name': name,
        'author_avatar': avatar,
        'content': content,
        'liked': false
      }
      if (!Array.isArray(this.annotations[annotationIdx].comments[commentIdx].sub_comments)) {
        this.annotations[annotationIdx].comments[commentIdx].sub_comments = []
      }
      this.annotations[annotationIdx].comments[commentIdx].sub_comment_count += 1
      this.annotations[annotationIdx].comments[commentIdx].sub_comments.push(comment)
      console.log(this.annotations)
      annotationSubComment(this.annotations[annotationIdx].id, this.annotations[annotationIdx].comments[commentIdx].id, {comment: content})
        .then(res => {
          const resData = res.data
          const l = this.annotations[annotationIdx].comments[commentIdx].sub_comments.length - 1
          this.annotations[annotationIdx].comments[commentIdx].sub_comments[l].id = resData.id
          this.annotations[annotationIdx].comments[commentIdx].sub_comments[l].date = resData.date
        })
    }
    // commentToggleLike (params) {
    //   const annotationIdx = params.annotation_idx
    //   const commentIdx = params.comment_idx
    //   this.annotations[annotationIdx].comments[commentIdx].liked = !this.annotations[annotationIdx].comments[commentIdx].liked
    //   console.log(this.annotations[annotationIdx].comments[commentIdx].liked)
    //   const commentID = this.annotations[annotationIdx].comments[commentIdx].id
    //   annotationCommentLike(commentID, 1)
    // }
  }
}
</script>

<style scoped>

</style>
