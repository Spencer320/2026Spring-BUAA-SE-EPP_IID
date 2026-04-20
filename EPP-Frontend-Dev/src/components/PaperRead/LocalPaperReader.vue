<template>
    <el-row style="overflow: hidden; height: 100vh;">
      <el-col :span="16" style="margin-top: 60px;">
        <iframe v-if="pdfUrl" :src="pdfUrl" style="width: 100%; height: calc(100vh - 60px);" frameborder="0">
        </iframe>
      </el-col>
      <el-col :span="8" style="margin-top: 60px">
        <read-assistant :paperID="paper_id" :fileReadingId="fileReadingID" />
      </el-col>
    </el-row>
</template>

<script>
import request from '@/request/request'
import { resolvePdfFileUrl } from '@/utils/resolvePdfFileUrl'
import ReadAssistant from './LocalReadAssistant.vue'
export default {
  components: {
    'read-assistant': ReadAssistant
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
      fileReadingID: ''
    }
  },
  created () {
    this.fetchPaperPDF()
    this.fileReadingID = this.$route.query.fileReadingID
  },
  methods: {
    fetchPaperPDF () {
      request.get('/getDocumentURL?document_id=' + this.paper_id)
        .then((response) => {
          const fileUrl = resolvePdfFileUrl(response.data.local_url, this.$BASE_URL)
          this.pdfUrl = '/static/web/viewer.html?file=' + encodeURIComponent(fileUrl)
          //   this.pdfUrl = '../../../static/Res3ATN -- Deep 3D Residual Attention Network for Hand Gesture  Recognition in Videos.pdf'
          console.log('论文PDF为', this.pdfUrl)
        })
        .catch((error) => {
          console.log('请求论文PDF失败 ', error)
        })
    }
  }

}
</script>

<style scoped>

</style>
