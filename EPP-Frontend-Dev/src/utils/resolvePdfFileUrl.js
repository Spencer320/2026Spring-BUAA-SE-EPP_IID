/**
 * 将后端返回的 local_url 转为 PDF.js 可加载的绝对地址。
 * 开发环境使用与页面同源 + webpack 代理 /resource，避免跨域导致 PDF 空白。
 */
export function resolvePdfFileUrl (localUrl, baseUrl) {
  if (!localUrl) return ''
  if (/^https?:\/\//i.test(localUrl)) return localUrl
  const path = localUrl.startsWith('/') ? localUrl : '/' + localUrl
  if (process.env.NODE_ENV === 'development') {
    if (typeof window !== 'undefined' && window.location && window.location.origin) {
      return window.location.origin + path
    }
  }
  return (baseUrl || '') + path
}
