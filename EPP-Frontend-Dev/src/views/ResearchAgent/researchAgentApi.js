import request from '@/request/request.js'

const LEGACY_PREFIX = 'research-agent'

function unwrap (resp) {
  const body = resp && resp.data
  if (body && body.ok === true && body.data !== undefined) {
    return { ...resp, data: body.data }
  }
  return resp
}

export function listSessions (params) {
  return request.get(`${LEGACY_PREFIX}/sessions/`, { params }).then(unwrap)
}

export function createSession (data) {
  return request.post(`${LEGACY_PREFIX}/sessions/`, data).then(unwrap)
}

export function createSessionWithFirstMessage (content, title = '新会话', options = {}) {
  return request.post(`${LEGACY_PREFIX}/sessions/messages/`, { content, title, ...options }).then(unwrap)
}

export function getSession (sessionId) {
  return request.get(`${LEGACY_PREFIX}/sessions/${sessionId}/`).then(unwrap)
}

export function deleteSession (sessionId) {
  return request.delete(`${LEGACY_PREFIX}/sessions/${sessionId}/`).then(unwrap)
}

export function batchDeleteSessions (sessionIds) {
  return request.post(`${LEGACY_PREFIX}/sessions/batch-delete/`, { session_ids: sessionIds }).then(unwrap)
}

export function updateSessionTitle (sessionId, title) {
  return request.patch(`${LEGACY_PREFIX}/sessions/${sessionId}/`, { title }).then(unwrap)
}

export function postMessage (sessionId, payload) {
  const body = typeof payload === 'string' ? { content: payload } : payload
  return request.post(`${LEGACY_PREFIX}/sessions/${sessionId}/messages/`, body).then(unwrap)
}

export function getTask (taskId) {
  return request.get(`${LEGACY_PREFIX}/tasks/${taskId}/status/`).then(unwrap)
}

export function postIntervention (taskId, body) {
  const decision = body && body.decision
  const action = decision === 'approve' ? 'allow' : (decision === 'reject' ? 'abort' : 'revise')
  const payload = { action }
  if (action === 'revise') payload.message = body && body.message ? body.message : ''
  return request.post(`${LEGACY_PREFIX}/tasks/${taskId}/actions/`, payload).then(unwrap)
}

export function postCancelTask (taskId) {
  return request.post(`${LEGACY_PREFIX}/tasks/${taskId}/cancel/`, {}).then(unwrap)
}

export function postFollowUp (taskId, payload) {
  return request.post(`${LEGACY_PREFIX}/tasks/${taskId}/follow-up/`, payload).then(unwrap)
}

export function downloadTaskReport (taskId) {
  return request.get(`${LEGACY_PREFIX}/tasks/${taskId}/download/`, { responseType: 'blob' })
}
