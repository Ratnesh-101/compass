// Vercel Edge Middleware / Proxy Signer
// Signs proxy requests to Compass backend with an HMAC SHA-256 edge signature
// over the current timestamp, allowing backend to safely trust parts[-2] in XFF.
// Signing is skipped (fail closed) when EDGE_HMAC_SECRET is unset; there is no built-in default secret.

import { next } from '@vercel/edge'

export const config = {
  matcher: ['/api/:path*', '/chat', '/health'],
}

async function hmacSha256(secret, message) {
  const enc = new TextEncoder()
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  )
  const signature = await crypto.subtle.sign('HMAC', key, enc.encode(message))
  return Array.from(new Uint8Array(signature))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

export async function buildEdgeSignature(secret, clientIp, nowSeconds) {
  const timestamp = String(nowSeconds)
  const payload = `${clientIp}|${timestamp}`
  const signature = await hmacSha256(secret, payload)
  return `${clientIp}|${timestamp}|${signature}`
}

export default async function middleware(request) {
  const requestHeaders = new Headers(request.headers)
  requestHeaders.delete('x-compass-edge-sig')

  const secret = (process.env.EDGE_HMAC_SECRET || process.env.VERCEL_EDGE_SECRET || '').trim()
  if (secret) {
    const xff = request.headers.get('x-forwarded-for') || ''
    const clientIp = xff ? xff.split(',')[0].trim() : (request.ip || '127.0.0.1')
    const nowSeconds = Math.floor(Date.now() / 1000)
    const edgeSigHeader = await buildEdgeSignature(secret, clientIp, nowSeconds)
    requestHeaders.set('x-compass-edge-sig', edgeSigHeader)
  }

  return next({
    request: {
      headers: requestHeaders,
    },
  })
}
