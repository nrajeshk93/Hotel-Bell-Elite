import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--allow-file-access-from-files','--disable-web-security','--no-sandbox']
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 520, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(path.join(__dirname, 'six_font_probe.html')).href, { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);
  await new Promise(r => setTimeout(r, 500));
  await page.screenshot({ path: path.join(__dirname, 'six_font_probe.png') });
  console.log('ok');
} finally { await browser.close(); }
