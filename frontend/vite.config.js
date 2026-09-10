import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import path from 'node:path'

// 跨平台推导 backend/static 绝对路径
const projectRoot = path.resolve(__dirname, '..')
const staticDir = path.join(projectRoot, 'backend', 'static')

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    outDir: staticDir,    // 阶段2：构建产物直接写入 backend/static，由 FastAPI 托管
    emptyOutDir: true,   // 构建前清空目录，避免残留旧文件
  },
  server: {
    port: 5173,
    proxy: {
      // 前端 baseURL=/api，后端路由已加 prefix="/api"，直接透传即可
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout: 600000,       // 模型首次加载可能需数分钟
        proxyTimeout: 600000,
      }
    }
  }
})
