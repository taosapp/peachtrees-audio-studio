import request from './request'

export const ttsAPI = {
  // 获取音色列表
  getVoices: () => request.get('/v1/tts/voices'),

  // 上传参考音频，保存音色
  saveVoice: (formData, onProgress) => request.post('/v1/tts/voices', formData, {
    onUploadProgress: e => onProgress && onProgress(Math.round(e.loaded / e.total * 100))
  }),

  // 删除音色
  deleteVoice: (voiceName) => request.delete(`/v1/tts/voices/${encodeURIComponent(voiceName)}`),

  /**
   * 提交TTS异步合成任务（新接口，推荐使用）
   * @param {FormData} formData - voice_name, gen_text, speed, nfe_steps, cfg_strength, remove_silence
   * @returns { task_id, task_type, message, queue_position, total_pending }
   */
  submitTask: (formData) => request.post('/v1/tts/submit', formData),

  /**
   * 旧同步合成（兼容保留）
   */
  synthesizeByVoice: (formData) => request.post('/v1/tts/synthesize/by_voice', formData),

  // 获取音色参考音频（用于试听）
  getVoiceAudio: (voiceName) => request.get(`/v1/tts/voices/${encodeURIComponent(voiceName)}/audio`, {
    responseType: 'blob'
  }),

  // 下载合成音频
  downloadAudio: (filename) => request.get(`/v1/tts/download/${encodeURIComponent(filename)}`, {
    responseType: 'blob'
  }),

  // 查询任务状态
  getTaskStatus: (taskId) => request.get(`/v1/tasks/${taskId}`),

  // 获取历史记录（按类型）
  getHistory: (params) => request.get('/v1/tasks', { params }),

  // 删除任务记录
  deleteTask: (taskId) => request.delete(`/v1/tasks/${taskId}`),
}
