import json, sys, time, urllib.request, urllib.error
BASE = "https://fpganow.com/wp-json/fpganow-hwrun/v1/"
def call(path, body=None):
    data = json.dumps(body).encode() if body else None
    hdr = {"Content-Type": "application/json", "X-FPGANOW-HWRUN": "1"} if body else {}
    req = urllib.request.Request(BASE + path, data=data, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:300]
pcap = sys.argv[1]
for impl in sys.argv[2:]:
    st, r = call("runs", {"pcap": pcap, "implementation": impl, "board": "kr260"})
    print(f"\n### {impl}: submit -> {st} {r}")
    if st != 202: continue
    rid = r["id"]; t0 = time.time()
    while True:
        time.sleep(3)
        st, run = call("runs/" + rid)
        if st != 200: print("poll", st, run); continue
        if run["status"] in ("done", "failed"): break
        if time.time() - t0 > 300: print("timeout"); break
    print(f"status: {run['status']} in {time.time()-t0:.0f} s")
    for l in run.get("log", []): print("  log:", l)
    print("summary:", json.dumps(run.get("summary"), indent=None))
    if run.get("error"): print("error:", run["error"])
    rows = run.get("rows") or []
    bad = [x for x in rows if not x.get("match", x.get("ok", True))]
    print(f"rows: {len(rows)}  mismatches: {len(bad)}")
    for x in bad[:5]: print("   ", json.dumps(x)[:300])
    rep = run.get("report") or ""
    if rep: print("report tail:\n" + "\n".join(rep.strip().splitlines()[-8:]))
