import type { RouteRecordRaw } from 'vue-router'

import AppLayout from '@/layout/AppLayout.vue'

export const commonRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    component: AppLayout,
    redirect: '/dashboard',
    meta: { title: 'GovSafeAgent', description: '政企智能体安全控制台', icon: 'Monitor', order: 0 },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: { title: '安全总览', description: '核心运行态势与风险信号', icon: 'DataAnalysis', order: 10 },
      },
      {
        path: 'workbench',
        name: 'SecurityWorkbench',
        component: () => import('@/views/security-workbench/index.vue'),
        meta: { title: '安全检测台', description: 'Skill、MCP、Agent 与模型统一测试入口', icon: 'Aim', order: 15 },
      },
      {
        path: 'agent',
        name: 'AgentPlayground',
        component: () => import('@/views/agent-playground/index.vue'),
        meta: { title: '智能体演练', description: '四场景安全智能体编排验证', icon: 'Cpu', order: 20 },
      },
      {
        path: 'skills',
        name: 'SkillCenter',
        component: () => import('@/views/skill-center/index.vue'),
        meta: { title: 'Skill 中心', description: '独立创新 Skill 注册与运行证据', icon: 'Collection', order: 30 },
      },
      {
        path: 'mcp',
        name: 'MCPGateway',
        component: () => import('@/views/mcp-gateway/index.vue'),
        meta: { title: 'MCP 网关', description: '工具调用最小权限与策略裁决', icon: 'Connection', order: 40 },
      },
      {
        path: 'graphify',
        name: 'GraphifyCenter',
        component: () => import('@/views/graphify-center/index.vue'),
        meta: { title: '能力图谱', description: 'Graphify-Gov 能力检索与路径证据', icon: 'Share', order: 50 },
      },
      {
        path: 'router',
        name: 'RouterMonitor',
        component: () => import('@/views/router-monitor/index.vue'),
        meta: { title: '路由监控', description: 'SafeRouter-Gov 计划与任务运行态势', icon: 'Guide', order: 60 },
      },
      {
        path: 'approvals',
        name: 'ApprovalCenter',
        component: () => import('@/views/approval-center/index.vue'),
        meta: { title: '审批中心', description: '高风险动作人工闭环处置', icon: 'Checked', order: 70 },
      },
      {
        path: 'audit',
        name: 'AuditTrace',
        component: () => import('@/views/audit-trace/index.vue'),
        meta: { title: '审计追踪', description: '按 Trace 查询可验证事件链', icon: 'DocumentChecked', order: 80 },
      },
      {
        path: 'models',
        name: 'ModelGateway',
        component: () => import('@/views/model-gateway/index.vue'),
        meta: { title: '模型网关', description: '多模型路由、预算与降级治理', icon: 'Platform', order: 90 },
      },
      {
        path: 'evaluations',
        name: 'EvalCenter',
        component: () => import('@/views/eval-center/index.vue'),
        meta: { title: '安全评测', description: 'AgentSecEval-Gov 指标与结果', icon: 'Histogram', order: 100 },
      },
      {
        path: 'settings',
        name: 'SystemSettings',
        component: () => import('@/views/system-settings/index.vue'),
        meta: { title: '系统治理', description: '身份、策略版本与服务边界', icon: 'Setting', order: 110 },
      },
    ],
  },
]
