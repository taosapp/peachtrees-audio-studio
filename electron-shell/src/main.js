/**
 * PeachTrees Media Studio - Electron 主进程
 *
 * 架构借鉴 DSH Desktop 的「壳+webserver」模式：
 * - Electron 只负责系统级能力（窗口/托盘/生命周期）
 * - Python 后端作为子进程拉起，提供 HTTP 服务
 * - 主窗口加载 localhost URL，由 FastAPI 托管 Vue3 静态构建
 */

const { app, BrowserWindow, Tray, Menu, dialog, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const { existsSync } = require('fs');

// ── 配置 ──────────────────────────────────────────────────────────────────────
const BACKEND_PORT = 8000;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const HEALTH_URL = `${BACKEND_URL}/health`;
const MAX_WAIT_MS = 60000;       // 后端启动最长等待时间
const POLL_INTERVAL_MS = 1000;   // 健康检查间隔

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let isDev = process.argv.includes('--dev');

// ── Python 子进程管理 ───────────────────────────────────────────────────────────

/**
 * 查找后端目录（支持开发模式和打包模式）
 */
function getBackendDir() {
  if (isDev) {
    // 开发模式：项目根目录下的 backend/
    return path.join(__dirname, '..', '..', 'backend');
  }
  // 打包模式：resources/backend/（需通过 extraResources 配置打包）
  return path.join(process.resourcesPath, 'backend');
}

/**
 * 查找 manage.py
 */
function getManageScript() {
  if (isDev) {
    return path.join(__dirname, '..', '..', 'manage.py');
  }
  return path.join(process.resourcesPath, 'manage.py');
}

/**
 * 启动 Python 后端子进程
 */
function startPythonBackend() {
  const backendDir = getBackendDir();
  const manageScript = getManageScript();

  if (!existsSync(manageScript)) {
    dialog.showErrorBox(
      '启动失败',
      `未找到 manage.py: ${manageScript}\n请确保后端已正确安装。`
    );
    app.quit();
    return;
  }

  // 通过 manage.py start 启动后端（复用跨平台启动逻辑）
  const pythonCmd = process.env.PEACHTREES_PYTHON || 'python';
  pythonProcess = spawn(pythonCmd, [manageScript, 'start'], {
    cwd: path.dirname(manageScript),
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    },
    windowsHide: true,
    shell: false,
  });

  pythonProcess.on('error', (err) => {
    console.error('Python 进程启动失败:', err);
    dialog.showErrorBox(
      '后端启动失败',
      `无法启动 Python 后端: ${err.message}\n请检查 Python 环境是否已安装。`
    );
    app.quit();
  });

  pythonProcess.on('exit', (code) => {
    console.log(`Python 后端进程退出，代码: ${code}`);
  });
}

/**
 * 等待后端就绪（轮询 /health 端点）
 */
function waitForBackend() {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();

    const checkHealth = () => {
      const req = http.get(HEALTH_URL, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          retry();
        }
      });

      req.on('error', () => retry());
      req.setTimeout(3000, () => {
        req.destroy();
        retry();
      });
    };

    const retry = () => {
      if (Date.now() - startTime > MAX_WAIT_MS) {
        reject(new Error(`后端启动超时（${MAX_WAIT_MS / 1000}s）`));
      } else {
        setTimeout(checkHealth, POLL_INTERVAL_MS);
      }
    };

    checkHealth();
  });
}

/**
 * 停止 Python 后端子进程
 */
function stopPythonBackend() {
  if (!pythonProcess) return;

  // 通过 manage.py stop 优雅停止（跨平台端口进程管理）
  try {
    const manageScript = getManageScript();
    const pythonCmd = process.env.PEACHTREES_PYTHON || 'python';
    spawn(pythonCmd, [manageScript, 'stop'], {
      cwd: path.dirname(manageScript),
      windowsHide: true,
      shell: false,
    });
  } catch (e) {
    console.error('优雅停止失败，直接 kill:', e);
    pythonProcess.kill('SIGTERM');
  }
}

// ── 窗口管理 ────────────────────────────────────────────────────────────────────

/**
 * 创建主窗口
 */
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 600,
    title: 'PeachTrees Media Studio',
    icon: getIconPath(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    // 阶段4：首次启动先显示原生 setup-wizard，后端就绪后切换
    show: false,  // 先隐藏，加载完成后显示
  });

  // 先加载启动向导（原生 UI）
  const wizardPath = path.join(__dirname, 'native-ui', 'setup-wizard.html');
  if (existsSync(wizardPath)) {
    mainWindow.loadFile(wizardPath);
    mainWindow.show();
  }

  // 等待后端就绪后切换到主界面
  waitForBackend()
    .then(() => {
      console.log('后端就绪，加载主界面...');
      mainWindow.loadURL(BACKEND_URL);
      mainWindow.show();
      mainWindow.focus();
    })
    .catch((err) => {
      dialog.showErrorBox('启动失败', err.message);
      app.quit();
    });

  // 开发模式打开 DevTools
  if (isDev) {
    mainWindow.webContents.on('did-finish-load', () => {
      mainWindow.webContents.openDevTools();
    });
  }

  // 外部链接在系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http')) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
  });

  mainWindow.on('close', (e) => {
    if (pythonProcess) {
      e.preventDefault();
      stopPythonBackend();
      setTimeout(() => {
        pythonProcess = null;
        app.quit();
      }, 2000);
    }
  });
}

/**
 * 获取平台对应图标路径
 */
function getIconPath() {
  const iconDir = path.join(__dirname, '..', 'build');
  if (process.platform === 'darwin') {
    return path.join(iconDir, 'icon.icns');
  } else if (process.platform === 'linux') {
    return path.join(iconDir, 'icon.png');
  }
  return path.join(iconDir, 'icon.ico');
}

// ── 系统托盘 ────────────────────────────────────────────────────────────────────

function createTray() {
  const iconPath = path.join(__dirname, '..', 'build', 'tray-icon.png');
  if (!existsSync(iconPath)) return;

  tray = new Tray(iconPath);
  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    {
      label: '访问 API 文档',
      click: () => {
        shell.openExternal(`${BACKEND_URL}/docs`);
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        stopPythonBackend();
        setTimeout(() => app.quit(), 1000);
      },
    },
  ]);

  tray.setToolTip('PeachTrees Media Studio');
  tray.setContextMenu(contextMenu);
  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

// ── 应用生命周期 ─────────────────────────────────────────────────────────────────

const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    // 启动 Python 后端
    startPythonBackend();

    // 创建窗口和托盘
    createMainWindow();
    createTray();

    // macOS: 激活时恢复窗口
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow();
      }
    });
  });

  app.on('before-quit', () => {
    stopPythonBackend();
  });

  app.on('window-all-closed', () => {
    // macOS: 关闭窗口时不退出应用（保留托盘）
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });
}
