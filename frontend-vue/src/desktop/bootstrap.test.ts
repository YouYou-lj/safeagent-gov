import { describe, expect, it } from 'vitest'

import { configureApiBaseUrl, request } from '@/utils/request'

describe('desktop API boundary', () => {
  it('accepts only loopback HTTP endpoints', () => {
    configureApiBaseUrl('http://127.0.0.1:8765/')
    expect(request.defaults.baseURL).toBe('http://127.0.0.1:8765')
    expect(() => configureApiBaseUrl('https://example.com')).toThrow(/回环端口/)
    expect(() => configureApiBaseUrl('http://localhost:8765')).toThrow(/回环端口/)
  })
})
