#!/usr/bin/env python3
"""site/status.html: is this project maintained, in plain words, generated from committed data only.

    python tools/build_status.py            write site/status.html
    python tools/build_status.py --check    fail if the committed page differs from a fresh build (stamped like every page)
    python tools/build_status.py --self-test

Everything the page states is read from the repository: the schedules from .github/workflows/*.yml (the cron lines, turned into words), the last
verified month from evidence/watermarks.json, the reports and the missed month from the sweep report pages under site/sweeps/, and the feed
addresses from tools/build_feeds.py. Nothing is dated "today", so the page changes only when those files do. If the watermark file is empty the
page says that no month has yet been recorded as verified; it never infers a verified month from a report.

One small inline script is progressive enhancement. It asks GitHub's public API (api.github.com, nothing else) for the latest run of each workflow
and writes "last run: date, result" beside the job. It sends no token, stores nothing, and on any failure leaves the page exactly as generated.
The privacy page says so; --check fails if this page contacts GitHub and the privacy page does not say it.
"""
import html, json, re, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import yaml
import site_pages as sp
import build_feeds as bf

GITHUB = "https://github.com/openworkplacehealth/OWHS"
API = "https://api.github.com/repos/openworkplacehealth/OWHS/actions/workflows/{file}/runs?per_page=1&branch=main"
ORD = {1: "1st", 2: "2nd", 3: "3rd"}
DAYS = {"0": "Sundays", "1": "Mondays", "2": "Tuesdays", "3": "Wednesdays", "4": "Thursdays", "5": "Fridays", "6": "Saturdays", "7": "Sundays"}

# What each scheduled job is for, in the words of the workflow's own header comment. The keys must be exactly the workflows that have a schedule
# (the self-test refuses a new scheduled workflow with no entry here, and an entry for a workflow that no longer has one). "issues" is the
# open-issues filter that shows what the job raised; the self-test checks that a label named there is still used by the workflow.
JOBS = {
    "harvest.yml": {"name": "Evidence search", "what": "Searches the open scholarly indexes for new psychometric literature on every instrument in the registry and opens one issue for the month. "
                    "It lists candidate works to be read. It changes no dataset, no grade and no page.",
                    "issues": ("label", "evidence-sweep")},
    "retraction-watch.yml": {"name": "Corrections and retractions check", "what": "Checks every DOI the registry cites for correction, expression of concern, retraction or withdrawal notices, "
                             "and opens an issue naming the work and the records that cite it if it finds one. Nothing is removed or regraded automatically.",
                             "issues": ("title", "Retraction watch")},
    "tripwire.yml": {"name": "Monthly verification", "what": "Checks that the month's evidence search really happened and finished. If it did not, it opens one issue for the month "
                     "that names the month and the one action needed, so a missed month is noticed rather than silent.",
                     "issues": ("label", "maintenance")},
    "licence-watch.yml": {"name": "Licence check", "what": "Fetches every licence page the registry cites and compares it with the recorded baseline. It reports a change, or a page it could "
                          "not check, in one standing issue. It never edits a licence class; a person reads the page.",
                          "issues": ("label", "licence")},
}


def cron_words(cron):
    """'0 6 1 * *' -> 'Monthly, on the 1st, from 06:00 UTC'; '0 7 * * 1' -> 'Weekly, on Mondays, from 07:00 UTC'. Any other shape is refused."""
    m = re.fullmatch(r"(\d{1,2}) (\d{1,2}) (\d{1,2}|\*) \* (\d|\*)", cron.strip())
    if not m:
        raise SystemExit(f"tool error: cron {cron!r} is not a monthly or weekly shape this page can put into words")
    minute, hour, dom, dow = m.groups()
    clock = f"{int(hour):02d}:{int(minute):02d} UTC"
    if dom != "*" and dow == "*":
        n = int(dom)
        if not 1 <= n <= 28:
            raise SystemExit(f"tool error: day of month {n} is not a day every month has")
        return f"Monthly, on the {ORD.get(n, str(n) + 'th')}, from {clock}"
    if dow != "*" and dom == "*":
        return f"Weekly, on {DAYS[dow]}, from {clock}"
    raise SystemExit(f"tool error: cron {cron!r} mixes day of month and day of week")


def schedules(root=ROOT):
    """{workflow file: cron} for every workflow with exactly one schedule; a workflow with more is refused rather than half described."""
    out = {}
    for f in sorted((root / ".github" / "workflows").glob("*.yml")):
        y = yaml.safe_load(f.read_text(encoding="utf-8"))
        on = y.get(True, y.get("on")) or {}
        sch = on.get("schedule") if isinstance(on, dict) else None
        if sch:
            if len(sch) != 1:
                raise SystemExit(f"tool error: {f.name} has {len(sch)} schedules; this page describes one each")
            out[f.name] = sch[0]["cron"]
    return out


def order_key(item):
    """Monthly jobs by day of the month, then weekly ones."""
    cron = item[1].split()
    return (0, int(cron[2])) if cron[2] != "*" else (1, int(cron[4]))


def watermark_state(root=ROOT):
    w = json.loads((root / "evidence" / "watermarks.json").read_text(encoding="utf-8"))
    dates = sorted(e["last_complete_to"] for e in (w.get("entries") or {}).values() if isinstance(e, dict) and e.get("last_complete_to"))
    return dates


def sweep_reports(root=ROOT):
    """Each sweep report page: its month, its own meta line, its filing date, whether it says no verified sweep exists, and the issue it links."""
    out = []
    for f in sorted((root / "site" / "sweeps").glob("*.html")):
        t = f.read_text(encoding="utf-8")
        title = re.search(r"<title>(.*?)</title>", t, re.S).group(1).split(" | ")[0]
        meta = re.search(r'<p class="meta">(.*?)</p>', t, re.S)
        meta = " ".join(html.unescape(re.sub(r"<[^>]+>", "", meta.group(1))).split()) if meta else ""
        issue = re.search(r'href="(https://github\.com/openworkplacehealth/OWHS/issues/\d+)"[^>]*>(?:issue )?(#\d+)', t)
        out.append({"file": f.name, "month": f.stem, "title": title.replace("Evidence sweep, ", ""), "meta": meta, "missed": "no verified sweep" in meta, "issue": issue.groups() if issue else None})
    return out


def month_name(ym):
    names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    y, m = ym.split("-")
    return f"{names[int(m) - 1]} {y}"


def long_date(iso):
    y, m, d = iso.split("-")
    return f"{int(d)} {month_name(iso[:7]).split()[0]} {y}"


SCRIPT = """<script>
/* Progressive enhancement. Asks GitHub's public API for the latest run of each job and writes it beside the job. Nothing is stored; on any failure the page stays as it was. */
(function(){
  if(!window.fetch){return;}
  var API="%s";
  document.querySelectorAll("[data-wf]").forEach(function(el){
    var f=el.getAttribute("data-wf");
    fetch(API.replace("{file}",f),{headers:{"Accept":"application/vnd.github+json"}})
      .then(function(r){return r.ok?r.json():null;})
      .then(function(j){
        var run=j&&j.workflow_runs&&j.workflow_runs[0];
        if(!run||!run.created_at){return;}
        var result=run.status==="completed"?(run.conclusion||"finished"):run.status;
        el.textContent="Last run on GitHub: "+run.created_at.slice(0,10)+", "+String(result).replace(/_/g," ")+".";
      })
      .catch(function(){});
  });
})();
</script>""" % API


def render_body(root=ROOT):
    sched = schedules(root)
    reports = sweep_reports(root)
    marks = watermark_state(root)
    jobs = []
    for f, cron in sorted(sched.items(), key=order_key):
        j = JOBS[f]
        kind, val = j["issues"]
        q = f"label%3A{val}" if kind == "label" else f"%22{val.replace(' ', '+')}%22+in%3Atitle"
        issues = f"{GITHUB}/issues?q=is%3Aissue+is%3Aopen+{q}"
        issue_text = f"open issues labelled {val}" if kind == "label" else f"open issues titled {val}"
        jobs.append(f"""<div class="job">
  <h3>{sp.esc(j['name'])}</h3>
  <p class="when">{sp.esc(cron_words(cron))}</p>
  <p>{sp.esc(j['what'])}</p>
  <p class="live" data-wf="{f}"></p>
  <p class="links"><a href="{GITHUB}/actions/workflows/{f}">Run history on GitHub</a> · <a href="{issues}">{sp.esc(issue_text[0].upper() + issue_text[1:])}</a></p>
</div>""")
    latest = reports[-1]
    if marks:
        verified = (f"<p>The watermark file records a complete, accepted full-inventory search up to <strong>{long_date(marks[-1])}</strong>. "
                    "A month is recorded as verified only when the monthly verification accepts a complete search of the whole inventory and the record is committed through a reviewed pull request.</p>")
    else:
        verified = ("<p><strong>No month has yet been recorded as verified.</strong> The repository's watermark file (<code>evidence/watermarks.json</code>) is empty. "
                    "It advances only after a complete search of the whole inventory that the monthly verification accepts, and the change is committed through a reviewed pull request. "
                    "Until then this site does not claim a verified month.</p>")
    verified += (f'<p>The most recent report is <a href="sweeps/{latest["file"]}">{sp.esc(latest["title"])}</a>. Its own summary line reads: '
                 f'<em>{sp.esc(latest["meta"])}</em>. Read the report for what that run did and did not cover.</p>')
    missed = [r for r in reports if r["missed"]]
    if missed:
        items = []
        for r in missed:
            extra = f' The check that noticed it opened <a href="{r["issue"][0]}">issue {sp.esc(r["issue"][1])}</a>.' if r["issue"] else ""
            items.append(f'<li><strong>{month_name(r["month"])}.</strong> The planned search did not complete, so there is no verified search for the month. '
                         f'Read the <a href="sweeps/{r["file"]}">note on what happened</a>.{extra}</li>')
        missed_html = "<ul>" + "".join(items) + "</ul>"
    else:
        missed_html = "<p>No report in the repository records a missed month.</p>"
    report_items = "".join(f'<li><a href="sweeps/{r["file"]}">{sp.esc(month_name(r["month"]))}</a>: {sp.esc(r["meta"])}</li>' for r in reversed(reports))
    feeds = "".join(f'<li><a href="{f["file"]}">{sp.esc(f["label"])}</a> <span class="meta">({sp.esc(f["file"])})</span></li>' for f in bf.FEEDS)
    return f"""<span class="status-chip">status · generated from the repository</span>
<h1>Is this project maintained?</h1>
<p class="lede">The registry is kept up by four scheduled jobs in the public repository. This page says when each runs, what the repository records about the last months, where to see live results, and how to follow changes. It states only what the committed files show.</p>

<h2 id="what-runs">What runs and when</h2>
<p>Times are as the schedule is written in the workflow files. GitHub can start a scheduled job late, and a job can fail; the sections below say what the record shows, not what was meant to happen.</p>
{"".join(jobs)}

<h2 id="last-verified">The last verified month</h2>
{verified}

<h2 id="missed">Months that were missed</h2>
{missed_html}
<p>A missed month is a month without a verified search. It does not mean nothing was published in that field that month; it means the registry did not search for it systematically, and the note for the month says what was done instead.</p>

<h2 id="reports">Reports so far</h2>
<ul>{report_items}</ul>
<p>Registry and specification changes are in the <a href="changelog.html">changelog</a>. How the evidence search works, and what it may not do, is on the <a href="automation.html">maintenance page</a>.</p>

<h2 id="live">Where to see live results</h2>
<ul>
  <li><a href="{GITHUB}/actions">All workflow runs</a> on GitHub, newest first.</li>
  <li>Open issues the jobs raise: <a href="{GITHUB}/issues?q=is%3Aissue+is%3Aopen+label%3Aevidence-sweep">evidence-sweep</a>, <a href="{GITHUB}/issues?q=is%3Aissue+is%3Aopen+label%3Amaintenance">maintenance</a>, <a href="{GITHUB}/issues?q=is%3Aissue+is%3Aopen+label%3Alicence">licence</a>.</li>
</ul>
<p>The grey "last run" lines above come from GitHub's public API. When you open this page, your browser asks api.github.com for the latest run of each job; GitHub receives your IP address as any site you visit does, and nothing is sent or stored by us. If your browser blocks the request or GitHub does not answer, the lines do not appear and the rest of the page is unchanged. They show the latest run of any kind, including one started by hand, so read them with the run history. See the <a href="privacy.html">privacy page</a>.</p>

<h2 id="follow">Follow</h2>
<p>There is no email sign-up and this site collects no addresses. Ways to follow without one:</p>
<ul>
  <li><strong>Feeds</strong> (Atom, for a feed reader). Each entry carries the date the changelog or report gives it.
    <ul>{feeds}</ul></li>
  <li><strong>The changelog</strong> on this site: <a href="changelog.html">every change to the registry, the specification and the site</a>, newest first.</li>
  <li><strong>On GitHub, for developers:</strong> open the <a href="{GITHUB}">repository</a>, choose Watch, then Custom, then Releases, to be told when a tagged release is published. Choose Issues or Pull requests as well to follow discussion. Tagged releases are listed on the <a href="{GITHUB}/releases">releases page</a>.</li>
</ul>
{SCRIPT}"""


def build(root=ROOT):
    return sp.shell("Status: is OWHS maintained? | OWHS",
                    "What runs and when, the last month recorded as verified, the months that were missed, where to see live results, and how to follow OWHS, all from the repository's own files.",
                    render_body(root))


def privacy_problems(root=ROOT):
    page = (root / "site" / "status.html").read_text(encoding="utf-8") if (root / "site" / "status.html").exists() else build(root)
    priv = (root / "site" / "privacy.html").read_text(encoding="utf-8")
    out = []
    if "api.github.com" in page and "api.github.com" not in priv:
        out.append("the status page contacts api.github.com and the privacy page does not say so")
    mine = [x for x in re.findall(r"<script>(.*?)</script>", page, re.S) if "data-wf" in x]   # the page's own script, not the managed visit-counting one
    if len(mine) != 1:
        return out + [f"expected exactly one status script, found {len(mine)}"]
    hosts = set(re.findall(r"https?://([a-z0-9.-]+)", mine[0]))
    if hosts - {"api.github.com"}:
        out.append(f"the status page's script names a host other than api.github.com: {sorted(hosts - {'api.github.com'})}")
    vj = json.loads((root / "vercel.json").read_text(encoding="utf-8"))
    for h in vj.get("headers", []):
        for kv in h.get("headers", []):
            if kv.get("key", "").lower() == "content-security-policy" and "api.github.com" not in kv.get("value", ""):
                out.append("vercel.json sets a Content-Security-Policy that would block api.github.com")
    if "Content-Security-Policy" in page:
        out.append("a page-level Content-Security-Policy is present and has not been checked against api.github.com")
    return out


def write():
    (sp.SITE_ROOT / "status.html").write_text(build(), encoding="utf-8")
    print("wrote status.html")


def check():
    sp.check_built(Path(__file__).resolve(), ["status.html"], "the status page")
    bad = privacy_problems()
    if bad:
        sys.exit("status page and privacy page disagree:\n" + "".join(f"  {b}\n" for b in bad))
    print("up to date: the privacy page says what the status page contacts")


def self_test():
    fails = []
    def t(name, ok, detail=""):
        if not ok:
            fails.append(f"{name} {detail}".strip())
    sched = schedules()
    t("the scheduled workflows are exactly the ones this page describes", set(sched) == set(JOBS), f"{sorted(sched)} vs {sorted(JOBS)}")
    t("cron lines become words", cron_words("0 6 1 * *") == "Monthly, on the 1st, from 06:00 UTC" and cron_words("0 8 3 * *") == "Monthly, on the 3rd, from 08:00 UTC"
      and cron_words("0 7 * * 1") == "Weekly, on Mondays, from 07:00 UTC", cron_words("0 7 * * 1"))
    t("the four schedules read as the maintenance cycle describes them",
      [cron_words(c) for _, c in sorted(sched.items(), key=order_key)] == ["Monthly, on the 1st, from 06:00 UTC", "Monthly, on the 2nd, from 07:00 UTC", "Monthly, on the 3rd, from 08:00 UTC", "Weekly, on Mondays, from 07:00 UTC"],
      [cron_words(c) for c in sched.values()])
    for bad in ("0 6 1,15 * *", "*/5 * * * *", "0 6 1 1 *", "0 6 31 * *", "0 6 1 * 1"):
        try:
            cron_words(bad); t(f"an unsupported cron {bad!r} is refused", False)
        except SystemExit:
            pass
    for f, j in JOBS.items():
        kind, val = j["issues"]
        text = (ROOT / ".github" / "workflows" / f).read_text(encoding="utf-8")
        t(f"{f}: the issue filter names something the workflow uses", (f"--label {val}" in text) if kind == "label" else (val in text), val)
    page = build()
    t("the page has one script and it names no host but api.github.com", page.count("<script>") == 1 and not privacy_problems(), privacy_problems())
    t("the page has no form and sends no credentials", "<form" not in page and "Authorization" not in page and "token" not in page.lower())
    t("every job has a live line and a link to its run history", all(f'data-wf="{f}"' in page and f"/actions/workflows/{f}" in page for f in JOBS))
    t("with an empty watermark file the page says no month is recorded as verified", bool(watermark_state()) or "No month has yet been recorded as verified" in page)
    t("the missed month is found from its report and linked", any(r["missed"] and r["month"] == "2026-10" for r in sweep_reports()) and "sweeps/2026-10.html" in page)
    t("the page names no em dash", "—" not in page and "–" not in page)
    t("the page does not promise an email sign-up", "There is no email sign-up" in page and "subscribe" not in page.lower())
    # a populated watermark changes the wording; an unreadable one is refused
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as tmp:
        r2 = Path(tmp)
        for d in (".github/workflows", "evidence", "site/sweeps"):
            shutil.copytree(ROOT / d, r2 / d)
        shutil.copy(ROOT / "vercel.json", r2 / "vercel.json")
        (r2 / "evidence" / "watermarks.json").write_text(json.dumps({"entries": {"a" * 64: {"last_complete_to": "2026-12-01"}}}), encoding="utf-8")
        body = render_body(r2)
        t("a recorded watermark is stated with its date and the no-month sentence disappears", "1 December 2026" in body and "No month has yet been recorded" not in body)
        (r2 / ".github" / "workflows" / "harvest.yml").write_text("on:\n  schedule:\n    - cron: '0 6 1 * *'\n    - cron: '0 6 2 * *'\n", encoding="utf-8")
        try:
            schedules(r2); t("a workflow with two schedules is refused", False)
        except SystemExit:
            pass
    if fails:
        print("self-test FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("self-test ok: 15 cases (cron wording, job table matches the workflows, no host but api.github.com, no form, watermark wording, missed month, no sign-up promise)")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        write()
