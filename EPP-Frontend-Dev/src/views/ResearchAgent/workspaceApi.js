/**
 * 用户工作区 API 封装
 *
 * 对应后端 business/api/workspace.py 提供的接口：
 *   GET    /api/workspace/files[?path=<dir>]   列出目录内容
 *   POST   /api/workspace/files                上传文件（multipart）
 *   GET    /api/workspace/files/<rel_path>     下载文件（流式）
 *   DELETE /api/workspace/files/<rel_path>     删除文件或空目录
 *   POST   /api/workspace/mkdir                创建子目录
 */

import request from '@/request/request.js'

function encodeWorkspacePath (relPath = '') {
  return String(relPath)
    .split('/')
    .filter(Boolean)
    .map(seg => encodeURIComponent(seg))
    .join('/')
}

function backendMessage (body, fallback) {
  return (body && body.error && body.error.message) || fallback
}

async function extractErrorMessage (error, fallback) {
  const data = error && error.response && error.response.data
  if (data instanceof Blob) {
    const text = await data.text()
    if (text) {
      try {
        return backendMessage(JSON.parse(text), fallback)
      } catch (e) {
        return text
      }
    }
  }
  if (typeof data === 'string' && data) {
    try {
      return backendMessage(JSON.parse(data), fallback)
    } catch (e) {
      return data
    }
  }
  return backendMessage(data, (error && error.message) || fallback)
}

function raiseApiError (error, fallback) {
  return extractErrorMessage(error, fallback).then(message => {
    throw new Error(message)
  })
}

/** 列出工作区指定目录的内容，path 为空字符串时列出根目录 */
export function listWorkspaceFiles (path = '') {
  return request.get('workspace/files', { params: path ? { path } : {} })
    .then(resp => {
      const body = resp && resp.data
      if (body && body.ok) return body.data
      throw new Error(backendMessage(body, '列出目录失败'))
    })
    .catch(error => raiseApiError(error, '列出目录失败'))
}

/**
 * 下载文件到用户本机。
 * 以 blob 方式获取响应后创建临时链接触发浏览器"另存为"。
 *
 * @param {string} relPath - 相对于工作区根目录的文件路径（含斜杠）
 * @param {string} filename - 建议保存的文件名，不传时从路径末尾取
 */
export function downloadWorkspaceFile (relPath, filename) {
  return request.get(`workspace/files/${encodeWorkspacePath(relPath)}`, { responseType: 'blob' })
    .then(blob => {
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || relPath.split('/').pop() || 'download'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    })
    .catch(error => raiseApiError(error, '下载失败'))
}

/**
 * 上传一个或多个文件到工作区。
 *
 * @param {File[]} files  - 原生 File 对象数组
 * @param {string} path   - 目标子目录路径（默认为根目录）
 * @returns {Promise<{uploaded: Array}>}
 */
export function uploadWorkspaceFiles (files, path = '') {
  const form = new FormData()
  files.forEach(f => form.append('file', f))
  if (path) form.append('path', path)
  return request.post('workspace/files', form)
    .then(resp => {
      const body = resp && resp.data
      if (body && body.ok) return body.data
      throw new Error(backendMessage(body, '上传失败'))
    })
    .catch(error => raiseApiError(error, '上传失败'))
}

/**
 * 删除工作区内的文件或空目录。
 *
 * @param {string} relPath - 相对路径
 */
export function deleteWorkspacePath (relPath) {
  return request.delete(`workspace/files/${encodeWorkspacePath(relPath)}`)
    .then(resp => {
      const body = resp && resp.data
      if (body && body.ok) return body.data
      throw new Error(backendMessage(body, '删除失败'))
    })
    .catch(error => raiseApiError(error, '删除失败'))
}

/**
 * 在工作区内创建子目录（支持多级）。
 *
 * @param {string} path - 相对路径，如 "papers/2026"
 */
export function mkdirWorkspace (path) {
  return request.post('workspace/mkdir', { path })
    .then(resp => {
      const body = resp && resp.data
      if (body && body.ok) return body.data
      throw new Error(backendMessage(body, '创建目录失败'))
    })
    .catch(error => raiseApiError(error, '创建目录失败'))
}
