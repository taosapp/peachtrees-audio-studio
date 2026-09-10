<template>
    <div class="tts-page">
        <!-- 模型/任务状态提示 -->
        <ModelStatusAlerts />

        <el-row :gutter="24">
            <!-- 左：参数区 -->
            <el-col :span="12">
                <el-card shadow="never" class="synth-card">
                    <template #header>
                        <span class="card-title"
                            ><el-icon><ChatLineSquare /></el-icon>
                            合成参数</span
                        >
                    </template>

                    <!-- 音色选择（单选 + 试听） -->
                    <div
                        class="voice-radio-group"
                        v-if="voices.length"
                    >
                        <label class="voice-radio-label"
                            >选择音色</label
                        >
                        <div
                            v-for="v in voices"
                            :key="v.name"
                            class="voice-radio-item"
                            :class="{
                                active:
                                    synthForm.voice_name === v.name,
                            }"
                            @click="synthForm.voice_name = v.name"
                        >
                            <el-radio
                                v-model="synthForm.voice_name"
                                :value="v.name"
                                :label="v.name"
                            >
                                <span class="voice-radio-name"
                                    >🎙️ {{ v.name }}</span
                                >
                                <span
                                    class="voice-radio-duration"
                                    >{{
                                        formatSec(v.ref_duration)
                                    }}</span
                                >
                            </el-radio>
                            <el-button
                                size="small"
                                circle
                                :type="
                                    playingPreview === v.name
                                        ? 'warning'
                                        : 'default'
                                "
                                :icon="
                                    playingPreview === v.name
                                        ? VideoPause
                                        : VideoPlay
                                "
                                @click.stop="togglePreview(v)"
                                :title="
                                    playingPreview === v.name
                                        ? '暂停'
                                        : '试听'
                                "
                            />
                        </div>
                    </div>
                    <el-empty
                        v-if="!voices.length"
                        description="暂无已保存音色，请先在「声音克隆」页上传"
                        :image-size="60"
                    />

                    <!-- 隐藏的音频播放器（用于试听） -->
                    <audio
                        ref="previewAudioRef"
                        @ended="onPreviewEnded"
                        style="display: none"
                    />

                    <!-- 合成文本 -->
                    <el-form
                        :model="synthForm"
                        label-width="90px"
                        class="synth-form"
                    >
                        <el-form-item label="合成文本" required>
                            <el-input
                                v-model="synthForm.gen_text"
                                type="textarea"
                                :rows="6"
                                placeholder="输入要合成的文本内容..."
                                maxlength="1500"
                                show-word-limit
                            />
                            <div class="pinyin-hint">
                                多音字可用 <code>[zhu4]</code> 直接替换该字来纠正读音（数字为声调），如：著名 → [zhu4]名；勿写成 著[zhu4]名（会重复发音）
                            </div>
                        </el-form-item>

                        <!-- 高级参数 -->
                        <el-collapse class="advanced-collapse">
                            <el-collapse-item
                                title="高级参数（可选）"
                                name="advanced"
                            >
                                <el-form-item label="语速">
                                    <el-slider
                                        v-model="synthForm.speed"
                                        :min="0.5"
                                        :max="2.0"
                                        :step="0.1"
                                        show-input
                                    />
                                </el-form-item>
                                <el-form-item label="去除静音">
                                    <el-switch
                                        v-model="
                                            synthForm.remove_silence
                                        "
                                    />
                                </el-form-item>
                                <el-form-item label="随机种子">
                                    <el-input-number
                                        v-model="synthForm.seed"
                                        :min="0"
                                        :max="2147483647"
                                        controls-position="right"
                                    />
                                </el-form-item>
                            </el-collapse-item>
                        </el-collapse>
                    </el-form>

                    <!-- 合成按钮 -->
                    <div
                        class="action-bar"
                        style="margin-top: 12px"
                    >
                        <el-button
                            type="primary"
                            size="large"
                            :loading="synthesizing"
                            :disabled="!canSynthesize"
                            @click="startSynthesize"
                        >
                            <el-icon><VideoPlay /></el-icon>
                            {{
                                synthesizing
                                    ? `合成中... ${elapsedSec}s`
                                    : "开始合成"
                            }}
                        </el-button>
                        <el-button size="large" @click="resetSynth"
                            >重置</el-button
                        >
                    </div>
                    <div v-if="synthesizing" class="synth-progress">
                        <div class="synth-status-row">
                            <span class="synth-status-text">{{ taskMessage || "正在提交合成任务..." }}</span>
                            <span class="synth-elapsed">
                                <el-icon><Timer /></el-icon>
                                已花费 <strong>{{ elapsedSec }}</strong> 秒
                            </span>
                        </div>
                        <el-progress
                            :percentage="synthAnimPercent"
                            :stroke-width="8"
                            striped
                            striped-flow
                            :duration="15"
                        />
                    </div>
                </el-card>
            </el-col>

            <!-- 右：结果区 -->
            <el-col :span="12">
                <el-card
                    shadow="never"
                    class="result-card"
                    :style="{ opacity: audioUrl ? 1 : 0.5 }"
                >
                    <template #header>
                        <div class="result-header">
                            <span class="card-title"
                                ><el-icon><VideoPlay /></el-icon>
                                合成结果</span
                            >
                            <el-button
                                v-if="audioUrl"
                                size="small"
                                type="success"
                                @click="downloadAudio"
                            >
                                <el-icon><Download /></el-icon>
                                下载音频
                            </el-button>
                        </div>
                    </template>

                    <div v-if="audioUrl" class="audio-player">
                        <audio
                            ref="audioRef"
                            :src="audioUrl"
                            controls
                            style="width: 100%"
                        />
                        <div class="result-meta">
                            <span>时长：{{ resultDuration }}</span>
                            <span
                                >采样率：{{
                                    resultSampleRate
                                }}
                                Hz</span
                            >
                        </div>
                        <el-divider />
                        <div class="result-info-box">
                            <div class="result-label">
                                合成文本：
                            </div>
                            <div class="result-gen-text">
                                {{ synthForm.gen_text }}
                            </div>
                        </div>
                    </div>
                    <el-empty
                        v-else
                        description="合成结果将在此处显示"
                        :image-size="80"
                    />
                </el-card>
            </el-col>
        </el-row>
    </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import {
    VideoPlay,
    VideoPause,
    Timer,
    Download,
    ChatLineSquare,
} from "@element-plus/icons-vue";
import { ttsAPI } from "@/api/tts";
import ModelStatusAlerts from "@/components/ModelStatusAlerts.vue";

const route = useRoute();

// ── 语音合成 ────────────────────────────────────────────
const synthesizing = ref(false);
const synthAnimPercent = ref(0);
const elapsedSec = ref(0);
const audioUrl = ref("");
const audioRef = ref();
const resultDuration = ref("");
const resultSampleRate = ref("");
const resultFilename = ref("");

const currentTaskId = ref("");
const taskMessage = ref("");
let pollingTimer = null;

let _elapsedTimer = null;

// 后端是否已上报真实分片进度（收到后不再推进假动画进度）
const realProgressSeen = ref(false);
// 恢复跟踪进行中任务的最长轮询时长：服务重启可能留下永远停在
// processing 的僵尸任务，超过该时长停止轮询并提示用户
const RESUME_POLL_MAX_MS = 30 * 60 * 1000;
let resumeDeadline = 0;

function _startElapsedTimer() {
    elapsedSec.value = 0;
    realProgressSeen.value = false;
    synthAnimPercent.value = 5;
    _elapsedTimer = setInterval(() => {
        elapsedSec.value++;
        // 动画进度：缓慢爬升到最多 90%，让用户感知进展；
        // 收到后端真实分片进度后交由真实进度驱动
        if (!realProgressSeen.value && synthAnimPercent.value < 90) {
            const step = synthAnimPercent.value < 30 ? 3 : synthAnimPercent.value < 60 ? 1.5 : 0.5;
            synthAnimPercent.value = Math.min(90, synthAnimPercent.value + step);
        }
    }, 1000);
}

function _stopElapsedTimer() {
    if (_elapsedTimer) {
        clearInterval(_elapsedTimer);
        _elapsedTimer = null;
    }
    synthAnimPercent.value = 100;
}

const synthForm = ref({
    voice_name: "",
    gen_text: "",
    speed: 1.2,  // 与后端默认值保持一致（用户要求默认 1.2 倍速）
    remove_silence: true,
    seed: 20260812,
});

const canSynthesize = computed(() => {
    return synthForm.value.voice_name && synthForm.value.gen_text.trim();
});

/**
 * 轮询任务状态直至完成/失败。
 * @param {string} taskId 任务ID
 * @param {boolean} resumed 是否为刷新页面后恢复的跟踪（带僵尸任务超时兜底）
 */
function startPolling(taskId, resumed = false) {
    if (resumed) resumeDeadline = Date.now() + RESUME_POLL_MAX_MS;
    const _clearPollingTimer = () => {
        if (pollingTimer) {
            clearTimeout(pollingTimer);
            pollingTimer = null;
        }
    };
    const pollOnce = async () => {
        // 守卫：已经处理过完成/失败/异常，不再继续
        if (!synthesizing.value) return;
        try {
            const taskRes = await ttsAPI.getTaskStatus(taskId);
            // await 期间状态可能已变更，再次守卫
            if (!synthesizing.value) return;
            const status = taskRes.data.status;
            taskMessage.value = taskRes.data.message || "正在合成中...";

            // 后端返回真实分片进度（0-100）时优先展示
            if (
                typeof taskRes.data.progress === "number" &&
                taskRes.data.progress > 0
            ) {
                realProgressSeen.value = true;
                synthAnimPercent.value = taskRes.data.progress;
            }

            if (status === "done") {
                _clearPollingTimer();
                synthesizing.value = false;
                _stopElapsedTimer();

                // 加载音频结果
                if (taskRes.data.result_filename) {
                    resultFilename.value = taskRes.data.result_filename;
                    audioUrl.value = `/api/v1/tts/download/${encodeURIComponent(taskRes.data.result_filename)}`;
                    resultDuration.value = taskRes.data.tts_duration_sec ? taskRes.data.tts_duration_sec.toFixed(2) + "秒" : "未知";
                    resultSampleRate.value = taskRes.data.sample_rate ? taskRes.data.sample_rate + " Hz" : "24000 Hz";
                    ElMessage.success("语音合成完成！");
                } else {
                    ElMessage.error("未找到生成的音频文件");
                }
            } else if (status === "failed") {
                _clearPollingTimer();
                synthesizing.value = false;
                _stopElapsedTimer();
                ElMessage.error(`合成失败: ${taskRes.data.message}`);
            } else if (resumed && Date.now() > resumeDeadline) {
                // 恢复的僵尸任务兜底：长时间无结果则停止跟踪
                _clearPollingTimer();
                synthesizing.value = false;
                _stopElapsedTimer();
                ElMessage.warning("任务长时间未完成（可能因服务重启中断），请到任务记录页查看");
            } else {
                // 仍在处理中，调度下一次查询
                pollingTimer = setTimeout(pollOnce, 1500);
            }
        } catch (err) {
            console.error("Polling error:", err);
            // 轮询连续失败时停止轮询并提示，避免无意义的死循环
            _clearPollingTimer();
            synthesizing.value = false;
            _stopElapsedTimer();
            ElMessage.error("任务状态查询失败，请刷新页面查看任务记录");
        }
    };
    pollingTimer = setTimeout(pollOnce, 1500);
}

// 页面加载/刷新后恢复跟踪进行中的合成任务（长文本合成需数分钟，刷新不丢跟踪）
async function resumeRunningTask() {
    if (synthesizing.value) return;
    try {
        const res = await ttsAPI.getHistory({
            task_type: "tts",
            page: 1,
            page_size: 10,
        });
        const running = (res.data.items || []).find(
            (t) => t.status === "pending" || t.status === "processing"
        );
        if (!running) return;
        currentTaskId.value = running.task_id;
        synthesizing.value = true;
        taskMessage.value = running.message || "检测到进行中的合成任务，已恢复跟踪...";
        _startElapsedTimer();
        startPolling(running.task_id, true);
    } catch {
        /* 恢复失败静默处理，不影响页面正常使用 */
    }
}

async function startSynthesize() {
    if (!canSynthesize.value) return;
    synthesizing.value = true;
    taskMessage.value = "已提交合成任务...";
    _startElapsedTimer();

    try {
        const fd = new FormData();
        fd.append("voice_name", synthForm.value.voice_name);
        fd.append("gen_text", synthForm.value.gen_text);
        fd.append("speed", synthForm.value.speed);
        fd.append("remove_silence", synthForm.value.remove_silence);
        fd.append("seed", synthForm.value.seed);

        // 使用异步任务接口提交，随后轮询任务状态
        const res = await ttsAPI.submitTask(fd);
        currentTaskId.value = res.data.task_id;
        startPolling(res.data.task_id);

    } catch (e) {
        console.error('Synthesis error:', e);
        const errDetail = e.response?.data?.detail || e.message;
        ElMessage.error("提交失败：" + errDetail);
        _stopElapsedTimer();
        synthesizing.value = false;
    }
}

async function downloadAudio() {
    if (!resultFilename.value) return;
    try {
        const blobRes = await ttsAPI.downloadAudio(resultFilename.value);
        const blob = new Blob([blobRes.data], { type: "audio/wav" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `tts_${Date.now()}.wav`;
        a.click();
        URL.revokeObjectURL(url);
        ElMessage.success("下载成功");
    } catch (e) {
        ElMessage.error("下载失败");
    }
}

function resetSynth() {
    _stopElapsedTimer();
    synthesizing.value = false;
    elapsedSec.value = 0;
    synthAnimPercent.value = 0;
    audioUrl.value = "";
    // 保留已选音色，仅清空文本与结果，方便连续调整文案重新合成
    synthForm.value.gen_text = "";
    synthForm.value.speed = 1.2;
    synthForm.value.remove_silence = true;
    synthForm.value.seed = 20260812;
}

// ── 音色试听 ────────────────────────────────────────────
const voices = ref([]);
const loadingVoices = ref(false);
const playingPreview = ref(null);
const previewAudioRef = ref();
const previewObjectUrl = ref("");

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

function togglePreview(v) {
    const audio = previewAudioRef.value;
    if (!audio) return;
    if (playingPreview.value === v.name) {
        audio.pause();
        playingPreview.value = null;
        return;
    }
    if (playingPreview.value) {
        audio.pause();
        playingPreview.value = null;
        if (previewObjectUrl.value) {
            URL.revokeObjectURL(previewObjectUrl.value);
            previewObjectUrl.value = "";
        }
    }
    try {
        ttsAPI
            .getVoiceAudio(v.name)
            .then((res) => {
                const blob = new Blob([res.data], { type: "audio/wav" });
                if (previewObjectUrl.value) {
                    URL.revokeObjectURL(previewObjectUrl.value);
                }
                previewObjectUrl.value = URL.createObjectURL(blob);
                audio.src = previewObjectUrl.value;
                audio.play();
                playingPreview.value = v.name;
            })
            .catch(() => {
                ElMessage.error("试听失败");
            });
    } catch {
        ElMessage.error("试听失败");
    }
}

function onPreviewEnded() {
    playingPreview.value = null;
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
    // 从"声音克隆"页"使用"按钮跳转过来时选中指定音色
    const queryVoice = route.query.voice;
    if (queryVoice && voices.value.some((v) => v.name === queryVoice)) {
        synthForm.value.voice_name = queryVoice;
    } else if (voices.value.length > 0 && !synthForm.value.voice_name) {
        // 自动选中第一个音色
        synthForm.value.voice_name = voices.value[0].name;
    }
    // 恢复跟踪进行中的合成任务（页面刷新后不丢失进度）
    resumeRunningTask();
});

onBeforeUnmount(() => {
    _stopElapsedTimer();
    if (pollingTimer) {
        clearTimeout(pollingTimer);
        pollingTimer = null;
    }
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

.synth-card,
.result-card {
    border-radius: 10px;
    margin-bottom: 20px;
}

.voice-radio-group {
    margin-bottom: 16px;
}
.voice-radio-label {
    display: block;
    font-size: 13px;
    color: #909399;
    margin-bottom: 8px;
}
.voice-radio-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border: 1px solid #ebeef5;
    border-radius: 8px;
    padding: 8px 12px;
    margin-bottom: 8px;
    cursor: pointer;
    transition: all 0.2s;
}
.voice-radio-item.active {
    border-color: #409eff;
    background: #f0f7ff;
}
.voice-radio-name {
    font-weight: 500;
}
.voice-radio-duration {
    margin-left: 8px;
    font-size: 12px;
    color: #909399;
}

.synth-form {
    margin-top: 16px;
}

.pinyin-hint {
    margin-top: 6px;
    font-size: 12px;
    color: #909399;
    line-height: 1.6;
}
.pinyin-hint code {
    background: #f0f0f5;
    border-radius: 4px;
    padding: 0 4px;
    color: #6366f1;
    font-size: 12px;
}

.action-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 8px;
    flex-wrap: wrap;
}

.synth-progress {
    margin-top: 12px;
}
.synth-status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}
.synth-status-text {
    font-size: 13px;
    color: #606266;
}
.synth-elapsed {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    color: #409eff;
    font-weight: 500;
}
.synth-elapsed strong {
    font-size: 15px;
    color: #e6a23c;
}

.result-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.result-meta {
    display: flex;
    gap: 16px;
    justify-content: flex-end;
    font-size: 12px;
    color: #909399;
    margin-top: 8px;
}
.result-info-box {
    background: #f5f7fa;
    border-radius: 8px;
    padding: 12px;
}
.result-label {
    font-size: 12px;
    color: #909399;
    margin-bottom: 4px;
}
.result-gen-text {
    font-size: 13px;
    color: #303133;
    line-height: 1.7;
    max-height: 200px;
    overflow-y: auto;
}
</style>
