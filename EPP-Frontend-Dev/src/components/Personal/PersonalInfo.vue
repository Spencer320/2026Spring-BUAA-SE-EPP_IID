<template>
  <div class="profile">
    <el-card class="user-info">
      <el-card class="inside-card">
        <button class="avatar-button" @click="showAvatarUpload">
          <img class="avatar" :src="path" alt="User Avatar">
        </button>
        <div class="text-container">
          <p>{{ greeting }} ，{{ username }}！</p>
        </div>
      </el-card>
    </el-card>
    <el-card class="other-info">
      <div class="other-text">
        <el-statistic title="注册时间">
          <template slot="formatter">
            <i
              class="el-icon-stopwatch"
            ></i>
            {{ loginTime }}
          </template>
        </el-statistic>
        <el-statistic title="收藏数">
          <template slot="formatter">
            <i
              class="el-icon-star-off"
            ></i>
            {{ favorites }}
          </template>
        </el-statistic>
        <el-statistic title="点赞数">
          <template slot="formatter">
            <i
              class="el-icon-goods"
            ></i>
            {{ likes }}
          </template>
        </el-statistic>
      </div>
    </el-card>
    <el-dialog
      title="上传头像"
      :visible.sync="avatarUploadVisible"
      width="20%">
      <el-upload
        class="avatar-uploader"
        :action="this.$BASE_API_URL + '/userInfo/avatar'"
        name="avatar"
        with-credentials="true"
        :show-file-list="false"
        :on-success="handleAvatarSuccess"
        :before-upload="beforeAvatarUpload">
        <i v-if="!imgUrl" class="el-icon-plus avatar-uploader-icon"></i>
      </el-upload>
    </el-dialog>
  </div>
</template>

<script>
import { fetchUserInfo } from '@/request/userRequest.js'
import { EventBus } from '../../utils/eventBus'
export default {
  data () {
    return {
      path: '/resource/uploads/users/avatars/20240517092510_23.jpg',
      username: '',
      loginTime: '',
      favorites: 0,
      likes: 0,
      greeting: '你好',
      avatarUploadVisible: false,
      imageUrl: ''
    }
  },
  methods: {
    async getUserInfo () {
      try {
        const loading = this.$loading({
          lock: true,
          spinner: 'el-icon-loading',
          background: 'rgba(255, 255, 255, 0.7)',
          target: '.other-info'
        })
        var res = (await fetchUserInfo()).data
        this.path = this.$BASE_URL + res.avatar
        this.username = res.username
        this.loginTime = res.registration_date
        this.favorites = res.collected_papers_cnt
        this.likes = res.liked_papers_cnt
        loading.close()
      } catch (error) {
        console.log(error)
        console.log('getUserInfoError')
      }
    },
    showAvatarUpload () {
      this.avatarUploadVisible = true
    },
    handleAvatarSuccess (res, file) {
      this.path = this.$BASE_URL + res.avatar
      this.imageUrl = this.path
      this.$message({
        message: '头像上传成功！',
        type: 'success'
      })
      localStorage.setItem('avatar', this.path)
      this.avatarUploadVisible = false
      EventBus.$emit('updateAvatar', this.path)
    },
    beforeAvatarUpload (file) {
      const isPhoto = file.type === 'image/jpeg' || file.type === 'image/png' || file.type === 'image/jpg'
      const isLt2M = file.size / 1024 / 1024 < 2

      if (!isPhoto) {
        this.$message.error('上传头像图片只能是 JPG 格式!')
      }
      if (!isLt2M) {
        this.$message.error('上传头像图片大小不能超过 2MB!')
      }
      return isPhoto && isLt2M
    }
  },
  mounted () {
    if (localStorage.getItem('username')) {
      this.username = localStorage.getItem('username')
      this.path = localStorage.getItem('avatar')
      if (localStorage.getItem('loginTime')) {
        this.loginTime = localStorage.getItem('loginTime')
      } else {
        this.getUserInfo()
      }
      if (localStorage.getItem('favorites')) {
        this.favorites = localStorage.getItem('favorites')
      } else {
        this.getUserInfo()
      }
      if (localStorage.getItem('likes')) {
        this.likes = localStorage.getItem('likes')
      } else {
        this.getUserInfo()
      }
    } else {
      this.getUserInfo()
    }
    // 设置问候语
    const hour = new Date().getHours()
    if (hour >= 5 && hour < 12) {
      this.greeting = '🌞早上好'
    } else if (hour >= 12 && hour < 18) {
      this.greeting = '🌻下午好'
    } else if (hour >= 18 && hour < 24) {
      this.greeting = '⭐晚上好'
    } else {
      this.greeting = '🌃夜深了'
    }
  }
}
</script>

<style scoped>
.profile {
  display: flex;
  position: absolute;
  flex-direction: column;
  align-items: center;
}

.user-info {
  margin-left: 10px;
  height: 480px;
  width: 980px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 20px;
  border-radius: 12px;
  background-image: url('../../assets/library.jpg');
  background-size: cover;
  background-repeat: no-repeat;
  background-position: center;
}

.avatar-button {
  background-color: transparent;
  border: none;
  cursor: pointer;
}
.avatar {
  width: 100px; /* 设置头像的宽度 */
  height: 100px; /* 设置头像的高度 */
  border-radius: 50%; /* 设置头像为圆形 */
  margin-top: 100px; /* 设置头像与下方元素的间距 */
  margin-bottom: 5px;
  object-fit: cover;
}
.user-info p {
  margin: 5px 0;
  font-size: 18px;
}

.user-info p:first-child {
  font-size: 20px;
  font-weight: bold;
}

.text-container {
  text-align: center;
}

.inside-card {
  background-color: rgba(246, 247, 248, 0.65);
  border-radius: 12px;
  border: 0cap;
  bottom: 50%;
  width: 300px;
  height: 300px;
  transform: translateY(-50%);
  padding: 10px;
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); /* 添加阴影效果，提升层次感 */
}

.other-info {
  display: flex;
  justify-content: space-around;
  background-color: rgba(246, 247, 248, 0.65);
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
  border: 0cap;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); /* 添加阴影效果，提升层次感 */
  margin-left: 10px;
  height: 160px;
  width: 900px;
  padding: 20px;
  border-radius: 12px;
  transform: translateY(-50%);
  transition: box-shadow 0.3s, transform 0.3s;
}
@keyframes bounce {
      0%, 100% {
        transform: translateY(-50%);
      }
      50% {
        transform: translateY(-60%);
      }
    }
.other-info:hover {
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
  /* 实现一个回弹效果 */
  animation: bounce 0.5s ease;
  position: relative;
  z-index: 1;
}
.other-text {
  display: flex;
  justify-content: space-around;
  width: 800px;
}
.avatar-uploader {
    border: 1px dashed #d9d9d9;
    border-radius: 6px;
    cursor: pointer;
    position: relative;
    overflow: hidden;
}
.avatar-uploader:hover {
    border-color: #409EFF;
}
.avatar-uploader-icon {
  font-size: 40px;
  color: #8c939d;
  width: 178px;
  height: 178px;
  line-height: 178px;
  text-align: center;
}
::v-deep(.el-dialog) {
  border-radius: 12px;
  opacity: 0.9;
}
</style>
