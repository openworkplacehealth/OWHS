#!/usr/bin/env python3
"""Parity and privacy test for the browser checker at site/check/: the page must give the reference tools' verdicts, and
must make no request while it checks a file.

    python tools/check_browser_checker.py [--chrome PATH] [--screenshots DIR] [--keep-going]

Every fixture is run twice. Once through the command line, as CI and the validation report run it:
    python tools/validate.py schemas/v0.2/<Entity>.json examples/v0.2/<file>        (every examples/v0.2 file)
    python tools/check_entity_graph.py <bundle>                                     (EntityGraph.valid.json and every case)
and once through the page itself, in headless Chrome driven over the DevTools protocol (no browser-automation library):
the fixture's text is put in the page's text box, its type chosen, the Check button pressed and the page's own JSON report
read back. The test fails on any difference in verdict (exit code, and for bundles the checker's state) or in the rule
identifiers reported (for bundles, the rule and JSON pointer of every error). Differences in message wording alone are
counted and printed but do not fail the test, since they can only arise from a different jsonschema release on the
command line than the one the page vendors; the count says when to update the page's copy.

It also checks, on the same page:
  - type detection names the right type for every passing record fixture (the page's convenience, not a verdict);
  - a file chosen through the file input is checked byte for byte as given;
  - after the first check has loaded the engine, the browser is switched offline and every later check still runs;
  - the browser records no request after that point, the local server receives none, and no request at any point goes
    anywhere but the page's own origin;
  - the page's Content-Security-Policy reports no violation, and the page has no visit-counting script;
  - the policy is in force: a deliberate request to another origin, made at the end, is refused and reported.

Needs only the Python standard library, the packages in requirements.txt and a Chrome or Chromium binary (found on PATH,
at the usual macOS location, or given with --chrome or the CHROME environment variable). Exit 0 all checks passed, 1 a
check failed, 2 the test could not run.
"""
import base64, functools, http.server, json, os, queue, shutil, socketserver, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PY = sys.executable


# ---------------------------------------------------------------- local static server (records every path it serves)
class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript", ".js": "text/javascript",
                      ".wasm": "application/wasm", ".whl": "application/zip", ".woff2": "font/woff2", ".json": "application/json"}
    log = []

    def log_message(self, *a): pass

    def do_GET(self):
        Handler.log.append(self.path)
        return super().do_GET()


def serve():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(SITE)))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


# ---------------------------------------------------------------- Chrome over --remote-debugging-pipe
def find_chrome(given):
    for c in [given, os.environ.get("CHROME"), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]:
        if c and (shutil.which(c) or Path(c).exists()): return shutil.which(c) or c
    return None


class Chrome:
    def __init__(self, exe):
        self.profile = tempfile.mkdtemp(prefix="owhs-chrome-")
        to_chrome_r, self._w = os.pipe()
        self._r, from_chrome_w = os.pipe()
        def wire():
            os.dup2(to_chrome_r, 3); os.dup2(from_chrome_w, 4)
        args = [exe, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                "--disable-gpu", "--disable-extensions", "--disable-background-networking", "--disable-component-update", "--disable-sync",
                "--metrics-recording-only", "--disable-default-apps", "--mute-audio", "--hide-scrollbars", "about:blank"]
        if sys.platform.startswith("linux"): args.insert(1, "--no-sandbox")       # CI runners restrict the user namespaces Chrome's sandbox uses
        self.proc = subprocess.Popen(args, preexec_fn=wire, close_fds=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_chrome_r); os.close(from_chrome_w)
        self._id, self._pending, self.events, self._lock = 0, {}, queue.Queue(), threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        buf = b""
        while True:
            chunk = os.read(self._r, 1 << 16)
            if not chunk: break
            buf += chunk
            while b"\0" in buf:
                msg, buf = buf.split(b"\0", 1)
                m = json.loads(msg)
                if "id" in m and m["id"] in self._pending: self._pending.pop(m["id"]).put(m)
                else: self.events.put(m)

    def send(self, method, params=None, session=None, timeout=120):
        with self._lock:
            self._id += 1; i = self._id
            q = queue.Queue(); self._pending[i] = q
            msg = {"id": i, "method": method, "params": params or {}}
            if session: msg["sessionId"] = session
            os.write(self._w, json.dumps(msg).encode() + b"\0")
        m = q.get(timeout=timeout)
        if "error" in m: raise RuntimeError(f"{method}: {m['error']}")
        return m["result"]

    def close(self):
        try: self.send("Browser.close", timeout=10)
        except Exception: pass
        try: self.proc.wait(10)
        except Exception: self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


class Page:
    """One tab, with every network request, console error and CSP violation recorded."""
    def __init__(self, chrome, width=1280, height=900, mobile=False):
        self.c = chrome
        t = chrome.send("Target.createTarget", {"url": "about:blank"})
        self.s = chrome.send("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})["sessionId"]
        for d in ("Page", "Network", "Runtime", "Log"): self.cmd(f"{d}.enable")
        self.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective+' '+e.blockedURI));"})
        self.size(width, height, mobile)
        self.requests, self.errors = [], []

    def cmd(self, method, params=None, timeout=120): return self.c.send(method, params, self.s, timeout)

    def size(self, width, height, mobile=False):
        self.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 2 if mobile else 1, "mobile": mobile})

    def drain(self):
        while True:
            try: m = self.c.events.get_nowait()
            except queue.Empty: return
            if m.get("sessionId") != self.s: continue
            p = m.get("params", {})
            if m["method"] == "Network.requestWillBeSent": self.requests.append(p["request"]["url"])
            elif m["method"] == "Log.entryAdded" and p["entry"]["level"] == "error": self.errors.append(p["entry"].get("text", ""))
            elif m["method"] == "Runtime.exceptionThrown": self.errors.append(p["exceptionDetails"].get("text", ""))
            elif m["method"] == "Page.loadEventFired": self._loaded = True

    def goto(self, url):
        self._loaded = False
        self.cmd("Page.navigate", {"url": url})
        end = time.time() + 60
        while not self._loaded and time.time() < end: time.sleep(0.05); self.drain()
        if not self._loaded: raise RuntimeError(f"page did not load: {url}")

    def js(self, expr, timeout=180):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, timeout=timeout)
        self.drain()
        if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"]["text"])
        return r["result"].get("value")

    def screenshot(self, path, full=True):
        params = {"format": "png"}
        if full:
            m = self.cmd("Page.getLayoutMetrics")["cssContentSize"]
            params.update({"captureBeyondViewport": True, "clip": {"x": 0, "y": 0, "width": m["width"], "height": m["height"], "scale": 1}})
        Path(path).write_bytes(base64.b64decode(self.cmd("Page.captureScreenshot", params)["data"]))


WAIT_FOR_REPORT = """
(async () => {
  const run = document.getElementById('run'), out = document.getElementById('report-json');
  for (let i = 0; i < 9000; i++) {
    await new Promise(r => setTimeout(r, 20));
    if (out.textContent && !run.disabled) return out.textContent;
  }
  return null;
})()"""


def page_check(page, text, kind):
    """Through the page's own controls: the text box, the type list and the Check button. Returns the page's JSON report."""
    page.js(f"""(() => {{
      document.getElementById('report-json').textContent = '';
      const k = document.getElementById('kind'); k.value = {json.dumps(kind)};
      const t = document.getElementById('input'); t.value = {json.dumps(text)}; t.dispatchEvent(new Event('input'));
      document.getElementById('run').click();
    }})()""")
    out = page.js(WAIT_FOR_REPORT)
    if out is None: raise RuntimeError("the page produced no report")
    return json.loads(out)


# ---------------------------------------------------------------- the reference, through the command line
def native_record(entity, path):
    r = subprocess.run([PY, str(ROOT / "tools" / "validate.py"), str(ROOT / "schemas" / "v0.2" / f"{entity}.json"), str(path)], capture_output=True, text=True)
    return r.returncode, [l for l in r.stdout.splitlines() if l.startswith("[")]


def native_bundle(path):
    r = subprocess.run([PY, str(ROOT / "tools" / "check_entity_graph.py"), str(path)], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout)


def tags(lines): return sorted({l[1:l.index("]")] for l in lines})


def main(argv):
    exe = find_chrome(argv[argv.index("--chrome") + 1] if "--chrome" in argv else None)
    shots = Path(argv[argv.index("--screenshots") + 1]) if "--screenshots" in argv else None
    if not exe: print("[tool] no Chrome or Chromium found; give --chrome PATH or set CHROME", file=sys.stderr); return 2
    records = sorted((ROOT / "examples" / "v0.2").glob("*.json"))
    bdir = ROOT / "examples" / "bundles" / "v0.2"
    bundles = [bdir / "EntityGraph.valid.json"] + [bdir / c["file"] for c in json.loads((bdir / "cases.manifest.json").read_text(encoding="utf-8"))["cases"]]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        nat_r = list(pool.map(lambda p: native_record(p.name.split(".")[0], p), records))
        nat_b = list(pool.map(native_bundle, bundles))
    failures, wording = [], []
    def fail(msg):
        failures.append(msg); print("FAIL", msg)

    httpd, origin = serve()
    chrome = Chrome(exe)
    try:
        page = Page(chrome)
        page.goto(origin + "/check/")
        t0 = time.time()
        first = page_check(page, (ROOT / "examples" / "v0.2" / "AbsenceEpisode.valid.json").read_text(encoding="utf-8"), "AbsenceEpisode")
        load_s = time.time() - t0
        if first["verdict"] != "structurally_conformant": fail(f"warm-up check did not pass: {first['verdict']}")
        loaded_requests = list(page.requests)
        foreign = [u for u in loaded_requests if not u.startswith(origin) and not u.startswith(("data:", "blob:", "about:"))]
        if foreign: fail(f"requests left the page's origin while loading: {foreign[:5]}")
        mark_server = len(Handler.log); mark_browser = len(page.requests)
        page.cmd("Network.emulateNetworkConditions", {"offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})

        same_r = same_b = 0
        for p, (code, lines) in zip(records, nat_r):
            entity = p.name.split(".")[0]
            rep = page_check(page, p.read_text(encoding="utf-8"), entity)
            got_code, got_lines = rep["tool"]["exit_code"], rep["tool"]["output"]
            got_lines = [l for l in got_lines if l.startswith("[")]
            if got_code != code: fail(f"{p.name}: exit code {got_code} in the page, {code} on the command line")
            elif tags(got_lines) != tags(lines): fail(f"{p.name}: rules {tags(got_lines)} in the page, {tags(lines)} on the command line")
            else:
                same_r += 1
                if got_lines != lines: wording.append(p.name)
            want_verdict = "structurally_conformant" if code == 0 else "not_conformant"
            if rep["verdict"] != want_verdict: fail(f"{p.name}: page shows {rep['verdict']}, the tool's exit code {code} means {want_verdict}")
            if code == 1 and len(rep["findings"]) != len([l for l in lines if not l.startswith("[profile]")]): fail(f"{p.name}: the page lists {len(rep['findings'])} findings for {len(lines)} lines")
        for p, (code, nrep) in zip(bundles, nat_b):
            rep = page_check(page, p.read_text(encoding="utf-8"), "bundle")
            g = rep.get("entity_graph_report") or {}
            key = lambda r: sorted((e["rule"], e["pointer"]) for e in r.get("errors", []))
            if rep["tool"]["exit_code"] != code or g.get("state") != nrep.get("state"): fail(f"{p.name}: page {rep['tool']['exit_code']}/{g.get('state')}, command line {code}/{nrep.get('state')}")
            elif key(g) != key(nrep): fail(f"{p.name}: errors {key(g)} in the page, {key(nrep)} on the command line")
            else:
                same_b += 1
                if g != nrep: wording.append(p.name)
        detected = 0
        valid = [p for p in records if p.name.endswith(".valid.json")]
        for p in valid:
            rep = page_check(page, p.read_text(encoding="utf-8"), "auto")
            if rep["input"] == f"one {p.name.split('.')[0]} record" and rep["record_type_chosen_by"].startswith("detected"): detected += 1
            else: fail(f"{p.name}: detected as {rep['input']!r}")
        rep = page_check(page, (bdir / "EntityGraph.valid.json").read_text(encoding="utf-8"), "auto")
        if rep["input"] != "entity-graph bundle": fail(f"EntityGraph.valid.json: detected as {rep['input']!r}")
        # a chosen file is checked as given, through the file input
        doc = page.cmd("DOM.getDocument")["root"]["nodeId"]
        node = page.cmd("DOM.querySelector", {"nodeId": doc, "selector": "#file"})["nodeId"]
        bad = ROOT / "examples" / "v0.2" / "AbsenceEpisode.invalid.json"
        page.js("document.getElementById('report-json').textContent=''; document.getElementById('kind').value='AbsenceEpisode'")
        page.cmd("DOM.setFileInputFiles", {"nodeId": node, "files": [str(bad)]})
        page.js("new Promise(r => setTimeout(r, 300))")
        page.js("document.getElementById('run').click()")
        rep = json.loads(page.js(WAIT_FOR_REPORT))
        if tags(rep["tool"]["output"]) != tags(nat_r[records.index(bad)][1]): fail("a file chosen through the file input was not checked as given")

        page.drain()
        after_browser = page.requests[mark_browser:]
        after_server = Handler.log[mark_server:]
        if after_browser: fail(f"the browser made {len(after_browser)} request(s) while checking files: {after_browser[:5]}")
        if after_server: fail(f"the server received {len(after_server)} request(s) while files were checked: {after_server[:5]}")
        csp = page.js("window.__csp")
        if csp: fail(f"Content-Security-Policy violations: {csp[:5]}")
        if page.js("typeof window.posthog") != "undefined" or page.js("!!document.querySelector('script:not([src])')"): fail("the page carries an inline or visit-counting script")
        if page.errors: fail(f"console errors: {page.errors[:5]}")
        refused = page.js("fetch('https://example.org/owhs-csp-probe').then(() => 'fetched', () => 'refused')")
        probe = page.js("window.__csp")
        if refused != "refused" or not any("connect-src" in v for v in probe): fail(f"the Content-Security-Policy is not in force: a request to another origin was {refused}, violations {probe}")
        page.cmd("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})

        print(f"records: {same_r} of {len(records)} fixtures give the same verdict and rules in the page as on the command line")
        print(f"bundles: {same_b} of {len(bundles)} fixtures give the same state, rules and pointers in the page as on the command line")
        print(f"wording: {len(wording)} fixture(s) differ only in message text{(': ' + ', '.join(wording[:8])) if wording else ''}")
        print(f"detection: {detected} of {len(valid)} passing record fixtures and the valid bundle detected as their own type")
        print(f"requests: {len(loaded_requests)} while loading the page and the engine ({first_load_mb(loaded_requests, origin):.1f} MB served), all from the page's origin; "
              f"{len(after_browser)} in the browser and {len(after_server)} at the server during {len(records) + len(bundles) + len(valid) + 2} checks made offline")
        print(f"engine load and first check: {load_s:.1f} s")

        if shots:
            shots.mkdir(parents=True, exist_ok=True)
            take_screenshots(chrome, origin, shots)
            print(f"screenshots written to {shots}")
    finally:
        chrome.close(); httpd.shutdown()
    print("all checks passed" if not failures else f"{len(failures)} check(s) FAILED")
    return 1 if failures else 0


def first_load_mb(urls, origin):
    total = 0
    for u in urls:
        if u.startswith(origin):
            p = SITE / u[len(origin):].split("?")[0].lstrip("/")
            if p.is_dir(): p = p / "index.html"
            if p.is_file(): total += p.stat().st_size
    return total / 1e6


def take_screenshots(chrome, origin, out):
    """The page empty, after a passing sample and after a failing sample, at desktop and phone widths."""
    for label, (w, h, mobile) in {"desktop": (1280, 900, False), "phone": (390, 844, True)}.items():
        page = Page(chrome, w, h, mobile)
        page.goto(origin + "/check/")
        page.js("document.fonts.ready.then(() => true)")
        page.screenshot(out / f"{label}-1-empty.png")
        for name, idx in (("2-pass", 0), ("3-fail", 1)):
            page.js("document.getElementById('report-json').textContent=''")
            page.js(f"document.querySelectorAll('button.sample')[{idx}].click()")
            page.js(WAIT_FOR_REPORT)
            page.js("new Promise(r => setTimeout(r, 400))")
            page.screenshot(out / f"{label}-{name}.png")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
