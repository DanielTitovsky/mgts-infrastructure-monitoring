import assert from 'node:assert/strict'
import test from 'node:test'
import { tokenCookieOptions } from '../utils/authCookie.ts'

const DAY = 24 * 60 * 60 * 1000
const MAX_COOKIE_AGE = 30 * DAY

function jwt(payload) {
  return `header.${Buffer.from(JSON.stringify(payload)).toString('base64url')}.signature`
}

test('persistent JWT cookie follows the token exp and has safe browser scope', () => {
  const now = Date.UTC(2026, 0, 1)
  const expiry = Math.floor((now + 7 * DAY) / 1000)
  const options = tokenCookieOptions(jwt({ exp: expiry }), true, now)

  assert.equal(options.path, '/')
  assert.equal(options.sameSite, 'lax')
  assert.equal(options.secure, true)
  assert.equal(options.expires.getTime(), expiry * 1000)
})

test('HTTP previews do not set Secure, and missing or longer expiry stays capped at 30 days', () => {
  const now = Date.UTC(2026, 0, 1)
  const options = tokenCookieOptions(jwt({ exp: Math.floor((now + 90 * DAY) / 1000) }), false, now)

  assert.equal(options.secure, false)
  assert.equal(options.expires.getTime(), now + MAX_COOKIE_AGE)
  assert.equal(tokenCookieOptions('invalid-token', false, now).expires.getTime(), now + MAX_COOKIE_AGE)
  assert.equal(tokenCookieOptions(jwt({ sub: 'user' }), false, now).expires.getTime(), now + MAX_COOKIE_AGE)
})

test('expired token expiry is not extended by the persistent cookie', () => {
  const now = Date.UTC(2026, 0, 1)
  const expiry = Math.floor((now - DAY) / 1000)

  assert.equal(tokenCookieOptions(jwt({ exp: expiry }), true, now).expires.getTime(), expiry * 1000)
})
