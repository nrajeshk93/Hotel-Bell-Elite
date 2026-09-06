#!/usr/bin/env node
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(import.meta.url);
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const HTML = path.join(__dirname, 'sim_current.html');
const OUT_PNG = path.join(__dirname, 'bill_512_sim_current.png');
const OUT_META = path.join(__dirname, 'bill_512_sim_current.meta.json');
async function main() {
  if (!fs.existsSync(CHROME)) throw new Error('Chrome not found at ' + CHROME);
  if (!fs.existsSync(HTML)) throw new Error('Missing ' + HTML);
  let puppeteer;
  try { puppeteer = require('puppeteer-core'); } catch (e) {
    throw new Error('puppeteer-core not installed in ' + __dirname);
  }
  const launchOpts = { executablePath: CHROME, headless: 'new',
    args: ['--allow-file-access-from-files','--disable-web-security','--no-sandbox','--disable-dev-shm-usage'] };
  const browser = await puppeteer['launch'](launchOpts);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 480, height: 1600, deviceScaleFactor: 1 });
    const fileUrl = pathToFileURL(HTML).href;
    await page.goto(fileUrl, { waitUntil: 'load', timeout: 60000 });
    await page.waitForFunction(() => typeof window.run === 'function' && typeof window.html2canvas === 'function', { timeout: 30000 });
    const meta = await page.evaluate(async () => {
      const m = await window.run();
      return { ...(m || window.__meta || {}), hasPng: !!(window.__png && String(window.__png).startsWith('data:image/png')), pngDataUrl: window.__png || null };
    });
    if (!meta.pngDataUrl) throw new Error('window.__png missing after run()');
    const m = String(meta.pngDataUrl).match(/^data:image\/png;base64,(.+)$/);
    if (!m) throw new Error('Unexpected __png data URL');
    const buf = Buffer.from(m[1], 'base64');
    fs.writeFileSync(OUT_PNG, buf);
    const outMeta = { png: OUT_PNG, bytes: buf.length, width: meta.tw, height: meta.th, canvasW: meta.canvasW, canvasH: meta.canvasH, scrollW: meta.scrollW, scale: meta.scale, thermalDots: meta.thermalDots, supersample: meta.supersample, threshold: meta.threshold, letterSpacing: meta.letterSpacing, wordSpacing: meta.wordSpacing, captureFont: meta.captureFont, computedFamily: meta.computedFamily, computedWeight: meta.computedWeight, order_no: meta.order_no, grand_total: meta.grand_total, at: new Date().toISOString() };
    fs.writeFileSync(OUT_META, JSON.stringify(outMeta, null, 2));
    console.log(JSON.stringify(outMeta, null, 2));
  } finally { await browser.close(); }
}
main().catch((err) => { console.error(err); process.exit(1); });
