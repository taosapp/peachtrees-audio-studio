# Electron 壳使用说明

> PeachTrees Media Studio 桌面应用壳，基于「壳+webserver」架构。

## 架构

设计思路：

```
electron-shell/
├── src/
│   ├── main.js               ← 主进程：窗口/托盘/Python 子进程管理
│   ├── preload.cjs            ← 预加载脚本（安全 IPC）
│   └── native-ui/
│       └── setup-wizard.html  ← 启动向导（后端就绪前显示）
├── build/                     ← 图标资源（需放置 icon.ico/.icns/.png）
├── package.json
└── README.md
```

## 工作原理

1. Electron 启动 → 显示 setup-wizard.html（加载中状态）
2. 通过 `python manage.py start` 拉起后端子进程
3. 轮询 `http://127.0.0.1:8000/health` 直到后端就绪
4. 主窗口加载 `http://127.0.0.1:8000`（FastAPI 托管的 Vue3 前端）
5. 关闭窗口时通过 `python manage.py stop` 优雅停止后端

## 开发模式

```bash
cd electron-shell
npm install
npm start          # 启动 Electron 壳（需先构建前端）
```

前端构建：
```bash
# 项目根目录
python manage.py build   # 或 cd frontend && npm run build
```

## 打包

```bash
cd electron-shell
npm run build:win       # Windows: NSIS 安装包
npm run build:mac       # macOS: DMG
npm run build:linux     # Linux: AppImage + deb
```

**注意**：打包前需通过 `extraResources` 配置将 Python 后端打包进应用，
且需单独处理 7.2GB 模型文件的分发（建议首次启动时下载）。

## 自签证书 HTTPS（可选，未来增强）

使用 `selfsigned` 包
为后端生成自签证书，让同网段设备也能通过 HTTPS 访问。

## 自动更新（可选，未来增强）

使用 `electron-updater`，配置 GitHub Releases 后
可实现应用自动更新（模型文件需单独增量下载）。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PEACHTREES_PYTHON` | `python` | 指定 Python 解释器路径 |
