import request from '@/utils/request.js'

const MANAGE_PREFIX = '/api/research-agent/manage'

/** 科研助手（basic / workspace）行为审计 */
export const getAssistantBehaviorLogs = (params) =>
    request({
        method: 'get',
        url: `${MANAGE_PREFIX}/assistant/behavior-logs/`,
        params
    })

export const getAssistantTaskBehaviorChain = (taskId) =>
    request({
        method: 'get',
        url: `${MANAGE_PREFIX}/assistant/tasks/${taskId}/behavior-chain/`
    })

export const exportAssistantBehaviorLogs = (data) =>
    request({
        method: 'post',
        url: `${MANAGE_PREFIX}/assistant/behavior-logs/export/`,
        data
    })

/** 深度研究（AgentTask）行为审计 */
export const getDeepResearchBehaviorLogs = (params) =>
    request({
        method: 'get',
        url: `${MANAGE_PREFIX}/deep-research/behavior-logs/`,
        params
    })

export const getDeepResearchTaskBehaviorChain = (taskId) =>
    request({
        method: 'get',
        url: `${MANAGE_PREFIX}/deep-research/tasks/${taskId}/behavior-chain/`
    })

export const exportDeepResearchBehaviorLogs = (data) =>
    request({
        method: 'post',
        url: `${MANAGE_PREFIX}/deep-research/behavior-logs/export/`,
        data
    })

