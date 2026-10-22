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
function tick(){
  fetch('/api/health').then(r=>r.json()).then(h=>{
    document.getElementById('roles').innerHTML =
      Object.entries(h.roles).map(([role,state]) =>
        `<span class="role">${role}<br><span class="badge" style="background:${COLORS[state]||'#888'}">${state}</span></span>`
      ).join('');
  });
  fetch('/api/timeline?limit=60').then(r=>r.json()).then(t=>{
    document.getElementById('timeline').innerHTML =
      t.events.slice().reverse().map(e =>
        `<div><span class="tick">t+${String(e.tick).padStart(4,'0')}</span> <b>${e.kind}</b> ${e.summary||''}</div>`
      ).join('');
  });
  fetch('/api/affected').then(r=>r.json()).then(a=>{
    const rows = Object.entries(a.affected_work);
    document.getElementById('affected').innerHTML = rows.length
      ? '<table><tr><th>incident</th><th>disposition</th></tr>' +
        rows.map(([i,d])=>`<tr><td>${i}</td><td>${d}</td></tr>`).join('') + '</table>'
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
  body { background:#0d1117; color:#e6edf3; font-family:ui-monospace,Menlo,Consolas,monospace;
         margin:0; padding:18px; font-size:15px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:#8b949e; margin-bottom:6px; line-height:1.6; max-width:900px; }
  .sub a { color:#58a6ff; }
  .honest { color:#d29922; font-size:13px; margin-bottom:14px; max-width:900px; line-height:1.6; }
  .guide { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px;
           margin-bottom:14px; max-width:900px; }
  .guide h2 { font-size:13px; text-transform:uppercase; letter-spacing:1px; color:#8b949e; margin:0 0 8px; }
  .guide ol { margin:0; padding-left:20px; line-height:1.7; color:#c9d1d9; }
  #chat { max-width:900px; }
  .msg { margin:10px 0; padding:10px 14px; border-radius:8px; line-height:1.65; }
  .user { background:#1c2b4a; border:1px solid #2f4a7a; margin-left:60px; white-space:pre-wrap; }
  .bot { background:#161b22; border:1px solid #30363d; margin-right:40px; white-space:pre-wrap; }
  .contrast { background:#161b22; border:1px solid #d29922; border-radius:8px; padding:12px;
              margin:10px 40px 10px 0; }
  .contrast h3 { margin:0 0 10px; font-size:16px; color:#f0b429; }
  .cgrid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .card { border-radius:6px; padding:10px 12px; }
  .card h4 { margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:1px; }
  .card ul { margin:0; padding-left:18px; line-height:1.7; }
  .outside { background:#21262d; } .outside h4 { color:#8b949e; }
  .sentinelc { background:#3d1f1f; border:1px solid #e74c3c; } .sentinelc h4 { color:#ff7b72; }
  .punchline { margin-top:10px; color:#f0b429; font-weight:bold; line-height:1.6; }
  .resumebox { background:#12261c; border:1px solid #2ecc71; border-radius:8px; padding:12px;
               margin:10px 40px 10px 0; }
  .resumebox h3 { margin:0 0 8px; color:#2ecc71; font-size:16px; }
  .reportbox { background:#161b22; border:1px solid #58a6ff; border-radius:8px; padding:12px;
               margin:10px 40px 10px 0; }
  .reportbox h3 { margin:0 0 10px; color:#58a6ff; font-size:16px; }
  .buckets { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-bottom:10px; }
  .bucket { border-radius:6px; padding:10px 12px; }
  .bucket h4 { margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:1px; }
  .bucket ul { margin:0; padding-left:18px; }
  .b-ok { background:#12261c; border:1px solid #2ecc71; } .b-ok h4 { color:#2ecc71; }
  .b-rec { background:#1c2b4a; border:1px solid #58a6ff; } .b-rec h4 { color:#58a6ff; }
  .b-rev { background:#3d1f1f; border:1px solid #e74c3c; } .b-rev h4 { color:#ff7b72; }
  .narr { border-left:3px solid #58a6ff; padding:8px 12px; margin:10px 0; line-height:1.6; color:#c9d1d9; }
  pre.score { background:#0d1117; border:1px solid #30363d; border-radius:6px; padding:10px 12px;
              overflow-x:auto; line-height:1.7; }
  table.cmp { border-collapse:collapse; width:100%; margin:10px 0; }
  table.cmp th, table.cmp td { text-align:left; padding:8px 10px; border:1px solid #30363d;
                               vertical-align:top; line-height:1.6; }
  table.cmp th { background:#21262d; }
  .kv { color:#8b949e; }
  #composer { max-width:900px; margin-top:14px; display:flex; gap:8px; }
  #q { flex:1; background:#161b22; border:1px solid #30363d; border-radius:6px; color:#e6edf3;
       padding:10px 12px; font-size:15px; font-family:inherit; }
  button { background:#238636; border:none; border-radius:6px; color:#fff; padding:10px 16px;
           font-size:14px; cursor:pointer; font-family:inherit; }
  button.alt { background:#21262d; border:1px solid #30363d; }
  .chips { max-width:900px; margin:10px 0; display:flex; flex-wrap:wrap; gap:8px; }
  .chip { background:#161b22; border:1px solid #58a6ff; color:#58a6ff; border-radius:16px;
          padding:6px 12px; font-size:13px; cursor:pointer; }
  .tick { color:#8b949e; }
</style></head>
<body>
<h1>SIMULATED ALEXA+ EXPERIENCE</h1>
<div class="sub">A simulated conversational front-end for the <b>Agent Continuity Layer</b> —
a reliability layer for agent workflows. &middot; <a href="/">live dashboard</a> &middot;
<a href="/showcase">scenario showcase</a></div>
<div class="honest">Honest simulation: the chat and intent mapping are simulated
(deterministic keyword matching — no network, no model, no API keys). Everything underneath —
the four-agent workflow, gray-failure detection, fencing, standby failover, checkpoints —
is the real continuity engine, driven with zero mocks.</div>
<div class="guide"><h2>Guided demo — the one beat to watch</h2>
<ol>
<li>"Investigate incident INC-1043 and prepare a remediation plan. Don't execute an unsafe action."</li>
<li>"Inject a gray failure." — a <b>deterministic, preconfigured</b> fault: the scripted backend returns a plausible-but-wrong plan violating the invariant <i>never restart the database for this incident class</i>.</li>
<li>"Continue." — watch the outside-view vs sentinel contrast, then the resume proof.</li>
<li>"Test the fence." — the fenced primary retries with its revoked generation; the store rejects it.</li>
<li>"What happened to my tasks?" — the three-bucket report + reliability scorecard (times in <b>ticks</b>, not seconds).</li>
<li>"Run the ablation." — workflow alone vs workflow + layer, from real runs.</li>
</ol>
<div class="tick">Three fault scenarios: gray semantic violation · silent dependency failure · stale write from a fenced agent. Each states its enforced invariant up front — never generalized AI-failure detection.</div></div>
<div id="chat"></div>
<div class="chips">
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
document.querySelectorAll('.chip').forEach(c=>{ c.onclick = ()=>send(c.dataset.q); });
addBot(md("Hi — I'm a **simulated** conversational front-end for the Agent Continuity Layer, a **reliability layer for agent workflows**. Give me an incident to investigate, e.g. **\\"Investigate incident INC-1043 and prepare a remediation plan.\\"**"));
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
    return f'<div class="msg bot">{_sim_escape(str(msg))}</div>'


_SIM_SESSIONS: dict = {}
_SIM_SESSION_CAP = 128


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
        return jsonify({
            "session_id": session_id,
            "messages": [{"kind": m.get("kind", "text"),
                          "html": _render_sim_message(m),
                          "text": m.get("text", "")} for m in outgoing],
        })

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
