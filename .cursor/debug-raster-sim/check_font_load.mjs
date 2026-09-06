import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
const require = createRequire(import.meta.url);
const puppeteer = require('puppeteer-core');
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const HTML = path.join(__dirname, 'sim_current.html');
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--allow-file-access-from-files','--disable-web-security','--no-sandbox']
});
const page = await browser.newPage();
page.on('console', m => console.log('CONSOLE', m.type(), m.text()));
await page.goto(pathToFileURL(HTML).href, { waitUntil: 'load', timeout: 60000 });
await page.waitForFunction(() => typeof window.run === 'function', { timeout: 30000 });
const info = await page.evaluate(async () => {
  // replicate font inject from run
  const html = buildPosCustomerBillHtml({"order_no":"INV/1987/2026-27","table_label":"Chair 4","outlet":"bar","saved_at":"2026-09-05 20:24:00","created_by":"Administrator","subtotal":600,"vat":60,"gst":0,"cgst":0,"ugst":0,"grand_total":660,"lines":[{"name":"BLENDERS PRIDE","qty":5,"rate":132,"line_total":660}],"payments":[{"payment_method_label":"Room Transfer","amount":660}]},{outlet:'bar',userLabel:'Administrator'});
  const iframe=document.createElement('iframe'); iframe.style.cssText='position:fixed;left:0;top:0;width:420px;height:1400px;border:0'; document.body.appendChild(iframe);
  const idoc=iframe.contentDocument; idoc.open(); idoc.write(html); idoc.close();
  if(idoc.fonts&&idoc.fonts.ready) await idoc.fonts.ready;
  const fontRoot = new URL('../../static/fonts/', location.href).href;
  const interFace=(w,f)=>'@font-face{font-family:"Inter";font-style:normal;font-weight:'+w+';font-display:swap;src:url("'+fontRoot+f+'") format("woff2")}';
  const style=idoc.createElement('style');
  style.textContent = interFace(400,'inter-latin-400-normal.woff2')+interFace(700,'inter-latin-700-normal.woff2')+interFace(800,'inter-latin-800-normal.woff2')+
    'body,.bill-sheet{font-family:"Inter",sans-serif !important} .totals .grand{font-weight:800 !important}';
  idoc.head.appendChild(style);
  const loads = {};
  for (const spec of ['400 12.5px "Inter"','700 12.5px "Inter"','800 15px "Inter"']) {
    try {
      const faces = await idoc.fonts.load(spec);
      loads[spec] = { count: faces.length, family: faces[0] && faces[0].family, status: faces[0] && faces[0].status };
    } catch (e) {
      loads[spec] = { error: String(e) };
    }
  }
  await new Promise(r=>setTimeout(r,300));
  const target = idoc.querySelector('.bill-sheet');
  const grand = idoc.querySelector('.totals .grand');
  const cs = idoc.defaultView.getComputedStyle(grand || target);
  const check = document.createElement('canvas');
  check.width = 80; check.height = 100;
  const ctx = check.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0,0,80,100);
  ctx.fillStyle = '#000';
  ctx.font = '800 72px Inter';
  ctx.fillText('6', 10, 80);
  const dataUrl = check.toDataURL('image/png');
  return {
    fontRoot,
    loads,
    computedFamily: cs.fontFamily,
    computedWeight: cs.fontWeight,
    fontsSize: idoc.fonts.size,
    sixPng: dataUrl
  };
});
console.log(JSON.stringify({...info, sixPng: info.sixPng.slice(0,60)+'...'}, null, 2));
const fs = await import('node:fs');
const m = info.sixPng.match(/^data:image\/png;base64,(.+)$/);
fs.writeFileSync(path.join(__dirname, 'inter_six_probe.png'), Buffer.from(m[1], 'base64'));
console.log('wrote inter_six_probe.png');
await browser.close();
