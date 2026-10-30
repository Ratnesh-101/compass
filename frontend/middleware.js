// Vercel Edge Middleware / Proxy Signer
// Signs proxy requests to Compass backend with an HMAC SHA-256 edge signature
// over the current timestamp, allowing backend to safely trust parts[-2] in XFF.
// Fails closed with 500 JSON error when EDGE_HMAC_SECRET is unset in production.

import { next } from '@vercel/edge'

export const config = {
  matcher: ['/api/:path*', '/chat', '/health'],
}

const devFallbackSecret = crypto.randomUUID()

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

  const isProduction =
    process.env.VERCEL_ENV === 'production' ||
    process.env.NODE_ENV === 'production' ||
    process.env.ENVIRONMENT === 'production' ||
    process.env.ENV === 'production'

  let secret = (process.env.EDGE_HMAC_SECRET || process.env.VERCEL_EDGE_SECRET || '').trim()
  if (!secret) {
    if (isProduction) {
      return new Response(
        JSON.stringify({
          error: 'EDGE_HMAC_SECRET environment variable is missing in production',
        }),
        {
          status: 500,
          headers: { 'content-type': 'application/json' },
        }
      )
    }
    secret = devFallbackSecret
  }

  const xff = request.headers.get('x-forwarded-for') || ''
  const clientIp = xff ? xff.split(',')[0].trim() : (request.ip || '127.0.0.1')
  const nowSeconds = Math.floor(Date.now() / 1000)
  const edgeSigHeader = await buildEdgeSignature(secret, clientIp, nowSeconds)
  requestHeaders.set('x-compass-edge-sig', edgeSigHeader)

  return next({
    request: {
      headers: requestHeaders,
    },
  })
}
