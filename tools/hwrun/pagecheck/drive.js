const puppeteer = require('puppeteer-core');
const fs = require('fs');
const OUT = process.argv[2] || "."; const URL = 'https://fpganow.com/index.php/run-on-hardware/';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });
  const page = await browser.newPage();
  await page.setViewport({ width: 1300, height: 1800 });
  const errors = []; page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  const status = () => page.$eval('#hwrun-status', e => e.textContent);
  const waitStatus = async (re, ms) => { const t0 = Date.now(); let s; while (Date.now() - t0 < ms) { s = await status(); if (re.test(s)) return s; await sleep(1000); } throw new Error('timeout waiting for ' + re + ', last status: ' + s); };

  async function runOnce(pcap, impl, tag) {
    await page.select('#hwrun-pcap', pcap); await page.select('#hwrun-impl', impl);
    await page.click('#hwrun-run');
    const t0 = Date.now();
    const s = await waitStatus(/^(Done|Run failed|Could not start)/, 150000);
    const secs = ((Date.now() - t0) / 1000).toFixed(0);
    console.log(`\n### ${tag}: "${s}" after ${secs} s`);
    if (!/^Done/.test(s)) return null;
    const cards = await page.$$eval('#hwrun-cards .hwrun-card', els => els.map(e => e.querySelector('.hwrun-card-label').textContent + ' = ' + e.querySelector('.hwrun-card-value').textContent));
    cards.forEach(c => console.log('  card: ' + c));
    const frames = await page.$$eval('#hwrun-frames tbody tr', trs => trs.map(tr => [...tr.cells].map(c => c.textContent).join(' | ')));
    console.log('  per-frame rows: ' + frames.length); frames.forEach(f => console.log('    ' + f));
    const nrows = await page.$$eval('#hwrun-table tbody tr', trs => trs.length);
    const warn = await page.$$eval('#hwrun-table tbody tr.is-warn', trs => trs.length);
    const na = await page.$$eval('#hwrun-table tbody td span[title]', s => s.length);
    console.log(`  message rows: ${nrows}, warn rows: ${warn}, n/a latency cells: ${na}`);
    const csv = await page.$eval('#hwrun-csv', a => a.href);
    const csvInfo = await page.evaluate(async u => { const r = await fetch(u); const t = await r.text(); return { status: r.status, ct: r.headers.get('content-type'), lines: t.split('\n').length, head: t.split('\n')[0].slice(0, 120) }; }, csv);
    console.log('  csv: ' + JSON.stringify(csvInfo));
    await page.click('#hwrun-report-toggle');
    const rep = await page.$eval('#hwrun-report', e => ({ hidden: e.hidden, len: e.textContent.length }));
    console.log('  report after toggle: ' + JSON.stringify(rep));
    const chart = await page.$eval('#hwrun-chart', c => ({ w: c.width, h: c.height }));
    console.log('  chart canvas: ' + JSON.stringify(chart) + ' url: ' + page.url());
    await page.screenshot({ path: `${OUT}/page_${tag}.png`, fullPage: true });
    return page.url();
  }

  await page.goto(URL, { waitUntil: 'networkidle2' });
  console.log('initial status: "' + await waitStatus(/loaded|not available/, 30000) + '"');
  const opts = await page.$$eval('#hwrun-pcap option', o => o.map(x => x.value));
  console.log('pcap options: ' + opts.join(', '));
  console.log('impl options: ' + (await page.$$eval('#hwrun-impl option', o => o.map(x => x.value + '=' + x.textContent))).join('; '));

  const url1 = await runOnce('frame_boundary_repro', 'labview', 'labview');
  // immediate second click: cooldown path
  await page.click('#hwrun-run');
  console.log('\n### immediate re-run: "' + await waitStatus(/Could not start|Queued|Done|Run failed/, 30000) + '"');
  console.log('  run button disabled: ' + await page.$eval('#hwrun-run', b => b.disabled));
  await sleep(22000);
  await runOnce('frame_boundary_repro', 'rtl', 'rtl');

  // shareable link
  if (url1) {
    await page.goto(url1, { waitUntil: 'networkidle2' });
    const s = await waitStatus(/^(Done|Run failed|Lost)/, 30000);
    const n = await page.$$eval('#hwrun-table tbody tr', trs => trs.length);
    console.log('\n### shareable link ' + url1 + '\n  status: "' + s + '", rows: ' + n);
  }
  // phone width
  await page.setViewport({ width: 390, height: 844, isMobile: true });
  await page.goto(URL, { waitUntil: 'networkidle2' }); await waitStatus(/loaded|not available/, 30000);
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  console.log('\n### phone viewport scrollWidth: ' + sw);
  await page.screenshot({ path: `${OUT}/page_phone.png`, fullPage: false });
  console.log('\nJS errors: ' + (errors.length ? errors.join('\n  ') : 'none'));
  await page.close(); browser.disconnect();
})().catch(e => { console.error('FAILED: ' + e.message); process.exit(1); });
