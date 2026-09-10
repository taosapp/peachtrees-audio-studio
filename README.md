# PeachTrees Audio Studio

本应用有2个功能 **声音克隆、文本转语音**。主要功能已实现，仍在开发中，并未正式发布版本。

支持 **Windows、macOS、Linux XFCE** 三平台，采用「壳+webserver」架构，可选 Electron 桌面壳。

---

## 🚀 1. 快速启动与管理

### Windows

#### 第一步：一键安装依赖
*   **直接双击运行根目录下的 `install_deps.bat`**。
*   脚本会自动检测 Python/pip 环境，并为您提供 [1] GPU (Nvidia CUDA) 或 [2] CPU 运行硬件选择。
*   选择后将自动拉起最新适配的 PyTorch 并以清华国内源极速完成核心业务及 CosyVoice3 模型全部运行依赖的安装。

#### 第二步：构建前端（首次或前端更新后）
```powershell
python manage.py build
```
该命令会将 Vue3 前端构建到 `backend/static/`，由后端 FastAPI 静态托管，无需独立前端进程。

#### 第三步：启动/管理服务
```powershell
python manage.py start    # 启动后端服务（前端已由后端托管）
python manage.py stop     # 关闭后端服务
python manage.py restart  # 重启后端服务
python manage.py status   # 查看服务运行状态
```

启动后访问 `http://localhost:8000` 即可使用声音克隆/合成控制台。

### macOS / Linux

#### 第一步：一键安装依赖
```bash
chmod +x install_deps.sh
./install_deps.sh
```
脚本会自动检测包管理器（brew/apt/dnf/yum/pacman）并安装 FFmpeg 和 Python 依赖。
macOS 用户可选择 MPS（Apple Silicon GPU）模式，Linux 用户可选择 CUDA 或 CPU 模式。

#### 第二步：构建前端
```bash
python3 manage.py build
```

#### 第三步：启动服务
```bash
python3 manage.py start
```

#### 可选：创建桌面快捷方式（Linux XFCE）
将 `peachtrees-media-studio.desktop` 复制到 `~/.local/share/applications/`，修改其中的 `Path` 和 `Exec` 为实际项目路径。

### Electron 桌面壳（可选）

项目内置 Electron 壳，可将 Web 应用包装为原生桌面应用：

```powershell
cd electron-shell
npm install
# Windows 下需设置镜像下载 Electron 二进制
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
node node_modules/electron/install.js

# 启动（需先完成上述依赖安装和前端构建）
cd ..
./start_electron.bat    # Windows
# 或 cd electron-shell && npx electron . --dev
```

启动后 Electron 壳会自动拉起 Python 后端，显示启动向导，后端就绪后加载主界面。

---

## ⚙️ 2. 环境配置 (`backend/.env`)

**仅支持 SQLite，零配置**：数据库文件自动创建于 `backend/data/pt_media_studio.db`，无需安装任何数据库服务：

```ini
DATABASE_URL=sqlite+aiosqlite:///D:/ai/peachtreesMediaStudio/backend/data/pt_media_studio.db
```

平台配置模板位于 `backend/` 目录，复制为 `.env` 后按实际路径修改：
*   `.env.windows` - Windows 配置模板
*   `.env.macos` - macOS 配置模板（MPS 优化）
*   `.env.linux` - Linux 配置模板

其他可配置项：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MAX_UPLOAD_MB` | 50 | 参考音频上传大小上限（MB） |
| `MAX_REF_SECONDS` | 15 | 参考音频最大时长（秒），超出自动截断 |
| `MAX_OUTPUT_FILES` | 500 | 合成输出目录保留文件数，超出自动清理 |
| `TTS_NUM_THREADS` | 4 | CPU 推理线程数（0=torch 默认，macOS MPS 建议设为 0） |

---

## 🌐 3. 服务访问地址

服务成功启动后，您可通过以下链接进行访问和调试：

| 模块 | 地址 | 说明 |
|------|------|------|
| **Web 界面** | [http://localhost:8000](http://localhost:8000) | 声音克隆/合成控制台（FastAPI 静态托管） |
| **后端 API 文档** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger API 交互调试文档 |
| **健康检查** | [http://localhost:8000/health](http://localhost:8000/health) | 后端服务健康状态 |

---

## 📁 4. 目录结构说明

```text
peachtreesMediaStudio/
├── README.md                       # 本启动指南
├── 改造文档.md                      # 跨平台改造完整方案与验收标准
├── install_deps.bat                 # Windows 依赖一键安装工具（支持 GPU / CPU 选择）
├── install_deps.sh                  # Linux/macOS 依赖安装脚本（支持 MPS / CUDA / CPU）
├── start_electron.bat               # Windows Electron 壳一键启动脚本
├── peachtrees-media-studio.desktop  # Linux XFCE 桌面快捷方式模板
├── manage.py                        # 跨平台服务管理脚本（start/stop/restart/status/build）
│
├── backend/                         # 后端 FastAPI 根目录
│   ├── main.py                      # FastAPI 入口服务（含 SPA 静态托管）
│   ├── init_voices.py               # 运行时音色库目录初始化
│   ├── tts_infer_worker.py          # CosyVoice3 独立进程持久化推理 Worker
│   ├── requirements.txt             # 后端及 CosyVoice3/Matcha 完整包依赖定义（含平台标记）
│   ├── .env                         # 配置文件（从平台模板复制）
│   ├── core/                        # 核心支撑模块
│   │   ├── config.py                # 配置（pydantic-settings）
│   │   ├── database.py              # 数据库连接（SQLite + aiosqlite）
│   │   └── platform.py              # 跨平台抽象层（FFmpeg/端口/Python 探测）
│   ├── models/                      # ORM 实体（voices、task_records 表）
│   ├── api/v1/                      # API 控制器（tts 合成、tasks 任务管理、models 状态）
│   ├── services/                    # 核心业务服务（tts_service）
│   ├── static/                      # 前端构建产物（由 manage.py build 生成，git 忽略）
│   ├── models/CosyVoice/            # 预训练 CosyVoice3 权重目录（~7.2 GB，需手动放置）
│   ├── voices/                      # 用户上传并提取生成的音色克隆库
│   └── tts_outputs/                 # 运行时合成音频输出文件夹
│
├── frontend/                        # 前端 Vue3 根目录
│   ├── src/
│   │   ├── main.js                  # 前端应用入口
│   │   ├── router/index.js          # Vue Router 路由配置
│   │   ├── layouts/                 # 主侧边栏布局组件
│   │   ├── api/                     # Axios 请求封装组件
│   │   └── views/                   # 视图文件夹（Dashboard、VoiceClone、Tasks）
│   ├── vite.config.js              # Vite 构建配置（输出到 backend/static/）
│   └── package.json                 # 前端依赖配置
│
└── electron-shell/                  # Electron 桌面壳（可选）
    ├── src/
    │   ├── main.js                  # 主进程（窗口/托盘/Python 子进程管理）
    │   ├── preload.cjs              # 预加载脚本（安全 IPC）
    │   └── native-ui/
    │       └── setup-wizard.html    # 启动向导（后端就绪前展示）
    ├── build/                       # 图标资源
    └── package.json                 # Electron 壳依赖配置
```

---

## 🌍 5. 跨平台支持

| 平台 | 后端 | FFmpeg | PyTorch | 桌面壳 |
|---|---|---|---|---|
| **Windows** | ✅ 已验证 | WinGet / imageio-ffmpeg | CUDA / CPU | ✅ 已验证 |
| **macOS** | ✅ 代码就绪 | Homebrew | MPS / CPU | 代码就绪 |
| **Linux XFCE** | ✅ 代码就绪 | apt/dnf/yum/pacman | CUDA / CPU | 代码就绪 |

跨平台实现要点：
*   `backend/core/platform.py` 统一封装平台检测、FFmpeg 查找、端口进程管理
*   `tts_service.py` / `tts_infer_worker.py` 的 triton monkey-patch 对非 Linux 平台生效
*   `requirements.txt` 使用 `sys_platform` 标记实现按平台安装依赖
*   前端构建为静态文件由 FastAPI 托管，消除前端进程依赖

---

## 💡 6. 常见问题解答 (FAQ)

### Q1：如何备份我克隆的音色？
您只需将 `backend/voices/` 目录下的所有文件以及数据库文件（SQLite 为 `backend/data/pt_media_studio.db`）一起备份，即可完美移植备份到任意其他设备。

### Q2：参考文字必须手动输入吗？
是的。参考文字必须手动填写且与参考音频内容完全一致，否则克隆音色会失真。

### Q3：上传的音频有大小限制吗？
参考音频上传上限默认 50MB（`MAX_UPLOAD_MB` 可调），仅支持常见音频格式（wav/mp3/flac/m4a/aac/ogg/opus/wma/webm），超长音频会自动截断至 15 秒。

### Q4：macOS 上 PyTorch 如何选择？
macOS 不支持 CUDA，但支持 MPS（Apple Silicon GPU 加速）。运行 `install_deps.sh` 时选择选项 [3] 即可安装 MPS 兼容版本。`TTS_NUM_THREADS` 建议设为 0，由 torch 自行管理 MPS 并行度。
