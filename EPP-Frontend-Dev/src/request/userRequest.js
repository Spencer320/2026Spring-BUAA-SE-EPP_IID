// api.js
import Vue from 'vue'
import axios from 'axios'
import router from '../router'
import request from './request'
import message from 'element-ui'
// import { cat } from 'shelljs'
axios.defaults.withCredentials = true

Vue.prototype.$axios = axios

// 初始化阶段，不可以读取 Vue.prototype.***
const baseURL = process.env.NODE_ENV === 'development' ? '/api' : process.env.VUE_APP_API_ROOT

const api = axios.create({
  baseURL,
  timeout: 5000 // 设置超时时间
})

api.interceptors.response.use(
  response => {
    let res = response
    return res
  },
  error => {
    // 对于登录接口，直接返回错误
    const skipUrls = ['login', 'sign', 'logout']
    if (error.response.config.url && skipUrls.some(url => error.response.config.url.includes(url))) {
      return Promise.reject(error)
    }
    if (error.response && error.response.status === 400) {
      return api.get('/testLogin').then(testLoginResponse => {
        return Promise.reject(error)
      }).catch(testLoginError => {
        if (testLoginError.response.status === 403) {
          document.cookie = 'userlogin=; expires=Thu, 01 Jan 1970 00:00:00 UTC'
          router.push('/dashboard')
          message.Message({
            type: 'error',
            message: '未登录或登录过期，请重新登录！'
          })
        }
        return Promise.reject(error)
      })
    }
    return Promise.reject(error)
  }
)

export const login = async (params) => {
  try {
    console.log(params)
    const response = await api.post('login', params)
    console.log(response)
    localStorage.clear() // 清除所有缓存
    localStorage.setItem('jwt-token', response.data.token)
    var expiredTime = response.data.expired_time
    if (expiredTime) {
      expiredTime = 'expires=' + new Date(expiredTime).toUTCString()
      document.cookie = 'userlogin=' + response.data.username + '; ' + expiredTime
    }
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const logout = async () => {
  try {
    const response = api.get('logout')
    document.cookie = 'userlogin=; expires=Thu, 01 Jan 1970 00:00:00 UTC'
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const register = async (params) => {
  try {
    console.log(params)
    const response = api.post('sign', params)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
    // throw new Error(error.response.data.message)
  }
}

export const fetchCollectedPapers = async () => {
  console.log('fetchCollectPapers')
  return request.get('userInfo/collectedPapers')
    .then(response => {
      console.log(response)
      return response
    })
    .catch(error => {
      throw new Error(error.response.data.message)
    })
}

export const deleteCollectedPapers = async (data) => {
  try {
    console.log('deleteCollectPapers')
    const response = request.delete('userInfo/delCollectedPapers', data)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const deleteReport = async (data) => {
  try {
    console.log('deleteReport')
    const response = request.delete('userInfo/delSummaryReports', data)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const fetchTranslations = async () => {
  try {
    console.log('fetchTranslations')
    const response = await request.get('userInfo/translations')
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const deleteTranslation = async (translationId) => {
  try {
    console.log('deleteTranslation')
    const response = await request.delete(`userInfo/translation/${translationId}`)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(
      (error.response && error.response.data && error.response.data.message) || '删除失败'
    )
  }
}

export const fetchSearchHistory = async () => {
  try {
    console.log('fetchSearchHistory')
    const response = request.get('userInfo/searchHistory')
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const deleteSearchHistory = async (params) => {
  try {
    console.log('deleteReport')
    const response = request.delete('userInfo/delSearchHistory', params)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const fetchReports = async () => {
  try {
    console.log('fetchReports')
    const response = request.get('userInfo/summaryReports')
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const fetchUserInfo = async () => {
  try {
    console.log('fetchInfo')
    const response = await request.get('userInfo/userInfo')
    console.log(response)
    localStorage.setItem('username', response.data.username)
    localStorage.setItem('avatar', Vue.prototype.$BASE_URL + response.data.avatar)
    localStorage.setItem('loginTime', response.data.registration_date)
    localStorage.setItem('favorites', response.data.collected_papers_cnt)
    localStorage.setItem('likes', response.data.liked_papers_cnt)
    return response
  } catch (error) {
    console.log(error)
    throw new Error(error.response.data.message)
  }
}
export const fetchChat = async () => {
  try {
    console.log('fetchChat')
    const response = request.get('userInfo/paperReading')
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const deleteChat = async (data) => {
  try {
    console.log('deleteChat')
    console.log(data)
    const response = request.delete('userInfo/delPaperReading', data)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const fetchDocument = async () => {
  try {
    console.log('fetchDocument')
    const response = request.get('userInfo/documents')
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const uploadDocument = async (formData) => {
  try {
    console.log('uploadDocument')
    console.log(formData)
    const response = await request.post('uploadPaper', formData)
    console.log(response)
    return response
  } catch (error) {
    const backendMsg =
      (error.response && error.response.data && (error.response.data.message || error.response.data.error)) ||
      error.message ||
      '上传失败'
    throw new Error(backendMsg)
  }
}
export const deleteDocument = async (params) => {
  try {
    console.log('deleteDocument')
    const response = request.post('removeUploadedPaper', params)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const fetchNotification = async (mode) => {
  try {
    console.log('fetchNotification')
    console.log(mode)
    const response = request.get('userInfo/notices', mode)
    console.log('response')
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const deleteNotification = async (data) => {
  try {
    console.log('deleteDocument')
    const response = request.delete('userInfo/delNotices', data)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const readNotification = async (data) => {
  try {
    console.log('readNotification')
    const response = request.post('userInfo/readNotices', data)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
export const fetchReportContent = async (params) => {
  try {
    console.log(params)
    console.log('fetchReportContent')
    const response = request.get('userInfo/getSummary', params)
    console.log(response)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const userVisitRecord = async () => {
  try {
    const response = await request.post('manage/recordVisit')
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const fetchAnnotations = async (paperID) => {
  try {
    const response = await request.get(`paper/annotations?paper_id=${paperID}`)
    return response.data
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const addAnnotation = async (paperID, params) => {
  try {
    const response = await request.put(`paper/annotation?paper_id=${paperID}`, params)
    return response.data
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const annotationLike = async (annotationID) => {
  try {
    const response = await request.post(`annotation/like/toggle?annotation_id=${annotationID}`)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const annotationCommentLike = async (commentID, commentLevel) => {
  try {
    const response = await request.post(`annotation/comments/like/toggle?comment_id=${commentID}&comment_level=${commentLevel}`)
    return response
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const annotationComment = async (annotationID, params) => {
  try {
    const response = await request.put(`annotation/comment?annotation_id=${annotationID}`, params)
    return response.data
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const annotationSubComment = async (annotationID, commentID, params) => {
  try {
    const response = await request.put(`annotation/comments/subcomment?annotation_id=${annotationID}&comment_id=${commentID}`, params)
    return response.data
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const fetchAnnotationComment = async (annotationID) => {
  try {
    const response = await request.get(`annotation/comments?annotation_id=${annotationID}`)
    return response.data
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}

export const fetchAnnotationSubComment = async (annotationID, commentID) => {
  try {
    const response = await request.get(`annotation/comment/subcomments?annotation_id=${annotationID}&comment_id=${commentID}`)
    return response.data
  } catch (error) {
    throw new Error(error.response.data.message)
  }
}
