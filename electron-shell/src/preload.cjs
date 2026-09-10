/**
 * PeachTrees Media Studio - Electron 预加载脚本
 *
 * 暴露安全的 IPC 接口给渲染进程，避免启用 nodeIntegration
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('peachtrees', {
  // 获取应用版本
  getVersion: () => ipcRenderer.invoke('get-version'),

  // 打开外部链接（系统浏览器）
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // 获取后端地址
  getBackendUrl: () => 'http://127.0.0.1:8000',

  // 获取 API 文档地址
  getApiDocsUrl: () => 'http://127.0.0.1:8000/docs',
});
