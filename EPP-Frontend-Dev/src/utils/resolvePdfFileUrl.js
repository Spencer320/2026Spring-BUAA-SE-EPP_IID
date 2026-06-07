/**
 * 将后端返回的 local_url 转为 PDF.js 可加载的绝对地址。
 * 优先使用当前页面同源，避免线上域名/HTTPS 入口和构建时 baseUrl 不一致导致 PDF.js 空白。
 */
export function resolvePdfFileUrl (localUrl, baseUrl) {
  if (!localUrl) return ''
  if (/^https?:\/\//i.test(localUrl)) return localUrl
  const path = localUrl.startsWith('/') ? localUrl : '/' + localUrl
  if (typeof window !== 'undefined' && window.location && window.location.origin) {
    return window.location.origin + path
  }
  return (baseUrl || '') + path
}
