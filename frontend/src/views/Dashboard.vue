<template>
  <div class="dashboard">
    <!-- 欢迎横幅 -->
    <div class="welcome-banner">
      <div>
        <h2>你好👋</h2>
        <p>今天也是高效创作的一天！</p>
      </div>
      <div class="banner-actions">
        <el-button type="primary" size="large" @click="router.push('/clone')">
          <el-icon><User /></el-icon> 声音克隆
        </el-button>
      </div>
    </div>

    <!-- 数据概览 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="6" v-for="stat in stats" :key="stat.label">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" :style="{ background: stat.bg }">
              <el-icon :size="22" :style="{ color: stat.color }">
                <component :is="stat.icon" />
              </el-icon>
            </div>
            <div>
              <div class="stat-value">{{ stat.value }}</div>
              <div class="stat-label">{{ stat.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近任务 -->
    <el-row :gutter="20" class="bottom-row">
      <el-col :span="24">
        <el-card shadow="never" header="最近处理记录">
          <el-empty v-if="!recentTasks.length" description="暂无处理记录" :image-size="80" />
            <el-table v-else :data="recentTasks" size="small" style="width: 100%">
              <el-table-column prop="filename" label="文件名" min-width="160" show-overflow-tooltip />
              <el-table-column prop="voice_name" label="使用音色" width="120" align="center" />
              <el-table-column prop="status" label="状态" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="created_at" label="时间" width="140" />
              <el-table-column label="操作" width="80" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="router.push('/tasks')">详情</el-button>
                </template>
              </el-table-column>
            </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ttsAPI } from '@/api/tts'

const router = useRouter()
const recentTasks = ref([])

const stats = computed(() => [
  { label: '累计克隆合成', value: totalProcessed.value + ' 次', icon: 'Microphone', bg: '#f0f0ff', color: '#6366f1' },
])

const totalProcessed = ref(0)

function statusLabel(s) { return { pending: '排队中', processing: '处理中', done: '完成', failed: '失败' }[s] || s }
function statusTagType(s) { return { pending: 'info', processing: 'warning', done: 'success', failed: 'danger' }[s] || '' }

onMounted(async () => {
  try {
    const res = await ttsAPI.getHistory({ page: 1, page_size: 5, task_type: 'tts' })
    recentTasks.value = res.data.items || []
    totalProcessed.value = res.data.total || 0
  } catch {}
})
</script>

<style scoped>
.dashboard { max-width: 1200px; }

.welcome-banner {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 28px 32px;
  color: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  gap: 16px;
}

.banner-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.welcome-banner h2 { font-size: 22px; margin-bottom: 6px; }
.welcome-banner p { opacity: 0.85; }

.stats-row { margin-bottom: 24px; }
.stat-card { border-radius: 10px; }
.stat-content { display: flex; align-items: center; gap: 16px; }
.stat-icon { width: 48px; height: 48px; border-radius: 10px; display: flex; align-items: center; justify-content: center; }
.stat-value { font-size: 22px; font-weight: 700; color: #303133; }
.stat-label { font-size: 13px; color: #909399; margin-top: 2px; }

.bottom-row {}
</style>
