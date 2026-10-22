# Test evidence — Alexa+ submission

- Date: 2026-10-22 (evening, America/Chicago)
- Commit: 01cdd58 (Docs: test evidence, rewritten Alexa+ Devpost draft, README counts)
- Branch: feature/gateway-fencing (PR to follow; merges to main)
- Command: `for t in test_continuity test_robust test_nemotron test_mcp test_showcase test_sim test_journal; do python3 $t.py; done`
- Environment: clean venv, Python 3.12.3, with flask, mcp>=2.0, pyyaml, requests installed — **zero skipped tests** (the dashboard and MCP checks that skip without optional deps all executed)
- Also offline: NEBIUS_API_KEY unset, CONTINUITY_LIVE unset; no network; deterministic (no randomness)

## Full output
```
=== test_continuity ===
PASS healthy run: 2 incidents, 8 stages, zero false failovers
PASS failure A (hard kill): detected, fenced, standby continued, no work lost
PASS failure B (silent dependency): gray failure caught, never called healthy, standby replayed the work
PASS failure C (gray semantic): invariant violation quarantined, database restart blocked, human flagged
PASS duplicates: standby resumed mid-stage, completed work not redone
PASS idempotency boundary: params are not part of action identity (pinned)
PASS fencing: stale generation rejected, rejoin only after probes, new generation issued, standby invalidated on rejoin
PASS checkpoint restore: standby resumed the failed incident's checkpoint, no replay, no cross-incident contamination
PASS concurrency: stale write racing a rotation is rejected; new generation writes normally
PASS rejoin denied while still degraded; granted after real recovery
PASS ledger: window + affected-work map + ordered timeline complete
PASS diagnostician: sentinel authoritative alone; stub only annotates
PASS nemotron seam: stub offline, live client ready for her key

13/13 tests passed

=== test_robust ===
127.0.0.1 - - [22/Oct/2026 18:15:03] "GET / HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 18:15:03] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 18:15:03] "GET /api/timeline?limit=10 HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 18:15:03] "GET /api/affected HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 18:15:03] "GET /api/money HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 18:15:03] "GET /api/report HTTP/1.1" 200 -
PASS config: defaults reproduce behavior; YAML overrides merge
PASS threaded smoke: 4x25 invocations, no lost updates, no duplicate effects
PASS checkpoint versioning: unknown schema rejected, failover continues fresh
PASS ledger export: valid forensic JSON with windows, affected-work map, TSFD/TRV/AFR
PASS metrics: TSFD/TRV/AFR definitions hold
PASS dashboard: all endpoints 200 with JSON on ephemeral port
PASS nemotron: 2 retries then success, no exception
PASS nemotron: circuit opens after 3 failures, silent stub fallback
PASS nemotron: never raises; sentinel verdicts identical on/off

9/9 tests passed

=== test_nemotron ===
PASS generator: no key -> static fallback, deterministic oracle
PASS generator: key set but no live opt-in -> stays static (offline)
PASS generator: live=True or CONTINUITY_LIVE=1 + key -> Nemotron selected
PASS generator: 3 Nemotron scenarios, deterministic oracle attached
PASS oracle: Nemotron-written probes judged deterministically (healthy passes, gray fails)
PASS generator: garbage output / dead transport -> silent static fallback
PASS narrative: labeled advisory, never alters a verdict
PASS client: base URL (.com) and default model match verified docs
PASS client: POST path, Bearer auth, body shape, parsing all verified
PASS diagnostician: stub by default; Nemotron only with live opt-in + key
PASS credit-safety: full world, key set, requests.post tripwire -> zero HTTP calls
PASS credit-safety: direct client construction gated at transport boundary

12/12 nemotron rework tests passed

=== test_mcp ===
PASS mcp list_incidents: both incidents, right dispositions
PASS mcp get_incident: stage records + disposition for INC-1043
PASS mcp get_incident: unknown id returns found=False, no raise
PASS mcp affected_work: matches the ledger exactly
PASS mcp fencing_state: window, failover tick, live epoch
PASS mcp fencing_state: live_epochs None in file mode (honest)
PASS mcp ledger_entries: kind filter, limit, cap
PASS mcp narrative: deterministic stub text, names the role
PASS mcp metrics: tsfd_ticks present
PASS mcp read-only: report untouched after every tool
PASS mcp build_server: 7 read-only tools registered

11/11 tests passed

=== test_showcase ===
PASS showcase index: 5 scenarios listed
PASS showcase gray: FAILOVER, affected-work map, narrative
PASS showcase healthy: no false failover
PASS showcase semantic: gray semantic caught and shown
PASS showcase duplicates: standby resumed, no double apply
PASS showcase 404: unknown scenario
PASS showcase: live view intact, no $20K panel

7/7 tests passed

=== test_sim ===
PASS nlu: conversational prompt -> start_task INC-1043 payments-api
PASS nlu: checkout + database specs map deterministically
PASS nlu: control intents (inject/continue/report/ablation/reset/help)
PASS offline: key in env cannot flip the sim online
PASS beat: gray failure -> contrast + fenced + checkpoint resume + duplicates prevented
PASS beat: silent failure -> replayed by standby (middle bucket)
PASS report: three buckets populated + scorecard + rerun command
PASS checkpoints: keyed by (agent, incident), no cross-talk
PASS ablation: baseline executes restart:database; layer blocks it; scorecard from the real ledger
PASS fence: stale write from fenced primary rejected at the store
PASS fence: no failover yet -> honest nudge, not a fake test
PASS honesty: faults labeled simulated; invariants named, not implied
PASS nlu: fence_test intent
PASS chat: 'run the ablation' returns the live comparison
PASS ablation: silent failure -> replayed by standby
PASS incident view: standby_activated present in incident timeline
PASS copy: no $20K language; framed as a reliability layer

17/17 sim tests passed

=== test_journal ===
PASS journal: canonical operation fingerprint
PASS journal: fingerprint covers service/op/target/params
PASS journal: key shared across operations -> rejected
PASS gateway: agent never saw the receipt; retry from SQLite
PASS gateway: stale generation rejected before provider dispatch
PASS journal: intent -> commit lifecycle
PASS journal: same key+payload retry reuses receipt, single effect
PASS journal: same key + different payload -> conflict, never silent
PASS journal: state survives close/reopen (crash recovery)
PASS journal: unknown with no receipt -> verify provider, never blind retry
PASS scenario: baseline double-books, protected books exactly once
PASS store: duplicate action id refused even past the journal
PASS receipt: every field read off journal/ledger/store
PASS offline: key in env cannot flip the journal scenario online
PASS honesty: no banned language in new/changed files

15/15 journal tests passed

```
