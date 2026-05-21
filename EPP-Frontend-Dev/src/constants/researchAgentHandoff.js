/** 科研助手 → 深度研究：携带展示区已选文献 */
export const DEEP_RESEARCH_HANDOFF_KEY = 'ra_deep_research_handoff'

export function saveDeepResearchHandoff (selectedPaperIds) {
  try {
    sessionStorage.setItem(
      DEEP_RESEARCH_HANDOFF_KEY,
      JSON.stringify({
        selectedPaperIds: Array.isArray(selectedPaperIds) ? selectedPaperIds : [],
        ts: Date.now()
      })
    )
  } catch (e) {
    /* ignore */
  }
}

export function consumeDeepResearchHandoff () {
  try {
    const raw = sessionStorage.getItem(DEEP_RESEARCH_HANDOFF_KEY)
    if (!raw) return null
    sessionStorage.removeItem(DEEP_RESEARCH_HANDOFF_KEY)
    const data = JSON.parse(raw)
    return Array.isArray(data.selectedPaperIds) ? data.selectedPaperIds : []
  } catch (e) {
    return null
  }
}
