# OmegaSen — Full LLM Scenario Pack

Date recorded: **2026-08-14** (local time UTC+3)
Screen recording duration: **12 minutes 42 seconds**
Recording started: **12:31:34 PM local**
Recording ended: **12:44:16 PM local**

## What's in this pack

- `screen_recording.mov` — the raw macOS screen capture (S07–S10 only; see note below)
- `runs/` — all 10 scenario output folders. Each contains:
  - `run.log` — human-readable timeline of what happened
  - `metrics.json` — machine-readable metrics + verdict
  - `snapshots.jsonl` — raw Unity snapshots + action requests + lifecycle events, one per line

## All 10 scenarios — logs included

| # | Scenario | Wall clock | Duration ceiling | In video? |
|---|---|---|---|---|
| S01 | `llm_smoke` (RotateRight → RotateLeft → MoveAhead) | 12:18:04 | 45 s | ❌ before recording |
| S02 | `llm_cancel_mid_flight` (start MoveAhead, then Cancel) | 12:22:24 | 60 s | ❌ before recording |
| S03 | `llm_moveto_navmesh` (pick first destination, MoveTo) | 12:25:47 | 60 s | ❌ before recording |
| S04 | `llm_unadvertised_action` (guardrail test — LLM told to invent `Fly`) | 12:27:22 | 30 s | ❌ before recording |
| S05 | `llm_one_in_flight` (five rotations back-to-back) | 12:28:06 | 90 s | ❌ before recording |
| S06 | `llm_search_existing_target` (search for `Interactable`) | 12:29:58 | 90 s | ❌ before recording |
| **S07** | `llm_search_missing_target_crixi` (search for absent `Crixi`, 3 min) | **12:32:02** | 180 s | ✅ recording 0:28–3:28 |
| **S08** | `llm_free_play_60s` (undirected LLM play) | **12:35:33** | 60 s | ✅ recording 3:59–4:59 |
| **S09** | `llm_search_crixi_180s` (goal-directed Crixi search, 3 min) | **12:36:44** | 180 s | ✅ recording 5:10–8:10 |
| **S10** | `llm_navigate_to_globe` (directed goal to reach Globe + Interact, 2 min) | **12:42:08** | 120 s | ✅ recording 10:34–12:34 |

## Timing table — where S07–S10 sit inside the video

| Video offset | Wall clock | Event |
|---|---|---|
| 0:00 | 12:31:34 | recording started (S01–S06 already complete) |
| 0:28 | 12:32:02 | S07 starts |
| 3:28 | 12:35:02 | S07 ends |
| 3:59 | 12:35:33 | S08 starts |
| 4:59 | 12:36:33 | S08 ends |
| 5:10 | 12:36:44 | S09 starts |
| 8:10 | 12:39:44 | S09 ends |
| 10:34 | 12:42:08 | S10 starts |
| 12:34 | 12:44:08 | S10 ends |
| 12:42 | 12:44:16 | recording stopped |

## Why the video only covers S07–S10

S01–S06 were run first as a **dry-run**: short single-action smokes to check wiring, burn the first-call LLM latency spike, and verify the guardrails. Recording started once those were confirmed working, so the tape captures the **long-form exploratory runs** where video adds real signal over the text logs.

The `run.log`, `metrics.json`, and `snapshots.jsonl` for S01–S06 are still in this pack — nothing is lost, just not on tape.

## Reading a `run.log`

Every event line starts with `t+SS.ss` — seconds elapsed since that scenario's own connect. For S07–S10 (in the video), match against the "Video offset" column above and add.

Example — a `t+10.06` line in the S09 run means:
- 10.06 s after S09 connected (12:36:54 PM wall clock)
- Video offset 5:10 + 10.06 = **5:20 into the recording**

## What each scenario proves

- **S01–S05** — the machinery: warm-up sequence, mid-flight Cancel, NavMesh MoveTo, guardrail against unadvertised actions, one-in-flight serialization.
- **S06** — LLM-driven exploration + deterministic detection when the target is present.
- **S07** — same as S06 but target is absent; documents timeout path.
- **S08** — how OmegaSen chooses actions with no goal at all (baseline).
- **S09** — same environment/target as S07 but with a stronger goal-text prompt. Comparison against S07 shows the prompt's effect.
- **S10** — whether OmegaSen chooses `MoveTo` (over primitives) when a goal names a known destination.
