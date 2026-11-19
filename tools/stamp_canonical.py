#!/usr/bin/env python3
"""Stamp a <link rel="canonical"> on every HTML page under site/, keyed to its path, plus the favicon link and
the Open Graph / Twitter card tags (derived from each page's own <title> and description, never new copy), and apply the
robots policy: the one word in ../robots-policy.txt (noindex | index) decides the robots meta on every page.
The generators always emit noindex; this tool is what makes a build match the published posture, so a
rebuild after the lift cannot quietly put noindex back. Also places the one managed footer line (trade mark
and licence, and the no-cookies line) as the last element of every page footer, and the one managed visit-counting
script before </head>, so every generator shares them. Also adds the Atom feed links (tools/build_feeds.py) to every page head, and one line of project links (status, follow, feed, how to cite, who uses OWHS, who maintains this) to the managed footer lines. Also places the one managed structured-data block (schema.org JSON-LD, built
by tools/jsonld.py from repository data only) before the visit-counting script. Idempotent. Run before any deploy."""
import os, re, sys, pathlib
BASE = "https://openworkplacehealth.org/"
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.dont_write_bytecode = True
import jsonld
SITE = pathlib.Path(os.environ.get("OWHS_SITE_DIR", ROOT / "site"))   # overridable so registry/build_registry_site.py --check can stamp a copy
POLICY = (ROOT / "robots-policy.txt").read_text(encoding="utf-8").strip().lower() if (ROOT / "robots-policy.txt").exists() else "noindex"
if POLICY not in ("noindex", "index"):
    sys.exit(f"robots-policy.txt must say noindex or index, not {POLICY!r}")
ROBOTS = '<meta name="robots" content="noindex, nofollow">' if POLICY == "noindex" else '<meta name="robots" content="index, follow">'
MARK = ('<!-- mark --><p class="tm" style="margin-top:12px;font-size:13px;color:var(--muted,#5c646c)"><a href="/status.html">Is it maintained?</a> · <a href="/status.html#follow">Follow</a> · '
        '<a href="/feed.xml">Feed</a> · <a href="/cite.html">How to cite</a> · <a href="/using-owhs.html">Who uses OWHS</a> · <a href="/governance.html#maintainers">Who maintains this</a></p>'
        '<p class="tm" style="margin-top:6px;font-size:13px;color:var(--muted,#5c646c)">OWHS\u2122 is a trade mark of '
        'All Toogether Ltd (UK application pending). For licences and third-party wording, see the <a href="/legal.html">legal page</a>.</p>'
        '<p class="tm" style="margin-top:6px;font-size:13px;color:var(--muted,#5c646c)">No cookies, no advertising, no marketing. '
        'Visits are counted without identifying anyone. <a href="/privacy.html">Privacy</a> · <a href="/legal.html">Legal</a></p><!-- /mark -->')
# Visit counting: PostHog in cookieless mode (nothing stored on the device, IP discarded at ingest), page views and page leave only.
# person_profiles 'never': no person records are ever created and the SDK sends no $set of initial referrer/campaign properties.
ANALYTICS = ('<!-- analytics --><script>' + '!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);' +
             "posthog.init('phc_UBxs6DIFwK73c1QzudH8AWR6HHZtNAkqhpbz3lCcPfg',{api_host:'https://eu.i.posthog.com',ui_host:'https://eu.posthog.com',"
             "defaults:'2026-05-30',cookieless_mode:'always',person_profiles:'never',autocapture:false,capture_pageview:true,capture_pageleave:true,"
             "disable_session_recording:true,capture_heatmaps:false,capture_performance:false,capture_dead_clicks:false,rageclick:false,disable_surveys:true});"
             '</script><!-- /analytics -->')

# Small-screen fit shared by every page, because each page carries its own inline stylesheet. At phone width the navigation rows sit close
# together (they were five tall rows) and any table that is wider than the screen scrolls inside itself instead of widening the page, and long unbroken strings (addresses, identifiers, inline code) wrap;
# the registry matrix already has its own scroll container and is left alone.
MOBILE = ('<!-- mobile --><style>@media (max-width:640px){.nav-links{column-gap:16px;row-gap:2px;font-size:14.5px;line-height:1.4}'
          '.nav-links a{padding:5px 0}.subnav .wrap{column-gap:16px;row-gap:2px}.subnav a{padding:4px 0}'
          'table:not(.matrix){display:block;max-width:100%;overflow-x:auto}'
          'p,li,dd,a,:not(pre)>code{overflow-wrap:anywhere}td p,td li,td a,td code,th a{overflow-wrap:normal}}</style><!-- /mobile -->')

def head_mobile(t):
    t = re.sub(r"<!-- mobile -->.*?<!-- /mobile -->\n?", "", t, count=1, flags=re.S)
    if "<!-- analytics -->" in t:
        return t.replace("<!-- analytics -->", MOBILE + "\n<!-- analytics -->", 1)
    return t.replace("</head>", MOBILE + "\n</head>", 1)

def head_jsonld(t, rel):
    """One managed structured-data block before </head> (before the visit-counting script when that is present); rebuilt on every run."""
    graph = jsonld.blocks_for(rel, t, SITE)
    t = re.sub(r"<!-- jsonld -->.*?<!-- /jsonld -->\n?", "", t, count=1, flags=re.S)
    if graph is None:
        return t
    block = jsonld.serialise(graph)
    if "<!-- analytics -->" in t:
        return t.replace("<!-- analytics -->", block + "\n<!-- analytics -->", 1)
    return t.replace("</head>", block + "\n</head>", 1)

def head_analytics(t):
    """One managed script block before </head>; rebuilt on every run, added where absent."""
    if "<!-- analytics -->" in t:
        return re.sub(r"<!-- analytics -->.*?<!-- /analytics -->", lambda m: ANALYTICS, t, count=1, flags=re.S)
    if "</head>" in t:
        return t.replace("</head>", ANALYTICS + "\n</head>", 1)
    return t

def footer_mark(t):
    """One managed line at the end of the first footer; rebuilt on every run, added where absent."""
    if "<!-- mark -->" in t:
        return re.sub(r"<!-- mark -->.*?<!-- /mark -->", lambda m: MARK, t, count=1, flags=re.S)
    if "</div></footer>" in t:
        return t.replace("</div></footer>", MARK + "\n</div></footer>", 1)
    return t

n = 0
for p in sorted(SITE.rglob("*.html")):
    rel = p.relative_to(SITE).as_posix()
    if rel == "404.html":
        orig = p.read_text(encoding="utf-8"); t2 = head_analytics(footer_mark(orig))   # always noindex, never canonical; footer line + counting only
        if t2 != orig:
            p.write_text(t2, encoding="utf-8"); n += 1
        continue
    url = BASE + ("" if rel == "index.html" else rel[:-len("index.html")] if rel.endswith("/index.html") else rel)
    tag = f'<link rel="canonical" href="{url}">'
    orig = p.read_text(encoding="utf-8")
    t = re.sub(r'<meta name="robots" content="[^"]*">', ROBOTS, orig, count=1)
    if 'rel="canonical"' in t:
        t2 = re.sub(r'<link rel="canonical" href="[^"]*">', tag, t, count=1)
    elif '<meta name="robots"' in t:
        t2 = re.sub(r'(<meta name="robots"[^>]*>)', r'\1\n' + tag, t, count=1)
    else:
        print("no robots meta, skipped:", rel, file=sys.stderr); continue
    # favicon + social cards: one managed block after the canonical, rebuilt on every run from the page's own title/description
    title = re.search(r"<title>(.*?)</title>", t2, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', t2)
    block = ['<!-- auto -->', '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
             '<link rel="alternate" type="application/atom+xml" title="OWHS changelog: all changes" href="/feed.xml">',
             '<link rel="alternate" type="application/atom+xml" title="OWHS evidence sweep reports" href="/feed-sweeps.xml">',
             '<meta property="og:type" content="website">', '<meta property="og:site_name" content="Open Workplace Health Standard">',
             f'<meta property="og:url" content="{url}">']
    if title: block.append(f'<meta property="og:title" content="{" ".join(title.group(1).split())}">')
    if desc: block.append(f'<meta property="og:description" content="{desc.group(1)}">')
    # One shared social card. Without an og:image a link pasted into LinkedIn renders with no picture,
    # and summary_large_image is what makes the card the wide format rather than a thumbnail.
    block += [f'<meta property="og:image" content="{BASE}owhs-card.png">',
              '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">',
              '<meta property="og:image:alt" content="The Open Workplace Health Standard: an open data standard for UK workplace health">',
              '<meta name="twitter:card" content="summary_large_image">',
              f'<meta name="twitter:image" content="{BASE}owhs-card.png">', '<!-- /auto -->']
    block = "\n".join(block)
    if "<!-- auto -->" in t2:
        t2 = re.sub(r"<!-- auto -->.*?<!-- /auto -->", lambda m: block, t2, count=1, flags=re.S)
    else:
        t2 = t2.replace(tag, tag + "\n" + block, 1)
    t2 = head_jsonld(head_mobile(head_analytics(footer_mark(t2))), rel)
    if t2 != orig:
        p.write_text(t2, encoding="utf-8"); n += 1
print(f"canonical stamped or refreshed on {n} pages; robots policy {POLICY} applied")
