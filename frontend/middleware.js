// Vercel Edge Middleware / Proxy Signer
// Signs proxy requests to Compass backend with an HMAC SHA-256 edge signature
// over the current timestamp, allowing backend to safely trust parts[-2] in XFF.

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

export default async function middleware(request) {
  const secret = process.env.EDGE_HMAC_SECRET || process.env.VERCEL_EDGE_SECRET || 'compass_vercel_edge_hmac_secret_2026'
  const xff = request.headers.get('x-forwarded-for') || ''
  const clientIp = xff ? xff.split(',')[0].trim() : (request.ip || '127.0.0.1')
  const timestamp = Math.floor(Date.now() / 1000).toString()
  const payload = `${clientIp}|${timestamp}`
  const signature = await hmacSha256(secret, payload)
  const edgeSigHeader = `${clientIp}|${timestamp}|${signature}`

  const requestHeaders = new Headers(request.headers)
  requestHeaders.set('x-compass-edge-sig', edgeSigHeader)

  return new Response(null, {
    headers: requestHeaders,
  })
}
