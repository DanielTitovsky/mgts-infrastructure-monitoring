import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const requestSource = await readFile(new URL('../services/useRequest.ts', import.meta.url), 'utf8')
const nuxtConfig = await readFile(new URL('../nuxt.config.ts', import.meta.url), 'utf8')
const dokployCompose = await readFile(new URL('../../compose.dokploy.yml', import.meta.url), 'utf8')

test('frontend JWT header is configurable in browsers and stays Authorization for SSR', () => {
  assert.match(nuxtConfig, /apiTokenHeader:\s*'Authorization'/)
  assert.match(requestSource, /const apiTokenHeader = import\.meta\.client[\s\S]*?runtimeConfig\.public\.apiTokenHeader[\s\S]*?:\s*'Authorization'/)
  assert.match(requestSource, /if \(token\)\s*\{\s*const apiTokenHeader[\s\S]*?headers\[apiTokenHeader\]\s*=\s*`Bearer \$\{token\}`/)
})

test('Dokploy keeps gateway Basic auth and forwards only the configured JWT header upstream', () => {
  const backend = dokployCompose.slice(dokployCompose.indexOf('  backend:'), dokployCompose.indexOf('  frontend:'))
  const frontend = dokployCompose.slice(dokployCompose.indexOf('  frontend:'), dokployCompose.indexOf('  gateway:'))
  const gateway = dokployCompose.slice(dokployCompose.indexOf('  gateway:'), dokployCompose.indexOf('\nvolumes:'))

  assert.match(backend, /AUTH_REQUIRED:\s*'true'/)
  assert.doesNotMatch(backend, /ports:/)
  assert.match(frontend, /NUXT_PUBLIC_API_TOKEN_HEADER:\s*X-MGTS-Authorization/)
  assert.match(frontend, /ports:\s*!reset \[\]/)
  assert.match(gateway, /basic_auth\s*\{[\s\S]*?\}\s*reverse_proxy frontend:3000\s*\{/)
  assert.doesNotMatch(gateway, /\b(?:handle|route)\b/)
  assert.match(gateway, /header_up Authorization \{http\.request\.header\.X-MGTS-Authorization\}/)
  assert.match(gateway, /header_up -X-MGTS-Authorization/)
})
