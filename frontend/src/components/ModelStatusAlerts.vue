<template>
    <div>
        <!-- 模型状态提示 -->
        <el-alert
            v-if="ttsModelStatus"
            :type="ttsModelStatus.loaded ? 'success' : 'warning'"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
        >
            <template #title>
                <span>语音合成 (TTS): {{ ttsModelStatus.name }}</span>
                <span style="margin-left: 8px">{{ ttsModelStatus.message }}</span>
            </template>
        </el-alert>

        <!-- 任务运行状态提示 -->
        <el-alert
            v-if="taskStatus && taskStatus.tts_running"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
        >
            <template #title>
                <span>⚠️ {{ taskStatus.current_task?.description || '语音合成' }}正在进行中（已运行 {{ ttsRunningSeconds }} 秒），请等待完成后再提交新任务</span>
            </template>
        </el-alert>
    </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { modelsAPI } from "@/api/models";

const ttsModelStatus = ref(null);
const taskStatus = ref(null);

// 当前 TTS 任务已运行秒数（基于后端返回的锁获取时间戳）
const ttsRunningSeconds = computed(() => {
    const since = taskStatus.value?.tts_running_since;
    if (!since || !taskStatus.value?.tts_running) return 0;
    const t = new Date(since.replace(' ', 'T')).getTime();
    if (Number.isNaN(t)) return 0;
    return Math.max(0, Math.floor((Date.now() - t) / 1000));
});

async function loadModelStatus() {
    try {
        const res = await modelsAPI.getStatus();
        const tts = res.data.models?.find(m => m.name.includes('CosyVoice') || m.name.includes('TTS'));
        ttsModelStatus.value = tts || null;
    } catch {
        ttsModelStatus.value = null;
    }
}

async function loadTaskStatus() {
    try {
        const res = await modelsAPI.getTaskStatus();
        taskStatus.value = res.data;
    } catch {
        taskStatus.value = null;
    }
}

onMounted(async () => {
    await loadModelStatus();
    await loadTaskStatus();
});
</script>
