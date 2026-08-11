# PeachTrees Media Studio 声音克隆系统 (v2.2)

本项目已重构净化为 **极简单用户声音克隆与合成系统**。移除了旧版本中的视频字幕生成（ASR）、Redis/ARQ 队列依赖、身份注册/登录及多用户账单等冗余模块，让运行资源和体验达到最轻量状态。

---

## 🚀 1. 快速启动与管理（Windows 双击即用）

为方便用户及移植到其他设备，项目根目录下已内置完备的批处理管理脚本：

### 第一步：一键安装依赖
*   **直接双击运行根目录下的 `install_deps.bat`**。
*   脚本会自动检测 Python/pip 环境，并为您提供 [1] GPU (Nvidia CUDA) 或 [2] CPU 运行硬件选择。
*   选择后将自动拉起最新适配的 PyTorch 并以清华国内源极速完成核心业务及 CosyVoice3 模型全部运行依赖的安装。

### 第二步：一键启动/管理服务
*   **直接双击运行根目录下的 `manage.bat`**。
*   打开后会呈现交互式中文管理菜单，输入对应选项（1-5）并回车：
    *   `[1] 启动前后端服务`：会自动清理残留进程并分别弹出独立的后端与前端运行窗口（便于排查和查看实时日志）。
    *   `[2] 关闭前后端服务`：强力终止后台占用的 `8000` (后端) 和 `5173` (前端) 进程树并自动关闭窗口。
    *   `[3] 重启前后端服务`：一键关闭并重新拉起最新服务。
    *   `[4] 查看服务运行状态`：实时显示当前端口占用 PID 及访问链接。
    *   `[5] 退出管理器`。

---

## ⚙️ 2. 环境配置 (`backend/.env`)

**v2.3 起仅支持 SQLite，零配置**：数据库文件自动创建于 `backend/data/pt_media_studio.db`，无需安装任何数据库服务：

```ini
DATABASE_URL=sqlite+aiosqlite:///D:/ai/peachtreesMediaStudio/backend/data/pt_media_studio.db
```

其他可配置项：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MAX_UPLOAD_MB` | 50 | 参考音频上传大小上限（MB） |
| `MAX_REF_SECONDS` | 15 | 参考音频最大时长（秒），超出自动截断 |
| `MAX_OUTPUT_FILES` | 500 | 合成输出目录保留文件数，超出自动清理 |
| `TTS_NUM_THREADS` | 4 | CPU 推理线程数（0=torch 默认） |

---

## 🌐 3. 服务访问地址

服务成功启动后，您可通过以下链接进行访问和调试：

| 模块 | 地址 | 说明 |
|------|------|------|
| **前端 Web 界面** | [http://localhost:5173](http://localhost:5173) | 声音克隆/合成控制台 |
| **后端 API 文档** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger API 交互调试文档 |
| **API 根路径** | [http://localhost:8000](http://localhost:8000) | 后端服务根目录 |

---

## 📁 4. 目录结构说明

经过深度精简和无用文件物理删除后，项目目录结构如下：

```text
peachtreesMediaStudio/
├── README.md               # 本启动指南
├── install_deps.bat        # Windows 依赖一键安装工具（支持 GPU / CPU 选择）
├── manage.bat              # Windows 服务一键管理工具（图形菜单，支持启/停/重启/状态）
├── manage.py               # 核心跨平台服务管理控制脚本
│
├── backend/                # 后端 FastAPI 根目录
│   ├── main.py             # FastAPI 入口服务
│   ├── init_voices.py      # 运行时音色库目录初始化
│   ├── tts_infer_worker.py # CosyVoice3 独立进程持久化推理 Worker
│   ├── requirements.txt    # 后端及 CosyVoice3/Matcha 完整包依赖定义
│   ├── .env                # 配置文件（已优化为 127.0.0.1 连接）
│   ├── core/               # 核心支撑模块（数据库连接/常量配置）
│   ├── models/             # 精简后的 ORM 实体（仅保留 voices、task_records 表）
│   ├── api/v1/             # API 控制器（精简为：tts 合成、tasks 任务队列管理、models 状态）
│   ├── services/           # 核心业务服务（tts_service：内嵌防崩溃及 15 秒时长自动截断防崩机制）
│   ├── models/CosyVoice/   # 预训练 CosyVoice3 权重目录（~7.2 GB，模型文件请在此放置）
│   ├── voices/             # 用户上传并提取生成的音色克隆库（保存 .wav 剪质及 .pt 特征）
│   └── tts_outputs/        # 运行时合成音频输出文件夹
│
└── frontend/               # 前端 Vue3 根目录
    ├── src/
    │   ├── main.js         # 前端应用入口
    │   ├── router/index.js # Vue Router 路由配置（已切除鉴权/登录路由守卫）
    │   ├── layouts/        # 主侧边栏布局组件（剔除个人设置、字幕等导航）
    │   ├── api/            # Axios 请求封装组件
    │   └── views/          # 视图文件夹（Dashboard、VoiceClone、Tasks 任务记录页）
    ├── vite.config.js      # Vite 构建配置
    └── package.json        # 前端依赖配置
```

---

## 💡 5. 常见问题解答 (FAQ)

### Q1：为什么我点击合成提示 `AssertionError`？
本系统已在 `save_voice` 录入层和 `generate_speech` 推理层内嵌了 **参考音频自动截断保护（15秒）**。若您使用极个别外部导入的超长音频，系统会在开始合成前自动将其裁切到前 15s 以绕开 CosyVoice 底层 30s 提取限制，**确保您在任何时候合成都不再报错崩溃**。

### Q2：如何备份我克隆的音色？
您只需将 `backend/voices/` 目录下的所有文件以及数据库文件（SQLite 为 `backend/data/pt_media_studio.db`，MySQL 为 `voices` 表）一起备份，即可完美移植备份到任意其他设备。

### Q3：参考文字必须手动输入吗？
是的。v2.2 起已彻底移除 Whisper 自动转录依赖，参考文字必须手动填写且与参考音频内容完全一致，否则克隆音色会失真。

### Q4：上传的音频有大小限制吗？
参考音频上传上限默认 50MB（`MAX_UPLOAD_MB` 可调），仅支持常见音频格式（wav/mp3/flac/m4a/aac/ogg/opus/wma/webm），超长音频会自动截断至 15 秒。
