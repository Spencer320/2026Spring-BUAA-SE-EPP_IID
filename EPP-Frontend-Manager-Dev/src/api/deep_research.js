import request from '@/utils/request.js'

// ── 统计概览 ──────────────────────────────────────────────────────────────────

export const getDRStats = () => request({ method: 'get', url: '/api/manage/deep-research/stats' })

// ── 任务列表 ──────────────────────────────────────────────────────────────────

export const getDRTaskList = (params) => request({ method: 'get', url: '/api/manage/deep-research/tasks', params })

// ── 任务详情与执行轨迹 ────────────────────────────────────────────────────────

export const getDRTaskDetail = (taskId) => request({ method: 'get', url: `/api/manage/deep-research/tasks/${taskId}` })

export const getDRTaskArchive = (taskId) =>
    request({ method: 'get', url: `/api/manage/deep-research/tasks/${taskId}/archive` })

export const getDRTaskTrace = (taskId) =>
    request({ method: 'get', url: `/api/manage/deep-research/tasks/${taskId}/trace` })

// ── 管理干预操作 ──────────────────────────────────────────────────────────────

export const forceStopTask = (taskId, data) =>
    request({ method: 'post', url: `/api/manage/deep-research/tasks/${taskId}/force-stop`, data })

export const suppressOutput = (taskId, data) =>
    request({ method: 'post', url: `/api/manage/deep-research/tasks/${taskId}/suppress-output`, data })

export const unsuppressOutput = (taskId, data) =>
    request({ method: 'post', url: `/api/manage/deep-research/tasks/${taskId}/unsuppress-output`, data })

// ── 审计日志 ──────────────────────────────────────────────────────────────────

export const getTaskAuditLogs = (taskId) =>
    request({ method: 'get', url: `/api/manage/deep-research/tasks/${taskId}/audit-logs` })

export const getGlobalAuditLogs = (params) =>
    request({ method: 'get', url: '/api/manage/deep-research/audit-logs', params })
