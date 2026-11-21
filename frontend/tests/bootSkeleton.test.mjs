import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const htmlPath = new URL('../index.html', import.meta.url);
const cssPath = new URL('../src/index.css', import.meta.url);

const html = readFileSync(htmlPath, 'utf8');
const indexCss = readFileSync(cssPath, 'utf8');

test('a: boot-skeleton is inside #root before #boot-seo and carries accessibility attributes', () => {
  assert.ok(html.includes('id="boot-skeleton"'), 'html must contain id="boot-skeleton"');
  assert.match(html, /<div[^>]*id="boot-skeleton"[^>]*role="status"/, 'must have role="status"');
  assert.match(html, /<div[^>]*id="boot-skeleton"[^>]*aria-busy="true"/, 'must have aria-busy="true"');
  assert.ok(html.includes('Loading Compass'), 'must contain sr text "Loading Compass"');

  const rootIndex = html.indexOf('<div id="root">');
  const skeletonIndex = html.indexOf('id="boot-skeleton"');
  const seoIndex = html.indexOf('id="boot-seo"');

  assert.ok(rootIndex !== -1, 'Root element must exist');
  assert.ok(skeletonIndex !== -1, 'Skeleton element must exist');
  assert.ok(seoIndex !== -1, 'SEO element must exist');
  assert.ok(rootIndex < skeletonIndex, '#root must come before #boot-skeleton');
  assert.ok(skeletonIndex < seoIndex, '#boot-skeleton must come before #boot-seo');
});

test('b: boot-skeleton-css is <= 4096 chars, has reduced motion, media queries, and no url or @import', () => {
  const match = html.match(/<style id="boot-skeleton-css">([\s\S]*?)<\/style>/);
  assert.ok(match, '<style id="boot-skeleton-css"> must exist');
  const css = match[1];

  assert.ok(css.length <= 4096, `Expected CSS length <= 4096, got ${css.length}`);

  const reducedMotionIndex = css.indexOf('prefers-reduced-motion');
  assert.ok(reducedMotionIndex !== -1, 'CSS must contain prefers-reduced-motion');
  const afterReducedMotion = css.slice(reducedMotionIndex);
  assert.match(afterReducedMotion, /animation:\s*none/, 'CSS must contain animation: none after prefers-reduced-motion');

  assert.ok(css.includes('html[data-theme="dark"]'), 'CSS must contain html[data-theme="dark"]');
  assert.ok(css.includes('prefers-color-scheme: dark'), 'CSS must contain prefers-color-scheme: dark');
  assert.ok(css.includes('max-width: 767px'), 'CSS must contain max-width: 767px');
  assert.ok(css.includes('data-sidebar="collapsed"'), 'CSS must contain data-sidebar="collapsed"');

  assert.ok(!css.includes('url('), 'CSS must not contain url(');
  assert.ok(!css.includes('@import'), 'CSS must not contain @import');
});

test('c: token sync matches src/index.css light and dark tokens', () => {
  const match = html.match(/<style id="boot-skeleton-css">([\s\S]*?)<\/style>/);
  assert.ok(match, '<style id="boot-skeleton-css"> must exist');
  const bootCss = match[1].toLowerCase();

  const lightBlockMatch = indexCss.match(/:root,\s*:root\[data-theme="light"\]\s*\{([\s\S]*?)\}/);
  assert.ok(lightBlockMatch, 'Light token block must exist in src/index.css');
  const lightBlock = lightBlockMatch[1];

  const darkBlockMatch = indexCss.match(/:root\[data-theme="dark"\],\s*html\.dark\s*\{([\s\S]*?)\}/);
  assert.ok(darkBlockMatch, 'Dark token block must exist in src/index.css');
  const darkBlock = darkBlockMatch[1];

  const tokenNames = ['--bg-app', '--bg-card', '--bg-card-soft', '--border'];

  for (const token of tokenNames) {
    const lightValMatch = lightBlock.match(new RegExp(`${token}:\\s*(#[0-9a-fA-F]+)`));
    assert.ok(lightValMatch, `Light token ${token} must have hex value`);
    const lightVal = lightValMatch[1].toLowerCase();
    assert.ok(bootCss.includes(lightVal), `Boot CSS must contain light token value ${lightVal} for ${token}`);

    const darkValMatch = darkBlock.match(new RegExp(`${token}:\\s*(#[0-9a-fA-F]+)`));
    assert.ok(darkValMatch, `Dark token ${token} must have hex value`);
    const darkVal = darkValMatch[1].toLowerCase();
    assert.ok(bootCss.includes(darkVal), `Boot CSS must contain dark token value ${darkVal} for ${token}`);
  }
});

test('d: SEO shell content is preserved after id="boot-seo"', () => {
  const seoIndex = html.indexOf('id="boot-seo"');
  assert.ok(seoIndex !== -1, 'id="boot-seo" must exist');

  const afterSeo = html.slice(seoIndex);
  assert.ok(afterSeo.includes('Your AI Copilot for Projects, Coursework and Hackathons'));
  assert.ok(afterSeo.includes('href="/career"'));
  assert.ok(afterSeo.includes('href="/timeline"'));
  assert.ok(afterSeo.includes('href="/terms"'));
});

test('e: head contains noscript overriding skeleton and seo; body contains boot-noscript', () => {
  const headMatch = html.match(/<head>([\s\S]*?)<\/head>/);
  assert.ok(headMatch, '<head> must exist');
  const head = headMatch[1];

  assert.match(head, /<noscript>[\s\S]*?#boot-skeleton\{display:none[\s\S]*?<\/noscript>/);
  assert.match(head, /<noscript>[\s\S]*?#boot-seo\{position:static[\s\S]*?<\/noscript>/);

  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/);
  assert.ok(bodyMatch, '<body> must exist');
  const body = bodyMatch[1];

  assert.ok(body.includes('class="boot-noscript"'));
});

test('f: Google Fonts link uses non-blocking preload and onload swap with noscript fallback', () => {
  assert.ok(html.includes('rel="preload" as="style"'));
  assert.ok(html.includes("this.rel='stylesheet'"));
  assert.match(html, /<link[^>]*rel="preload"[^>]*href="https:\/\/fonts\.googleapis\.com[^"]*"[^>]*onload="this\.onload=null;this\.rel='stylesheet'"/);

  const strippedHtml = html.replace(/<noscript>[\s\S]*?<\/noscript>/g, '');
  const remainingStylesheets = strippedHtml.match(/<link[^>]*rel="stylesheet"[^>]*>/g) || [];
  for (const link of remainingStylesheets) {
    // Compare the parsed host, not a substring of the whole tag.
    const href = (link.match(/href="([^"]+)"/) || [])[1] || '';
    let host = '';
    try {
      host = new URL(href).hostname;
    } catch {
      host = '';
    }
    assert.notEqual(host, 'fonts.googleapis.com', `Found blocking stylesheet link for fonts outside noscript: ${link}`);
  }
});

test('g: theme script contains sidebar collapsed logic and boot-slow timeout', () => {
  assert.ok(html.includes("localStorage.getItem('compass.theme')"));
  assert.ok(html.includes('compass.sidebar.collapsed'));

  assert.match(html, /<p[^>]*id="boot-slow"[^>]*class="boot-slow"[^>]*hidden/);
  assert.match(html, /setTimeout\(function\(\)\s*\{[\s\S]*?boot-slow[\s\S]*?hidden\s*=\s*false[\s\S]*?\},\s*15000\)/);
});

test('h: the only script with src is /src/main.jsx', () => {
  const scriptSrcMatches = Array.from(html.matchAll(/<script[^>]*\ssrc="([^"]+)"/g)).map((m) => m[1]);
  assert.deepEqual(scriptSrcMatches, ['/src/main.jsx']);
});
