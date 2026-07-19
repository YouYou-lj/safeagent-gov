<script setup lang="ts">
import {
  Aim,
  Checked,
  Collection,
  Connection,
  Cpu,
  DataAnalysis,
  DocumentChecked,
  Expand,
  Fold,
  Guide,
  Histogram,
  Key,
  Monitor,
  Platform,
  Setting,
  Share,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { computed, ref, watch } from 'vue'
import type { RouteMeta, RouteRecordRaw } from 'vue-router'
import { useRoute, useRouter } from 'vue-router'

import { commonRoutes } from '@/router/routes/common'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const collapsed = ref(false)
const mobileNavigation = ref(false)
const tokenDialog = ref(false)
const tokenDraft = ref(auth.token)

const icons: Record<string, Component> = {
  Aim,
  Checked,
  Collection,
  Connection,
  Cpu,
  DataAnalysis,
  DocumentChecked,
  Guide,
  Histogram,
  Monitor,
  Platform,
  Setting,
  Share,
}

const navigation = computed(() => {
  const children = commonRoutes[0]?.children ?? []
  return children
    .filter((item): item is RouteRecordRaw & { meta: RouteMeta } => item.meta !== undefined)
    .sort((left, right) => left.meta.order - right.meta.order)
})

watch(
  () => route.path,
  () => {
    mobileNavigation.value = false
  },
)

function saveToken(): void {
  auth.setToken(tokenDraft.value)
  tokenDialog.value = false
}

function clearToken(): void {
  auth.clearToken()
  tokenDraft.value = ''
}

function navigate(path: string): void {
  void router.push(path)
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-shell__sidebar" :class="{ 'app-shell__sidebar--collapsed': collapsed }">
      <div class="brand" @click="navigate('/dashboard')">
        <span class="brand__mark">G</span>
        <div v-if="!collapsed" class="brand__copy">
          <strong>GovSafeAgent</strong>
          <small>GOV AI SECURITY</small>
        </div>
      </div>
      <el-menu
        :default-active="route.path"
        :collapse="collapsed"
        :collapse-transition="false"
        class="navigation"
        router
      >
        <el-menu-item v-for="item in navigation" :key="item.path" :index="`/${item.path}`">
          <el-icon><component :is="icons[item.meta.icon]" /></el-icon>
          <template #title>
            {{ item.meta.title }}
          </template>
        </el-menu-item>
      </el-menu>
      <button class="collapse-button" type="button" @click="collapsed = !collapsed">
        <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon>
        <span v-if="!collapsed">收起导航</span>
      </button>
    </aside>

    <el-drawer
      v-model="mobileNavigation"
      direction="ltr"
      size="280px"
      :with-header="false"
    >
      <div class="brand brand--drawer">
        <span class="brand__mark">G</span>
        <div class="brand__copy">
          <strong>GovSafeAgent</strong><small>GOV AI SECURITY</small>
        </div>
      </div>
      <el-menu :default-active="route.path" router>
        <el-menu-item v-for="item in navigation" :key="item.path" :index="`/${item.path}`">
          <el-icon><component :is="icons[item.meta.icon]" /></el-icon>
          <template #title>
            {{ item.meta.title }}
          </template>
        </el-menu-item>
      </el-menu>
    </el-drawer>

    <div class="app-shell__workspace">
      <header class="topbar">
        <el-button
          class="topbar__mobile-trigger"
          text
          :icon="Expand"
          @click="mobileNavigation = true"
        />
        <div class="topbar__context">
          <strong>{{ route.meta.title }}</strong>
          <span>{{ route.meta.description }}</span>
        </div>
        <button class="identity" type="button" @click="tokenDialog = true">
          <span class="identity__signal" :class="{ 'identity__signal--ready': auth.isConfigured }" />
          <span class="identity__copy">
            <strong>{{ auth.isConfigured ? auth.role : '未配置身份' }}</strong>
            <small>{{ auth.isConfigured ? `${auth.tenantId} / ${auth.subject}` : '点击配置 Bearer Token' }}</small>
          </span>
          <el-icon><Key /></el-icon>
        </button>
      </header>
      <main class="app-shell__content">
        <RouterView />
      </main>
    </div>
  </div>

  <el-dialog v-model="tokenDialog" title="配置访问身份" width="min(560px, 92vw)">
    <p class="token-dialog__notice">
      Token 仅保存在当前浏览器 localStorage，并随每次 API 请求发送。前端解析内容只用于展示，服务端签名校验才是授权依据。
    </p>
    <el-input
      v-model="tokenDraft"
      type="textarea"
      :rows="6"
      resize="none"
      placeholder="粘贴由后端签发的 Bearer Token（无需输入 Bearer 前缀）"
      show-word-limit
      maxlength="8192"
    />
    <template #footer>
      <el-button
        type="danger"
        plain
        :disabled="!auth.isConfigured"
        @click="clearToken"
      >
        清除本地 Token
      </el-button>
      <el-button type="primary" @click="saveToken">
        保存配置
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped lang="scss">
.app-shell {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  min-height: 100dvh;

  &__sidebar {
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    flex-direction: column;
    width: var(--safe-layout-sidebar);
    height: 100dvh;
    border-right: 1px solid var(--safe-color-border);
    background: var(--safe-color-surface);
    transition: width 180ms ease;

    &--collapsed { width: 64px; }
  }

  &__workspace { min-width: 0; }

  &__content {
    width: min(100%, 1560px);
    margin: 0 auto;
    padding: 28px clamp(18px, 3vw, 42px) 52px;
  }
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  height: var(--safe-layout-header);
  padding: 10px 14px;
  overflow: hidden;
  cursor: pointer;

  &--drawer { padding: 6px 10px 18px; }

  &__mark {
    display: grid;
    flex: 0 0 38px;
    width: 38px;
    height: 38px;
    place-items: center;
    border-radius: 10px;
    color: var(--safe-color-text-inverse);
    background: var(--safe-color-accent);
    font-weight: 900;
  }

  &__copy {
    display: grid;
    min-width: 130px;

    strong { font-size: 17px; letter-spacing: 0.08em; }
    small { margin-top: 2px; color: var(--safe-color-text-secondary); font-size: 9px; letter-spacing: 0.12em; }
  }
}

.navigation {
  flex: 1;
  overflow-y: auto;
  border-right: 0;
}

.collapse-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 48px;
  border: 0;
  border-top: 1px solid var(--safe-color-border);
  color: var(--safe-color-text-secondary);
  background: transparent;
  cursor: pointer;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 9;
  display: flex;
  align-items: center;
  min-height: var(--safe-layout-header);
  padding: 8px clamp(18px, 3vw, 42px);
  border-bottom: 1px solid var(--safe-color-border);
  background: color-mix(in srgb, var(--safe-color-surface) 94%, transparent);
  backdrop-filter: blur(10px);

  &__mobile-trigger { display: none; }

  &__context {
    display: grid;
    flex: 1;
    min-width: 0;

    strong { font-size: 14px; }
    span { margin-top: 3px; overflow: hidden; color: var(--safe-color-text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
  }
}

.identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 7px 11px;
  border: 1px solid var(--safe-color-border);
  border-radius: var(--safe-radius-control);
  color: var(--safe-color-text);
  background: var(--safe-color-surface);
  cursor: pointer;

  &__signal {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--safe-color-danger);

    &--ready { background: var(--safe-color-success); }
  }

  &__copy {
    display: grid;
    min-width: 138px;
    text-align: left;

    strong { font-size: 12px; }
    small { max-width: 230px; margin-top: 2px; overflow: hidden; color: var(--safe-color-text-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
  }
}

.token-dialog__notice {
  margin: 0 0 16px;
  color: var(--safe-color-text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .app-shell {
    display: block;

    &__sidebar { display: none; }
  }

  .topbar__mobile-trigger { display: inline-flex; margin-right: 8px; }
}

@media (max-width: 560px) {
  .topbar__context span,
  .identity__copy { display: none; }

  .identity { min-height: 38px; padding: 7px 10px; }
  .app-shell__content { padding-top: 22px; }
}
</style>
