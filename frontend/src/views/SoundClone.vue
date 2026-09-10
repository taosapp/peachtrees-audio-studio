<template>
    <div class="clone-page">
        <!-- 模型/任务状态提示 -->
        <ModelStatusAlerts />

        <!-- 上传新音色 -->
        <el-card shadow="never" class="save-voice-card">
            <template #header>
                <span class="card-title"
                    ><el-icon><Microphone /></el-icon>
                    上传参考音频，保存音色</span
                >
            </template>

            <el-alert
                title="建议上传 3-30 秒的高质量人声音频，文字内容越准确克隆效果越好。"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 16px"
            />

            <el-upload
                ref="voiceUploadRef"
                drag
                :auto-upload="false"
                :on-change="handleVoiceFileChange"
                :on-remove="handleVoiceFileRemove"
                :limit="1"
                accept="audio/*"
                :show-file-list="true"
            >
                <div class="upload-inner-sm">
                    <el-icon :size="36" color="#a8abb2"
                        ><Microphone
                    /></el-icon>
                    <p class="upload-text-sm">
                        拖拽参考音频到此处，或 <em>点击上传</em>
                    </p>
                    <p class="upload-hint-sm">
                        支持 WAV / MP3 / FLAC / M4A
                    </p>
                </div>
            </el-upload>

            <div v-if="voiceFile" class="file-info">
                <el-icon><Document /></el-icon>
                <span>{{ voiceFile.name }}</span>
            </div>

            <el-form
                :model="voiceForm"
                label-width="110px"
                class="voice-form"
            >
                <el-form-item label="音色名称" required>
                    <el-input
                        v-model="voiceForm.voice_name"
                        placeholder="例如：主播小美"
                        maxlength="30"
                        show-word-limit
                    />
                </el-form-item>
                <el-form-item label="音频文字内容" required>
                    <el-input
                        v-model="voiceForm.ref_text"
                        type="textarea"
                        :rows="3"
                        placeholder="请填写这段音频里说的内容（必填，必须与音频内容完全一致以保证克隆效果）"
                    />
                </el-form-item>
            </el-form>

            <div class="action-bar">
                <el-button
                    type="primary"
                    :loading="savingVoice"
                    :disabled="!voiceFile || !voiceForm.voice_name || !voiceForm.ref_text"
                    @click="saveVoice"
                >
                    <el-icon><Upload /></el-icon>
                    {{ savingVoice ? "保存中..." : "保存音色" }}
                </el-button>
                <el-progress
                    v-if="savingVoice"
                    :percentage="voiceUploadPercent"
                    :stroke-width="6"
                    style="width: 200px"
                />
            </div>
        </el-card>

        <!-- 已保存音色列表 -->
        <el-card shadow="never" class="voice-list-card">
            <template #header>
                <div class="list-header">
                    <span class="card-title"
                        ><el-icon><User /></el-icon>
                        已保存音色</span
                    >
                    <el-button size="small" @click="loadVoices"
                        ><el-icon><Refresh /></el-icon>
                        刷新</el-button
                    >
                </div>
            </template>

            <!-- 音频播放器（隐藏，用于试听） -->
            <audio
                ref="previewAudioRef"
                @ended="onPreviewEnded"
                style="display: none"
            />

            <el-empty
                v-if="!voices.length && !loadingVoices"
                description="暂无已保存的音色"
                :image-size="80"
            />
            <div v-else class="voice-grid">
                <div
                    v-for="v in voices"
                    :key="v.name"
                    class="voice-card"
                >
                    <div class="voice-icon">🎙️</div>
                    <div class="voice-info">
                        <div class="voice-name">{{ v.name }}</div>
                        <div class="voice-meta">
                            <span
                                :title="v.ref_text || '（未填写参考文字）'"
                            >{{
                                v.ref_text
                                    ? v.ref_text.substring(0, 20) +
                                      "..."
                                    : "（未填写参考文字）"
                            }}</span>
                        </div>
                        <div class="voice-duration">
                            参考音频：{{
                                formatSec(v.ref_duration)
                            }}
                        </div>
                        <div class="voice-duration" :class="v.ref_pt_exists ? 'feature-ready' : 'feature-missing'">
                            音色特征：{{ v.ref_pt_exists ? '已就绪' : '缺失' }}
                        </div>
                    </div>
                    <div class="voice-actions">
                        <el-button
                            size="small"
                            :type="
                                playingVoice === v.name
                                    ? 'warning'
                                    : ''
                            "
                            plain
                            @click="togglePlayVoice(v)"
                        >
                            <el-icon v-if="playingVoice !== v.name"
                                ><VideoPlay
                            /></el-icon>
                            <el-icon v-else><VideoPause /></el-icon>
                            {{
                                playingVoice === v.name
                                    ? "暂停"
                                    : "播放"
                            }}
                        </el-button>
                        <el-button
                            size="small"
                            type="primary"
                            plain
                            @click="useVoice(v)"
                        >
                            <el-icon><MagicStick /></el-icon> 使用
                        </el-button>
                        <el-popconfirm
                            :title="`确定删除音色「${v.name}」？`"
                            @confirm="deleteVoice(v.name)"
                        >
                            <template #reference>
                                <el-button
                                    size="small"
                                    type="danger"
                                    plain
                                >
                                    <el-icon><Delete /></el-icon>
                                </el-button>
                            </template>
                        </el-popconfirm>
                    </div>
                </div>
            </div>
        </el-card>
    </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
    VideoPlay,
    VideoPause,
    Document,
    Refresh,
    Delete,
    Upload,
    Microphone,
    MagicStick,
    User,
} from "@element-plus/icons-vue";
import { ttsAPI } from "@/api/tts";
import ModelStatusAlerts from "@/components/ModelStatusAlerts.vue";

const router = useRouter();

// ── 音色管理 ────────────────────────────────────────────
const voiceUploadRef = ref();
const voiceFile = ref(null);
const savingVoice = ref(false);
const voiceUploadPercent = ref(0);
const voices = ref([]);
const loadingVoices = ref(false);
const playingVoice = ref(null);
const previewAudioRef = ref();
const previewObjectUrl = ref("");

const voiceForm = ref({
    voice_name: "",
    ref_text: "",
});

function handleVoiceFileChange(file) {
    voiceFile.value = file.raw;
}
function handleVoiceFileRemove() {
    voiceFile.value = null;
}

async function loadVoices() {
    loadingVoices.value = true;
    try {
        const res = await ttsAPI.getVoices();
        voices.value = res.data.voices || [];
    } catch {
        voices.value = [];
    } finally {
        loadingVoices.value = false;
    }
}

async function saveVoice() {
    if (!voiceFile.value || !voiceForm.value.voice_name || !voiceForm.value.ref_text) return;
    savingVoice.value = true;
    voiceUploadPercent.value = 0;
    try {
        const fd = new FormData();
        fd.append("ref_audio", voiceFile.value);
        fd.append("voice_name", voiceForm.value.voice_name);
        fd.append("ref_text", voiceForm.value.ref_text);
        await ttsAPI.saveVoice(fd, (p) => {
            voiceUploadPercent.value = p;
        });
        ElMessage.success("音色保存成功！");
        voiceFile.value = null;
        voiceForm.value.voice_name = "";
        voiceForm.value.ref_text = "";
        voiceUploadRef.value?.clearFiles();
        await loadVoices();
    } catch (e) {
        ElMessage.error("保存失败：" + (e.response?.data?.detail || e.message));
    } finally {
        savingVoice.value = false;
    }
}

async function deleteVoice(name) {
    try {
        await ttsAPI.deleteVoice(name);
        ElMessage.success("音色已删除");
        await loadVoices();
    } catch (e) {
        ElMessage.error("删除失败：" + (e.response?.data?.detail || e.message));
    }
}

// 跳转到"文字转语音"页面并选中该音色
function useVoice(v) {
    router.push({ path: "/tts", query: { voice: v.name } });
}

async function togglePlayVoice(v) {
    const audio = previewAudioRef.value;
    if (!audio) return;
    if (playingVoice.value === v.name) {
        audio.pause();
        playingVoice.value = null;
        return;
    }
    if (playingVoice.value) {
        audio.pause();
        if (previewObjectUrl.value) {
            URL.revokeObjectURL(previewObjectUrl.value);
            previewObjectUrl.value = "";
        }
    }
    try {
        const res = await ttsAPI.getVoiceAudio(v.name);
        const blob = new Blob([res.data], { type: "audio/wav" });
        if (previewObjectUrl.value) {
            URL.revokeObjectURL(previewObjectUrl.value);
        }
        previewObjectUrl.value = URL.createObjectURL(blob);
        audio.src = previewObjectUrl.value;
        await audio.play();
        playingVoice.value = v.name;
    } catch {
        ElMessage.error("播放失败，请重试");
    }
}

function onPreviewEnded() {
    playingVoice.value = null;
}

// ── 工具 ────────────────────────────────────────────────
function formatSec(sec) {
    if (!sec) return "—";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return m > 0 ? `${m}分${s}秒` : `${s}秒`;
}

onMounted(async () => {
    await loadVoices();
});

onBeforeUnmount(() => {
    if (previewObjectUrl.value) {
        URL.revokeObjectURL(previewObjectUrl.value);
    }
});
</script>

<style scoped>
.card-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
}

.save-voice-card,
.voice-list-card {
    border-radius: 10px;
    margin-bottom: 20px;
}

.upload-inner-sm {
    padding: 20px 0;
    text-align: center;
}
.upload-text-sm {
    font-size: 14px;
    color: #606266;
    margin: 10px 0 4px;
}
.upload-text-sm em {
    color: #409eff;
    font-style: normal;
}
.upload-hint-sm {
    font-size: 12px;
    color: #aaa;
}

.file-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: #f5f7fa;
    border-radius: 8px;
    font-size: 13px;
    color: #606266;
    margin-top: 10px;
}

.voice-form {
    margin-top: 16px;
}

.action-bar {
    display: flex;
	justify-content: flex-end;
    align-items: center;
    gap: 12px;
    margin-top: 8px;
    flex-wrap: wrap;
}

.list-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.voice-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
}

.voice-card {
    border: 1px solid #ebeef5;
    border-radius: 10px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    transition: box-shadow 0.2s;
}
.voice-card:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.voice-icon {
    font-size: 32px;
}
.voice-info {
    flex: 1;
}
.voice-name {
    font-size: 15px;
    font-weight: 600;
    color: #303133;
    margin-bottom: 4px;
}
.voice-meta {
    font-size: 12px;
    color: #909399;
}
.voice-duration {
    font-size: 12px;
    color: #c0c4cc;
    margin-top: 2px;
}
.feature-ready {
    color: #67c23a;
}
.feature-missing {
    color: #e6a23c;
}
.voice-actions {
    display: flex;
    gap: 6px;
}
</style>
