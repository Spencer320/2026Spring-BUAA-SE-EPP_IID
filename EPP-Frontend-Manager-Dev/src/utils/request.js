import axios from 'axios'
// import { ElMessage } from 'element-plus'

const serverURL = import.meta.env.VITE_API_BASE_URL

const instance = axios.create({ baseURL: serverURL })
instance.defaults.withCredentials = true

// ✅ 请求拦截器：添加 token 到请求头
instance.interceptors.request.use(
    (config) => {
        config.headers['Content-Type'] = 'application/json;charset=utf-8'

        const token = localStorage.getItem('token')
        if (token) {
            config.headers.Authorization = token // 以 Authorization 方式发送 token
        }
        return config
    },
    (error) => {
        return Promise.reject(error)
    }
)

export default instance
export { serverURL }
