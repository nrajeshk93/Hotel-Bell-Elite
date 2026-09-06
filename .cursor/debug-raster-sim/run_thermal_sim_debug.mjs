import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const HTML = path.join(path.dirname(fileURLToPath(import.meta.url)), 'sim_current.html');
const browser = await puppeteer['launch']({ executablePath: CHROME, headless: 'new', args: ['--allow-file-access-from-files','--disable-web-security','--no-sandbox'] });
const page = await browser.newPage();
page.on('pageerror', e => console.log('PAGEERROR', e.message));
page.on('console', m => console.log('CONSOLE', m.type(), m.text()));
const url = pathToFileURL(HTML).href;
console.log('goto', url);
const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
console.log('status', resp && resp.status());
await new Promise(r => setTimeout(r, 2000));
const info = await page.evaluate(() => ({
  title: document.title,
  scripts: document.scripts.length,
  hasRun: typeof window.run,
  hasH2c: typeof window.html2canvas,
  hasBuild: typeof window.buildPosCustomerBillHtml,
  bodyLen: (document.body && document.body.innerHTML.length) || 0,
  firstText: (document.body && document.body.innerText || '').slice(0,200)
}));
console.log(JSON.stringify(info,null,2));
await browser.close();
