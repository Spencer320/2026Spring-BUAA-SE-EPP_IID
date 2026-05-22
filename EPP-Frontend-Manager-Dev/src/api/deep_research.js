import request from '@/utils/request.js'

const PREFIX = '/api/research-agent/manage/deep-research'

export const getDRStats = () => request({ method: 'get', url: `${PREFIX}/stats/` })

export const getDRTaskList = (params) => request({ method: 'get', url: `${PREFIX}/tasks/`, params })

export const getDRTaskDetail = (taskId) => request({ method: 'get', url: `${PREFIX}/tasks/${taskId}/detail/` })

export const cancelDRTask = (taskId) => request({ method: 'post', url: `${PREFIX}/tasks/${taskId}/cancel/` })
