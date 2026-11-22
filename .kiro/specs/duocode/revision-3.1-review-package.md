# DuoCode Revision 3.1 Review Package (final for gate review, strict hard-stop correction, RD-14 approved, PR #2 review addressed)

History: the revision 3.1 content was published on `spec/revision-3.1-review` and merged to `main` (PR #1, `b88580d`). The strict hard-stop correction (CR-9, section 3A) is on branch `spec/key-usage-strict-hard-stop`, created from that `main`. Commit hashes are reported with the branches, because a file cannot contain its own commit hash.

The project stays in specification and approval mode. This package contains no application code, no database migration and no implementation task. **No gate is signed off.** The architecture (Deno, TypeScript, Oak, PostgreSQL, Docker Compose, Caddy) is unchanged.

## 1. Gate status

| Gate | Task | Subject | Status |
|---|---|---|---|
| 1 | 1.1 | Requirements | Not signed off |
| 2 | 1.2 | Architecture | Not signed off |
| 3 | 1.3 | OpenAPI specification | Not signed off |
| 4 | 1.4 | Database schema and state machine | Not signed off |
| 5 | 1.5 | Security assessment | Not signed off |
| 6 | 1.6 | Licensing files and contributor arrangements | Not signed off. Inputs LI-1 to LI-4 outstanding |
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

## 3B. Rotation after 2^28 (CR-10) and PR #2 review findings (CR-11 to CR-14)

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

## 4. Files (revision 3.1 branch, for history)

Added: `.kiro/specs/duocode/revision-3.1-review-package.md` (replaces the revision 3 package), `.kiro/specs/duocode/check-consistency.py`, `.kiro/specs/duocode/verify-schema.py`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE`.
Removed: `.kiro/specs/duocode/revision-3-review-package.md` (superseded).
Modified: `.github/copilot-instructions.md`, `.kiro/specs/duocode/` (`database-schema.md`, `deployment.md`, `design.md`, `requirements.md`, `security-assessment.md`, `simulator-design.md`, `state-machine.md`, `tasks.md`, `test-strategy.md`, `traceability.md`), `README.md`, `openapi/openapi.yaml`.
The two `.py` files are specification tooling (consistency and schema verification). They are not application code or migrations. The branch contains the exact file list in the final report.

## 5. Verification results (actual output)

### 5.1 OpenAPI

Redocly lint of `openapi/openapi.yaml`: **valid, 0 errors, 0 warnings.** The OpenAPI document is not changed by CR-9.

### 5.2 Database schema, constraint and reservation tests

`verify-schema.py` extracts the DDL, the reservation, registration, sealing and pre-encryption-check statements **from `database-schema.md`**, so the tested SQL is the specified SQL. It applies them to a throwaway cluster and runs 58 tests.

| Server | Result |
|---|---|
| PostgreSQL 15.8 (Homebrew), with `pg_dump` and `pg_restore` | **58 of 58 passed**, three runs |
| PostgreSQL 16.16 embedded build (no `pg_dump` of its version available) | **57 of 57 passed, 1 skipped** (the logical restore test), two runs |
| **PostgreSQL 16.16 official `postgres:16` image (Debian, Docker Desktop)**, image digest `sha256:3950ad7c3148ca2175ef1b6c36c9efbf78957ae8fbe8b3a5d7c35af50500382f`, with its own `pg_dump` and `pg_restore` | **58 of 58 passed**, one run |

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

The rest of the 58 tests are the constraint tests (seats, nicknames and bidirectional controls, guess chain, credential binding, one rematch ever, idempotency, rotation record, rate limits, cleanup, invariant check, start-up validation rule).

**Limits, stated plainly.** No application exists. The instance in these tests is a small model of the allowance and claim rules. Its reservations, seals and checks go to real PostgreSQL. The tests prove the SQL, the constraints and the policy. They do not prove that a future vault follows the policy, which is why the (APP) tests in `test-strategy.md` are required in Phase 4. The staged rolling rotation (zero decrypt failures), the re-encryption recount, the claim-before-check order in the vault and the per-role health reporting are specified as (APP) tests and have not been run.

### 5.3 Specification consistency checks

`check-consistency.py`, final run on the final file set (24 checks). C24 was checked by mutation: replacing the extracted reservation statement in `verify-schema.py` with a hard-coded one makes C24 fail.

```
PASS C01 every requirement R1..R21 defined and in traceability matrix
PASS C02 every R<n>.<m> criterion reference exists
PASS C03 every TS group and TS-CONC id referenced is defined (18 groups, 28 concurrency scenarios)
PASS C04 every decision ID is defined in the register and none is unknown
PASS C05 no stale revision 2/3 identifiers or the email signature in the specification, README or licensing files
PASS C06 every "<file>.md section N" reference resolves to a heading
PASS C07 design.md API table matches OpenAPI paths and methods (13 operations)
PASS C08 every error code named anywhere exists in the OpenAPI ErrorCode enum (21 codes)
PASS C09 game states agree between OpenAPI, database enum and state machine
PASS C10 every `table.column` reference names a real column (12 tables in the DDL)
PASS C11 every configuration key named in the specification is in design.md section 13 (23 keys)
PASS C12 rate-limit scopes agree between design.md and deployment.md
PASS C13 licensing artefacts present, LICENSE is the FSF AGPL-3.0 text (sha256 0d96a4ff68ad6d4b...), NOTICE names AGPL-3.0-only
PASS C14 GitHub workflow files parse as YAML
PASS C15 no Phase 1 gate or task is marked approved in tasks.md
PASS C16 OpenAPI constrains codes to 4 symbols from 1..6
PASS C17 nickname forbidden character classes agree between OpenAPI and database CHECK (NUL aside)
PASS C18 OpenAPI rotation key pattern accepts v4 UUIDs and rejects v1 and wrong-variant values
PASS C19 every decision in the register has a row in the traceability decision map (72 decisions)
PASS C20 no decision recorded as approved in the register is still described as pending elsewhere
PASS C21 no application code, database migration or implementation directory exists
PASS C23 key usage design is consistent: one authoritative row per key, CHECK at 2^30, thresholds 2^27 / 2^28 / 2^30, strict statement, terms defined, sharding only mentioned as replaced
PASS C24 the schema verification tool takes the reservation, registration and sealing statements from database-schema.md
PASS C22 OpenAPI lint (Redocly): valid with 0 errors and 0 warnings
24 of 24 checks passed (0 skipped)
```

The checks are textual. They prove that identifiers, references and definitions agree. They cannot prove that the documents are right.

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
| `NOTICE` | Draft banner. Copyright lines are placeholders. **No names are asserted** (my earlier draft named one person, which I have removed) |
| `CONTRIBUTING.md` | Draft banner. Contribution terms proposed. External contributions closed until approved. Bracketed placeholders for the open inputs. Not legal advice |

Inputs only you can give. I have not invented any of them:

| ID | Input | Where it appears |
|---|---|---|
| LI-1 | Exact copyright holder names, and any affiliation to show | `NOTICE` (two placeholders) |
| LI-2 | Whether a contributor licence agreement is required before outside contributions | `CONTRIBUTING.md` section 2 |
| LI-3 | Legal review of the contribution terms and the dual-licensing position | `CONTRIBUTING.md` section 2 |
| LI-4 | Security contact address | `CONTRIBUTING.md` section 4 |

## 7. Outstanding issues

1. No technical decision is pending. RD-14 is approved.
2. All six gates await your explicit sign-off. Nothing is signed off.
3. LI-1 to LI-4 (section 6).
4. The (APP) tests and the restore and rotation drills with real tools (section 5.4).
5. Drafting proposals not explicitly approved: proxy access-log retention (14 days, no IP by default), backup recipients, a named owner for the Caddy build, the 7-day target for critical proxy security upgrades, re-verification of the Caddy version pins at build time. The privacy notice and UK GDPR wording remain tasks.
6. A fifth Copilot review of the CR-14 corrections is requested (see the report with PR #2).
