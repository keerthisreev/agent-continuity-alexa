"""Agent Continuity Layer dashboard -- minimal, video-readable.

Shows per-role live health state, a scrolling timeline, and the
affected-work map panel. JSON endpoints are polled by the page.

Run:
    python3 dashboard/app.py [--host 127.0.0.1] [--port 5000]
                             [--scenario gray|hard|silent|healthy]
                             [--step-delay 0.6]

The dashboard builds a demo world and replays the scenario live in a
background thread so the timeline animates. Ugly is fine; readable on
video is mandatory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template_string, request

from test_continuity import make_world, incident

from sim.scorecard import render_text as _render_scorecard_text

ROLES = ("triage", "diagnosis", "remediation", "escalation")

STATE_COLORS = {
    "HEALTHY": "#2ecc71",
    "DEGRADED": "#f1c40f",
    "QUARANTINED": "#e67e22",
    "FAILOVER": "#e74c3c",
    "RECOVERING": "#9b59b6",
    "REJOIN": "#3498db",
}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Agent Continuity Layer -- live</title>
<style>
  body { background:#0d1117; color:#e6edf3; font-family:ui-monospace,Menlo,Consolas,monospace;
         margin:0; padding:18px; font-size:15px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:#8b949e; margin-bottom:14px; }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:14px; }
  .panel { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; }
  .panel h2 { font-size:14px; text-transform:uppercase; letter-spacing:1px;
              color:#8b949e; margin:0 0 10px; }
  .badge { display:inline-block; padding:8px 14px; margin:4px; border-radius:6px;
           font-weight:bold; font-size:17px; color:#0d1117; }
  .role { font-size:13px; color:#8b949e; display:block; margin-bottom:8px; }
  #timeline { height:340px; overflow-y:auto; }
  #timeline div { padding:3px 0; border-bottom:1px solid #21262d; }
  table { border-collapse:collapse; width:100%; }
  td, th { text-align:left; padding:6px 8px; border-bottom:1px solid #21262d; }
  .tick { color:#8b949e; }
</style></head>
<body>
<h1>AGENT CONTINUITY LAYER <span class="tick">-- live</span></h1>
<div class="sub">the undercover agent is always watching &middot; scenario: <span id="scen"></span>
 &middot; <a href="/showcase" style="color:#58a6ff">scenario showcase</a>
 &middot; <a href="/sim" style="color:#58a6ff">simulated Alexa+ experience</a></div>
<div class="grid">
  <div class="panel"><h2>Role health</h2><div id="roles"></div></div>
  <div class="panel"><h2>Affected work</h2><div id="affected"></div></div>
  <div class="panel"><h2>Timeline (live)</h2><div id="timeline"></div></div>
</div>
<script>
const scen = new URLSearchParams(location.search).get('scenario') || 'gray';
document.getElementById('scen').textContent = scen;
const COLORS = __COLORS__;
// Summaries can carry agent/diagnostic text: never interpolate raw HTML.
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function tick(){
  fetch('/api/health').then(r=>r.json()).then(h=>{
    document.getElementById('roles').innerHTML =
      Object.entries(h.roles).map(([role,state]) =>
        `<span class="role">${esc(role)}<br><span class="badge" style="background:${COLORS[state]||'#888'}">${esc(state)}</span></span>`
      ).join('');
  });
  fetch('/api/timeline?limit=60').then(r=>r.json()).then(t=>{
    document.getElementById('timeline').innerHTML =
      t.events.slice().reverse().map(e =>
        `<div><span class="tick">t+${String(e.tick).padStart(4,'0')}</span> <b>${esc(e.kind)}</b> ${esc(e.summary||'')}</div>`
      ).join('');
  });
  fetch('/api/affected').then(r=>r.json()).then(a=>{
    const rows = Object.entries(a.affected_work);
    document.getElementById('affected').innerHTML = rows.length
      ? '<table><tr><th>incident</th><th>disposition</th></tr>' +
        rows.map(([i,d])=>`<tr><td>${esc(i)}</td><td>${esc(d)}</td></tr>`).join('') + '</table>'
      : '<span class="tick">no incidents yet</span>';
  });
}
tick(); setInterval(tick, 1000);
</script></body></html>
""".replace("__COLORS__", json.dumps(STATE_COLORS))


def _summarize(kind: str, detail: dict) -> str:
    d = detail or {}
    if kind == "state_transition":
        return f"{d.get('agent')}: {d.get('from')} -> {d.get('to')}"
    if kind == "anomaly":
        v = d.get("violations") or []
        return (v[0][:90] if v else "")
    if kind == "critical_violation":
        v = d.get("violations") or []
        return (v[0][:90] if v else "")
    if kind in ("suspicion_canary", "targeted_canary", "recovery_probe"):
        return "PASSED" if d.get("passed") else "FAILED"
    if kind == "standby_activated":
        return f"{d.get('standby')} resumed from t+{d.get('resumed_from_tick')}"
    if kind == "fencing":
        return f"{d.get('agent')}: {d.get('action')}"
    if kind == "duplicate_write_prevented":
        return str(d.get("action_id"))
    if kind == "human_review_flagged":
        return str(d.get("reason"))[:90]
    if kind == "diagnostician_note":
        return str(d.get("note"))[:110]
    if kind == "rejoin_complete":
        return f"{d.get('agent')} at generation {d.get('new_generation')}"
    if kind == "failure_window_open":
        return str(d.get("reason"))[:90]
    return ""


def run_live(layer, store, primaries, scenario: str, step_delay: float,
             stop: threading.Event) -> None:
    """Replay the demo scenario slowly so the dashboard animates."""
    inc1, inc2 = incident("INC-1042"), incident("INC-1043")
    for inc in (inc1, inc2):
        if stop.is_set():
            return
        if inc is inc2 and scenario != "healthy":
            if scenario == "hard":
                primaries["remediation"].alive = False
            elif scenario == "silent":
                primaries["remediation"].backend.mode = "llm_down"
            else:  # gray
                primaries["remediation"].backend.mode = "gray"
        ctx = {"incident": inc}
        for role in ROLES:
            if stop.is_set():
                return
            result = layer.invoke(role, ctx, primaries[role])
            layer.apply_effects(result, store)
            ctx[role] = result["output"]
            time.sleep(step_delay)
    if scenario == "healthy" or stop.is_set():
        return
    time.sleep(step_delay)
    primaries["remediation"].alive = True
    primaries["remediation"].backend.mode = "healthy"
    layer.attempt_rejoin("remediation")


# ---------------------------------------------------------------------------
# Scenario showcase: a named gallery of the repo's failure modes and test
# cases. Each scenario builds a fresh world, runs synchronously (no
# animation delay), and returns the verdict, affected-work map, forensic
# narrative, and condensed timeline for the result page.
# ---------------------------------------------------------------------------

def _gray_setup(primaries):
    primaries["remediation"].backend.mode = "llm_down"  # alive, useless


def _hard_setup(primaries):
    primaries["remediation"].alive = False  # kill -9


def _semantic_setup(primaries):
    primaries["remediation"].backend.mode = "gray"  # plausible but wrong


def _healthy_setup(primaries):
    pass  # nothing breaks


def _run_standard(setup):
    from test_continuity import make_world, incident, process_incident
    layer, store, primaries = make_world()
    process_incident(layer, store, primaries, incident("INC-1042"))
    setup(primaries)
    process_incident(layer, store, primaries, incident("INC-1043"))
    return layer


def _run_duplicates():
    # Standby resumes mid-stage; completed work is never redone.
    from test_continuity import make_world, incident
    layer, store, primaries = make_world()
    inc = incident("INC-900")
    ctx = {"incident": inc}
    for role in ("triage", "diagnosis"):
        r = layer.invoke(role, ctx, primaries[role])
        layer.apply_effects(r, store)
        ctx[role] = r["output"]
    r = layer.invoke("remediation", ctx, primaries["remediation"])
    action = r["output"]["actions"][0]
    aid = layer._action_id(inc["id"], "remediation", 0, action)
    store.apply_effect(r["active_agent_id"], "remediation",
                       r["generation"], aid, action)
    pkg = layer.checkpoint_package("remediation", inc["id"])
    pkg.completed_action_ids.append(aid)
    primaries["remediation"].alive = False
    r2 = layer.invoke("remediation", ctx, primaries["remediation"])
    layer.apply_effects(r2, store)
    return layer


SHOWCASE_SCENARIOS = {
    "gray": {
        "title": "B — silent dependency (the gray beat)",
        "blurb": ("LLM connection breaks. The agent stays alive, HTTP 200, "
                  "well-formed output -- and useless. Caught by contract "
                  "anomaly, suspicion canary, failover."),
        "runner": lambda: _run_standard(_gray_setup),
    },
    "hard": {
        "title": "A — hard kill",
        "blurb": ("The remediation process is killed outright. Liveness "
                  "notices immediately: quarantine, failover, standby "
                  "continues the workflow."),
        "runner": lambda: _run_standard(_hard_setup),
    },
    "semantic": {
        "title": "C — gray semantic",
        "blurb": ("Plausible but wrong: proposes a forbidden database "
                  "restart with no evidence. Business-invariant violation, "
                  "targeted canary, quarantine, human flagged."),
        "runner": lambda: _run_standard(_semantic_setup),
    },
    "healthy": {
        "title": "Healthy run (no false failover)",
        "blurb": ("Nothing breaks. Every role processes both incidents "
                  "cleanly and no standby is ever triggered -- the layer "
                  "must not invent failures."),
        "runner": lambda: _run_standard(_healthy_setup),
    },
    "duplicates": {
        "title": "No duplicate actions",
        "blurb": ("Primary dies mid-stage after one action is applied. The "
                  "standby resumes from the continuity package and skips "
                  "completed work -- each effect applied exactly once."),
        "runner": _run_duplicates,
    },
}


def run_showcase_scenario(name: str, diagnostician=None) -> dict:
    """Run one gallery scenario synchronously. Returns everything the
    result page needs. diagnostician=None -> default (Nemotron only with
    explicit live opt-in via CONTINUITY_LIVE=1 + key, stub otherwise);
    tests pass the stub explicitly."""
    from continuity import metrics as m
    from continuity.diagnostician import default_diagnostician
    from continuity.nemotron import live_enabled

    spec = SHOWCASE_SCENARIOS[name]
    layer = spec["runner"]()
    report = layer.ledger.report()
    diag = diagnostician or default_diagnostician(live=live_enabled())
    narrative = diag.incident_narrative(report)
    verdict = layer.sentinel.state_of("remediation")
    timeline = [
        {"tick": e["tick"], "kind": e["kind"],
         "summary": _summarize(e["kind"], e["detail"])}
        for e in layer.ledger.timeline[-40:]
    ]
    metrics = m.compute_metrics(layer.ledger)
    return {
        "name": name,
        "title": spec["title"],
        "blurb": spec["blurb"],
        "verdict": verdict,
        "affected_work": report["affected_work"],
        "narrative": narrative,
        "timeline": timeline,
        "tsfd": metrics.get("tsfd_ticks"),
        "trv": metrics.get("trv_ticks"),
        "afr": metrics.get("afr"),
        "duplicates_prevented": report["duplicates_prevented"],
        "human_review": [h["incident"] for h in report["human_review"]],
    }


SHOWCASE_CSS = """
  body { background:#0d1117; color:#e6edf3; font-family:ui-monospace,Menlo,Consolas,monospace;
         margin:0; padding:18px; font-size:15px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:#8b949e; margin-bottom:14px; }
  .sub a { color:#58a6ff; }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:14px; }
  .panel { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px; }
  .panel h2 { font-size:14px; text-transform:uppercase; letter-spacing:1px;
              color:#8b949e; margin:0 0 10px; }
  .blurb { color:#c9d1d9; margin-bottom:10px; line-height:1.5; }
  .run { color:#58a6ff; font-weight:bold; text-decoration:none; font-size:16px; }
  .badge { display:inline-block; padding:8px 14px; border-radius:6px;
           font-weight:bold; font-size:18px; color:#0d1117; }
  .narr { background:#0d1117; border-left:3px solid #58a6ff; padding:10px 12px;
          line-height:1.6; }
  table { border-collapse:collapse; width:100%; }
  td, th { text-align:left; padding:6px 8px; border-bottom:1px solid #21262d; }
  .tick { color:#8b949e; }
  .tl { max-height:420px; overflow-y:auto; }
  .tl div { padding:3px 0; border-bottom:1px solid #21262d; }
  .wide { grid-column: 1 / -1; }
"""

SHOWCASE_INDEX_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Agent Continuity Layer -- scenario showcase</title>
<style>""" + SHOWCASE_CSS + """</style></head>
<body>
<h1>SCENARIO SHOWCASE</h1>
<div class="sub">every example in the repo, runnable on demand &middot;
<a href="/">back to live view</a></div>
<div class="grid">
__CARDS__
</div></body></html>
"""

SHOWCASE_RESULT_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Showcase -- {{ result.title }}</title>
<style>""" + SHOWCASE_CSS + """</style></head>
<body>
<h1>{{ result.title }}</h1>
<div class="sub">{{ result.blurb }} &middot; <a href="/showcase">all scenarios</a></div>
<div class="grid">
  <div class="panel"><h2>Verdict</h2>
    <span class="badge" style="background:{% if result.verdict == 'FAILOVER' %}#e74c3c{% elif result.verdict == 'HEALTHY' %}#2ecc71{% else %}#f1c40f{% endif %}">{{ result.verdict }}</span>
    <div class="blurb" style="margin-top:10px">
      detection TSFD <b>{{ result.tsfd if result.tsfd is not none else '-' }}</b> ticks &middot;
      recovery TRV <b>{{ result.trv if result.trv is not none else '-' }}</b> ticks &middot;
      recovery rate <b>{{ '%.0f' % (result.afr * 100) + '%' if result.afr is not none else '-' }}</b><br>
      duplicates prevented <b>{{ result.duplicates_prevented }}</b>
      {% if result.human_review %}&middot; human review: <b>{{ result.human_review | join(', ') }}</b>{% endif %}
    </div>
  </div>
  <div class="panel"><h2>Affected work</h2>
    {% if result.affected_work %}
    <table><tr><th>incident</th><th>disposition</th></tr>
    {% for i, d in result.affected_work.items() %}<tr><td>{{ i }}</td><td>{{ d }}</td></tr>{% endfor %}
    </table>
    {% else %}<span class="tick">no incidents</span>{% endif %}
  </div>
  <div class="panel wide"><h2>Forensic narrative</h2>
    <div class="narr">{{ result.narrative }}</div>
  </div>
  <div class="panel wide"><h2>Timeline</h2><div class="tl">
    {% for e in result.timeline | reverse %}
    <div><span class="tick">t+{{ '%04d' % e.tick }}</span> <b>{{ e.kind }}</b> {{ e.summary or '' }}</div>
    {% endfor %}
  </div></div>
</div></body></html>
"""

SHOWCASE_404_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>not found</title>
<style>""" + SHOWCASE_CSS + """</style></head>
<body><h1>NO SUCH SCENARIO</h1>
<div class="sub"><a href="/showcase">back to the gallery</a></div></body></html>
"""


# ---------------------------------------------------------------------------
# Simulated Alexa+ experience: a chat-style front end for the reliability
# layer. The chat and intent mapping are simulated (deterministic, offline);
# the engine underneath is the real continuity layer. Additive: nothing
# above this line changes behavior.
# ---------------------------------------------------------------------------

SIM_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Simulated Alexa+ experience -- Agent Continuity Layer</title>
<style>
  :root {
    --bg: #f6f8fa; --card: #ffffff; --border: #d8dee4;
    --text: #1f2328; --muted: #57606a; --faint: #8b949e;
    --accent: #0969da; --accent-dark: #0550ae;
    --ok: #1a7f37; --ok-bg: #dafbe1;
    --warn: #9a6700; --warn-bg: #fff8c5;
    --bad: #cf222e; --bad-bg: #ffebe9;
    --code-bg: #f6f8fa;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: var(--sans);
         margin: 0; padding: 0; font-size: 16px; line-height: 1.6;
         -webkit-font-smoothing: antialiased; }
  .wrap { max-width: 980px; margin: 0 auto; padding: 32px 24px 64px; }
  .kicker { color: var(--faint); font-size: 12px; text-transform: uppercase;
            letter-spacing: 2px; margin-bottom: 10px; font-weight: 600; }
  h1 { font-size: 34px; margin: 0 0 12px; line-height: 1.25; letter-spacing: -0.5px; }
  .lede { font-size: 18px; color: var(--muted); max-width: 720px; margin: 0 0 28px; }
  .taskcard { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
              padding: 22px 24px; margin: 0 0 20px; box-shadow: 0 1px 3px rgba(31,35,40,.06); }
  .taskcard .req { font-size: 18px; margin: 4px 0 16px; padding-left: 14px;
                   border-left: 3px solid var(--accent); color: var(--text); }
  .taskcard table.meta { border-collapse: collapse; margin: 0 0 18px; font-size: 14px; width: 100%; }
  .taskcard table.meta td { padding: 6px 12px 6px 0; color: var(--text); vertical-align: top; }
  .taskcard table.meta td.k { color: var(--muted); white-space: nowrap; font-weight: 600; width: 110px; }
  .cta-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 0 0 14px; }
  button { font-family: var(--sans); font-size: 15px; border-radius: 8px; cursor: pointer;
           border: 1px solid transparent; }
  button.cta { background: var(--accent); color: #fff; font-weight: 600;
               font-size: 16px; padding: 13px 26px; }
  button.cta:hover { background: var(--accent-dark); }
  button.cta:disabled { background: var(--faint); cursor: wait; }
  button.ghost { background: var(--card); border-color: var(--border); color: var(--muted);
                 padding: 13px 18px; font-size: 15px; }
  button.ghost:hover { color: var(--text); border-color: var(--faint); }
  .disclosure { color: var(--muted); font-size: 13px; max-width: 720px; }
  .disclosure strong { color: var(--text); }
  #scenario-out { margin: 8px 0 24px; }
  #scenario-out:empty { display: none; }
  .loading { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
             padding: 28px; text-align: center; color: var(--muted); }
  .spinner { display: inline-block; width: 22px; height: 22px; margin-right: 10px;
             border: 3px solid var(--border); border-top-color: var(--accent);
             border-radius: 50%; animation: spin 0.9s linear infinite; vertical-align: -5px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .section-head { font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
                  color: var(--faint); font-weight: 700; margin: 32px 0 12px; }
  .msg { margin: 12px 0; padding: 14px 18px; border-radius: 12px; line-height: 1.65; }
  .user { background: #ddf4ff; border: 1px solid #b6e3ff; margin-left: 48px; white-space: pre-wrap; }
  .bot { background: var(--card); border: 1px solid var(--border); margin-right: 32px;
         white-space: pre-wrap; box-shadow: 0 1px 2px rgba(31,35,40,.05); }
  .contrast { background: var(--card); border: 1px solid var(--warn); border-radius: 12px;
              padding: 18px 20px; margin: 12px 32px 12px 0; }
  .contrast h3 { margin: 0 0 10px; font-size: 17px; color: var(--warn); }
  .cgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .card { border-radius: 8px; padding: 12px 14px; background: var(--bg); border: 1px solid var(--border); }
  .card h4 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
  .card ul { margin: 0; padding-left: 18px; line-height: 1.7; font-size: 14px; }
  .sentinelc { border-color: var(--bad); background: var(--bad-bg); }
  .sentinelc h4 { color: var(--bad); }
  .punchline { margin-top: 12px; color: var(--warn); font-weight: 600; line-height: 1.6; }
  .resumebox { background: var(--ok-bg); border: 1px solid var(--ok); border-radius: 12px;
                padding: 18px 20px; margin: 12px 32px 12px 0; }
  .resumebox h3 { margin: 0 0 8px; color: var(--ok); font-size: 17px; }
  .reportbox { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
                padding: 20px 22px; margin: 12px 0; box-shadow: 0 1px 3px rgba(31,35,40,.06); }
  .reportbox h3 { margin: 0 0 8px; color: var(--text); font-size: 19px; letter-spacing: -0.2px; }
  .reportbox > .tick { margin-bottom: 14px; }
  .verdict { display: inline-block; font-size: 12px; font-weight: 700; text-transform: uppercase;
             letter-spacing: 1px; padding: 4px 10px; border-radius: 20px; margin-bottom: 10px; }
  .verdict.ok { background: var(--ok-bg); color: var(--ok); }
  .verdict.warn { background: var(--warn-bg); color: var(--warn); }
  .verdict.bad { background: var(--bad-bg); color: var(--bad); }
  .receipt { background: var(--card); border: 1px solid var(--ok); border-left-width: 4px;
             border-radius: 8px; padding: 18px 20px; margin-top: 16px; }
  .receipt.halt { border-color: var(--warn); }
  .receipt h4 { margin: 0 0 10px; color: var(--text); font-size: 16px; }
  .receipt .kvrow { display: grid; grid-template-columns: 170px 1fr; gap: 10px;
                    padding: 7px 0; border-bottom: 1px solid var(--border); line-height: 1.6; font-size: 14px; }
  .receipt .kvrow:last-child { border-bottom: none; }
  .buckets { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  .bucket { border-radius: 8px; padding: 12px 14px; border: 1px solid var(--border); background: var(--bg); }
  .bucket h4 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .bucket ul { margin: 0; padding-left: 18px; font-size: 14px; }
  .b-ok { border-color: var(--ok); background: var(--ok-bg); } .b-ok h4 { color: var(--ok); }
  .b-rec { border-color: var(--accent); background: #ddf4ff; } .b-rec h4 { color: var(--accent); }
  .b-rev { border-color: var(--bad); background: var(--bad-bg); } .b-rev h4 { color: var(--bad); }
  .narr { border-left: 3px solid var(--accent); padding: 10px 14px; margin: 12px 0;
          line-height: 1.6; color: var(--muted); font-size: 15px; background: var(--card); }
  pre.score { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
              padding: 14px 16px; overflow-x: auto; line-height: 1.7; font-size: 13px;
              font-family: var(--mono); }
  .table-scroll { overflow-x: auto; margin: 12px 0; border: 1px solid var(--border);
                  border-radius: 8px; }
  table.cmp { border-collapse: collapse; width: 100%; min-width: 640px; font-size: 14px; }
  table.cmp th, table.cmp td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border);
                               vertical-align: top; line-height: 1.6; }
  table.cmp th { background: var(--bg); font-size: 13px; color: var(--muted);
                 text-transform: none; }
  table.cmp tr:last-child td { border-bottom: none; }
  .kv { color: var(--muted); }
  .kv b { color: var(--text); }
  #composer { margin-top: 16px; display: flex; gap: 8px; }
  #q { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 8px;
       color: var(--text); padding: 12px 14px; font-size: 15px; font-family: var(--sans); }
  #q:focus { outline: 2px solid var(--accent); outline-offset: -1px; border-color: var(--accent); }
  #send { background: var(--accent); color: #fff; padding: 12px 20px; font-weight: 600; }
  #send:hover { background: var(--accent-dark); }
  .chips { margin: 12px 0; display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { background: var(--card); border: 1px solid var(--accent); color: var(--accent);
          border-radius: 20px; padding: 7px 14px; font-size: 13px; cursor: pointer; font-weight: 500; }
  .chip:hover { background: #ddf4ff; }
  .tick { color: var(--muted); font-size: 13px; }
  .honest { background: var(--warn-bg); border: 1px solid #e3b341; border-radius: 8px;
            color: #5a4a00; font-size: 13px; padding: 12px 16px; margin: 20px 0; line-height: 1.6; }
  .guide { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
           padding: 20px 22px; margin-bottom: 16px; }
  .guide h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
              color: var(--faint); margin: 0 0 10px; font-weight: 700; }
  .guide ol { margin: 0 0 6px; padding-left: 20px; line-height: 1.7; color: var(--text); font-size: 15px; }
  .sub { color: var(--muted); font-size: 14px; }
  .sub a { color: var(--accent); }
  .timeline { margin: 0 0 14px; }
  .tl-step { display: flex; gap: 12px; margin: 10px 0; font-size: 14px; line-height: 1.55; }
  .tl-dot { flex: 0 0 12px; width: 12px; height: 12px; border-radius: 50%; margin-top: 5px; }
  .foot { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
          color: var(--faint); font-size: 13px; }
  .flow-steps { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }
  .flow-step { display: inline-flex; align-items: center; gap: 8px; background: var(--bg);
               border: 1px solid var(--border); border-radius: 999px; padding: 7px 12px;
               color: var(--text); font-size: 14px; font-weight: 600; }
  .flow-number { display: inline-grid; place-items: center; width: 22px; height: 22px;
                 border-radius: 50%; background: #ddf4ff; color: var(--accent); font-size: 12px; }
  .flow-arrow { color: var(--faint); font-weight: 600; }
  .task-promise { color: var(--muted); margin: 0 0 18px; }
  .advanced-panel { margin: 28px 0 0; border: 1px solid var(--border); border-radius: 12px;
                    background: var(--card); box-shadow: 0 1px 3px rgba(31,35,40,.04); }
  .advanced-panel > summary { list-style: none; display: flex; justify-content: space-between;
                              align-items: center; gap: 14px; cursor: pointer; padding: 18px 20px; }
  .advanced-panel > summary::-webkit-details-marker { display: none; }
  .advanced-panel > summary::marker { content: ""; }
  .advanced-panel > summary:hover .advanced-title { color: var(--accent); }
  .advanced-title { display: block; color: var(--text); font-weight: 700; font-size: 16px; }
  .advanced-subtitle { display: block; color: var(--muted); font-size: 13px; margin-top: 3px; }
  .advanced-toggle { flex: 0 0 auto; color: var(--accent); font-size: 13px; font-weight: 600;
                     border: 1px solid var(--border); padding: 5px 10px; border-radius: 999px; }
  .advanced-panel[open] .advanced-toggle { background: var(--bg); }
  .advanced-content { padding: 0 20px 20px; border-top: 1px solid var(--border); }
  .technical-proof { margin: 16px 0; padding: 18px 20px; border: 1px solid var(--border);
                     border-left: 4px solid var(--accent); border-radius: 10px; background: var(--card); }
  .technical-proof h4 { margin: 0 0 12px; font-size: 16px; color: var(--text); }
  .technical-proof-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
  .technical-proof-item { padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); }
  .technical-proof-item strong { display: block; margin-bottom: 6px; color: var(--text); font-size: 13px; }
  .technical-proof-item p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.55; }
  .technical-proof .tick { margin-top: 12px; line-height: 1.55; }
  @media (max-width: 720px) {
    h1 { font-size: 26px; }
    .lede { font-size: 16px; }
    .wrap { padding: 20px 16px 48px; }
    .cgrid, .buckets, .technical-proof-grid { grid-template-columns: 1fr; }
    .msg.user { margin-left: 0; }
    .msg.bot, .contrast, .resumebox { margin-right: 0; }
    .receipt .kvrow { grid-template-columns: 1fr; gap: 2px; }
    .taskcard table.meta td.k { width: 88px; }
  }
</style></head>
<body>
<div class="wrap">
<div class="kicker">Simulated Alexa+ experience &middot; Agent Continuity Layer</div>
<h1>The booking succeeded. The agent didn't know it.</h1>
<p class="lede">When an AI assistant loses the acknowledgement for an action that may already have
committed, retrying blindly can book twice. The Agent Continuity Layer reconciles the recorded
operation, resumes the workflow, or stops for human review — never guesses.</p>
<div class="taskcard">
<div class="kicker">The task — a fixed sample scenario</div>
<div class="req">&ldquo;Arrange an airport pickup for 6:30 tomorrow, add it to my calendar, and send my partner the details.&rdquo;</div>
<div class="flow-steps" aria-label="Workflow steps">
  <span class="flow-step"><span class="flow-number">1</span> Book the ride</span>
  <span class="flow-arrow" aria-hidden="true">→</span>
  <span class="flow-step"><span class="flow-number">2</span> Update calendar</span>
  <span class="flow-arrow" aria-hidden="true">→</span>
  <span class="flow-step"><span class="flow-number">3</span> Notify your partner</span>
</div>
<p class="task-promise">The ride is booked, but its confirmation gets lost. See how three recovery approaches handle the uncertainty.</p>
<div class="cta-row">
<button class="cta" id="runBtn" onclick="runChallenge('lost_ack','scenario-out')">&#9654; Run the booking scenario</button>
<button class="ghost" onclick="resetDemo()">Reset demo</button>
</div>
<div class="disclosure" id="simulationDisclosure" role="note"><strong>Simulation.</strong> No real ride is booked, no calendar event or notification is sent, and no live Alexa+ backend is called. This button runs the fixed example above; the optional assistant panel below exposes other scripted interactions.</div>
</div>
<div id="scenario-out" aria-live="polite"></div>
<details class="advanced-panel">
<summary><span><span class="advanced-title">Explore technical evidence</span><span class="advanced-subtitle">Other failure modes, diagnostic chat, and recovery details</span></span><span class="advanced-toggle">Optional</span></summary>
<div class="advanced-content">
<div class="section-head">Explore other failure modes</div>
<div class="guide">
<ol>
<li><b>B &middot; Propose an unsafe action</b> — a compromised agent proposes <i>restart:database</i>. The workflow alone executes it; the layer blocks it.</li>
<li><b>C &middot; Stale write after failover</b> — the fenced primary retries with its revoked generation. The store rejects it.</li>
<li><b>The gray failure (the original demo)</b> — investigate incident INC-1043, then inject a gray failure: a <b>deterministic, preconfigured</b> fault. "Continue" shows the outside-view vs sentinel contrast and the resume proof; "Test the fence" retries with the revoked generation; "What happened to my tasks?" gives the three-bucket report and scorecard (times in <b>ticks</b>, not seconds).</li>
</ol>
<div class="chips">
  <span class="chip" data-challenge="unsafe">B &middot; propose an unsafe action</span>
  <span class="chip" data-challenge="stale_write">C &middot; stale write after failover</span>
  <span class="chip" data-q="Investigate incident INC-1043 and prepare a remediation plan. Don't execute an unsafe action.">investigate INC-1043</span>
</div>
<div class="tick">Deterministic, preconfigured faults — never generalized AI-failure detection. Each challenge ends with a recovery receipt built from the journal + ledger.</div></div>
<div class="section-head">Ask the simulated assistant</div>
<div id="chat"></div>
<div class="chips">
  <span class="chip" data-q="Arrange an airport pickup for 6:30 tomorrow, add it to my calendar, and send my partner the details.">book airport pickup</span>
  <span class="chip" data-q="Investigate incident INC-1043 and prepare a remediation plan. Don't execute an unsafe action.">investigate INC-1043</span>
  <span class="chip" data-q="Check the checkout service error rate.">check checkout</span>
  <span class="chip" data-q="Probe the orders database for flaky dependencies.">probe database</span>
  <span class="chip" data-q="Inject a gray failure.">inject gray failure</span>
  <span class="chip" data-q="Inject a silent failure.">inject silent failure</span>
  <span class="chip" data-q="Test the fence.">test the fence</span>
  <span class="chip" data-q="Continue.">continue</span>
  <span class="chip" data-q="What happened to my tasks?">what happened?</span>
  <span class="chip" data-q="Run the ablation.">run ablation</span>
</div>
<div id="composer">
  <input id="q" placeholder="Ask in plain language — e.g. investigate incident INC-1043…" autocomplete="off">
  <button id="send">Send</button>
</div>
<div class="honest"><strong>Honest simulation.</strong> The chat and intent mapping are simulated
(deterministic keyword matching — no network, no model, no API keys). The continuity
mechanisms execute in the real code; the booking provider, calendar, notification
services, and injected faults are simulated.</div>
</div>
</details>
<div class="foot"><span class="sub"><a href="/">live dashboard</a> &middot;
<a href="/showcase">scenario showcase</a></span></div>
</div>
<script>
let sessionId = null;
const chat = document.getElementById('chat');
function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function md(s){ return esc(s).replace(/\\*\\*([^*]+)\\*\\*/g, '<b>$1</b>'); }
function addUser(t){
  chat.insertAdjacentHTML('beforeend', `<div class="msg user">${md(t)}</div>`);
}
function addBot(html){
  chat.insertAdjacentHTML('beforeend', `<div class="msg bot">${html}</div>`);
  window.scrollTo(0, document.body.scrollHeight);
}
function addRaw(html){
  chat.insertAdjacentHTML('beforeend', html);
  window.scrollTo(0, document.body.scrollHeight);
}
function send(text){
  const q = (text !== undefined ? text : document.getElementById('q').value).trim();
  if(!q) return;
  document.getElementById('q').value = '';
  addUser(q);
  fetch('/sim/api/message', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({session_id: sessionId, text: q})
  }).then(r=>r.json()).then(d=>{
    sessionId = d.session_id;
    d.messages.forEach(m=>{
      if(m.kind === 'text') addBot(md(m.text));
      else addRaw(m.html);
    });
  });
}
document.getElementById('send').onclick = ()=>send();
document.getElementById('q').addEventListener('keydown', e=>{ if(e.key==='Enter') send(); });
document.querySelectorAll('.chip').forEach(c=>{ if(!c.dataset.challenge) c.onclick = ()=>send(c.dataset.q); });
document.querySelectorAll('[data-challenge]').forEach(c=>{ c.onclick = ()=>runChallenge(c.dataset.challenge); });
function runChallenge(scenario, target){
  var out = target ? document.getElementById(target) : null;
  var btn = document.getElementById('runBtn');
  if(btn){ btn.disabled = true; }
  var wrapTables = function(){
    document.querySelectorAll('table.cmp').forEach(function(t){
      if(!t.parentElement.classList.contains('table-scroll')){
        var w = document.createElement('div'); w.className = 'table-scroll';
        t.parentNode.insertBefore(w, t); w.appendChild(t);
      }
    });
  };
  var show = function(html){
    if(out){ out.innerHTML = html; out.scrollIntoView({behavior:'smooth', block:'start'}); }
    else addRaw(html);
    wrapTables();
  };
  show('<div class="loading"><span class="spinner"></span>Running the challenge against the real engine…</div>');
  fetch('/sim/api/challenge', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({scenario: scenario})
  }).then(r=>r.json()).then(d=>{ show(d.html); })
   .catch(function(){ show('<div class="loading">The challenge request failed. Check the server and try again.</div>'); })
   .finally(function(){ if(btn){ btn.disabled = false; } });
}
function resetDemo(){
  var out = document.getElementById('scenario-out');
  if(out){ out.innerHTML = ''; }
  chat.innerHTML = '';
  sessionId = null;
  greet();
  window.scrollTo({top: 0, behavior: 'smooth'});
}
function greet(){
  addBot(md("Hi — I'm a **simulated** front-end for the Agent Continuity Layer. **Run the booking scenario above**: the provider commits, the ack is lost, and you'll see whether the retry books twice — naive vs idempotency-only vs the full layer, from real runs. Or type the booking request yourself: **\\"Arrange an airport pickup for 6:30 tomorrow, add it to my calendar, and send my partner the details.\\"**"));
}
greet();
</script></body></html>
"""


def _sim_escape(text: str) -> str:
    import html as _html
    return _html.escape(text or "")


def _sim_md(text: str) -> str:
    import re as _re
    return _re.sub(r"\*\*([^*]+)\*\*",
                   lambda m: "<b>" + _sim_escape(m.group(1)) + "</b>",
                   _sim_escape(text))


def _render_receipt(receipt: dict) -> str:
    """Render the recovery receipt card. Every value was read off the
    journal/ledger by sim/receipt.py -- this only formats."""
    import json as _json

    def _v(value):
        if isinstance(value, str):
            return _sim_escape(value)
        return _sim_escape(_json.dumps(value, default=str))

    op_rows = "".join(
        f'<tr><td class="kv"><b>{_sim_escape(op["label"])}</b><br>{_sim_escape(op["op_id"])}</td>'
        f'<td>{_v(op["effect_receipt"])}</td>'
        f'<td>{_sim_escape(op["retry_decision"])}<br><span class="tick">{_sim_escape(op["decision_source"])}</span></td>'
        f'<td>{_sim_escape(op["recovery_result"])}</td></tr>'
        for op in receipt["operations"])
    glob = "".join(
        f'<div class="kvrow"><span class="kv">{_sim_escape(k)}</span>'
        f'<span>{_v(v)}</span></div>'
        for k, v in (("checkpoint", receipt["checkpoint"]),
                     ("fencing", receipt["fencing"]),
                     ("final state", receipt["final_state"])))
    needs_review = bool((receipt.get("final_state") or {}).get("human_review_flags"))
    halt_cls = " halt" if needs_review else ""
    halt_badge = ('<span class="verdict warn">halted — human review required; '
                  'dependent steps did not run</span>' if needs_review else "")
    return (
        f'<div class="receipt{halt_cls}"><h4>Recovery receipt '
        f'— incident {_sim_escape(receipt["incident_id"])}</h4>'
        f'{halt_badge}'
        '<div class="tick" style="margin-bottom:8px">Proof of recovery, from '
        'the journal + forensic ledger — not a success message. '
        f'<a style="color:#58a6ff" href="/sim/api/receipt/{_sim_escape(receipt["incident_id"])}" '
        'target="_blank">JSON export</a></div>'
        '<table class="cmp"><tr><th>operation</th><th>effect receipt</th>'
        '<th>retry decision</th><th>recovery result</th></tr>'
        + op_rows + '</table>' + glob + '</div>')


def _render_sim_message(msg: dict) -> str:
    """Render one SimSession message dict to HTML for the /sim page."""
    kind = msg.get("kind")
    if kind == "text":
        return f'<div class="msg bot">{_sim_md(msg["text"])}</div>'
    if kind == "contrast":
        o, s = msg["outside"], msg["sentinel"]
        fault = (f'<div class="tick" style="margin-bottom:10px">'
                 f'{_sim_escape(msg.get("fault_label", ""))}<br>Enforced invariant(s): '
                 f'{_sim_escape("; ".join(msg.get("invariants", [])))}</div>'
                 if msg.get("fault_label") else "")
        return (
            '<div class="contrast">'
            f'<h3>{_sim_escape(msg["title"])}</h3>'
            + fault +
            '<div class="cgrid">'
            f'<div class="card outside"><h4>{_sim_escape(o["heading"])}</h4><ul>'
            + "".join(f"<li>{_sim_escape(x)}</li>" for x in o["lines"]) +
            '</ul></div>'
            f'<div class="card sentinelc"><h4>{_sim_escape(s["heading"])}</h4><ul>'
            + "".join(f"<li>{_sim_escape(x)}</li>" for x in s["lines"]) +
            '</ul></div></div>'
            f'<div class="punchline">{_sim_escape(msg["punchline"])}</div></div>')
    if kind == "resume":
        rows = [
            ("incident", msg["incident"]),
            ("resumed from tick", f"t+{msg['resumed_from_tick']:04d}"
             if msg["resumed_from_tick"] is not None else "-"),
            ("already completed (skipped, not redone)",
             ", ".join(msg["already_completed"]) or "-"),
            ("fencing generation (remediation)", str(msg["generation"])),
            ("duplicate writes prevented", str(msg["duplicates_prevented"])),
        ]
        return (
            '<div class="resumebox"><h3>Resume, not a restart</h3>'
            f'<div style="margin-bottom:8px;line-height:1.6">{_sim_escape(msg["text"])}</div>'
            '<table class="cmp">' +
            "".join(f'<tr><td class="kv">{_sim_escape(k)}</td>'
                    f'<td>{_sim_escape(str(v))}</td></tr>' for k, v in rows) +
            '</table></div>')
    if kind == "fence_test":
        inv = "".join(f"<li>{_sim_escape(i)}</li>" for i in msg["invariants"])
        verdict = ("<b style='color:#2ecc71'>REJECTED</b>" if msg["rejected"]
                   else "<b style='color:#e74c3c'>ACCEPTED (bug!)</b>")
        return (
            '<div class="resumebox"><h3>Stale write — fence test</h3>'
            f'<div class="tick" style="margin-bottom:8px">{_sim_escape(msg["honest_label"])}</div>'
            f'<div style="margin-bottom:8px">Enforced invariant(s):<ul>{inv}</ul></div>'
            '<table class="cmp">'
            f'<tr><td class="kv">attempted generation (fenced primary)</td><td>{msg["attempted_generation"]}</td></tr>'
            f'<tr><td class="kv">current generation</td><td>{msg["current_generation"]}</td></tr>'
            f'<tr><td class="kv">action attempted</td><td>{_sim_escape(msg["action"])}</td></tr>'
            f'<tr><td class="kv">verdict</td><td>{verdict}</td></tr>'
            + (f'<tr><td class="kv">rejection reason</td><td>{_sim_escape(msg["reason"])}</td></tr>'
               if msg["rejected"] else "") +
            '</table></div>')
    if kind == "report":
        b = msg["buckets"]
        def _bucket(title, css, items, extra=""):
            inner = ("<ul>" + "".join(f"<li>{_sim_escape(i)}</li>" for i in items)
                     + "</ul>") if items else '<span class="tick">—</span>'
            return (f'<div class="bucket {css}"><h4>{title}</h4>{inner}{extra}</div>')
        reasons = "".join(
            f'<div class="kv">⚠ {_sim_escape(i)}: {_sim_escape(r)}</div>'
            for i, r in msg["review_reasons"].items())
        return (
            '<div class="reportbox"><h3>What happened to your tasks</h3>'
            '<div class="buckets">'
            + _bucket("Completed clean", "b-ok", b["completed_clean"])
            + _bucket("Recovered via standby + checkpoint", "b-rec",
                      b["recovered_via_standby"])
            + _bucket("Needs human review", "b-rev",
                      b["needs_human_review"], reasons) +
            '</div>'
            f'<div class="narr">{_sim_escape(msg["narrative"])}</div>'
            f'<pre class="score">{_sim_escape(chr(10).join(msg["scorecard_lines"]))}</pre>'
            '</div>')
    if kind == "ablation":
        c = msg["comparison"]
        rows = "".join(
            f'<tr><td class="kv"><b>{_sim_escape(r["aspect"])}</b></td>'
            f'<td>{_sim_escape(r["baseline"])}</td>'
            f'<td>{_sim_escape(r["protected"])}</td></tr>'
            for r in c["rows"])
        return (
            '<div class="reportbox"><h3>Ablation: workflow alone vs '
            'workflow + continuity layer</h3>'
            f'<div class="tick" style="margin-bottom:8px">incident {c["incident_id"]} · '
            f'failure {c["failure"]} (deterministic, preconfigured scripted fault) · '
            'same agents, same steps, same scripted outputs — the only '
            'difference is the layer. An ablation, not a competitor comparison.</div>'
            '<table class="cmp"><tr><th></th><th>Workflow alone</th>'
            '<th>Workflow + layer</th></tr>' + rows + '</table>'
            f'<pre class="score">{_sim_escape(chr(10).join(_render_scorecard_text(c["scorecard"])))}</pre>'
            '</div>')
    if kind == "challenge":
        c = msg["comparison"]
        three_way = c.get("three_way", False)
        scenario = msg.get("scenario", "")
        if scenario == "lost_ack":
            verdict = ('<span class="verdict ok">1 booking · retry reused the receipt · '
                       'no duplicates</span> '
                       '<span class="verdict warn">provider-state-loss variant: '
                       'halted · human review required</span>')
        elif scenario == "unsafe":
            verdict = ('<span class="verdict ok">unsafe action blocked — '
                       'no effect executed</span>')
        elif scenario == "stale_write":
            verdict = ('<span class="verdict ok">stale write rejected at the '
                       'store boundary</span>')
        else:
            verdict = ""
        if three_way:
            rows = "".join(
                f'<tr><td class="kv"><b>{_sim_escape(r["aspect"])}</b></td>'
                f'<td>{_sim_escape(r["baseline"])}</td>'
                f'<td>{_sim_escape(r["idempotency_only"])}</td>'
                f'<td>{_sim_escape(r["protected"])}</td></tr>'
                for r in c["rows"])
            header = ('<table class="cmp"><tr><th></th><th>Naive retry</th>'
                      '<th>Idempotency-only</th><th>Full continuity layer</th></tr>'
                      + rows + '</table>')
            sub = ('three approaches, same fault — every cell measured from '
                   'the runs\u2019 own records. Idempotency-only matches the '
                   'full layer where the provider honors its key; the layer\u2019s '
                   'edge is uncertain outcomes, dependent-step safety, and '
                   'stale-agent fencing.')
        else:
            rows = "".join(
                f'<tr><td class="kv"><b>{_sim_escape(r["aspect"])}</b></td>'
                f'<td>{_sim_escape(r["baseline"])}</td>'
                f'<td>{_sim_escape(r["protected"])}</td></tr>'
                for r in c["rows"])
            header = ('<table class="cmp"><tr><th></th><th>Workflow alone</th>'
                      '<th>Workflow + layer</th></tr>' + rows + '</table>')
            sub = 'same steps both sides — the only difference is the layer.'
        tl = ""
        for t in msg.get("timeline", []):
            dot = "#3fb950" if t["state"] == "ok" else "#f0b429"
            tl += (f'<div class="tl-step"><span class="tl-dot" '
                   f'style="background:{dot}"></span>'
                   f'<div><b>{_sim_escape(t["phase"])}. '
                   f'{_sim_escape(t["title"])}</b><br>'
                   f'<span class="tick">{_sim_escape(t["detail"])}</span>'
                   f'</div></div>')
        if tl:
            tl = (f'<div class="timeline"><div class="kicker" '
                  f'style="margin-bottom:6px">Recovery timeline — from this run\u2019s records</div>'
                  f'{tl}</div>')
        if scenario == "lost_ack":
            technical_proof = (
                '<section class="technical-proof" aria-label="Technical proof beyond idempotency">'
                '<h4>What the continuity layer adds beyond retry deduplication</h4>'
                '<div class="technical-proof-grid">'
                '<div class="technical-proof-item"><strong>Persist before acknowledgement</strong>'
                '<p>The gateway stores the operation intent and committed effect receipt in SQLite before the acknowledgement is returned.</p></div>'
                '<div class="technical-proof-item"><strong>Reconcile before retry</strong>'
                '<p>The retry reloads the receipt from the journal. Identity covers service, operation, target, and parameters; a mismatched reuse is rejected.</p></div>'
                '<div class="technical-proof-item"><strong>Fail closed on unknown state</strong>'
                '<p>If the provider cannot verify the receipt, the run halts for human review; dependent calendar and notification steps do not proceed.</p></div>'
                '</div><div class="tick">Scope: the services and fault are simulated. Safe external reconciliation still requires provider idempotency or reliable state verification.</div></section>'
            )
        elif scenario == "unsafe":
            technical_proof = (
                '<section class="technical-proof" aria-label="Technical proof for invariant enforcement">'
                '<h4>This is enforcement, not a warning</h4>'
                '<div class="technical-proof-grid">'
                '<div class="technical-proof-item"><strong>Business invariant</strong>'
                '<p>The proposed restart:database action violates the scenario invariant and is blocked before the effect is applied.</p></div>'
                '<div class="technical-proof-item"><strong>Controlled comparison</strong>'
                '<p>The baseline workflow and protected workflow run the same scripted scenario; the layer is the changed variable.</p></div>'
                '<div class="technical-proof-item"><strong>Recorded decision</strong>'
                '<p>The challenge result and recovery receipt expose the blocked action and final disposition instead of relying on narration alone.</p></div>'
                '</div><div class="tick">Scope: this is a deterministic, preconfigured fault—not a claim of generalized semantic detection.</div></section>'
            )
        elif scenario == "stale_write":
            technical_proof = (
                '<section class="technical-proof" aria-label="Technical proof for fencing">'
                '<h4>Why a stale agent cannot keep writing</h4>'
                '<div class="technical-proof-grid">'
                '<div class="technical-proof-item"><strong>Generation authority</strong>'
                '<p>Failover rotates the role generation. The prior primary continues to hold only its old generation.</p></div>'
                '<div class="technical-proof-item"><strong>Boundary checks</strong>'
                '<p>The gateway checks authority before dispatch; the provider and local store also enforce their fencing contracts.</p></div>'
                '<div class="technical-proof-item"><strong>No effect on rejection</strong>'
                '<p>A stale generation is rejected and the refusal is recorded; a rejection is not misreported as a successful write.</p></div>'
                '</div><div class="tick">Fencing and idempotency solve different problems: fencing rejects stale writers; idempotency/reconciliation handles repeated operations.</div></section>'
            )
        else:
            technical_proof = ""
        return (
            '<div class="reportbox"><h3>'
            f'{_sim_escape(msg.get("title", "Break-it challenge"))}</h3>'
            f'{verdict}'
            f'<div class="tick" style="margin-bottom:8px">incident {c["incident_id"]} · '
            f'failure {c["failure"]} (deterministic, preconfigured scripted fault) · '
            f'{sub}</div>'
            + technical_proof + tl + header +
            f'<pre class="score">{_sim_escape(chr(10).join(_render_scorecard_text(c["scorecard"])))}</pre>'
            + _render_receipt(msg["receipt"]) +
            '</div>')
    if kind == "booking_receipt":
        return (
            '<div class="reportbox"><h3>'
            f'{_sim_escape(msg.get("title", "Booking recovery"))}</h3>'
            f'<div class="tick" style="margin-bottom:8px">incident {msg["incident_id"]} · '
            'deterministic, preconfigured simulated fault (lost acknowledgement) · '
            'every value below was read off the journal/ledger by sim/receipt.py.</div>'
            + _render_receipt(msg["receipt"]) +
            '</div>')
    return f'<div class="msg bot">{_sim_escape(str(msg))}</div>'


_SIM_SESSIONS: dict = {}
_SIM_SESSION_CAP = 128

# Receipts from break-it challenges, keyed by incident id, backing
# GET /sim/api/receipt/<incident_id>. Populated only by real runs.
_CHALLENGE_RECEIPTS: dict = {}


def _sim_get_session(session_id):
    import uuid as _uuid
    from sim.alexa_plus_sim import SimSession
    if not session_id or session_id not in _SIM_SESSIONS:
        session_id = _uuid.uuid4().hex[:12]
        _SIM_SESSIONS[session_id] = SimSession()
        # Bound memory: demo sessions are ephemeral; evict the oldest.
        while len(_SIM_SESSIONS) > _SIM_SESSION_CAP:
            _SIM_SESSIONS.pop(next(iter(_SIM_SESSIONS)))
    return session_id, _SIM_SESSIONS[session_id]



def create_app(layer=None, scenario: str = "gray", step_delay: float = 0.6,
               autostart: bool = True):
    """Build the Flask app. If `layer` is None, a demo world is built and
    the scenario replays in a background thread."""
    if layer is None:
        from store import IncidentStore
        layer, store, primaries = _demo_world()
        stop = threading.Event()
        if autostart:
            t = threading.Thread(target=run_live,
                                 args=(layer, store, primaries, scenario,
                                       step_delay, stop),
                                 daemon=True, name="dashboard-live-runner")
            t.start()
    else:
        store, primaries, stop = None, None, None

    app = Flask(__name__)
    app.config["layer"] = layer

    @app.get("/")
    def index():
        return render_template_string(PAGE)

    @app.get("/api/health")
    def api_health():
        lyr = app.config["layer"]
        with lyr.sentinel._lock:
            roles = {r: lyr.sentinel.state.get(r, "?") for r in ROLES}
        return jsonify({"roles": roles, "tick": lyr.clock.now()})

    @app.get("/api/timeline")
    def api_timeline():
        from flask import request
        lyr = app.config["layer"]
        limit = request.args.get("limit", default=60, type=int)
        with lyr.ledger._lock:
            events = list(lyr.ledger.timeline[-limit:])
        return jsonify({"events": [
            {"tick": e["tick"], "kind": e["kind"],
             "summary": _summarize(e["kind"], e["detail"])}
            for e in events]})

    @app.get("/api/affected")
    def api_affected():
        lyr = app.config["layer"]
        return jsonify({"affected_work": lyr.ledger.affected_work()})

    @app.get("/api/money")
    def api_money():
        # JSON only now (no UI panel). Kept because test_robust.py reads it.
        lyr = app.config["layer"]
        from continuity import metrics as m
        with lyr.ledger._lock:
            windows = list(lyr.ledger.windows)
            duplicates = lyr.ledger.duplicates_prevented
            lkg = next((e["detail"].get("resumed_from_tick")
                        for e in lyr.ledger.timeline
                        if e["kind"] == "standby_activated"), None)
        return jsonify({
            "window": windows[-1] if windows else None,
            "metrics": m.compute_metrics(lyr.ledger),
            "duplicates_prevented": duplicates,
            "last_known_good": lkg,
        })

    @app.get("/api/report")
    def api_report():
        return jsonify(app.config["layer"].ledger.export_dict())

    @app.get("/showcase")
    def showcase_index():
        cards = "".join(
            f'<div class="panel"><h2>{s["title"]}</h2>'
            f'<div class="blurb">{s["blurb"]}</div>'
            f'<a class="run" href="/showcase/{name}">run it &rarr;</a></div>'
            for name, s in SHOWCASE_SCENARIOS.items())
        return render_template_string(SHOWCASE_INDEX_PAGE.replace(
            "__CARDS__", cards))

    @app.get("/showcase/<name>")
    def showcase_run(name):
        if name not in SHOWCASE_SCENARIOS:
            return render_template_string(SHOWCASE_404_PAGE), 404
        result = run_showcase_scenario(name)
        return render_template_string(SHOWCASE_RESULT_PAGE, result=result)

    @app.get("/sim")
    def sim_page():
        return render_template_string(SIM_PAGE)

    @app.post("/sim/api/message")
    def sim_message():
        data = request.get_json(force=True) or {}
        session_id, session = _sim_get_session(data.get("session_id"))
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"session_id": session_id, "messages": []})
        try:
            outgoing = session.handle(text)
        except Exception as exc:  # noqa: BLE001 - the sim must never 500
            outgoing = [{"kind": "text",
                         "text": f"Something went wrong in the sim: {exc}. "
                                 "Try 'reset' for a fresh session."}]
        for m in outgoing:
            if m.get("kind") == "booking_receipt" and m.get("receipt"):
                _CHALLENGE_RECEIPTS[m["incident_id"]] = m["receipt"]
        return jsonify({
            "session_id": session_id,
            "messages": [{"kind": m.get("kind", "text"),
                          "html": _render_sim_message(m),
                          "text": m.get("text", "")} for m in outgoing],
        })

    @app.post("/sim/api/challenge")
    def sim_challenge():
        from sim.ablation import run_challenge
        data = request.get_json(force=True) or {}
        scenario = data.get("scenario")
        try:
            result = run_challenge(scenario)
        except Exception as exc:  # noqa: BLE001 - the sim must never 500
            return jsonify({"html":
                            f'<div class="msg bot">Challenge failed: '
                            f'{_sim_escape(str(exc))}</div>'})
        _CHALLENGE_RECEIPTS[result["incident_id"]] = result["receipt"]
        while len(_CHALLENGE_RECEIPTS) > _SIM_SESSION_CAP:
            _CHALLENGE_RECEIPTS.pop(next(iter(_CHALLENGE_RECEIPTS)))
        html = _render_sim_message({"kind": "challenge", **result})
        return jsonify({"html": html,
                        "incident_id": result["incident_id"]})

    @app.get("/sim/api/receipt/<incident_id>")
    def sim_receipt(incident_id):
        receipt = _CHALLENGE_RECEIPTS.get(incident_id)
        if receipt is None:
            return jsonify({"error": "no receipt for incident",
                            "incident_id": incident_id}), 404
        return jsonify(receipt)

    return app


def _demo_world():
    from agents.triage import TriageAgent
    from agents.diagnosis import DiagnosisAgent
    from agents.remediation import RemediationAgent
    from agents.escalation import EscalationAgent
    from agents.standbys import make_standby
    from continuity.adapter import ContinuityLayer
    from continuity.checkpoint import STATE_ADAPTERS
    from continuity.contracts import CONTRACTS
    from continuity.diagnostician import default_diagnostician
    from continuity.nemotron import live_enabled
    from continuity.standby import StandbyController
    from store import IncidentStore

    # Offline unless CONTINUITY_LIVE=1 is explicitly set (credit safety:
    # key presence alone never enables network calls).
    layer = ContinuityLayer(diagnostician=default_diagnostician(
        live=live_enabled()))
    store = IncidentStore(layer.fencing, layer.ledger)
    primaries = {
        "triage": TriageAgent(),
        "diagnosis": DiagnosisAgent(),
        "remediation": RemediationAgent(),
        "escalation": EscalationAgent(),
    }
    for role, agent in primaries.items():
        layer.register(agent.agent_id, CONTRACTS[role],
                       state_adapter=STATE_ADAPTERS[role],
                       standby=StandbyController(make_standby(role)),
                       primary=agent)
    return layer, store, primaries


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent Continuity Layer dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--scenario", choices=("gray", "hard", "silent", "healthy"),
                    default="gray")
    ap.add_argument("--step-delay", type=float, default=0.6,
                    help="seconds between stages (video readability)")
    args = ap.parse_args()
    app = create_app(scenario=args.scenario, step_delay=args.step_delay)
    print(f"dashboard: http://{args.host}:{args.port}/  (scenario={args.scenario})")
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
