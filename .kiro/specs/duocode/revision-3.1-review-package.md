# DuoCode Revision 3.1 Review Package (final for gate review, strict hard-stop correction, RD-14 approved, PR #2 review addressed)

History: the revision 3.1 content was published on `spec/revision-3.1-review` and merged to `main` (PR #1, `b88580d`). The strict hard-stop correction (CR-9, section 3A) is on branch `spec/key-usage-strict-hard-stop`, created from that `main`. Commit hashes are reported with the branches, because a file cannot contain its own commit hash.

The project stays in specification and approval mode. This package contains no application code, no database migration and no implementation task. **All six gates are signed off. Gate 2's reopened sentence in `design.md` section 16 was re-confirmed the same day (see `tasks.md` 1.2). Task 1.9 (Phase 1 complete) is not. The task 1.8 fixes (CR-25, section 3C) reopened parts of Gates 1 to 5, which are awaiting owner confirmation. Task 1.7 is confirmed (2026-11-22). Task 1.8 awaits the owner marking it complete.** The architecture (Deno, TypeScript, Oak, PostgreSQL, Docker Compose, Caddy) is unchanged.

## 1. Gate status

| Gate | Task | Subject | Status |
|---|---|---|---|
| 1 | 1.1 | Requirements | **Signed off 2026-11-22**, David Johnson (G4DPZ), as at `53c46df`. R19 licensing text approved at Gate 6. CR-25 reopened R8.8, R10.7, R10.14, R20.3 and RD-16 to RD-20: awaiting owner confirmation |
| 2 | 1.2 | Architecture | **Signed off 2026-11-22**, David Johnson (G4DPZ), as at `bcba9f6`, as written (online rotation kept). OI-1 and OI-2 open. CR-24 command-list wording in `deployment.md` 2.1 and 6.3 and `design.md` section 3 **re-confirmed 2026-11-22**. The `design.md` section 16 status sentence **re-confirmed 2026-11-22**; CR-25 reopened `design.md` and `deployment.md` parts (section 3C): awaiting owner confirmation |
| 3 | 1.3 | OpenAPI specification | **Signed off 2026-11-22**, David Johnson (G4DPZ), as `openapi.yaml` draft 6 (CR-22: `500`/`503` on every operation, `429` on admin); CR-25 reopened `400` on four operations and the nickname input schema: awaiting owner confirmation |
| 4 | 1.4 | Database schema and state machine | **Signed off 2026-11-22**, David Johnson (G4DPZ), schema as at `e9c01eb`, state machine with CR-23 (write order includes the claim, pre-encryption check and commit-time check); CR-25 reopened `database-schema.md` and `state-machine.md` parts: awaiting owner confirmation |
| 5 | 1.5 | Security assessment | **Signed off 2026-11-22**, David Johnson (G4DPZ), `security-assessment.md` and `test-strategy.md` at `cbc43bf` plus the alignment fixes in CR-24 (threats T1 to T39); CR-25 reopened `security-assessment.md`, `test-strategy.md` and `simulator-design.md` parts: awaiting owner confirmation |
| 6 | 1.6 | Licensing files and contributor arrangements | **Signed off 2026-11-22**, David Johnson (G4DPZ). LI-1, LI-2 and LI-4 given; LI-3 (legal review) outstanding |
| Prerequisite | 1.7 | README confirmed | **Done 2026-11-22**, David Johnson (G4DPZ), "merge 9 and confirm 1.7" |
| Prerequisite | 1.8 | Copilot review of the specification | Findings fixed (section 3C). Awaits the owner marking it complete |
| Sign-off | 1.9 | Phase 1 complete, Phase 2 authorised | Not authorised |

## 2. What to read for each gate

| Gate | Read |
|---|---|
| 1 | `requirements.md` (decision register, R1 to R21), `traceability.md` |
| 2 | `design.md` (sections 5, 8, 9, 11), `deployment.md` (sections 4, 5, 6, 12) |
| 3 | `openapi/openapi.yaml` |
| 4 | `database-schema.md` (especially 3, 6.2), `state-machine.md` |
| 5 | `security-assessment.md` (2.2, 3.1, 3.3a, 3.5, 6.2, 7), `test-strategy.md`, `simulator-design.md` |
| 6 | `LICENSE`, `NOTICE`, `CONTRIBUTING.md` at the repository root, and section 6 below |

## 3. How your latest decisions were incorporated

| Decision | What changed | Where |
|---|---|---|
| RD-2 approved with conditions | Values stay configurable (tested), enforcement is shared through PostgreSQL, store failure fails closed with `503` | R20.2, R20.7, R20.8, `deployment.md` 4.2, TS-RATE |
| RD-10 approved | Warn 2^27, rotate by 2^28, hard stop 2^30. The counter accounts for every encryption invocation, including failed or rolled-back transactions | R10.10, `security-assessment.md` 3.3a |
| RD-13 approved with conditions | **The mechanism changed** (and was tightened again by CR-9, section 3A). The draft updated a counter at the end of the request transaction, which a rollback would undo. It is now a durable reservation: a block of encryptions is reserved in its own autocommit transaction before any encryption, each invocation consumes a unit, and an encryption without a reserved unit cannot happen. The counter can over-count, never under-count. After any restore, a new key is activated before traffic, the old key stays `DECRYPT_ONLY` for decryption and never becomes `ACTIVE` again | R10.10, R10.13, R21.4, `database-schema.md` 6.2, `design.md` 9.1, `deployment.md` 6.1 |
| RD-11 approved | Third serialisation exception with your five conditions. The replacement token never appears in logs, diagnostics, metrics, traces or error responses. Replay never reactivates the old token | R8.13, R10.7, R13.2, `state-machine.md` 3.1, TS-CRED, TS-SEC |
| RD-12 approved | Rotation revokes the player's unused rematch capability in the same transaction (already specified, now recorded as approved and tested) | R8.6 |
| CH-1 with qualification | Display-security tests added. New R1.5 (JSON string only, `nosniff`, clients must escape and isolate bidirectional context) | R1.5, TS-VAL |
| CH-2 | `rate_limits` excluded from backups, rate-limit key not backed up | `deployment.md` 5 |
| CH-3 with qualification | **Rule changed from my draft.** Creating a rematch revokes every other unused capability of the original in the same transaction. The loser then receives `401`. Minting after a marker exists still returns `409` | R9.9, `state-machine.md` 3, 4 |
| CH-4 with qualification | Player-keyed buckets. Rotation does not reset them (tested) | R20.4, TS-RATE |
| CH-5 with qualification | Deterministic rotation keys derived from seed, game number, seat and rotation index, UUIDv4 format. The simulator refuses to run without `--test-deployment` | R15.5, `simulator-design.md` |
| CH-6 | Module pinned to its exact commit. Reproducible build and provenance checks retained | `deployment.md` 4.3 |

Other changes in this round: the OpenAPI document was edited so lint reports 0 warnings (section 5.1). Lock levels were simplified to L0 (autocommit rate-limit and reservation statements), L1 (game row) and L2 (child rows). The key ring gains `generation` and `deactivatedAt`. The OD-1 to OD-10 table and decision-to-requirement rows for CH, LI and OD-9, OD-10 were added so the register and the traceability matrix agree. The register no longer has any pending technical decision.

## 3A. Strict encryption hard-stop correction (CR-9, owner feedback)

Your point was right. The revision 3.1 draft refused a reservation only after the total was already above the limit, and let concurrent instances overshoot by up to one block each. Both are removed. This section is the summary. The specification is `database-schema.md` section 6.2.

**Is the 32-shard design retained?** It is **replaced** by one authoritative counter row per key. With shards, two instances working on different shard rows could each see room below the limit and both reserve, because the total across shards was not checked atomically. I confirmed this with a deterministic negative control in the test tool: two sessions that both saw room each inserted one block into different shards and the total ended at 2^30 plus one block. One row per key removes the race, and the contention (one statement per 1024 encryptions per instance on one row) is not significant at DuoCode's volume.

**Terms (used identically everywhere).** A *reserved unit* is one permitted encryption counted in `R`. An *encryption invocation* is one actual encryption and consumes one reserved unit held by the instance. An *allowance* is the reserved units an instance holds unconsumed, and is part of `R`.

**The reservation algorithm.** The authoritative statements (registration, reservation, pre-encryption check, commit-time check, sealing) are in `database-schema.md` section 6.2 and are not copied here, so this package cannot drift from them (CR-14). In outline: one row per key holds the reserved total; an instance reserves whole blocks with one atomic conditional statement in its own autocommit transaction before any encryption; it claims units for an operation before the transaction and runs the pre-encryption check last; each encryption consumes a claimed unit; every writing transaction re-checks the sealed flag under a share lock before commit; and a `CHECK` at 2^30 is the database backstop.

**Guarantees** (G1 to G8 in the specification, each tested): `R` never exceeds 2^30. Every invocation consumes a reserved unit, including those in failed or rolled-back transactions. Outstanding allowances are inside `R`. No instance can obtain units that take `R` past the limit. Concurrent reservations cannot pass the limit independently, because they all update one row and a waiting update re-evaluates the limit against the latest committed total. An instance never encrypts with an exhausted allowance. A restore cannot let encryption resume under a key whose counter may have rolled back. `R` can overestimate, never underestimate.

**Exact threshold behaviour**

| Reserved units reach | Behaviour |
|---|---|
| 2^27 | Warning metric, one operational warning per key per process start, admin health state `warning`. Reservations continue |
| 2^28 | `ROTATION_OVERDUE`: critical alert, admin health state `degraded` (the public `/healthz` stays `ok` and reveals nothing about keys), rotation is mandatory. **Reservations continue to be granted until the hard stop** (RD-14, approved), because refusing at 2^28 would turn a late rotation into an outage while the margin is still large |
| 2^30 | Hard stop. A block that would take `R` above 2^30 is refused whole. `R` can equal 2^30 exactly, so at most 2^30 encryptions ever happen. Once instances use the units they hold, no encryption occurs under the key and encrypting operations fail closed with `503`. Decryption is unaffected |

**Restore.** The restore procedure activates a new key as the only active key, **seals every older key** (`keys:seal` sets its counter to 2^30, so any reservation under it is refused even if the ring were wrong), and restarts every instance so no allowance survives, all before traffic. A planned rotation seals the old key once every instance runs the new ring.

**RD-14: approved.** Reservations between 2^28 and 2^30 continue (rotation overdue: critical alert and degraded admin health state), and the hard stop at 2^30 is absolute and inclusive. It is recorded in the decision register and the traceability matrix.

**Files changed for CR-9:** `database-schema.md`, `design.md`, `security-assessment.md`, `deployment.md`, `test-strategy.md`, `requirements.md` (R10.10, R10.13, CR-9, RD-14, glossary), `traceability.md`, `tasks.md`, `verify-schema.py`, `check-consistency.py`, and this package.

## 3B. Rotation after 2^28 (CR-10) and PR #2 review findings (CR-11 to CR-21)

### Rotation completed after the 2^28 threshold (your clarification)

Specified once in `database-schema.md` section 6.3, summarised in `security-assessment.md` 3.6a, and the same in `deployment.md` 6.1 (restore) and 6.4 (planned rotation).

| Your requirement | How it is met |
|---|---|
| The new key becomes the active key | New key registered and **staged** on every instance first, then set as the only `ACTIVE` key by a rolling restart. The ring is read only at process start, so the active key cannot change while a process runs |
| The previous key becomes decrypt-only | `DECRYPT_ONLY` with `deactivatedAt`. Decryption continues. It never becomes active again |
| Outstanding in-memory allowances for the previous key must no longer be usable | Two mechanisms. Restarted instances have no allowance (memory only). The previous key is then **sealed** (`sealed = true`, counter at 2^30), and every encrypting request runs a pre-encryption check on the sealed flag before it begins, so an instance that was missed cannot use a stale allowance for any request that begins after the seal commits. Since the third review, no ciphertext under the previous key can be committed after the seal, because every writing transaction re-checks the sealed flag under a share lock immediately before commit (CR-13) |
| Unused reservations stay counted | Sealing raises the counter to 2^30 and never lowers it. Unused units remain inside the total |
| No instance resumes encryption under the previous key merely because it holds an allowance | An allowance is permission to use units already counted, never permission to use the key. The key must also be the instance's active key and unsealed |

New: the `sealed` column with `CHECK (NOT sealed OR reserved = 2^30)`. The reservation statement adds `AND NOT sealed`.

### Copilot review of PR #2

Copilot reviewed commit `4e64b22` and left 13 findings (5 high, 8 medium). All were substantive and I accepted all of them. One was already overtaken by a later commit. The fixes are recorded as CR-11.

| # | Finding | Disposition |
|---|---|---|
| 1 | Reject duplicate key material across identifiers (a reused key under a new id gets a fresh counter) | Accepted. Ring loader, `keys:generate` and `keys:verify` reject duplicate material and non-increasing identifiers. `highestKeyId` is monotonic. New threat T35 |
| 2 | Reject zero and negative reservation blocks (a negative block could lower the counter) | Accepted and tested. The statement has `AND $2 > 0`, start-up requires a block of at least 1, tests cover 0, -1, -1024, -10240 |
| 3 | Seal keys even when their usage row is missing | Accepted and tested. Sealing is now an upsert, so a missing row is inserted sealed, and a later registration cannot reset it. A restore-past-registration scenario is tested |
| 4 | Require the newest ring and key-id history before sealing | Accepted. The restore uses the newest ring (highest `generation`) and `highestKeyId`, seals every id in it, and generates an id above `highestKeyId` |
| 5 | Stop and drain every encrypting job before restoration, and keep the restart on the lossless path | Accepted. Step 1 stops and drains `app`, `cleanup`, `reencrypt` and key jobs, and the lossless comparison is read only after that. The restart of every instance is still required when the new key is skipped |
| 6 | Allow budget-safe start-up with an exhausted key | Accepted. The start-up self-test decrypts a known-answer value that `keys:generate` encrypted once and counted. It never encrypts, so an instance starts with a sealed or exhausted key, serves reads and decryption, and answers encrypting requests with `503` |
| 7 | Add key-usage and readiness fields to the health contract | Already resolved by commit `019fb21`: key usage is admin-only (metrics and admin health state), the public `/healthz` deliberately exposes nothing about keys, and the OpenAPI description now says so. No contract change was needed |
| 8 | Allow authenticated replays after reservation refusal | Accepted. A failed preflight no longer rejects the request. It runs through authorisation, replay lookup and rule checks, and ends with `503` only where a fresh encryption is needed, before anything is written. A lost rotation response can therefore always be replayed |
| 9 | Reserve enough blocks for the whole operation | Accepted and tested. An operation gets `ceil(shortfall / block)` whole blocks in one statement. A block of 1 still works for a 22-unit operation |
| 10 | Atomically allocate units before the transaction | Accepted. An operation claims its units from the allowance in one synchronous step before `BEGIN` and returns the unused ones. A model test races 16 requests for the last unit |
| 11 | Refresh health from the authoritative row without new reservations | Accepted. Each instance re-reads the `key_usage` rows at start-up and every `KEY_USAGE_REFRESH_SECONDS` (new setting, default 30) |
| 12 | Stop the sampler when a reservation worker fails | Accepted and fixed in `verify-schema.py` (try/finally) |
| 13 | Always finish session A after an assertion failure | Accepted and fixed in `verify-schema.py` (the session is released in a finally block) |

Findings 1 to 6 and 8 to 11 change the specification. Findings 12 and 13 fix the test script so a regression cannot hang CI. The PostgreSQL-specific findings (2, 3, 12, 13) are covered by the real PostgreSQL tests in section 5.2.

### Second Copilot review of PR #2 (commit `b8302f6`): findings and dispositions (CR-12)

Copilot's second review raised 9 new findings and kept 2 earlier threads open (duplicate key material, exhausted-key start-up), both of which were already fixed in `b8302f6` and are now extended. All 9 new findings were substantive. I accepted all of them. Two of them show real defects in my own previous fix, which I should state plainly: the restore procedure, followed literally, would have sealed the key it had just generated, and the claim step could have granted more units than the allowance really held.

| # | Finding | Disposition |
|---|---|---|
| 1 | Post-seal exposure is not one request: several requests across instances can have passed the check before the seal | Accepted. Stated at this round as the sum of the claims of all operations that had passed the check, with a timed wait. **Superseded in the third round (CR-13)** by a commit-time check that makes the bound strict |
| 2 | Restore seals "every id in the newest ring", which includes the new key | **Real defect, fixed.** The procedure records the set S of identifiers **before** the new key is added, seals exactly S, and never the new key. A test shows the failure the wrong order would cause |
| 3 | `keys:generate` orders a counted self-test encryption before registration, but an unregistered key cannot reserve | Accepted. Order is now: check material, **register**, **reserve** at least one unit, **then** encrypt, write the ring entry. A new key starts at counter 1 or more, never 0, and the "counter 0" wording is corrected everywhere |
| 4 | Activating a new key during a rolling restart makes updated instances write ciphertext that old-ring instances cannot decrypt | **Real defect, fixed.** Rotation now has three phases: **stage** the key on every instance (new ring status `STAGED`: loaded, decrypts, never encrypts), **activate** it, then **seal and drain** the previous key. The rotation tool refuses to activate until every instance has the key staged |
| 5 | A re-encryption job can run out of claimed units when a live token rotation adds ciphertext between its count and its lock | Accepted. Data-dependent operations recount **under the game lock** before any write, and if they need more they roll back, enlarge the claim outside the transaction, and retry. No reservation is ever made inside the transaction |
| 6 | The allowance can change while a reservation is in progress, so the claim could exceed what exists | **Real defect, fixed.** The claim is checked and decremented in one synchronous step **after** every wait, the shortfall is recomputed from the current allowance, and the loop repeats. One reservation per key is in flight per process. A model test with real reservations checks that no claim exceeds the allowance |
| 7 | Retired key material can be added again under a new identifier above `highestKeyId` | Accepted. The ring keeps a permanent `fingerprintHistory` of every key ever registered, and `key_usage.fingerprint` is `UNIQUE` and never deleted, so the database refuses re-registration even after the old key is retired and removed. Tested: material of a sealed, retired key is refused under a new identifier |
| 8 | Sealing the old key makes health critical for ever after a normal rotation | Accepted. Health is evaluated by key role. A sealed, non-active key reports `sealed` and raises no alert. A sealed key that the ring lists as `ACTIVE` is `critical` |
| 9 | A test passes while violating the reservation and no-reuse invariants (allowance of 1 with `R` = 0) | **Real defect in the test, fixed.** The unit is now really reserved first, consumed claims are shown to stay spent, and only an unused claim is returned and re-claimed |
| carried | Reject duplicate key material across identifiers | Already fixed in `b8302f6`, extended by the fingerprint history (7) |
| carried | Allow budget-safe start-up with an exhausted key | Already fixed in `b8302f6` (start-up decrypts a known-answer vector and never encrypts). It now also states that `keys:generate` reserves a unit before encrypting it |

### Third Copilot review of PR #2 (commit `ae11a21`): findings and dispositions (CR-13)

Copilot's third review raised 10 new findings. All were substantive and accepted. The most important one showed that my "bound on exposure after the seal" was not enforced: a timed wait cannot stop a slow operation, and a request could pass the sealed check with no claim and claim later. I replaced the wait with a mechanism that makes the bound strict.

| # | Finding | Disposition |
|---|---|---|
| 1 | Registration `ON CONFLICT DO NOTHING` accepts different material for an existing identifier | Accepted and tested. Registration is idempotent only for the same fingerprint (`ON CONFLICT ... DO UPDATE ... WHERE fingerprint matches RETURNING`), a mismatch returns no row and stops `keys:generate` before reserving, and a new identifier is above both the ring's `highestKeyId` and the highest registered identifier |
| 2 | A request can pass the sealed check without a claim, claim later and encrypt after the seal | Accepted. The claim is taken **before** the pre-encryption check, which is the last step before `BEGIN`, and returned if the check fails |
| 3 | Restore loses the database fingerprint row of a key retired early | Accepted and tested. The restore seals **every identifier in the ring's `fingerprintHistory`** (every key ever registered), which also restores the fingerprint row, so the database backstop against reuse returns |
| 4 | The lossless proof checks only the active key | Accepted. The proof covers every key that can still encrypt, including `STAGED` keys. If any fails, the restore is not lossless |
| 5 | The 60-second wait is not an enforced deadline | **Accepted, and the mechanism is replaced.** Every transaction that writes ciphertext runs `SELECT sealed FROM key_usage WHERE key_id = $1 FOR SHARE` immediately before commit and rolls back if sealed. The seal `UPDATE` waits for those share locks, and later checks see the seal. **No ciphertext under a key can be committed after its seal.** The timed wait and its setting are removed. Tested on PostgreSQL: the seal waited for a transaction in its check, and a transaction checking afterwards read `sealed` |
| 6 | The consistency checker can crash on a missing hard-stop default | Fixed (guarded) |
| 7 | A refused reservation should not give up if another request returned units meanwhile | Accepted and tested (model with real reservations): one more synchronous allowance check after a refusal |
| 8 | `503` is not declared on `submitSecretCode` and `submitGuess` | Fixed in `openapi.yaml` (draft 5 still lints with 0 warnings) |
| 9 | The interleaving test can hang if `finish(A)` fails | Fixed: A is released before the executor shuts down, and B is bounded by `lock_timeout` |
| 10 | The start-up validation model required the block to divide 2^30 | Fixed: the block only has to divide the configured hard stop |
| carried | Allow budget-safe start-up with an exhausted key | Already fixed in `b8302f6` and unchanged |

New lock level L3 (`design.md` 8.2): the key row in share mode, taken last before commit. The L0 statements that wait for it hold no other lock, so no deadlock is possible.

### Fourth Copilot review of PR #2 (commit `6838bf1`): findings and dispositions (CR-14)

10 new findings, all accepted. Two older threads (duplicate key material, `503` on code and guess submission) were already fixed in earlier commits and were answered in their threads.

| # | Finding | Disposition |
|---|---|---|
| 1 | C24 still passes if the verifier hard-codes the SQL | Fixed. C24 now requires every SQL-producing assignment in `verify-schema.py` to extract from the specification |
| 2 | A failing test can leave session `a` holding a lock and hang the next test | Fixed with `finally` cleanup |
| 3 | The retry test never reaches the post-refusal recheck | Fixed. The unit is returned between the refused reservation and the final check, and the test fails if the recheck is removed |
| 4 | An interrupted `keys:generate` can lose the identifier and fingerprint before they are in the backed-up history | Accepted. The history entry is written (`PENDING`) and the ring backed up **before** registration. An interrupted entry becomes `ABANDONED` and is never reused, and a restore seals it |
| 5 | A lossy restore seals a pending `STAGED` key but leaves it staged | Accepted. Such a key is abandoned and a fresh key is generated. Activation refuses a sealed key |
| 6 | The lossless proof can pass while a historical key's row is missing or its seal undone | Accepted. The proof also requires every history identifier's row to be present with the same fingerprint and sealed flag |
| 7 | `design.md` 8.1 still ordered the check before the claim | **Real inconsistency, fixed.** 8.1 now says claim first, check last, as 9.1 does |
| 8 | The review package carried incomplete SQL copies | Fixed. The package refers to `database-schema.md` 6.2 instead of copying statements |
| 9 | Loaded material is not bound to the fingerprint registered for its identifier | Accepted and tested. The loader checks each entry against the history, and the pre-encryption check and the reservation statement both require `key_usage.fingerprint` to match the loaded material |
| 10 | Retirement allowed the usage row to be removed | **Real inconsistency, fixed.** The row is kept for ever. Only the key material is destroyed |

### Fifth Copilot review of PR #2 (commit `f7b08f7`): findings and dispositions (CR-15)

7 new findings, all accepted. The carried threads (duplicate key material, `503` declarations, budget-safe start-up) were fixed earlier, answered in place and marked resolved.

| # | Finding | Disposition |
|---|---|---|
| 1 | `keys:generate` printed a ring entry containing the key material | Accepted. Key material is written directly to the protected ring and never printed. Output shows identifier, status and a fingerprint prefix |
| 2 | The verifier did not pause a request between its check and the seal | Accepted. New PostgreSQL test: a request passes its check, the key is sealed, and its commit-time check rolls it back |
| 3 | The verifier's request model checked before claiming | **Real inconsistency in the test, fixed.** The model now claims, checks last, returns the claim on failure, and consumes only that claim |
| 4 | A stalled session could hang the suite | Fixed: stalled sessions are killed and reaped before continuing |
| 5 | Concurrent generators could publish from stale ring snapshots | Accepted. Every ring change takes a single-writer advisory lock for its whole run and writes the ring with a version check on `generation`. Tested on PostgreSQL |
| 6 | No execution context could write the ring and its backup | Accepted. New `keymgmt` job (`deployment.md` 2.1) with its own database role, a writable ring source, backup-store access and narrow Deno permissions. Application permissions are unchanged |
| 7 | The security assessment's recovery shortcut checked only active and staged keys | **Real inconsistency, fixed.** It now includes the history checks, as in R10.13 and `deployment.md` 6.1 |

### Sixth Copilot review of PR #2 (commit `eacffa4`): findings and dispositions (CR-16)

2 new findings, both accepted. Copilot also re-listed the original comments on duplicate key material and on the `503` declarations. Those threads were fixed and resolved earlier, and the comments only moved to the new commit.

| # | Finding | Disposition |
|---|---|---|
| 1 | The `keymgmt` role lacked `SELECT` on `key_usage`, and `keys:verify` needs game ciphertext the ring-writing job should not see | Accepted and tested. `keymgmt` gets `SELECT`, `INSERT`, `UPDATE` on `key_usage` and `SELECT` on the new reports table. `keys:verify` moves to a separate read-only `keyverify` job |
| 2 | The activation tool could not read per-instance ring generations, which are behind the admin listener | Accepted and tested. New table `instance_ring_reports`: every instance reports its loaded ring at start-up and on each refresh. `keys:activate <id> --expect N` refuses unless exactly N fresh reports all include the staged key. No admin access is needed |

### Seventh Copilot review of PR #2 (commit `ae3cdf6`): findings and dispositions (CR-17)

6 new findings, all accepted.

| # | Finding | Disposition |
|---|---|---|
| 1 | N recent reports are not an authoritative roster: a stopped process's report can stand in for a live reader that stopped reporting | **Real gap, fixed.** The roster is now the set of processes holding a presence lock on a live database connection (`pg_locks`). A stopped process drops its lock immediately. A live reader without a report blocks activation, and a process must hold its lock and have reported before it serves requests. Tested with real sessions |
| 2 | Task 9.2a gave `keyverify` write and backup rights | Fixed. Only `keymgmt` writes, backs up and publishes. `keyverify` is read-only |
| 3 | The report and cleanup statements need `SELECT` and `DELETE` | Fixed and tested under a restricted role |
| 4 | `keyverify` cannot rebuild the authenticated data without `players.game_id` | Fixed. `SELECT (id, game_id)` on `players` only, with nicknames refused. Tested |
| 5 | No activation path for bootstrap and offline restore. `bool_and` gave `NULL` on an empty table | Fixed. `keys:activate --offline` works only when no presence lock is held. Online activation needs at least one live reader and returns `false`, never `NULL`. Tested |
| 6 | Roster participants did not match their permissions | Fixed. `app`, `cleanup` and a running `reencrypt` take presence locks and report. `keyverify` holds a blocking lock in a separate class. `keymgmt` is outside the roster. One-shot jobs must not run during phases 1 and 2 |

### Eighth Copilot review of PR #2 (commit `6291387`): concerns and dispositions (CR-18)

No inline findings. Copilot marked the PR "Needs a closer look" and named three areas for human assessment. The owner asked for them to be addressed.

| # | Concern | Assessment and disposition |
|---|---|---|
| 1 | Reader-admission races could let a reader serve without the newly activated key | **Real.** A process that loaded the ring before staging, but registered after the activation check, would not have the key and would not be counted. Fixed with an admission gate: activation first commits the staged key into `ring_state.required_key_ids`, then reads the roster, and every reader checks that set right after taking its presence lock and exits if its ring lacks a key. A reader admitted before the commit is in the roster and must report the key. Tested on PostgreSQL |
| 2 | The verifier handshake is unbounded | **Real, as an availability risk.** A hung `keyverify` blocked activation for ever, and `keymgmt` could wait without limit. Fixed: `keyverify` takes the ring lock with a shared try-lock and exits if a ring change is running, and it has a hard deadline (`KEYVERIFY_MAX_SECONDS`). `keymgmt` waits at most `KEYMGMT_LOCK_WAIT_SECONDS` and then names the holders. Tested on PostgreSQL |
| 3 | Encryption-unit accounting has gaps during retries | **Real gap in the wording.** The transaction helper's single retry and the re-encryption retry did not say they needed a new claim, so a retry could have encrypted a second time against a unit already spent. Fixed: every retry is a fresh attempt with a new claim and a new pre-encryption check, spent units are never returned, and a unit is consumed before the cipher is called. Tested with a real rollback |

### Ninth Copilot review of PR #2 (commit `62f3434`): findings and dispositions (CR-19)

3 new findings, all accepted. All concern the admission gate added in round 8.

| # | Finding | Disposition |
|---|---|---|
| 1 | The DDL did not create the `ring_state` row, and the test masked this by inserting its own | **Real defect, fixed.** The DDL now inserts the singleton row. The DDL test checks it exists, and the admission test no longer creates it. Every gate update uses `RETURNING`, and zero rows is an error |
| 2 | The roles had no rights on `ring_state` | Fixed and tested under restricted roles. `keymgmt` gets `SELECT` and `UPDATE`. The application and `keyverify` roles get `SELECT` only. `keymgmt` also gets `SELECT` on the `key_id` columns it needs for the reconciliation pre-check |
| 3 | A restored gate can still require a retired key or an abandoned staged key, which would block the verifier and every restarted reader | **Real gap, fixed.** New `keys:reconcile-gate`. It runs offline under the ring lock, confirms that every key referenced by restored ciphertext is in the newest ring, and sets the gate to that ring's keys. The restore procedure runs it before verification and again after the new key is activated. Tested |

### Tenth Copilot review of PR #2 (commit `0a1ce30`): findings and dispositions (CR-20)

2 new findings, both accepted. Both concern the restore procedure added in round 9.

| # | Finding | Disposition |
|---|---|---|
| 1 | The grant named a `key_id` column on `token_rotations`, which has `token_key_id` | **Real defect, fixed.** The grant now names the actual columns, as column grants. A PostgreSQL test checks that the grants are valid, the pre-check runs, and ciphertext is refused |
| 2 | The restore restarted the readers before the second reconciliation, which refuses while readers are live | **Real defect, fixed.** Abandonment, reconciliation and verification now all run while every service is stopped. The services start once, in step 9, as fresh processes. The security assessment and R10.13 say the same |

### Eleventh Copilot review of PR #2 (commit `41e7644`) and close of the review loop (CR-21)

No inline findings. Copilot marked the PR "Needs a closer look" and named two concerns. By owner decision (option B), this is the last fix round on PR #2, followed by one regression-check review. Further procedural findings go to Phase 9.

| # | Concern | Disposition |
|---|---|---|
| 1 | Recovery can fail before migrations run | **Real defect, fixed.** Migrations ran at step 7 of the restore, after steps that use `ring_state`, `instance_ring_reports` and the newer `key_usage` columns. They now run at step 3, straight after the database is restored. The later steps are renumbered and their cross-references updated |
| 2 | A key could be activated while a reader lacks it | **Not reproduced from the specification, deferred.** Copilot gave no path. Recorded as task 9.6a, to be settled against the real tooling, starting with the window between a reader taking its presence lock and completing its admission check |

## 3C. Task 1.8 whole-specification review (Copilot, PRs #12 to #16, snapshot 732d4fb)
Copilot reviewed the whole specification in five group PRs (#12 to #16) against snapshot `732d4fb`: 52 inline findings. The triage is in the task record (`triage.md`). All 52 are listed below. The changes are CR-25 in `requirements.md`. Gates 1 to 5 are reopened for the changed parts only, and those parts are awaiting owner confirmation (`tasks.md` 1.1 to 1.5). Gate 6 is untouched (`LICENSE`, `NOTICE` and `CONTRIBUTING.md` unchanged). Task 1.8 awaits the owner marking it complete.
| ID | Where | Disposition | Where fixed |
|---|---|---|---|
| A1 | `copilot-instructions.md:21` | Fixed in CR-25 | `.github/copilot-instructions.md`: decrypted-value ban limited to logs, diagnostics, errors and non-contract responses |
| A2 | `copilot-instructions.md:25` | Fixed in CR-25 | `.github/copilot-instructions.md`: lossless-restore exception restored |
| A3 | `requirements.md:306` | Fixed in CR-25 | `requirements.md` R8.8: join exceptions `GAME_FULL`, `INVALID_INVITATION` |
| A4 | `requirements.md:334` | Fixed in CR-25 | `requirements.md` R10.7: API-path scope, controlled maintenance decryption |
| A5 | `requirements.md:353` | Fixed in CR-25 | `requirements.md` R10.14: online rotation separate from the offline restore |
| A6 | `requirements.md:441` | Fixed by owner decision RD-16 | `requirements.md` R20.3: token buckets in the application layer only |
| A7 | `review package:316` | Fixed in CR-25 | This package: section 5.3 labelled historical, current run in 5.3a |
| A8 | `traceability.md:32` | Fixed in CR-25 | `traceability.md` R10: `getHealth` (readiness), `getMetrics` (key usage state) |
| A9 | `README.md:163` | Fixed in CR-25 | `README.md`: roadmap stages versus `tasks.md` phases |
| A10 | `README.md:219` | Fixed in CR-25 | `README.md`: simulator example has `--test-deployment` |
| B1 | `ci.yml:51` | Fixed in CR-25 | `ci.yml` hygiene regex covers `.env.*`, exempts `.env.example` |
| B2 | `ci.yml:119` | Deferred to task 2.5 | `tasks.md` 2.5 |
| B3 | `ci.yml:120` | Deferred to task 2.5 | `tasks.md` 2.5 |
| B4 | `deployment.md:29` | Fixed by owner decision RD-17 | `deployment.md` 1, `design.md` 13 (admin listener on the internal network interface) |
| B5 | `deployment.md:146` | Fixed in CR-25 | `deployment.md` 4.3: `modules/standard` import |
| B6 | `deployment.md:236` | Fixed in CR-25 | `deployment.md` 6.4: metadata only, no ring entry printed |
| B7 | `ci.yml:78` | Deferred to task 2.6 | `tasks.md` 2.6 |
| B8 | `deployment.md:118` | Fixed by owner decision RD-18 | `deployment.md` 4.2, `state-machine.md` 3.1, `design.md` (validated replays exempt from `pl:rotate`) |
| B9 | `deployment.md:222` | Fixed by owner decision RD-19 | `deployment.md` 6.2, `database-schema.md`, `security-assessment.md` (offline missing-key recovery) |
| B10 | `deployment.md:270` | Fixed in CR-25 | `deployment.md` 7: alerts from reserved totals |
| B11 | `design.md:125` | Fixed in CR-25 | `design.md` 5.1, 8.1, 11 and `deployment.md`: one `ip:authfail` sequence |
| B12 | `deployment.md:87` | Fixed in CR-25 | `deployment.md` 4.1: route templates only in proxy logs |
| B13 | `design.md:296` | Fixed in CR-25 | `design.md` 10: HKDF label `duocode/mac/v1` |
| B14 | `security-assessment.md:32` | Fixed in CR-25 | `security-assessment.md`: invitation errors as in R8.8 |
| C1 | `database-schema.md:113` | Fixed in CR-25 | `database-schema.md`: composite foreign key on `idempotency_keys`; schema test |
| C2 | `database-schema.md:127` | Fixed in CR-25 | `database-schema.md`: composite foreign keys on `token_rotations`; schema test |
| C3 | `database-schema.md:401` | Fixed in CR-25 | `database-schema.md`: previous presence report deleted on lock acquisition |
| C4 | `database-schema.md:468` | Fixed in CR-25 | `database-schema.md`, `deployment.md` 2.1: reconciliation covers `idempotency_keys.fingerprint_key_id`; schema test |
| C5 | `database-schema.md:562` | Fixed in CR-25 | `database-schema.md`: `CREATE INDEX CONCURRENTLY` not supported by the migration runner |
| C6 | `database-schema.md:516` | Fixed in CR-25 | `database-schema.md` 7: batch cleanup locks games `FOR UPDATE SKIP LOCKED`, then rechecks `replay_until`; schema test |
| C7 | `state-machine.md:58` | Fixed by owner decision RD-20 | `state-machine.md` 3, `design.md`, `security-assessment.md` T28 (revoked tokens rejected before player buckets) |
| C8 | `state-machine.md:75` | Fixed in CR-25 | `state-machine.md`: consumed invitation maps to `GAME_FULL` |
| C9 | `openapi.yaml:184` | Fixed in CR-25 | `openapi.yaml`: `400` on four operations; check C33 |
| C10 | `openapi.yaml:613` | Fixed in CR-25 | `openapi.yaml`: `NicknameInput` without length or pattern |
| C11 | `state-machine.md:93` | Fixed in CR-25 | `state-machine.md`: ordering relative to the snapshot at the first data statement |
| C12 | `state-machine.md:182` | Fixed in CR-25 | `state-machine.md`: API replay refusal versus later cleanup |
| D1 | `check-consistency.py:175` | Done (`f7658ed`) | Ticked 1.9 accepted by C15 and C21 |
| D2 | `check-consistency.py:193` | Fixed in CR-25 | `check-consistency.py` C16 inspects the Code schema |
| D3 | `check-consistency.py:228` | Fixed in CR-25 | `check-consistency.py` C21 checks the `git` exit status |
| D4 | `simulator-design.md:59` | Fixed in CR-25 | `simulator-design.md`: pair of responses checked |
| D5 | `simulator-design.md:65` | Fixed in CR-25 | `simulator-design.md`: `401 INVALID_CREDENTIALS` for the consumed capability |
| D6 | `simulator-design.md:116` | Fixed in CR-25 | `simulator-design.md` 9, `ci.yml`: `--lost-rotation-rate 0.5`, `--test-deployment` |
| D7 | `test-strategy.md:98` | Fixed in CR-25 | `test-strategy.md`: no `pl:*` rows, `ip:authfail` charged |
| D8 | `test-strategy.md:119` | Fixed in CR-25 | `test-strategy.md`: lost-token check scoped to existing seats |
| D9 | `test-strategy.md:193` | Fixed in CR-25 | `test-strategy.md`: key-id columns readable by reconciliation |
| D10 | `test-strategy.md:204` | Fixed in CR-25 | `test-strategy.md`, `simulator-design.md`: secrecy scan by field and ownership |
| D11 | `test-strategy.md:329` | Fixed in CR-25 | `test-strategy.md`: history set frozen before generation |
| D12 | `test-strategy.md:329` | Fixed in CR-25 | `test-strategy.md`: per-identifier proof |
| D13 | `test-strategy.md:362` | Fixed in CR-25 | `test-strategy.md` 17: `audit` required; check C35 |
| E1 | `verify-schema.py:23` | Fixed in CR-25 | `verify-schema.py`: exits under `python -O` |
| E2 | `verify-schema.py:60` | Fixed in CR-25 | `verify-schema.py`: `stop()` checked before the data directory is touched |
| E3 | `verify-schema.py:416` | Fixed in CR-25 | `verify-schema.py`: psql helper checks the exit status |

**Owner decisions** (David Johnson (G4DPZ), 2026-11-22, statement "accept the recommendations"): RD-16 (A6) R20.3 applies to the application layer only; RD-17 (B4) the admin listener binds to the internal network interface only; RD-18 (B8) validated rotation replays are exempt from `pl:rotate`; RD-19 (B9) offline missing-key recovery; RD-20 (C7) known-revoked tokens are rejected before player buckets are charged, except rotation requests.
**Task 1.7** was confirmed on 2026-11-22 by David Johnson (G4DPZ), statement "merge 9 and confirm 1.7".
**Open questions for the owners** (not decided here): (1) the configuration key form for the admin listener address (RD-17); (2) the option form of the missing-key recovery step, to be defined in task 9.2a (RD-19); (3) whether the rotation-request reading of RD-20 is as intended (a request carrying a revoked token skips the early rejection and the `pl:rotate` charge, and a non-replay failure is charged to `ip:authfail` only); (4) the nonzero `--lost-rotation-rate` for CI (0.5 was chosen); (5) the separate owner-approved procedure for online index builds named under C5 is not defined.
## 4. Files (revision 3.1 branch, for history)

Added: `.kiro/specs/duocode/revision-3.1-review-package.md` (replaces the revision 3 package), `.kiro/specs/duocode/check-consistency.py`, `.kiro/specs/duocode/verify-schema.py`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE`.
Removed: `.kiro/specs/duocode/revision-3-review-package.md` (superseded).
Modified: `.github/copilot-instructions.md`, `.kiro/specs/duocode/` (`database-schema.md`, `deployment.md`, `design.md`, `requirements.md`, `security-assessment.md`, `simulator-design.md`, `state-machine.md`, `tasks.md`, `test-strategy.md`, `traceability.md`), `README.md`, `openapi/openapi.yaml`.
The two `.py` files are specification tooling (consistency and schema verification). They are not application code or migrations. The branch contains the exact file list in the final report.

## 5. Verification results (actual output)

### 5.1 OpenAPI

Redocly lint of `openapi/openapi.yaml`: **valid, 0 errors, 0 warnings.** The OpenAPI document is not changed by CR-9.

### 5.2 Database schema, constraint and reservation tests

`verify-schema.py` extracts the DDL, the reservation, registration, sealing and pre-encryption-check statements **from `database-schema.md`**, so the tested SQL is the specified SQL. It applies them to a throwaway cluster and runs 69 tests.

| Server | Result |
|---|---|
| PostgreSQL 15.8 (Homebrew), with `pg_dump` and `pg_restore` | **69 of 69 passed**, two runs |
| PostgreSQL 16.16 embedded build (no `pg_dump` of its version available) | **68 of 68 passed, 1 skipped** (the logical restore test), two runs |
| **PostgreSQL 16.16 official `postgres:16` image (Debian, Docker Desktop)**, image digest `sha256:3950ad7c3148ca2175ef1b6c36c9efbf78957ae8fbe8b3a5d7c35af50500382f`, with its own `pg_dump` and `pg_restore` | **69 of 69 passed**, one run |

What the tests cover (all use the real PostgreSQL statements and real concurrent connections, not a mocked counter):

| Test | Result |
|---|---|
| Reservation that takes `R` exactly to 2^30 | Granted, `R` = 2^30, the next one refused |
| Reservation that would go beyond 2^30 | Refused whole, `R` unchanged. A direct write above 2^30 is rejected by the `CHECK` |
| Several instances reserving concurrently | 16 and 32 connections near the limit: exactly the available blocks granted, `R` ends at 2^30, a sampler never saw more (the sampler is stopped in a `finally`). Eight instances × 100 reservations: no lost increment |
| Outstanding allowances while another instance approaches the limit | A holds a block, B takes the last, C is refused, nobody uses more units than reserved |
| Failed and rolled-back transactions still consume units | Real rolled-back and error-aborted transactions: the counter never decreased and always covered the invocations |
| Crash and restart with an unused allowance | The counter did not decrease, lost units stayed counted |
| Statement strictness | A second reservation started while the first is uncommitted waited, then was refused. Session A is always released |
| Negative control | The replaced shard design ended at 2^30 plus one block under the same kind of interleaving |
| Zero and negative reservations | Matched no row, changed nothing |
| Whole blocks sized to the operation | A block of 1 still obtains 22 units in one statement, and a request that does not fit is refused whole |
| Sealing a missing row | Inserts a sealed row. A later registration does not reset it |
| Pre-encryption check and sealed flag | Unsealed usable, sealed and unregistered not usable, `sealed` without the counter at 2^30 rejected |
| Rotation completed after 2^28 | Reservations still granted past 2^28. After sealing, the stale allowance holder was refused, unused units stayed counted, and a fresh instance worked under the new key |
| Atomic claims (corrected) | One really reserved unit, 16 racing requests: exactly one claimed and consumed it, a consumed unit is never returned, an unused claim is returned and re-claimed |
| **Claim recheck after a reservation in progress (new, CR-12)** | 12 threads with real reservations: no claim exceeded the real allowance, the allowance never went negative, every unit was either claimed or still in the allowance |
| **Fingerprint uniqueness (new, CR-12)** | Material of a sealed (retired) key was refused under a new identifier. New material accepted |
| **`keys:generate` order (new, CR-12)** | An unregistered key cannot reserve. After register then reserve, the new key's counter is at least 1 |
| **Restore seals exactly the old set (new, CR-12)** | The new key was usable and the old keys were not. Sealing the new key by mistake was shown to make it unusable |
| **Health by key role (new, CR-12 rule)** | A sealed non-active key is `sealed` with no alert, a sealed active key is `critical`, only the active key can warn |
| Restore (physical) and restore past a key's registration | Restored counter behind. Old keys sealed, new key registered, stale ring refused. A key absent from the restored database was sealed by identifier |
| Logical restore with `pg_dump` / `pg_restore` | `rate_limits` data excluded from the dump and absent after restore, restored counter behind, sealing stopped the old key |
| **Commit-time check (new, CR-13)** | The seal waited for a transaction holding the key row `FOR SHARE`, that transaction committed first, and a transaction checking after the seal read `sealed`. No ciphertext row was committed after the seal |
| **Registration idempotent only for the same material (new, CR-13)** | Same material: row returned. Different material on the same id: no row, nothing changed. Same material on a new id: refused |
| **Restore seals the whole fingerprint history (new, CR-13)** | A key registered after the backup and retired early was sealed again from the history, and its material was then refused under a new id |
| **Lossless proof including staged keys (new, CR-13 rule)** | A missing or lagging staged key makes the restore not lossless |
| **Retry after a refused reservation (CR-13, corrected CR-14)** | A unit returned between the refusal and the final check was claimed by the same call, and the same scenario fails without the recheck |
| **Material bound to the registry (new, CR-14)** | Reservation and pre-encryption check refused a key whose loaded material differs from the registered fingerprint |
| **Lossless proof covers history keys (new, CR-14 rule)** | A missing history row or an undone seal makes the restore not lossless |
| **Retired keys keep their row (new, CR-14)** | The row stays after retirement and the material is refused under a new identifier |
| **In-flight request between check and seal (new, CR-15)** | A request that passed its check before the seal had its transaction rolled back by the commit-time check after the seal. Its unit stayed counted |
| **Ring single-writer lock (new, CR-15)** | A second operation could not take the ring advisory lock while the first held it |
| **Staged-activation roster (CR-16, reworked CR-17)** | With real sessions holding presence locks: a stopped process with a fresh report was not counted, a live reader without a report or without the staged key blocked activation, a running `keyverify` blocked it, and an empty roster or an expected count of 0 gave `false` |
| **Offline activation (new, CR-17)** | Allowed only with no presence lock held, refused while any reader was live |
| **Report privileges (new, CR-17)** | The restricted application role could upsert its report and prune old reports |
| **Admission gate (new, CR-18)** | After activation committed the staged key, a reader with the old ring was refused. A reader admitted just before was counted and blocked activation until it reported the key |
| **Bounded locks (new, CR-18)** | `keyverify`'s shared try-lock failed during a ring change, `keymgmt`'s exclusive try-lock failed during a verification, and both succeeded once the other was gone |
| **Retry is a fresh attempt (new, CR-18 model)** | After a real rollback, the spent unit could not be reused. The retry claimed again, and invocations stayed within the reserved total |
| **Gate singleton and privileges (new, CR-19)** | The schema creates the `ring_state` row. `keymgmt` could update it. The application and `keyverify` roles could run the admission check and were refused updates |
| **Reconciliation privileges (new, CR-20)** | The column grants on `secret_codes(key_id)`, `guesses(key_id)` and `token_rotations(token_key_id)` were valid, the pre-check ran under the restricted role, and every ciphertext column was refused |
| **Gate reconciliation after restore (new, CR-19)** | A restored gate requiring a retired key and an abandoned staged key refused every reader. It was reconciled to the newest ring's keys, after which readers were admitted. Reconciliation was refused while a reader was live, and the referenced-key pre-check caught ciphertext under a key outside the ring |
| **Role separation (CR-16, extended CR-17)** | `keymgmt` could change `key_usage` and was refused `secret_codes` and `guesses`. `keyverify` could read them and join them to `players(id, game_id)`, and was refused nicknames and any change |

The rest of the 69 tests are the constraint tests (seats, nicknames and bidirectional controls, guess chain, credential binding, one rematch ever, idempotency, rotation record, rate limits, cleanup, invariant check, start-up validation rule).

**Limits, stated plainly.** No application exists. The instance in these tests is a small model of the allowance and claim rules. Its reservations, seals and checks go to real PostgreSQL. The tests prove the SQL, the constraints and the policy. They do not prove that a future vault follows the policy, which is why the (APP) tests in `test-strategy.md` are required in Phase 4. The staged rolling rotation (zero decrypt failures), the re-encryption recount, the claim-before-check order in the vault and the per-role health reporting are specified as (APP) tests and have not been run.

### 5.3 Specification consistency checks

Historical, from an earlier snapshot (revision 3.1 at the time of Gate 5 preparation): the transcript below is the 24-check run of that snapshot and is kept for history. The current run is in 5.3a.

`check-consistency.py`, final run on the final file set (24 checks). C24 was checked by mutation: replacing the extracted reservation statement in `verify-schema.py` with a hard-coded one makes C24 fail.

```
PASS C01 every requirement R1..R21 defined and in traceability matrix
PASS C02 every R<n>.<m> criterion reference exists
PASS C03 every TS group and TS-CONC id referenced is defined (18 groups, 29 concurrency scenarios)
PASS C04 every decision ID is defined in the register and none is unknown
PASS C05 no stale revision 2/3 identifiers or the email signature in the specification, README or licensing files
PASS C06 every "<file>.md section N" reference resolves to a heading
PASS C07 design.md API table matches OpenAPI paths and methods (13 operations)
PASS C08 every error code named anywhere exists in the OpenAPI ErrorCode enum (21 codes)
PASS C09 game states agree between OpenAPI, database enum and state machine
PASS C10 every `table.column` reference names a real column (14 tables in the DDL)
PASS C11 every configuration key named in the specification is in design.md section 13 (25 keys)
PASS C12 rate-limit scopes agree between design.md and deployment.md
PASS C13 licensing artefacts present, LICENSE is the FSF AGPL-3.0 text (sha256 0d96a4ff68ad6d4b...), NOTICE names AGPL-3.0-only
PASS C14 GitHub workflow files parse as YAML
PASS C15 no Phase 1 gate or task is marked approved in tasks.md
PASS C16 OpenAPI constrains codes to 4 symbols from 1..6
PASS C17 nickname forbidden character classes agree between OpenAPI and database CHECK (NUL aside)
PASS C18 OpenAPI rotation key pattern accepts v4 UUIDs and rejects v1 and wrong-variant values
PASS C19 every decision in the register has a row in the traceability decision map (78 decisions)
PASS C20 no decision recorded as approved in the register is still described as pending elsewhere
PASS C21 no application code, database migration or implementation directory exists
PASS C23 key usage design is consistent: one authoritative row per key, CHECK at 2^30, thresholds 2^27 / 2^28 / 2^30, strict statement, terms defined, sharding only mentioned as replaced
PASS C24 the schema verification tool takes the reservation, registration and sealing statements from database-schema.md
PASS C22 OpenAPI lint (Redocly): valid with 0 errors and 0 warnings
24 of 24 checks passed (0 skipped)
```

The checks are textual. They prove that identifiers, references and definitions agree. They cannot prove that the documents are right.

### 5.3a Current run (task 1.8 fixes, branch `spec/1.8-fixes`)
Run on the branch after the CR-25 changes. `check-consistency.py` (36 checks; C31 to C36 are new, C16 and C21 were hardened):
```
PASS C01 every requirement R1..R21 defined and in traceability matrix
PASS C02 every R<n>.<m> criterion reference exists
PASS C03 every TS group and TS-CONC id referenced is defined (18 groups, 29 concurrency scenarios)
PASS C04 every decision ID is defined in the register and none is unknown
PASS C05 no stale revision 2/3 identifiers or the email signature in the specification, README or licensing files
PASS C06 every "<file>.md section N" reference resolves to a heading
PASS C07 design.md API table matches OpenAPI paths and methods (13 operations)
PASS C08 every error code named anywhere exists in the OpenAPI ErrorCode enum (21 codes)
PASS C09 game states agree between OpenAPI, database enum and state machine
PASS C10 every `table.column` reference names a real column (14 tables in the DDL)
PASS C11 every configuration key named in the specification is in design.md section 13 (25 keys)
PASS C12 rate-limit scopes agree between design.md and deployment.md
PASS C13 licensing artefacts present, LICENSE is the FSF AGPL-3.0 text (sha256 0d96a4ff68ad6d4b...), NOTICE names AGPL-3.0-only, and after Gate 6 no draft banner or placeholder remains and NOTICE names the LI-1 holders
PASS C14 GitHub workflow files parse as YAML
PASS C15 only Phase 1 gates are marked done, each with a recorded owner sign-off (signed: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6)
PASS C16 OpenAPI constrains codes to 4 symbols from 1..6
PASS C17 nickname forbidden character classes agree between OpenAPI and database CHECK (NUL aside)
PASS C18 OpenAPI rotation key pattern accepts v4 UUIDs and rejects v1 and wrong-variant values
PASS C19 every decision in the register has a row in the traceability decision map (91 decisions)
PASS C20 no decision recorded as approved in the register is still described as pending elsewhere
PASS C21 no application code, database migration or implementation directory exists (only specification, licensing, CI skeleton and the two specification tool scripts)
PASS C23 key usage design is consistent: one authoritative row per key, CHECK at 2^30, thresholds 2^27 / 2^28 / 2^30, strict statement, terms defined, sharding only mentioned as replaced
PASS C24 the schema verification tool takes the reservation, registration and sealing statements from database-schema.md
PASS C25 every OpenAPI operation declares 500 and 503, and admin operations declare 429
PASS C26 state-machine 1.3 orders claim and pre-encryption check before BEGIN and the commit-time check before COMMIT
PASS C27 security assessment matches the approved schema and deployment (reservation, restore order, rotation, re-encryption), and every threat maps to test groups
PASS C28 every key command used in the specification is in the deployment.md 2.1 list, the design layout and task 9.2a (7 commands)
PASS C29 every heading quoted by name in requirements.md exists
PASS C30 the README layout lists exactly the approved design.md layout as full paths (34 paths) and carries no superseded approval statements
PASS C31 the join error exceptions (409 GAME_FULL, 404 INVALID_INVITATION, no blanket 401) agree in requirements, security assessment, state machine, copilot instructions and OpenAPI
PASS C32 the HKDF labels (lines that mention HKDF) are duocode/enc/v1 and duocode/mac/v1 only, and the guess fingerprint uses duocode/mac/v1 in design.md and security-assessment.md
PASS C33 every OpenAPI operation with a gameId path parameter declares 400
PASS C34 the CI repository hygiene step flags .env, .env.* and secret files and exempts only .env.example
PASS C35 the required merge checks in test-strategy.md include audit and ci.yml defines the audit job
PASS C36 validated pl:rotate replays are described as exempt wherever they are mentioned, and R20.3 limits token buckets to the application layer
PASS C22 OpenAPI lint (Redocly): valid with 0 errors and 0 warnings

36 of 36 checks passed (0 skipped)
```
Schema verification in Docker `postgres:16`: `71 of 71 tests passed on PostgreSQL 16.16 (Debian 16.16-1.pgdg13+1)` (71 tests; the two new ones cover the C1 and C2 constraints). Redocly lint of `openapi/openapi.yaml`: valid, 0 errors, 0 warnings. `actionlint` on `.github/workflows/ci.yml`: exit 0. The checks are textual and prove agreement of identifiers, references and definitions only.
### 5.4 Not verified, and why

| Item | Reason | How to complete it |
|---|---|---|
| (APP) counter tests: instrumented vault, `kill -9` of a running instance, forced rollback after a real encryption, real instances, replay after refusal, restart at the hard stop, ring validation, refresh, staged rolling rotation, re-encryption recount, exposure after the seal, per-role health | No application exists | TS-ENC and TS-CONC-20 to TS-CONC-28 in Phase 4 |
| Restore with a real key ring, `keys:seal`, `keys:generate` and `keys:verify` as tools, and the full restore and rotation drills | The tools and the ring do not exist. The SQL behaviour of sealing, restoring and registering was tested | TS-OPS, tasks 9.5 and 9.6 |
| Web Crypto details (HKDF, AES-GCM with the AAD layout), RFC 8785 library, Caddy build and reproducibility | No implementation or build | Tasks 4.5, 4.7, 9.3 |

The logical `pg_dump` restore test is no longer outstanding: it runs on PostgreSQL 15 and on the `postgres:16` image. It is skipped only on the embedded 16.16 server, which ships no `pg_dump`.

## 6. Licensing artefacts for gate 6

| File | State |
|---|---|
| `LICENSE` | Official FSF GNU AGPL v3 text, 34,523 bytes, SHA-256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`. Unmodified |
| `NOTICE` | Approved at Gate 6. Copyright holders David Johnson and Mike Hartley (LI-1) |
| `CONTRIBUTING.md` | Approved at Gate 6. No separate contributor licence agreement (LI-2). Legal review outstanding (LI-3). Security contact by post (LI-4). External contributions closed until the agreement-recording mechanism exists. Not legal advice |

Inputs given by David Johnson (G4DPZ) on 2026-11-22:

| ID | Input | Where it appears | Answer |
|---|---|---|---|
| LI-1 | Exact copyright holder names, and any affiliation to show | `NOTICE` | David Johnson and Mike Hartley |
| LI-2 | Whether a contributor licence agreement is required before outside contributions | `CONTRIBUTING.md` section 2 | No |
| LI-3 | Legal review of the contribution terms and the dual-licensing position | `CONTRIBUTING.md` section 2 | Outstanding |
| LI-4 | Security contact address | `CONTRIBUTING.md` section 4 | 96 Summerfields Avenue, Halesowen, B62 9NR |

## 7. Outstanding issues

1. No technical decision is pending. RD-14 is approved.
2. Gates 1 (requirements), 2 (architecture), 3 (OpenAPI), 4 (schema and state machine) and 5 (security assessment) are signed off as of 2026-11-22, and Gate 6 (licensing) is signed off with LI-3 outstanding. The task 1.8 fixes (CR-25, section 3C) reopened parts of Gates 1 to 5, which are awaiting owner confirmation (`tasks.md` 1.1 to 1.5). Task 1.7 is confirmed. Task 1.8 awaits the owner marking it complete. Task 1.9 awaits your explicit sign-off. Gate 2 was reopened for the CR-24 command-list wording in `deployment.md` 2.1 and 6.3 and `design.md` section 3, and re-confirmed on 2026-11-22. Gate 2's reopened sentence in `design.md` section 16 was re-confirmed the same day (see `tasks.md` 1.2). Operational inputs OI-1 (Caddy build owner) and OI-2 (backup provider) are open.
3. LI-3, legal review of the contribution terms and the dual-licensing position (section 6). With no separate contributor licence agreement (LI-2), commercial relicensing of outside contributions rests on `CONTRIBUTING.md` section 2 point 2.
4. The (APP) tests and the restore and rotation drills with real tools (section 5.4).
5. Proposals approved at Gate 2 (no further approval needed): proxy access logs 14 days with no client IP, backups encrypted to both founders and stored off the VPS, and the 7-day target for high or critical proxy advisories. Operational inputs still needed: OI-1, the named owner of the Caddy build maintenance, and OI-2, the off-VPS backup provider. Implementation tasks, not approvals: re-verifying the Caddy pins at build time (task 9.3), and the privacy notice and UK GDPR wording.
6. The Copilot review loop on PR #2 is closed by owner decision after round 11. One regression-check review of the CR-21 commit is requested. Task 9.6a carries the one unresolved concern.
