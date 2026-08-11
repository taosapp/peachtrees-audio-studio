<template>
  <div class="tasks-page">
    <!-- 任务统计 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="8" v-for="s in statCards" :key="s.label">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" :style="{ background: s.bg }">
              <span class="stat-dot" :style="{ background: s.color }"></span>
            </div>
            <div>
              <div class="stat-value" :style="{ color: s.color }">{{ s.value }}</div>
              <div class="stat-label">{{ s.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 任务列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="list-header">
          <span class="card-title">合成任务记录</span>
          <div class="header-actions">
            <el-select v-model="statusFilter" placeholder="全部状态" clearable size="small" style="width: 130px" @change="loadTasks(1)">
              <el-option label="排队中" value="pending" />
              <el-option label="处理中" value="processing" />
              <el-option label="已完成" value="done" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-button size="small" :icon="Refresh" @click="loadTasks(page)">刷新</el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="!loading && !tasks.length" description="暂无合成任务记录" :image-size="80" />

      <el-table v-else v-loading="loading" :data="tasks" size="default" style="width: 100%">
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column prop="voice_name" label="音色" width="120">
          <template #default="{ row }">
            <span v-if="row.voice_name">🎙️ {{ row.voice_name }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="gen_text" label="合成文本" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'error-text': row.status === 'failed' }">{{ row.message || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'done'"
              link
              type="success"
              size="small"
              :loading="downloadingId === row.task_id"
              @click="downloadResult(row)"
            >
              <el-icon><Download /></el-icon> 下载
            </el-button>
            <el-button
              v-else-if="row.status === 'pending' || row.status === 'processing'"
              link
              type="warning"
              size="small"
              @click="pollOne(row)"
            >
              <el-icon><Refresh /></el-icon> 查询
            </el-button>
            <el-button link type="danger" size="small" @click="removeTask(row)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row" v-if="total > pageSize">
        <el-pagination
          layout="prev, pager, next, total"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="loadTasks"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh, Delete } from '@element-plus/icons-vue'
import { ttsAPI } from '@/api/tts'

const tasks = ref([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = 10
const statusFilter = ref('')
const downloadingId = ref('')

const statCards = computed(() => {
  const counts = { done: 0, pending: 0, processing: 0, failed: 0 }
  tasks.value.forEach(t => { if (counts[t.status] !== undefined) counts[t.status]++ })
  return [
    { label: '已完成', value: counts.done, color: '#67c23a', bg: '#f0f9eb' },
    { label: '进行中', value: counts.pending + counts.processing, color: '#e6a23c', bg: '#fdf6ec' },
    { label: '失败', value: counts.failed, color: '#f56c6c', bg: '#fef0f0' },
  ]
})

function statusLabel(s) {
  return { pending: '排队中', processing: '处理中', done: '完成', failed: '失败' }[s] || s
}
function statusTagType(s) {
  return { pending: 'info', processing: 'warning', done: 'success', failed: 'danger' }[s] || ''
}

async function loadTasks(p = 1) {
  loading.value = true
  page.value = p
  try {
    const params = { page: p, page_size: pageSize, task_type: 'tts' }
    if (statusFilter.value) params.status = statusFilter.value
    // 后端列表接口暂不支持 status 过滤时按 keyword 兼容；此处仅传 task_type
    delete params.status
    const res = await ttsAPI.getHistory(params)
    tasks.value = res.data.items || []
    total.value = res.data.total || 0
  } catch {
    ElMessage.error('任务列表加载失败')
  } finally {
    loading.value = false
  }
}

async function pollOne(row) {
  try {
    const res = await ttsAPI.getTaskStatus(row.task_id)
    if (res.data.status === 'done' || res.data.status === 'failed') {
      ElMessage.success(res.data.status === 'done' ? '任务已完成' : '任务已失败')
      loadTasks(page.value)
    } else {
      ElMessage.info(`仍在${statusLabel(res.data.status)}`)
    }
  } catch {
    ElMessage.error('查询失败')
  }
}

async function downloadResult(row) {
  downloadingId.value = row.task_id
  try {
    // 详情接口返回 result_filename
    const detail = await ttsAPI.getTaskStatus(row.task_id)
    const filename = detail.data.result_filename
    if (!filename) {
      ElMessage.error('音频文件不存在')
      return
    }
    const blobRes = await ttsAPI.downloadAudio(filename)
    const blob = new Blob([blobRes.data], { type: 'audio/wav' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${row.voice_name || 'tts'}_${Date.now()}.wav`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('下载失败：' + (e.response?.data?.detail || e.message))
  } finally {
    downloadingId.value = ''
  }
}

async function removeTask(row) {
  try {
    await ElMessageBox.confirm(`确定删除任务「${row.filename || row.task_id.slice(0, 8)}」的记录？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await ttsAPI.deleteTask(row.task_id)
    ElMessage.success('已删除')
    loadTasks(page.value)
  } catch {
    ElMessage.error('删除失败')
  }
}

onMounted(() => loadTasks(1))
</script>

<style scoped>
.tasks-page { max-width: 1200px; }
.stats-row { margin-bottom: 20px; }
.stat-card { border-radius: 10px; }
.stat-content { display: flex; align-items: center; gap: 14px; }
.stat-icon {
  width: 44px; height: 44px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
}
.stat-dot { width: 16px; height: 16px; border-radius: 50%; display: inline-block; }
.stat-value { font-size: 22px; font-weight: 700; }
.stat-label { font-size: 13px; color: #909399; margin-top: 2px; }

.list-header { display: flex; align-items: center; justify-content: space-between; }
.card-title { font-weight: 600; }
.header-actions { display: flex; gap: 8px; }
.muted { color: #c0c4cc; }
.error-text { color: #f56c6c; }
.pagination-row { margin-top: 16px; display: flex; justify-content: flex-end; }
</style>
