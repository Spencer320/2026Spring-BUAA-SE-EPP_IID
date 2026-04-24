import request from '@/utils/request.js'

const PREFIX = '/api/research-agent/manage'

export const getResearchAgentBehaviorLogs = (params) =>
    request({
        method: 'get',
        url: `${PREFIX}/behavior-logs/`,
        params
    })

export const getResearchAgentTaskBehaviorChain = (taskId) =>
    request({
        method: 'get',
        url: `${PREFIX}/tasks/${taskId}/behavior-chain/`
    })

export const exportResearchAgentBehaviorLogs = (data) =>
    request({
        method: 'post',
        url: `${PREFIX}/behavior-logs/export/`,
        data
    })
