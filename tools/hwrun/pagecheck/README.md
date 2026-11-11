# tools/hwrun/pagecheck - end-to-end checks of the live "Run on Hardware" page

Written 2026-10-28 while verifying the production chain (fpganow.com -> SSH tunnel -> hwrun
service on this PC -> KR260). Everything here runs from WSL; the browser is Windows Chrome.

| File | What |
|------|------|
| `prodrun.py` | API-level test: submits runs through the production REST proxy exactly as the page does (`POST runs` with `X-FPGANOW-HWRUN: 1`), polls to completion, prints log, summary, mismatches. `python3 -I prodrun.py frame_boundary_repro labview rtl` - the proxy enforces a 20 s cooldown per IP, so a second submission within 20 s gets a 429. |
| `drive.js` | Browser-level test with puppeteer-core: loads the page, runs LabVIEW then RTL, checks cards / per-frame table / 203 message rows / CSV download / scorer-report toggle / cooldown message / shareable `?hwrun=<id>` link / phone-width layout, writes `page_*.png`. |
| `verify.js` | Short version: one LabVIEW run, prints the per-frame lines of the scorer report, writes `page_final.png`. |

```bash
cd tools/hwrun/pagecheck && npm i --no-audit --no-fund        # puppeteer-core only, no browser download
# Windows Chrome, headless, DevTools on 9222 (WSL is in mirrored networking mode, so localhost is shared):
'/mnt/c/Program Files/Google/Chrome/Application/chrome.exe' --headless=new --disable-gpu \
    --remote-debugging-port=9222 --remote-allow-origins='*' --user-data-dir="$(wslpath -w /tmp/pagecheck-profile)" about:blank &
node drive.js .            # ~90 s; the second argument is the output directory for the screenshots
# stop Chrome afterwards: find the pid with `netstat -ano | findstr :9222` in PowerShell and `taskkill /F /T /PID <pid>`
# (Stop-Process by CommandLine does not match in Windows PowerShell 5).
```

Results 2026-10-28 (both from the page): LabVIEW 203/203, median 684.8 ns; RTL 203/203, median
332.8 ns. Known cosmetic issue found and fixed the same day: `eval_sim.py`'s per-frame text
block included records with recv.time 0 (todo item 19) and printed ~5e8 ns; it now skips them
like the JSON summary does and says how many it left out.

`stats.js` (2026-11-02): `node stats.js <page url> <out dir> <labview|rtl> [run id]` - runs (or, with a run id,
reopens) a result and prints the "Latency statistics" table (min / mean / median / p95 / p99 / max for
both metrics). Works against the local dev copy too: `http://localhost:8200/index.php/run-on-hardware/`.
