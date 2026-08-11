import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api',
  timeout: 300000  // 视频处理可能需要较长时间
})

// 响应拦截：统一错误处理
request.interceptors.response.use(
  res => res,
  err => {
    const status = err.response?.status
    const msg = err.response?.data?.detail || err.message

    if (status === 403) {
      ElMessage.error('权限不足')
    } else if (status === 429) {
      ElMessage.warning('操作太频繁，请稍后再试')
    } else {
      ElMessage.error(msg || '请求失败')
    }
    return Promise.reject(err)
  }
)

export default request
