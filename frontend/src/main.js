import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import {
  ArrowDown,
  ChatLineSquare,
  CircleCheckFilled,
  CircleCloseFilled,
  CopyDocument,
  DataAnalysis,
  Delete,
  Document,
  Download,
  Expand,
  Headset,
  Fold,
  List,
  Loading,
  Lock,
  MagicStick,
  Microphone,
  Refresh,
  Search,
  SwitchButton,
  Timer,
  Upload,
  User,
  VideoCamera,
  VideoPause,
  VideoPlay
} from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'

const app = createApp(App)

// 按需注册图标，减少首包体积
const usedIcons = {
  ArrowDown,
  ChatLineSquare,
  CircleCheckFilled,
  CircleCloseFilled,
  CopyDocument,
  DataAnalysis,
  Delete,
  Document,
  Download,
  Expand,
  Headset,
  Fold,
  List,
  Loading,
  Lock,
  MagicStick,
  Microphone,
  Refresh,
  Search,
  SwitchButton,
  Timer,
  Upload,
  User,
  VideoCamera,
  VideoPause,
  VideoPlay
}

Object.entries(usedIcons).forEach(([name, component]) => {
  app.component(name, component)
})

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
