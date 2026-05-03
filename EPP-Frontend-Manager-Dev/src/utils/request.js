import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import store from '@/store'

const serverURL = import.meta.env.VITE_API_BASE_URL

const instance = axios.create({ baseURL: serverURL })
instance.defaults.withCredentials = true
let isHandlingTokenExpired = false

const extractErrorText = (error) => {
    return [error?.response?.data?.message, error?.response?.data?.error, error?.response?.data?.detail, error?.message]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
}

const decodeJwtPayload = (token) => {
    try {
        const parts = (token || '').split('.')
        if (parts.length < 2) return {}
        const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
        const padLen = payload.length % 4
        const normalized = payload + (padLen ? '='.repeat(4 - padLen) : '')
        return JSON.parse(atob(normalized))
    } catch {
        return {}
    }
}

const applyResearchAgentAdminHeaders = (config, token) => {
    const url = String(config?.url || '')
    if (!url.includes('/api/research-agent/manage/')) return

    const payload = decodeJwtPayload(token)
    const adminId = String(payload?.admin_id || '').trim()
    const managerName = String(store.state?.managerInfo?.managerName || '').trim()
    const researchUserId = adminId ? `admin-${adminId}` : managerName || 'manager'

    config.headers['X-Research-Role'] = 'admin'
    config.headers['X-Research-User-Id'] = researchUserId
}

// ✅ 请求拦截器：添加 token 到请求头
instance.interceptors.request.use(
    (config) => {
        config.headers['Content-Type'] = 'application/json;charset=utf-8'

        const token = localStorage.getItem('token')
        if (token) {
            config.headers.Authorization = token // 以 Authorization 方式发送 token
            applyResearchAgentAdminHeaders(config, token)
        }
        return config
    },
    (error) => {
        return Promise.reject(error)
    }
)

instance.interceptors.response.use(
    (response) => response,
    (error) => {
        const status = error?.response?.status
        const errorText = extractErrorText(error)
        const isTokenExpired =
            (status === 401 && errorText.includes('token') && errorText.includes('expired')) ||
            errorText.includes('token expired')

        if (isTokenExpired) {
            error.__handledTokenExpired = true

            if (!isHandlingTokenExpired) {
                isHandlingTokenExpired = true
                store.commit('setToken', '')
                store.commit('resetManagerInfo')
                ElMessage.warning('登录已过期，请重新登录')

                const currentPath = router.currentRoute?.value?.path
                const redirectPromise = currentPath !== '/login' ? router.replace('/login') : Promise.resolve()

                Promise.resolve(redirectPromise).finally(() => {
                    isHandlingTokenExpired = false
                })
            }
        }

        return Promise.reject(error)
    }
)

export default instance
export { serverURL }
