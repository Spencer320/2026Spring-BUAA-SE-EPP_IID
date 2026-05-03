import request from './request'

/**
 * 开始深度研究
 * @param {Object} data - 包含summary_report_id和research_requirement
 * @returns {Promise} - 请求Promise
 */
export function startDeepResearch (data) {
  return request({
    url: '/deep_research/start',
    method: 'post',
    data: data
  })
}

/**
 * 获取深度研究状态
 * @param {Object} params - 包含record_id
 * @returns {Promise} - 请求Promise
 */
export function getDeepResearchStatus (params) {
  return request({
    url: '/deep_research/status',
    method: 'get',
    params: params
  })
}

/**
 * 继续深度研究（追问）
 * @param {Object} data - 包含record_id和question
 * @returns {Promise} - 请求Promise
 */
export function continueDeepResearch (data) {
  return request({
    url: '/deep_research/continue',
    method: 'post',
    data: data
  })
}

/**
 * 重新生成局部内容
 * @param {Object} params - 包含record_id和section
 * @returns {Promise} - 请求Promise
 */
export function generateLocalSection (params) {
  return request({
    url: '/deep_research/local_section',
    method: 'get',
    params: params
  })
}

/**
 * 获取推荐问题
 * @param {Object} params - 包含record_id
 * @returns {Promise} - 请求Promise
 */
export function getRecommendedQuestions (params) {
  return request({
    url: '/deep_research/recommended_questions',
    method: 'get',
    params: params
  })
}
