<template>
  <el-container class="layout-wrapper">
    <!-- 侧边栏 -->
    <el-aside :width="isCollapsed ? '64px' : '220px'" class="sidebar">
      <div class="logo" @click="router.push('/clone')">
        <span class="logo-icon">🍑</span>
        <span v-if="!isCollapsed" class="logo-text">PeachTrees</span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapsed"
        :collapse-transition="false"
        router
        background-color="#1e1e2e"
        text-color="#cdd6f4"
        active-text-color="#cba6f7"
        class="side-menu"
      >
        <el-menu-item index="/clone">
          <el-icon><User /></el-icon>
          <template #title>声音克隆</template>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><List /></el-icon>
          <template #title>任务记录</template>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <el-tooltip :content="isCollapsed ? '展开' : '收起'" placement="right">
          <el-button link @click="isCollapsed = !isCollapsed" class="collapse-btn">
            <el-icon><Fold v-if="!isCollapsed" /><Expand v-else /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
    </el-aside>

    <!-- 主内容区 -->
    <el-container>
      <!-- 顶栏 -->
      <el-header class="topbar">
        <div class="topbar-left">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/clone' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentPageTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
      </el-header>

      <!-- 主体 -->
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const isCollapsed = ref(false)

const activeMenu = computed(() => route.path)

const pageTitles = {
  '/clone': '声音克隆',
  '/tasks': '任务记录',
}
const currentPageTitle = computed(() => {
  if (route.path.startsWith('/tasks/')) return '任务详情'
  return pageTitles[route.path] || ''
})
</script>

<style scoped>
.layout-wrapper { height: 100vh; overflow: hidden; }

.sidebar {
  background: #1e1e2e;
  display: flex;
  flex-direction: column;
  transition: width 0.3s;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  cursor: pointer;
  border-bottom: 1px solid #313244;
  gap: 10px;
}
.logo-icon { font-size: 24px; }
.logo-text { color: #cba6f7; font-size: 18px; font-weight: 700; white-space: nowrap; }

.side-menu { border-right: none; flex: 1; }

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid #313244;
  display: flex;
  justify-content: flex-end;
}
.collapse-btn { color: #6c7086; }

.topbar {
  height: 60px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}
.topbar-right { display: flex; align-items: center; gap: 20px; }
.user-avatar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 8px;
}
.username { font-size: 14px; color: #303133; font-weight: 500; }

.main-content {
  background: #f5f7fa;
  overflow-y: auto;
  padding: 24px;
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
