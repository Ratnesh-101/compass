import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url))
const html = read('../index.html').toString('utf8')
const robots = read('../public/robots.txt').toString('utf8')
const sitemap = read('../public/sitemap.xml').toString('utf8')
const SITE = 'https://compass-farmlytics.vercel.app/'

test('index.html carries canonical, description and an indexable robots meta', () => {
  assert.match(html, new RegExp(`<link rel="canonical" href="${SITE}" />`))
  assert.match(html, /<meta name="description" content="[^"]{80,}/)
  assert.match(html, /<meta name="robots" content="index, follow/)
})

test('social share image is a real 1200x630 PNG with dimensions and alt text', () => {
  assert.match(html, /property="og:image" content="https:\/\/compass-farmlytics\.vercel\.app\/og-image\.png/)
  assert.match(html, /name="twitter:image" content="https:\/\/compass-farmlytics\.vercel\.app\/og-image\.png/)
  assert.match(html, /property="og:image:width" content="1200"/)
  assert.match(html, /property="og:image:height" content="630"/)
  assert.match(html, /property="og:image:alt" content="[^"]+"/)
  assert.match(html, /name="twitter:image:alt" content="[^"]+"/)
  const png = read('../public/og-image.png')
  assert.equal(png.subarray(1, 4).toString('ascii'), 'PNG')
  assert.equal(png.readUInt32BE(16), 1200)
  assert.equal(png.readUInt32BE(20), 630)
})

test('JSON-LD structured data parses and describes the site and the app', () => {
  const match = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)
  assert.ok(match, 'JSON-LD block must exist')
  const types = JSON.parse(match[1])['@graph'].map((node) => node['@type'])
  assert.deepEqual(types.sort(), ['SoftwareApplication', 'WebSite'])
})

test('robots.txt allows the home page, blocks the API and points to the sitemap', () => {
  assert.match(robots, /^User-agent: \*/m)
  assert.match(robots, /^Disallow: \/api\//m)
  assert.match(robots, new RegExp(`^Sitemap: ${SITE}sitemap\\.xml`, 'm'))
})

test('sitemap lists the canonical home URL', () => {
  assert.match(sitemap, new RegExp(`<loc>${SITE}</loc>`))
})
