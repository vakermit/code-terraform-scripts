---
task: "Phase 3 — full base automation platform for Code: Terraform"
slug: 20261019-150000_phase03-automation-platform
project: code-terraform-game
phase: climbing
progress: 2/48
started: 2026-10-19T15:00:00Z
updated: 2026-10-19T16:40:00Z
principal_stated_goal: "then we will do a full rewrite for the next phase (3?)"
principal_stated_goal_source: conversation
principal_stated_goal_signal: 4
principal_stated_goal_locked: 2026-10-19T15:00:00Z
context_sufficient: true
interview_invoked: true
---

## Problem

Phase 2 automates machines one at a time. Each script is a competent local loop, and a Control Room card broadcasts an advisory policy that machines may honour or ignore. That was the right design under a belief that turned out to be only half true: hardware actions are indeed `[[self only]]`, but power breakers, script execution, deployment, construction planning and purchasing are all remotely writable, and planet-wide power is fully readable. So phase 2 leaves the base with no one actually in charge.

That gap stops mattering and starts hurting at tier 3. Mk III generators run **200× supplied and 5× starved**, while one Oxygen Mk III and one Pressure Mk III together want 13 t/h of water from a 10 t/h well. Brownout is all-or-nothing with no consumer priority and no partial shedding. Nothing in phase 2 can resolve a 40× swing that hinges on which machine gets the water, because nothing in phase 2 is allowed to say no.

## Vision

I leave the base for an hour of real time and come back to find it further along than I would have driven it myself — and when I ask why the smelter is off, the answer is one line on a card, not an investigation. The planner has been quietly measuring what a tonne of water buys in each pillar and spending it where it earns most; the base shed load *before* a brownout rather than recovering from one; a dust storm was decoded and collected inside its window while freight kept moving. Euphoric surprise is reading the decision trace and finding the machine made a call I would not have thought of, for a reason I can check.

## Out of Scope

- **No replacement of per-machine scripts.** Setpoints die with the owning script, so every machine keeps a permanent local loop. The platform governs; it never actuates.
- **No remote process control.** Throttles, recipes, navigation, drone dispatch, port wiring and Supply Dock orders stay local, because the API forbids otherwise.
- **No runtime code deployment in v1.** `apply_variant` works but requires a stopped target, which resets its setpoints. One universal script per machine type, role read from the bus.
- **No solver.** Four scarce currencies and a learned value model is a small linear program, and we have no linear programming available. Greedy ranking by the binding constraint is the committed approach.
- **No contract puzzle automation.** Contract solutions are one-shot answers living in `scripts/common/`; they are not phase work.
- **No optimisation of things the game already automates.** Fluid routing over built pipes and power pooling across wired subnets are the game's job, and scripts cannot choose a pipe route.
- **No second-guessing the operator.** A manual override wins, always, and is never silently reverted.

## Language

**Kernel** — the four cooperating Automations taken together. _Avoid_: "the controller", which in phase 2 named a single Control Room card and carried the false implication that it drives machines. The kernel allocates and polices; it cannot drive anything.

**Loop** — one Automation with one cadence: safety, logistics, planner, opportunity. _Avoid_: "service", "daemon". Each loop is a single script restarting from line 1 on load, which is the property that matters.

**Envelope** — what the safety loop publishes: how much of each scarce good is available to spend this moment, after reserve. _Avoid_: "budget", which got used for both the available total and an individual machine's share, and confused the two in conversation.

**Lease** — one machine's current allowance of a scarce good, broadcast with a freshness age. _Avoid_: "policy" (phase 2's word): a policy was advisory and base-wide, a lease is per-machine and expires.

**Shed order** — the planner's ranked list of what to cut first. _Avoid_: "priority", which invites a fixed subsystem hierarchy rather than a ranking recomputed from measured marginal value.

## Principles

- Absence of the kernel is a normal condition, not a fault. Every machine must behave sensibly when nothing is talking to it, because save/load, a stop and a crash all look identical from the machine's side.
- Fail-safe direction is a property of the machine, not of the controller. Life support holds; discretionary work idles. Only the machine knows which it is.
- The expensive thinking belongs out of the emergency path. Rank slowly, act fast on the ranking.
- A decision you cannot explain is a decision you cannot improve. Explanation is part of the feature, not instrumentation added later.
- Measure rather than assume, but start from the documented number. A seeded belief that is wrong and corrected beats an unseeded belief that never forms.
- One writer per piece of state. Contention is a design choice, and we decline it.

## Constraints

- Four Automations maximum for the kernel, against a 50-per-save cap. Each is one script with no `self`.
- The Data Archive is the only durable memory: 2,048 entries, 96-character keys, JSON-safe values of at most 8 levels and 16,384 nodes. Nothing sweeps it.
- The Signal Bus carries live coordination only: 64 messages per queue, 512 channels, payloads of at most 8 levels and 1,024 values.
- Every capability must be probed before use. `get_component("notebook")`, `("comms")`, `("markers")` and `("terraforming")` each return `None` before their research, and the platform must degrade rather than fail.
- Scripts restart from line 1 with no locals on save, load, stop and error. All kernel state reloads from the Archive on every start, and every write is idempotent.
- Machine ids are stable for the life of the save; display names are renameable. Key on ids only.
- The repo is the source of truth; code reaches the game through `bin/ct_sync.py`. Nothing is authored in the in-game editor except to be pulled back with `zyx`.
- `scripts/phase03/` must remain resolvable at all times: anything not yet rewritten falls back to `phase02` and `common`, so the base is never half-broken mid-rewrite.

## Goal

"then we will do a full rewrite for the next phase (3?)" — rewrite the script tree as `scripts/phase03/`, where four Automations form a one-directional pipeline (safety publishes an envelope, the planner allocates within it and ranks what to shed, logistics and opportunity execute), machines self-throttle to broadcast leases and fall back to their own declared fail-safe, the planner learns what each scarce unit buys in Terraform Points and spends accordingly, and every allocation is explainable from a decision trace on a card. Done means the base runs unattended through a brownout threat, a well going dormant and a storm window without operator intervention, and that each of those events is legible afterwards.

## Not yet specified

- fog: what the planner's value function should do with a pillar that is already complete but whose machines still feed the carbon cycle — the docs warn against shutting such a supply down, but give no reading that distinguishes it. Resolves by finding whether `pillars()` or `atmosphere` exposes the coupling.
- fog: whether Insight spending can be ranked at all before a second colony exists, since the curve is cumulative and shared. Resolves once two colonies are founded and `get_insight()` can be sampled against population.
- fog: how to estimate a Pioneer-hour's cost well enough to allocate it as a currency — phase 2's scout library remembers real trip costs, but not in a form the planner can price against water. Resolves by instrumenting one construction round trip and reading the recorded cost back.
- fog: whether the four loops can each complete a pass inside their cadence at late-game machine counts, given a per-tick step budget and no documented step count. Resolves by measuring a full planner pass against `clock` once the base is large.

## Test Strategy

<!-- Column order is the contract: isc | type | check | threshold | tool | anchors_to -->

| isc | type | check | threshold | tool | anchors_to |
| --- | --- | --- | --- | --- | --- |
| ISC-1 | bash | every phase03 script parses | 0 errors | `bash tools/check-syntax.sh scripts/phase03` | literal |
| ISC-2 | bash | ct_sync resolves every save slot under phase03 | 0 unresolved | `python bin/ct_sync.py status --phase 3` | literal |
| ISC-3 | bash | no phase03 script hard-codes a machine id | 0 matches | `bash tools/check-no-hardcoded-ids.sh` | derived: discovery-by-enumeration |
| ISC-4 | bash | every component handle is None-checked before use | 0 unguarded | `bash tools/check-capability-probes.sh` | derived: capability-probing |
| ISC-5 | manual | a second kernel start changes no state | 0 archive diffs | `start, snapshot keys, restart, compare` | derived: restart-idempotence |
| ISC-6 | manual | kernel runs with the Data Archive absent | runs, logs degraded | `force notebook None, observe console` | derived: capability-probing |
| ISC-7 | manual | kernel runs with the Signal Bus absent | every machine at fail-safe | `force comms None, observe machines` | derived: capability-probing |
| ISC-8 | manual | a lease whose age is None is treated as stale | fail-safe fires | `save, reload, observe the restored broadcast` | derived: freshness |
| ISC-9 | bash | no clear call is made with an empty prefix | 0 matches | `bash tools/check-no-wipe.sh` | derived: destructive-guard |
| ISC-10 | bash | no self-only method is called through a remote handle | 0 matches | `bash tools/check-no-remote-actuation.sh` | derived: govern-not-drive |
| ISC-11 | manual | a water-fed Mk III generator throttles to its lease | throttle tracks lease | `set a lease by hand on the bus, read the throttle` | literal |
| ISC-12 | manual | oxygen holds last good setpoint when kernel silent | no idle | `stop all automations, observe oxygen output` | derived: fail-safe-direction |
| ISC-13 | manual | smelter idles when kernel silent | throttle 0 | `stop all automations, observe the smelter` | derived: fail-safe-direction |
| ISC-14 | bash | FAIL_SAFE is declared in every machine script | 1 per script | `bash tools/check-fail-safe-declared.sh` | derived: fail-safe-direction |
| ISC-15 | manual | the envelope names watts, tonnes and reserve | 3 fields present | `read the envelope broadcast` | literal |
| ISC-16 | manual | one allocation dict is published per outpost | 1 per outpost | `list channels and count` | literal |
| ISC-17 | manual | projected load stays under generation minus reserve | 0 brownouts in 24h | `run 24 world hours, read the trace` | literal |
| ISC-18 | manual | the wattage table converges on measurement | within 10% observed | `compare the archive table to power total()` | derived: measure-not-assume |
| ISC-19 | manual | only machines safety shed are restored | operator-off untouched | `force a deficit, then relieve it` | derived: no-stranded-machines |
| ISC-20 | manual | life support is never shed first | ranks last | `force a deficit, read the shed sequence` | derived: fail-safe-direction |
| ISC-21 | manual | allocation shifts toward the largest pillar gap | follows the gap | `starve one pillar, observe the next allocation` | literal |
| ISC-22 | manual | the rate table is seeded and tagged with confidence | every entry tagged | `read the table before any measurement` | derived: measure-not-assume |
| ISC-23 | manual | a probe is capped and written to the trace | <=10% free water | `force a stale belief, observe the probe` | derived: bounded-exploration |
| ISC-24 | manual | an observed delta upgrades a belief to measured | tag changes | `allocate, wait, read the tag` | derived: measure-not-assume |
| ISC-25 | manual | constructor-hours appear as an allocated currency | present in allocation | `read an allocation during a build round` | literal |
| ISC-26 | manual | shed follows the planner ranking | matches shed order | `force a deficit, compare to the list` | derived: rank-slowly-act-fast |
| ISC-27 | manual | the planner never allocates beyond its envelope | sum <= envelope | `sum an allocation against its envelope` | derived: pipeline-direction |
| ISC-28 | manual | freight legs reconnect their ports per leg | one connect per leg | `run a two-leg haul, read the trace` | derived: no-held-connections |
| ISC-29 | manual | a planned build is executed by a parked Pioneer | job completes | `plan a pipe, observe the build` | literal |
| ISC-30 | manual | dock orders are reassigned after completion or expiry | re-enabled in one pass | `complete an order, observe the dock` | literal |
| ISC-31 | manual | a dust-storm message is decoded and collected in window | >=1 collection | `trigger a dust storm, observe the trip` | literal |
| ISC-32 | manual | freight is preempted only on an expiring deadline | trace names it | `saturate drone hours, trigger a storm` | derived: earliest-deadline-first |
| ISC-33 | manual | transmission fragments outlive the audible window | packets retained | `read fragments after the window closes` | derived: stateless-source |
| ISC-34 | manual | Insight is spent from a pooled ranking | spend crosses species | `reach two colonies, observe an unlock` | literal |
| ISC-49 | manual | every discretionary machine appears in an allocation | 0 unnamed | `compare an allocation to the enumerated consumers` | derived: pipeline-direction |
| ISC-35 | manual | any idle machine is explained by one trace row | answer in one row | `pick an idle machine, read the card` | literal |
| ISC-36 | manual | the trace is bounded per loop | <=40 rows, 1 key each | `read each loop's trace key node count` | derived: archive-budget |
| ISC-37 | manual | the card renders state and issues no commands | 0 writes from the card | `read the card source, watch a full tick` | derived: cards-are-views |
| ISC-38 | manual | each loop reaps its own prefix | 0 orphans after decommission | `decommission a machine, read archive keys` | derived: one-writer |
| ISC-39 | manual | the Crop Automator queue head is policed | blocked head reordered | `block the head, observe the reorder` | literal |
| ISC-40 | bash | no loop writes a key under another prefix | 0 cross-writes | `bash tools/check-prefix-ownership.sh` | derived: one-writer |
| ISC-42 | manual | an operator override survives a planner cadence | override held | `set an override, wait one full cadence` | derived: operator-first |
| ISC-43 | manual | three events are handled unattended in one hour | all three handled | `play one hour hands-off, read the trace` | literal |
| ISC-44 | manual | trace rows read as reasons a day later | operator judgement | `read forty rows cold, a day later` | derived: antecedent |
| ISC-45 | manual | a habitat is held inside its gas and liquid bands | within low and high | `read bands against levels across a crossing` | literal |
| ISC-46 | manual | the Plant Terraformer is never fed a starved batch | 0 starved batches | `run three batches, read the trace` | literal |
| ISC-47 | manual | biosite harvest respects the site cooldown | 0 wasted trips | `route to a cooling site, observe the refusal` | derived: measure-not-assume |
| ISC-48 | manual | all four automations run from repo source | 4 running, source matches | `sync, start each, compare source` | literal |
## Features

### F0 · Cross-cutting
Why: the properties that must hold in every script, because each one is a way the whole platform fails silently rather than loudly.

- [x] ISC-1: Every script under `scripts/phase03/` parses clean.
- [x] ISC-2: `ct_sync status --phase 3` resolves every save slot with no ambiguity.
- [ ] ISC-3: No phase03 script contains a hard-coded machine id; all discovery is by enumeration.
- [ ] ISC-4: Every component handle is probed for `None` before first use.
- [ ] ISC-5: Each loop reloads its full state from the Archive on start, and a second start changes nothing.
- [ ] ISC-6: The kernel runs with the Data Archive absent, logging a degraded mode rather than raising.
- [ ] ISC-7: The kernel runs with the Signal Bus absent, holding every machine at its declared fail-safe.
- [ ] ISC-8: Anti: no freshness check treats a `None` broadcast age as fresh.
- [ ] ISC-9: Anti: no script clears a marker or archive family with an empty prefix.
- [ ] ISC-10: Anti: no kernel loop invokes a self-only method through a remote handle.
- [ ] ISC-38: Each loop reaps its own Archive prefix against a fresh enumeration.
- [ ] ISC-40: Anti: no loop writes a key under another loop's prefix.
- [ ] ISC-43: The base handles a brownout threat, a dormant well and a storm window across one unattended hour.
- [ ] ISC-41: [DROPPED - duplicate of ISC-10; see Decisions 2026-10-19]

### F1 · One lease, end to end
Why: it proves the whole stack on a single path before any of it is widened, so an architectural mistake costs one subsystem rather than the rewrite. (after: ISC-1)

- [ ] ISC-11: A water-fed Mk III generator throttles to the water figure in its lease.
- [ ] ISC-12: The oxygen generator holds its last good setpoint when no fresh lease exists.
- [ ] ISC-13: The smelter idles when no fresh lease exists.
- [ ] ISC-14: `FAIL_SAFE` is declared in each machine script, not supplied by the kernel.
- [ ] ISC-15: The safety loop publishes an envelope naming free watts, free tonnes and the reserve floor.
- [ ] ISC-16: The planner publishes per-outpost allocation dicts keyed by machine id, one broadcast per outpost.

### F2 · The base never browns out
Why: brownout is all-or-nothing with no consumer priority, so the only winning move is to never reach the cliff. (after: ISC-15)

- [ ] ISC-17: Projected load stays under generation minus reserve across 24 world hours of normal play.
- [ ] ISC-18: The per-machine wattage table is measured rather than assumed.
- [ ] ISC-19: A machine the safety loop switched off is switched back on when headroom returns, and a machine the operator switched off is left alone.
- [ ] ISC-20: Anti: life support is never the first thing shed.

### F3 · Scarcity goes where it earns most
Why: the 200x-versus-5x cliff means allocation, not throughput, is the late-game lever; this is the feature the whole platform exists for. (after: ISC-16)

- [ ] ISC-21: Allocation shifts toward the pillar with the largest gap to its next target.
- [ ] ISC-22: The exchange-rate table is seeded from documented figures and marked with its confidence.
- [ ] ISC-23: A probe into a starved pillar is capped at a tenth of free water and written to the trace.
- [ ] ISC-24: An observed TP delta against spend upgrades a belief from seeded to measured.
- [ ] ISC-25: The planner allocates constructor-hours as a currency alongside watts and tonnes.
- [ ] ISC-26: The shed order is published with every allocation and ranked by marginal value.
- [ ] ISC-27: Anti: the planner never allocates beyond the envelope it was given.
- [ ] ISC-42: An operator override survives a full planner cadence without being reverted.

### F4 · Material and builds arrive without me
Why: the game has no cross-site item transport, so every tonne that moves is a scripted leg, and this is where unattended play actually breaks down.

- [ ] ISC-28: Freight legs reconnect their ports per leg rather than assuming a held connection.
- [ ] ISC-29: A planned construction is executed by a Pioneer that parks in range and calls execute.
- [ ] ISC-30: Supply Dock orders are reassigned and re-enabled after a completion or weekly expiry.

### F5 · Windfalls are not missed
Why: storm aftermath, weekly boards and Insight all expire or compound on their own clocks, and steady-state logistics will always starve them.

- [ ] ISC-31: A dust-storm message is decoded from retained packets and collected inside its window.
- [ ] ISC-32: Opportunity preempts a freight leg only when a deadline would otherwise lapse, and says so in the trace.
- [ ] ISC-33: Transmission fragments are retained in the Archive, since the receiver keeps no history.
- [ ] ISC-34: Insight is spent from a pooled ranking rather than per-colony.

### F6 · I can see why
Why: four loops allocating from a learned model is opaque in a way phase 2 never was, and per-script breakpoints cannot debug a decision spread across four scripts.

- [ ] ISC-49: A discretionary machine is named in every allocation, so permission is granted rather than merely not withheld.
- [ ] ISC-35: Any machine being off is explained by one row of the decision trace.
- [ ] ISC-36: The trace is bounded to forty rows per loop, each loop owning its own key.
- [ ] ISC-37: A card renders the envelope, the current allocation and the trace without issuing commands.
- [ ] ISC-44: Antecedent: the trace rows read as reasons a day later, with the machine, the rank, the figure and the cause on one line.

### F7 · The biosphere runs itself
Why: plants and wildlife are half the Terraform Index, and their 12-to-24-hour feedback loops are the one place hand-tuning is impossible.

- [ ] ISC-39: The Crop Automator queue head is policed, reordered when it blocks.
- [ ] ISC-45: A habitat is held inside its gas and liquid bands across a stage crossing.
- [ ] ISC-46: The Plant Terraformer is fed from measured Forage throughput, never a starved batch.
- [ ] ISC-47: Biosite harvest respects the site cooldown rather than sending a wasted trip.

### F8 · Phase 3 deploys from the repo
Why: the kernel is worthless if it cannot reach the game, and the deployment path for an Automation is unverified today.

- [ ] ISC-48: All four automations run in game from repo source, confirmed identical.

## Decisions

- 2026-10-19: Kernel hosted in Automations, not a Control Room card. A card dies on brownout and an Automation does not, which is disqualifying for the loop that manages brownouts.
- 2026-10-19: Authority is a supervisor with budget plus breakers, not an orchestrator. All process control is `[[self only]]` and setpoints reset when the owning script stops, so central actuation is not available at any price.
- 2026-10-19: Objective is marginal TP per scarce unit, learned. `pillars()` gives gaps but TP does not map 1:1 to raw units, so the rate must be measured.
- 2026-10-19: Enforcement is lease-then-breaker. Cooperation in the normal case, an absolute breaker for a machine that overruns or stops answering.
- 2026-10-19: One universal script per machine type with its role read from the bus, rather than role variants hot-swapped by the kernel. `apply_variant` needs a stopped target, and stopping resets setpoints.
- 2026-10-19: Four loops, not three. Deadline-driven windfalls and steady-state freight genuinely compete, and a storm must not be able to starve hauling.
- 2026-10-19: refined: the loops form a one-directional pipeline rather than a priority stack. A safety loop empowered to overrule an allocation would have to re-derive which machine matters, duplicating the planner in the worst conditions.
- 2026-10-19: Shedding follows a planner-published ranking. The slow loop ranks, the fast loop obeys, which keeps the expensive thinking out of the emergency path.
- 2026-10-19: One writer per Archive prefix, few keys holding fat dicts keyed by machine id. Contention needs two writers, so this makes `transaction()` largely unnecessary.
- 2026-10-19: Leases live on the bus, not in the Archive. Machines need a freshness age and the Archive has none; the Archive keeps what was learned, the bus carries what is true now.
- 2026-10-19: Vehicle time is a first-class allocated currency. Overrode a recommendation to leave it inside logistics; the planner now carries four currencies and needs learned travel costs.
- 2026-10-19: Full rewrite including the biosphere. Overrode a recommendation to scope to the industrial tier; the phase fallback chain makes a partial landing safe, so the larger target costs no safety.
- 2026-10-19: Sequencing is one vertical slice, then widen. Nothing else validates the pipeline before most of the code is written.
- 2026-10-19: Automation deployment is solved, and the fog entry asking about it is killed. An Automation created in game appears as `automation_N.py` in the same external-editor directory as every other script, so `ct_sync` reaches it exactly as it reaches a Control Room card — by slot id, through the slot map, with no new mechanism. ISC-48 already carries the claim.
- 2026-10-19: Registered `capability`, `bus` and `trace` by writing `state.libraryScripts` in the save directly, with the game stopped and a backup taken, because the in-game Import as Game Library step is not something a script can reach. The schema was copied from an existing entry rather than invented: source three times over, a fresh `libraryIncarnationId` from the high-water counter, everything else at its idle default.
- 2026-10-19: Safety ships with its breaker disarmed (`ENFORCE = False`), printing what it would shed rather than shedding. The first pass runs on an empty wattage table and reads the base from live draw alone, so on a base near capacity it could shed within seconds of starting, against the crude fallback order because no planner is ranking yet. A loop that can switch a base off earns a rehearsal.
- 2026-10-19: Safety restores only machines recorded in its own shed ledger, persisted as `safety.shed`. Restoring every unpowered machine would have overridden the operator's own power-offs, which Principles forbids, and an unpersisted ledger would leave shed machines dark forever after a reload.
- 2026-10-19: The wattage table is a high-water mark per machine type rather than a live reading. A grid member's consumed figure is documented as 0 W for a powered-off or idle machine, so the live reading cannot say what a machine would draw once it starts, which is the only figure headroom needs.
- 2026-10-19: ISC-41 dropped as a duplicate of ISC-10; both asserted that no remote actuation call appears in phase03. Tombstoned rather than renumbered, per ID stability.
- 2026-10-19: F7 and F8 re-homed. Archive hygiene (ISC-38, ISC-40) and the unattended-hour acceptance claim (ISC-43) were misfiled under biosphere and deployment; they are cross-cutting. ISC-45 to ISC-48 added so both features carry claims of their own subject.
- 2026-10-19: Opportunity may preempt freight on an expiring deadline, against a standing drone reserve the planner holds back. Aftermath expires in 48 to 96 hours behind a 4-hour decode window, so a fully committed fleet would simply lose it.

## Learning

- conjectured: an unregistered file under `lib/` is importable anyway, since both machine scripts reported `running` with no error after the swap.
  refuted by: the console history. `automation_1` died on `ModuleNotFoundError: No module named 'capability'` at its import line. The machine scripts' own failures had simply rotated out of a 500-entry console window before I looked.
  learned: registration is required, and "no error in the snapshot" is not evidence of success when the evidence window is a ring buffer. Read the console history, not the status field.
  criterion now: ISC-48.

- conjectured: the decision trace could be one Archive key that every loop appends to, since forty rows is small and the loops run at different cadences.
  refuted by: writing it. A shared key has two or more writers, which is exactly the contention the one-writer-per-prefix rule was adopted to avoid, and the Archive offers no lock worth building on.
  learned: a shared log is shared mutable state wearing a different hat. Each loop owns its own trace key and the card merges on the world hour, the only clock all four share.
  criterion now: ISC-36.

- conjectured: the planner need only allocate to machines that consume a scarce fluid, since those are the ones in contention.
  refuted by: writing the smelter. Its fail-safe is to idle, so a machine the planner never names idles forever. An allocation is permission, and silence reads as refusal.
  learned: a fail-safe of idle obliges the planner to name that machine every pass. Discretionary machines get a run grant with no quantity, because their draw already sits inside the envelope safety measured.
  criterion now: ISC-49.

- conjectured: central control was impossible because hardware actions are self-only, so the controller could only advise.
  refuted by: `run_control` documented verbatim as "use it to build a supervisor", carrying `allowsRemoteWrites: True`, alongside `power_control.set_powered` and `.total()`.
  learned: the self-only rule bounds *actuation*, not authority. Breakers, script lifecycle, deployment, construction and purchasing are all remote, and planet-wide power is readable.
  criterion now: ISC-15, ISC-17.

- conjectured: a lease could carry one global fail-safe instruction, since the kernel knows the situation best.
  refuted by: writing the first lease snippet, where kernel silence mapped to idle and would therefore have idled life support on a kernel crash.
  learned: fail-safe direction is knowledge the machine has and the kernel does not. It belongs in the script as a declared constant.
  criterion now: ISC-12, ISC-13, ISC-14.

## Verification

<!-- One-line provenance stubs only; the proof lives in git and in the save. -->

- ISC-1: `tools/check-syntax.sh scripts/phase03` green at a570daf.
- ISC-2: `ct_sync phases --phase 3` reports 41 of 41 resolved, no ambiguity, at a570daf.

## Remaining Work

- [ ] Create one Automation in game and record how it appears on disk — blocks the kernel's deployment path and is currently fog.
- [ ] Explicit slot mapping in `ct_sync` for cards and automations — delegated to its own session, since several `panel_N` slots currently collapse to one base name.
- [ ] ISC-11 cannot be verified on this base: every generator is tier 1, so no machine consumes water and the lease has nothing to throttle. It needs a Mk III pack installed before the claim means anything. Left as an open claim rather than a fog entry, because the question is precisely stated and the falsifier is nameable; only the hardware is missing.
- [ ] Write the five unwritten `tools/check-*.sh` probes that F0 claims already name — no-hardcoded-ids, capability-probes, fail-safe-declared, no-remote-actuation, no-wipe, prefix-ownership. ISC-1's probe exists and is green; the rest are named in Test Strategy but have no script yet, so those claims cannot go red-before-build until they do.
- [ ] Decide whether the Steam Condenser changes the water allocation problem enough to re-rank — gated behind 1,000,000 Plants, far outside this run.
