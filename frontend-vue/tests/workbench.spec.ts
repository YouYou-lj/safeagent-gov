import { describe, expect, it } from 'vitest'

import type { EphemeralChatPayload, McpManifestScanPayload } from '@/api/workbench'

describe('安全检测工作台契约', () => {
  it('MCP 检测请求只携带离线描述文本', () => {
    const payload: McpManifestScanPayload = {
      content: 'name: demo',
      format: 'yaml',
      source_name: 'demo.yaml',
    }
    expect(Object.keys(payload).sort()).toEqual(['content', 'format', 'source_name'])
  })

  it('临时模型会话显式携带数据分级且禁用隐式工具字段', () => {
    const payload: EphemeralChatPayload = {
      provider: 'ollama',
      model: 'qwen3:8b',
      timeout_seconds: 15,
      messages: [{ role: 'user', content: '公开测试' }],
      max_output_tokens: 128,
      temperature: 0,
      data_classification: 'public',
    }
    expect(payload.data_classification).toBe('public')
    expect('tools' in payload).toBe(false)
    expect('capability_ticket' in payload).toBe(false)
  })
})
