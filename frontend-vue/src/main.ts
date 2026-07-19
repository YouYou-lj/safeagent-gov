import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import '@/theme/index.scss'

import { ElLoading } from 'element-plus'
import { createApp } from 'vue'

import App from '@/App.vue'
import { bootstrapDesktop } from '@/desktop/bootstrap'
import router from '@/router'
import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

async function startApplication(): Promise<void> {
  const app = createApp(App).use(pinia).use(router).use(ElLoading)
  const desktop = await bootstrapDesktop()
  if (desktop) useAuthStore(pinia).setEphemeralToken(desktop.token)
  app.mount('#app')
}

function renderStartupFailure(error: unknown): void {
  const root = document.querySelector<HTMLElement>('#app')
  if (!root) return
  const panel = document.createElement('main')
  panel.style.cssText =
    'max-width:720px;margin:12vh auto;padding:32px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;line-height:1.7;color:#17324d'
  const title = document.createElement('h1')
  title.textContent = '本地安全服务启动失败'
  const detail = document.createElement('p')
  detail.textContent = String(error)
  const hint = document.createElement('p')
  hint.textContent = '请退出应用后重试；若问题持续，请运行 desktop 中的 Sidecar 验证命令。'
  panel.append(title, detail, hint)
  root.replaceChildren(panel)
}

void startApplication().catch(renderStartupFailure)
