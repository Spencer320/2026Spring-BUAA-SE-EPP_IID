import request from '@/request/request.js'

const PREFIX = 'research-agent'

export function listSessions (params) {
  return request.get(`${PREFIX}/sessions/`, { params })
}

export function createSession (data) {
  return request.post(`${PREFIX}/sessions/`, data)
}

export function getSession (sessionId) {
  return request.get(`${PREFIX}/sessions/${sessionId}/`)
}

export function postMessage (sessionId, content) {
  return request.post(`${PREFIX}/sessions/${sessionId}/messages/`, { content })
}

export function getTask (taskId) {
  return request.get(`${PREFIX}/tasks/${taskId}/`)
}

export function postIntervention (taskId, body) {
  return request.post(`${PREFIX}/tasks/${taskId}/intervention/`, body)
}

export function postCancelTask (taskId) {
  return request.post(`${PREFIX}/tasks/${taskId}/cancel/`, {})
}
