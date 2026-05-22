import request from '@/utils/request.js'

const PREFIX = '/api/research-agent/manage/assistant'

export const getAssistantStats = () => request({ method: 'get', url: `${PREFIX}/stats/` })

export const getAssistantTaskList = (params) => request({ method: 'get', url: `${PREFIX}/tasks/`, params })

export const getAssistantTaskDetail = (taskId) => request({ method: 'get', url: `${PREFIX}/tasks/${taskId}/detail/` })

export const cancelAssistantTask = (taskId) => request({ method: 'post', url: `${PREFIX}/tasks/${taskId}/cancel/` })
