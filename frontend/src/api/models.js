import request from './request'

export const modelsAPI = {
  // 获取所有模型状态
  getStatus: () => request.get('/v1/models/status'),
  
  // 获取当前任务运行状态
  getTaskStatus: () => request.get('/v1/models/task-status'),
}