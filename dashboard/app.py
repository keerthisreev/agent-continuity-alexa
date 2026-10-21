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

from flask import Flask, jsonify, render_template_string

from test_continuity import make_world, incident

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
 &middot; <a href="/showcase" style="color:#58a6ff">scenario showcase</a></div>
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
        return f"{d.get('agent')} at epoch {d.get('new_epoch')}"
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
    store.apply_effect(r["active_agent_id"], r["epoch"], aid, action)
    layer._checkpoints["remediation"].completed_action_ids.append(aid)
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
    result page needs. diagnostician=None -> default (Nemotron when the
    key is set, stub otherwise); tests pass the stub explicitly."""
    from continuity import metrics as m
    from continuity.diagnostician import default_diagnostician

    spec = SHOWCASE_SCENARIOS[name]
    layer = spec["runner"]()
    report = layer.ledger.report()
    diag = diagnostician or default_diagnostician()
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
    from continuity.standby import StandbyController
    from store import IncidentStore

    layer = ContinuityLayer(diagnostician=default_diagnostician())
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
