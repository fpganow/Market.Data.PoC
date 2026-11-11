const puppeteer = require('puppeteer-core'); const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' }); const p = await b.newPage();
  await p.setViewport({ width: 1300, height: 1800 });
  await p.goto('https://fpganow.com/index.php/run-on-hardware/', { waitUntil: 'networkidle2' });
  const st = () => p.$eval('#hwrun-status', e => e.textContent);
  for (let i = 0; i < 30 && !/loaded/.test(await st()); i++) await sleep(1000);
  await p.select('#hwrun-pcap', 'frame_boundary_repro'); await p.select('#hwrun-impl', 'labview'); await p.click('#hwrun-run');
  let s; for (let i = 0; i < 150; i++) { s = await st(); if (/^(Done|Run failed|Could not)/.test(s)) break; await sleep(1000); }
  console.log('status: ' + s + '  ' + p.url());
  await p.click('#hwrun-report-toggle');
  const rep = await p.$eval('#hwrun-report', e => e.textContent);
  console.log(rep.split('\n').filter(l => /per frame|frame\s+\d/.test(l)).join('\n'));
  await p.screenshot({ path: process.argv[2] + '/page_final.png', fullPage: true });
  await p.close(); b.disconnect();
})().catch(e => { console.error('FAILED ' + e.message); process.exit(1); });
