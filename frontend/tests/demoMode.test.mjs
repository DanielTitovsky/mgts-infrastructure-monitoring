import assert from 'node:assert/strict'
import test from 'node:test'
import { isDemoModeEnabled } from '../services/demoMode.ts'
import { mockRequest } from '../services/mockApi.ts'

test('demo mode is enabled only by the explicit public true value', () => {
  assert.equal(isDemoModeEnabled(true), true)
  assert.equal(isDemoModeEnabled('true'), true)
  assert.equal(isDemoModeEnabled(false), false)
  assert.equal(isDemoModeEnabled('false'), false)
  assert.equal(isDemoModeEnabled(undefined), false)
  assert.equal(isDemoModeEnabled('TRUE'), false)
  assert.equal(isDemoModeEnabled('1'), false)
})

test('mock object photos can be replaced and removed without a backend', async () => {
  const formData = new FormData()
  formData.append('file', new Blob(['synthetic-preview']), 'preview.png')

  const firstUpload = await mockRequest('/api/infrastructure-objects/1/photo', {
    method: 'POST',
    body: formData,
  })
  assert.equal(firstUpload.success, true)
  assert.equal(firstUpload.data.processing_status, 'pending')
  assert.match(firstUpload.data.img_url, /^data:image\/svg\+xml/)

  const replacement = await mockRequest('/api/infrastructure-objects/1/photo', {
    method: 'POST',
    body: formData,
  })
  assert.equal(replacement.success, true)
  assert.equal(replacement.data.processed_img_url, firstUpload.data.processed_img_url)

  const removal = await mockRequest('/api/infrastructure-objects/1/photo', { method: 'DELETE' })
  assert.equal(removal.success, true)
  assert.equal(removal.data.img_url, null)
  assert.equal(removal.data.processed_img_url, null)
})
