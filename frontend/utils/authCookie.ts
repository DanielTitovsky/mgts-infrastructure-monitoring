const MAX_PERSISTENT_COOKIE_AGE_MS = 30 * 24 * 60 * 60 * 1000

function expiryFromToken(token: string, now: number) {
  const maximumExpiry = now + MAX_PERSISTENT_COOKIE_AGE_MS

  try {
    const payload = token.split('.')[1]
    if (!payload) return maximumExpiry

    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const claims = JSON.parse(atob(padded))
    const tokenExpiry = typeof claims.exp === 'number' ? claims.exp * 1000 : Number.NaN

    return Number.isFinite(tokenExpiry) ? Math.min(tokenExpiry, maximumExpiry) : maximumExpiry
  } catch {
    return maximumExpiry
  }
}

export function tokenCookieOptions(token: string, secure: boolean, now = Date.now()) {
  return {
    path: '/',
    sameSite: 'lax' as const,
    secure,
    expires: new Date(expiryFromToken(token, now)),
  }
}
