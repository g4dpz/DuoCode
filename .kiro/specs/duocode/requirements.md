# DuoCode Requirements (Backend MVP 1), revision 3.1 (final for gate review, strict hard-stop correction, RD-14 approved)

Source: `DuoCode-Requirements` v2.0 (baseline, dated 21 November 2026) and the owner decisions in the decision register.
Scope: MVP 1, a backend-only game playable through the REST API. The web application, PWA, white-label and multi-tenant work are out of scope.

Status: **Gate 1 approved by the owner on 2026-11-22 (David Johnson, G4DPZ), as at `main` commit `53c46df`. R19's licensing text stays pending Gate 6. Gate 2 (architecture) approved on 2026-11-22, with the key command-list wording in `deployment.md` 2.1 and 6.3 and `design.md` section 3 re-confirmed the same day (see `tasks.md` 1.2). Gate 3 (OpenAPI contract) approved on 2026-11-22. Gate 4 (database schema and state machine) approved on 2026-11-22. Gate 5 (security assessment) approved on 2026-11-22.** No implementation is authorised. Implementation stays unauthorised until all six Phase 1 gates in `tasks.md` are explicitly signed off. A change to this file after approval reopens Gate 1 for the changed requirement.

Revision history: revision 2 added the owner decisions OD-1 to OD-10. Revision 3 applied the owner review of revision 2. Revision 3.1 applies the owner review of revision 3: technical corrections CR-1 to CR-8, the RD-1 to RD-13 decisions, the CH-1 to CH-6 choices with the owner's qualifications, and the licensing artefacts. It does not change the architecture or widen MVP 1. The owner has approved all technical decisions below. Only the owner inputs listed under "Operational inputs still needed" (OI-1, OI-2) and "Inputs still needed for gate 6" (LI-1 to LI-4) remain open. The change summary is in `revision-3.1-review-package.md`.

## Specification set

This file owns the requirements and the decision register. Other artefacts own their own definitions and must not redefine them.

| Artefact | Owns |
|---|---|
| `requirements.md` (this file) | Requirements, acceptance criteria, decision register |
| `traceability.md` | Requirement to artefact, API operation, constraint, test and approval-status mapping |
| `design.md` | Architecture overview, layers, credential model, authorisation point, lock ordering, rate-limiting design, configuration keys and defaults |
| `../../../openapi/openapi.yaml` | The wire contract: paths, schemas, status codes, error codes |
| `database-schema.md` | Tables, constraints, migrations, retention clock rules, cleanup SQL |
| `state-machine.md` | Game, player-challenge and credential lifecycles, transition tables, expiry rule |
| `security-assessment.md` | Threats, encryption, key management, rotation implications, logging and metrics rules, residual risks |
| `test-strategy.md` | Test layers, required cases, test group IDs, CI jobs |
| `simulator-design.md` | Simulator behaviour and replay |
| `deployment.md` | Compose stack, secrets, rate-limit values, backups, restore, key recovery, scheduling |
| `revision-3.1-review-package.md` | Change summary from revision 3, verification results, remaining decisions |
| `LICENSE`, `NOTICE`, `CONTRIBUTING.md` (repository root) | Proposed licensing artefacts for gate 6 review |
| `tasks.md` | Phased tasks and approval gates |

## Glossary

- **Game**: One two-player match with a unique identifier.
- **Player**: A participant in one game, identified by a nickname and held to a game access token. A player has no account.
- **Secret code**: A sequence of 4 symbols chosen from 6. Repeats are allowed.
- **Guess**: A 4-symbol sequence submitted against the opponent's secret code.
- **Feedback**: A pair `(exact, misplaced)` of counts for one guess.
- **Solved**: A player's guess equals the opponent's secret code.
- **Exhausted**: A player has used all 10 guesses without solving.
- **Finished (player)**: A player is solved or exhausted.
- **Game access token**: Bearer credential that authorises one player's actions in one game.
- **Invitation token**: Single-use bearer credential that lets a second player join one game.
- **Rematch capability**: Bearer credential that authorises creating one rematch of one completed game. It grants no access to any game.
- **Credential**: Any of the three tokens above.
- **Reference time**: The database clock value read once at the authorisation point of a request. Every expiry and validity decision in that request uses it.
- **Reserved unit**: One permitted encryption under a key, counted in the key's authoritative reservation counter `R`. `R` counts units reserved, not encryptions performed, so `R` can exceed the number of invocations and never fall below it.
- **Encryption invocation**: One actual call that encrypts a value. It consumes one reserved unit held by the calling instance.
- **Allowance**: The reserved units one application instance holds in memory and has not yet consumed. Allowances are part of `R`.
- **Rematch marker**: A database row keyed by the original game that records that a rematch was created. It lives as long as the original game and does not depend on the rematch game's lifetime (R9.4).
- **Retention end** (`expires_at`): The instant at or after which a game and everything attached to it is expired.
- **Expired**: `reference time >= expires_at`. The same test applies in authentication, operations and cleanup.
- **Authorisation point**: The single function, called inside each request's database transaction, that decides whether a presented credential is currently valid for the requested operation (design section 5).
- **Rotation replay window**: The short period after a token rotation in which the old token, together with the same idempotency key, can retrieve the new token again (R8.13).
- **Engine**: The pure game-rules module with no HTTP, database, crypto or framework dependency.

## Fixed configuration (MVP 1)

| Parameter | Value |
|---|---|
| Players | 2 |
| Code positions | 4 |
| Symbols | 6 (integers `1`..`6` on the wire; artwork is a client concern) |
| Repeated symbols | Allowed |
| Maximum guesses per player | 10 |
| Feedback | Exact and misplaced counts |

The values live in one configuration object so later work can vary them. MVP 1 does not expose them through the API.

## Decision register

Status values: **Approved** (owner approved), **Approved with conditions** or **with extension** or **with qualification** (approved, and the conditions are applied in the text and listed in the row), **Pending** (needs an owner decision). No technical decision is pending in revision 3.1.

### Owner decisions from revision 2

All ten are Approved and unchanged in substance.

| ID | Decision | Applied in |
|---|---|---|
| OD-1 | Repository layout follows the baseline: `backend/`, `tools/`, `tools/simulator/`, `openapi/`, `docs/`. The README agrees. A `frontend/` directory is added when browser work starts. | R19.1, `design.md` section 3 |
| OD-2 | A player's own secret code is never returned by the API after submission, and is excluded from logs, diagnostics and error responses. | R3.6, R3.7, R13.2 |
| OD-3 | A player sees the opponent's guess count, solved flag and exhausted flag, never the opponent's guesses or feedback. | R6.3 |
| OD-4 | `Idempotency-Key` is mandatory on guess submission and fully specified. | R5 |
| OD-5 | Retention defaults: unjoined 7 days, in progress 30 days, completed 180 days, configurable. | R11 |
| OD-6 | Secret codes are encrypted at rest with authenticated encryption (AES-256-GCM). Keys are held outside PostgreSQL and its backups. | R10 |
| OD-7 | Game access tokens, rematch capabilities and invitation tokens are separate and hashed at rest. A rematch creates a new game with entirely new tokens. No token recovery. Rotation and revocation are atomic. | R8, R9 |
| OD-8 | Specification artefacts are separate files. The OpenAPI document is produced and reviewed before implementation. | R12.6, R19.5 |
| OD-9 | The baseline date of 21 November 2026 is correct. | Header |
| OD-10 | No implementation is authorised. Phase 1 contains the approval gates. | `tasks.md` |

### Decisions approved in the revision 3 review

| ID | Decision | Status | Applied in |
|---|---|---|---|
| ND-1 | Both secret codes are revealed only by the results endpoint once the game is `COMPLETED`. | Approved | R3.7, R7.4 |
| ND-2 | Rematch flow: the first requester creates the new game and shares the invitation out of band. One rematch per game. | Approved | R9 |
| ND-3 | Separate rematch capability. | Approved | R8.5, R9 |
| ND-4 | Access-token rotation, amended: rotation must be idempotent so a lost response does not lock the player out. Security implications documented. | Approved with amendment | R8.6, R8.13, `security-assessment.md` section 2.2 |
| ND-5 | Only state-changing requests extend the in-progress retention period. | Approved | R11.2 |
| ND-6 | Plain SHA-256 of independently generated 256-bit credentials. | Approved | R8.2 |
| ND-7 | Amended: stored guesses are encrypted with AES-256-GCM using the same key ring as secret codes. Feedback counts, guess numbers and solved or exhausted flags stay in plaintext. Goal: database-only access cannot reconstruct secret codes from guesses and feedback. | Approved with amendment | R4.1, R10, R5.12, `security-assessment.md` section 3 |
| ND-8 | Retention 7, 30 and 180 days. Hourly cleanup. Backups at most 35 days. No player-initiated deletion endpoint in MVP 1. | Approved | R11, R21 |
| ND-9 | Docker-secret-mounted JSON key ring, with documented generation, backup, recovery, rotation and compromise procedures. Old keys stay available as long as any backup containing ciphertext under them may be restored. | Approved with amendment | R10, R21 |
| C-1 | Credentials in `Authorization: Bearer`. Invitation token in the join request body. | Approved | R8 |
| C-2 | No invitation preview endpoint in MVP 1. | Approved | Out of scope |
| C-3 | Duplicate nicknames allowed. | Approved | R1.3 |
| C-4 | Administrative operations limited to metrics and cleanup behind a separate admin token. | Approved | R21 |
| C-5 | No token refresh flow. | Approved | R8 |
| C-6 | Rate limiting in two layers: coarse per-IP limits at the proxy and shared PostgreSQL limits in the application. Numerical values approved through RD-2. | Approved | R20 |
| C-7 | A valid credential of an expired but not yet deleted game returns `410 GAME_EXPIRED`. After deletion the response is `401 INVALID_CREDENTIALS`. Credential records are not retained to preserve the expired response. | Approved with clarification | R8.8, R11.3 |

### Engineering clarifications from the revision 3 review

| ID | Clarification | Applied in |
|---|---|---|
| CL-1 | Every authenticated operation validates current credential status at one authorisation point. Writes recheck under the game-row lock. Reads use one consistent snapshot. | R8.7, R8.11, R8.12 |
| CL-2 | Expiry is `reference time >= expires_at` everywhere. | R11.3 |
| CL-3 | Encryption documentation: key identifiers, nonce uniqueness, AAD, transactional re-encryption, backup recovery, key retirement. | R10, `security-assessment.md` section 3 |
| CL-4 | Rate limiting is shared across instances, using PostgreSQL, plus coarse IP limits at the proxy. Redis is not required. | R20 |
| CL-5 | Nickname validation: trim, reject empty, at most 24 code points, reject control characters, preserve the accepted value, allow duplicates. | R1.3 |
| CL-6 | Idempotency fingerprints use RFC 8785 JSON Canonicalization Scheme. | R5.12 |
| CL-7 | Database constraints enforce player limits, guess limits, rematch uniqueness and idempotency wherever practical. | R5.10, R9.4, `database-schema.md` section 3 |
| CL-8 | Lock ordering and deadlock avoidance documented. Join, guess, rotation, rematch and cleanup races are tested. | `design.md` section 8, R17 |

### Corrections in revision 3.1

| ID | Correction | Applied in |
|---|---|---|
| CR-1 | Decrypted game values may be serialised into an API response in exactly two cases: a player's own guesses and feedback through progress, and both codes, all guesses and feedback through results after `COMPLETED`. Results verify completion before any ciphertext is read. Decrypted values stay out of logs, diagnostics, metrics, traces, errors and persistent plaintext storage. | R7.5, R10.7, R13.2 |
| CR-2 | Authenticated reads use this order: preliminary non-authoritative credential lookup, rate-limit update in a short autocommit transaction, begin a read-only `REPEATABLE READ` transaction, authoritative credential validation as its first statement, all data from the same snapshot. Writes use the same first two steps, then lock the game row and validate. | R8.11, R8.12, R20 |
| CR-3 | Rotation idempotency keys must be UUIDv4 from a cryptographically secure random source. Other idempotency keys keep the general UUID rule. Replaying a successful rotation inside the window returns the original response and does not restore or reactivate the old token. Losing the replacement token after the window loses the seat. | R5.1, R8.13 |
| CR-4 | Caddy is retained with a pinned, reproducible custom build, with documented provenance and maintenance. | R18.6, `deployment.md` section 4.3 |
| CR-5 | `LICENSE`, `NOTICE` and `CONTRIBUTING.md` are prepared for gate 6 review now. | R19.2, `tasks.md` 1.6 |
| CR-6 | The stray email signature is removed from `README.md`. | R19.1 |
| CR-7 | All documents were reviewed for consistency with the revised decisions. Consistency checks are reported in the review package. | R19.5 |
| CR-8 | The rematch-created marker is a separate database row that survives deletion of the rematch game. | R9.4, R9.8, `database-schema.md` |
| CR-24 | Gate 5 preparation: `security-assessment.md` is aligned with the approved `database-schema.md` and `deployment.md`: the reservation statement shows the fingerprint condition; the restore summary abandons a sealed staged key, truncates `rate_limits` and runs cleanup before any service starts; the rotation summary states `keys:activate --expect`, the admission gate and that `reencrypt` and `keyverify` do not run in phases 1 and 2; re-encryption follows the claim, pre-encryption check and commit-time check; the ring mounts and key commands list `keyverify`, `keys:retire` and `keys:reconcile-gate`; threats T36 to T39 cover the key lifecycle protections of CR-13 to CR-21; the 9.6a concern is a residual risk. `test-strategy.md` maps every threat to test groups and TS-CONC-23 matches the commit-time check. The key commands are listed as one set everywhere: `deployment.md` 2.1 lists `keys:retire` and `keys:reconcile-gate` and says `keys:verify` runs in `keyverify`, `deployment.md` 6.3 and `security-assessment.md` 3.9 name `keys:retire`, and the `design.md` layout and task 9.2a list every command. Wording alignment only; no requirement, schema, contract or behaviour change. The `deployment.md` and `design.md` edits reopened Gate 2 for those lines, and the owner re-confirmed them on 2026-11-22. | R10.10, R10.13, R10.14, `security-assessment.md`, `test-strategy.md` 18, `deployment.md` 2.1, 6.3, `design.md` 3 |
| CR-23 | Gate 4 preparation: the write order of checks in `state-machine.md` 1.3 adds the two steps that `design.md` 8.1 and 9.1 already required: the encryption claim followed by the pre-encryption check as the last step before the transaction, and the commit-time sealed check (`FOR SHARE`) immediately before commit. A retry repeats from the claim. Wording alignment only; no schema, contract or requirement change. | R10.10, R10.14, `state-machine.md` 1.3 |
| CR-22 | Gate 3 preparation: the OpenAPI contract declares `500 INTERNAL_ERROR` and `503 SERVICE_UNAVAILABLE` on every operation, and `429` on the admin operations, so that the failure responses required by R10 (decryption failure), R20.7 (rate-limit store failure) and `design.md` 8.2 (lock timeout) are part of the contract. Contract only; no requirement text changed. | R10.7, R12.3, R20.7, `openapi.yaml` (draft 6) |
| CR-21 | Eleventh Copilot review of PR #2 (summary concerns, no inline findings): in the restore procedure, migrations now run straight after the database is restored, before any step that uses the newer tables and columns. The second concern (a key possibly activated while a reader lacks it) could not be reproduced from the specification text and is recorded as Phase 9 task 9.6a, to be settled against the real tooling. The Copilot review loop on PR #2 was stopped here by owner decision. | R10.13, R10.14, `deployment.md` 6.1, `tasks.md` 9.6a |
| CR-20 | Tenth Copilot review of PR #2: the reconciliation pre-check grant names the real columns (`token_rotations.token_key_id`); the restore procedure finishes abandonment, reconciliation and verification while every service is still stopped, and starts the services only once, at the end, as fresh processes. | R10.13, `deployment.md` 2.1, 6.1, `security-assessment.md` 3.6 |
| CR-19 | Ninth Copilot review of PR #2: the `ring_state` singleton row is created by the schema itself and every update checks that it changed one row; the roles get exactly the `ring_state` rights they need; after a restore the admission gate is reconciled offline with the newest ring, after confirming that no restored ciphertext needs a removed key, before verification and again after the new key is activated. | R10.13, R10.14, `database-schema.md` 6.2a, `deployment.md` 2.1, 6.1 |
| CR-18 | Eighth Copilot review of PR #2 (summary concerns, no inline findings): an admission gate (`ring_state.required_key_ids`) checked by every reader right after it takes its presence lock, committed by activation before it reads the roster, so no reader without the new key can be admitted uncounted; bounded lock waits for `keymgmt` and a shared ring lock plus a hard deadline for `keyverify`; every transaction retry is a fresh attempt with a new claim and a new pre-encryption check, spent units are never returned, and a unit is consumed before the cipher is called. | R10.10, R10.14, `database-schema.md` 6.2a, `design.md` 8.2, `deployment.md` 2.1 |
| CR-17 | Seventh Copilot review of PR #2: the activation roster is the set of processes holding a presence lock on a live database connection, so stopped processes are never counted and silent live ones block activation; an offline activation path for bootstrap and restore that refuses while any reader is live, and a query that cannot return NULL; report and cleanup privileges are complete; `keyverify` may read only `players(id, game_id)` in addition, and is kept read-only; roster participants are defined consistently with their permissions. | R10.14, `database-schema.md` 6.2a, `deployment.md` 2.1, 6.1, 6.4 |
| CR-16 | Sixth Copilot review of PR #2: the key-management role gets exactly the database rights its commands need, and `keys:verify` runs in a separate read-only `keyverify` job so the ring-writing job never sees game ciphertext; staged activation is enforced through a database-backed acknowledgement table (`instance_ring_reports`) and an expected instance count, not through the admin metrics listener. | R10.14, `database-schema.md` 6.2a, `deployment.md` 2.1, 6.4 |
| CR-15 | Fifth Copilot review of PR #2: a dedicated, narrowly privileged `keymgmt` job is the only context that changes the ring and writes key backups; key material is written directly to the protected ring and never printed; ring-changing operations are serialised by a single-writer advisory lock and a version-checked write; the recovery procedure in the security assessment includes the history checks of the lossless proof; the verifier's request model claims before it checks, an in-flight request between check and seal is tested, and stalled sessions are terminated. | R10.4, R10.13, `deployment.md` 2.1, `security-assessment.md` 3.6, `database-schema.md` 6.2 |
| CR-14 | Fourth Copilot review of PR #2: `keys:generate` records the identifier and fingerprint in the backed-up ring history (`PENDING`) before registering, with recovery for interrupted runs (`ABANDONED`); loaded material is bound to its history record and to the registered fingerprint (pre-encryption check and reservation statement); retired keys keep their usage row for ever; the lossless restore proof also covers every historical key; staged keys sealed by a restore are abandoned and activation refuses a sealed key; the request sequence in `design.md` 8.1 is corrected to claim first and check last; incomplete SQL copies in the review package are replaced by references; three verification-tool fixes. | R10.4, R10.10, R10.13, `database-schema.md` 6.2, `design.md` 8.1, 9.1, `security-assessment.md` 3.6, 3.9, `deployment.md` 6.1 |
| CR-13 | Third Copilot review of PR #2: a commit-time check under a share lock makes it impossible to commit ciphertext under a key after its seal (replacing the timed drain); the claim is taken before the pre-encryption check and the allowance is rechecked after a refused reservation; registration rejects a different fingerprint for an existing identifier and new identifiers are above every registered one; restore seals every identifier in the fingerprint history, which also restores the database fingerprint registry; the lossless proof covers every key that can still encrypt, including staged keys; `503` is declared on code and guess submission; three verification-tool fixes. | R10.4, R10.10, R10.13, R10.14, `database-schema.md` 6.2, 6.3, `design.md` 8.2, 9.1, `deployment.md` 6.1, 6.4, `openapi.yaml` |
| CR-12 | Second Copilot review of PR #2: a new key is staged on every instance before it is activated (new ring status `STAGED`), so a rolling restart never produces unreadable ciphertext; a key's fingerprint is kept for ever in the ring history and in a unique database column, so retired material can never be re-registered; `keys:generate` registers, reserves and only then encrypts the self-test value, so a new key starts at counter 1 and never 0; restore seals exactly the identifiers of the ring as it was before the new key was added; the post-seal exposure bound was stated, with a timed wait (both later replaced by the commit-time check of CR-13); the claim is rechecked synchronously after every reservation wait; re-encryption recounts under the game lock; sealed non-active keys report `sealed` and raise no alert; a test that misused an unreserved unit is corrected. | R10.4, R10.6, R10.10, R10.13, R10.14, `database-schema.md` 6.2, 6.3, `design.md` 9.1, `deployment.md` 6.1, 6.4 |
| CR-11 | Copilot review of PR #2: duplicate key material and identifier reuse rejected; reservations positive only and in whole blocks sized to the operation; sealing inserts a sealed row for a missing key; restore uses the newest ring and `highestKeyId`, stops and drains every encrypting process and restarts instances even on the lossless path; start-up self-test does not encrypt, so an exhausted key can start; replays and rule rejections still answered when no unit is available; units are claimed atomically before the transaction; each instance refreshes key usage state from the authoritative row; two verification-script robustness fixes. | R10.4, R10.6, R10.10, R10.13, `database-schema.md` 6.2, `design.md` 9.1, `verify-schema.py` |
| CR-10 | Key lifecycle after rotation, including a rotation completed after the 2^28 threshold: the new key becomes active, the previous key becomes decrypt-only and is sealed, outstanding in-memory allowances for it can no longer be used (a pre-encryption sealed check, no hot ring reload, restart before sealing), unused reservations stay counted, and no instance resumes encryption under the previous key because it holds an allowance. Consistent across the key lifecycle, deployment and recovery documents. | R10.14, `database-schema.md` 6.3 |
| CR-9 | The 2^30 hard stop is a strict global limit across all instances. One authoritative counter row per key replaces the 32 shards. A single atomic conditional statement grants reservations, so the total of reserved units can never exceed 2^30, allowances are inside the total, and concurrent instances cannot pass the limit independently. A key is sealed at every rotation and restore. Threshold behaviour is defined exactly, and reserved units are distinguished from encryption invocations throughout. | R10.10, R10.13, `database-schema.md` 6.2 |

### Decisions from the revision 3.1 review and the gate approvals (RD-1 to RD-15)

| ID | Owner response | Status | Applied in |
|---|---|---|---|
| RD-1 | Retain Caddy with a pinned, reproducible custom build of the selected rate-limit module. Document provenance and maintenance. | Approved | R18.6, `deployment.md` 4.3 |
| RD-2 | Recommended rate limits approved, provided that all values stay configurable, enforcement is shared across application instances, and a failure of the PostgreSQL rate-limit store fails closed with `503`. | Approved with conditions | R20.2, R20.7, R20.8, `deployment.md` 4.2 |
| RD-3 | Rotation replay window of 10 minutes. | Approved | R8.13 |
| RD-4 | Separate admin listener. | Approved | R21.1 |
| RD-5 | Unicode code-point counting, trimming and control-character rejection. Also reject bidirectional override and isolation controls. Preserve legitimate Unicode. | Approved with extension | R1.3 |
| RD-6 | Only one rematch ever per original game, even after the rematch expired or was deleted. The marker is independent of the rematch game's lifetime. | Approved | R9.4, R9.8 |
| RD-7 | No point-in-time recovery for MVP 1, accepted as a documented operational risk. Reassess before production. | Approved as accepted risk | R21.4, `deployment.md` 12 |
| RD-8 | HMAC fingerprints for guess requests. | Approved | R5.12 |
| RD-9 | HMAC of client IP in rate-limit storage, with documented privacy implications, retention and key management. | Approved | R20.4, R20.10, `security-assessment.md` 6.2 |
| RD-10 | Nonce thresholds: warning at 2^27 encryptions per key, mandatory rotation by 2^28, hard stop at 2^30. The counter must account for every encryption invocation, including those in failed or rolled-back application transactions. | Approved | R10.10, `security-assessment.md` 3.3a |
| RD-11 | Rotation replay may decrypt and return the replacement token, as a narrow third exception, only when: the original token is presented, the original UUIDv4 key is presented, the request fingerprint matches, the replay window is valid, and the replacement token has not been revoked. The replacement token never appears in logs, diagnostics, metrics or error responses. A replay never reactivates the old token. | Approved | R8.13, R10.7, R13.2 |
| RD-12 | Rotating a player's access token revokes that player's unused rematch capability in the same transaction. | Approved | R8.6 |
| RD-15 | Gate sign-off authority: an explicit statement from one owner is enough to sign off a Phase 1 gate, a re-confirmation, or task 1.9. Both owners are not required. Decided by David Johnson (G4DPZ) on 2026-11-22, statement "one owner's statement is enough". | Approved | `tasks.md` Phase 1, `.github/copilot-instructions.md` |
| RD-14 | Reservations continue between 2^28 (rotation overdue: critical alert, degraded admin health state) and the hard stop. The hard stop at 2^30 is absolute and inclusive: the counter may reach exactly 2^30 and no reservation takes it beyond. Refusing at 2^28 would add an availability risk with cryptographic headroom remaining. | Approved | R10.10, `database-schema.md` 6.2 |
| RD-13 | Key usage counter (refined by CR-9: one authoritative row per key and a strict conditional reservation, replacing the draft's shards), approved on conditions: reservations are durable and cannot be rolled back with the application transaction. The counter can never underestimate actual encryption usage. A database restore procedure prevents continued encryption under a key whose counter may have been rolled back. A new key is activated before traffic is accepted after a restoration where necessary. Old keys remain available for decryption. | Approved with conditions | R10.10, R10.13, R21.4, `database-schema.md`, `deployment.md` 6.1 |

### Choices CH-1 to CH-6

| ID | Owner response | Status | Applied in |
|---|---|---|---|
| CH-1 | Allow legitimate Unicode joiners and international text. Reject bidirectional embedding, override and isolation controls. Include display-security tests. | Approved with qualification | R1.3, R1.5, `test-strategy.md` TS-VAL |
| CH-2 | Exclude rate-limit data from backups. | Approved | `deployment.md` 5 |
| CH-3 | Revoke all unused rematch capabilities when a rematch is successfully created. | Approved with qualification (replaces the revision 3.1 draft rule that kept unused capabilities, unconsumed and answering `409`) | R9.9, `state-machine.md` 3, 4 |
| CH-4 | Player-keyed rate-limit buckets. Token rotation must not reset rate limits. | Approved with qualification | R20.4 |
| CH-5 | Deterministic UUIDv4-compatible rotation keys for simulator testing, derived from the simulator seed and game identity. Production keys always use cryptographically secure randomness. | Approved with qualification | R15.5, `simulator-design.md` |
| CH-6 | Pin the Caddy rate-limit module to its exact commit and retain the reproducible build and provenance checks. | Approved | R18.6, `deployment.md` 4.3 |

### Decisions awaiting owner approval

None of the technical decisions is pending. RD-14 was approved. Approval of the six Phase 1 gates, each to be authorised explicitly, remains with the owner (`tasks.md` Phase 1).

### Operational inputs still needed (not technical decisions)

| ID | Input needed from the owners | Where it shows |
|---|---|---|
| OI-1 | The founding collaborator who owns Caddy build maintenance | `deployment.md` 4.3 |
| OI-2 | The off-VPS backup storage provider | `deployment.md` 5 |

### Inputs still needed for gate 6 (licensing)

These are not technical decisions. The specification does not invent them: the files carry placeholders.

| ID | Input needed from the owners | Where it shows |
|---|---|---|
| LI-1 | Exact copyright holder names (and any affiliation to show) | `NOTICE` |
| LI-2 | Whether a contributor licence agreement is required before outside contributions | `CONTRIBUTING.md` 1, 2 |
| LI-3 | Legal review of the contribution terms and the dual-licensing position | `CONTRIBUTING.md` 2 |
| LI-4 | Security contact address | `CONTRIBUTING.md` 4 |

## Requirements

Acceptance criteria use EARS wording. Baseline references (FR-nnn, SIM-nnn, SCALE-nnn, section numbers) are in brackets. Requirements R1 to R19 keep their revision 2 numbers. R20 and R21 are new.

### R1: Game creation

1. WHEN a client creates a game with a valid nickname, THE system SHALL create a game in state `WAITING_FOR_PLAYER`, create the creator as seat 1, and return the game id, a game access token, an invitation token and the retention end. (FR-001 to FR-005)
2. THE system SHALL generate game ids and tokens from a cryptographically secure random source (credential format in `design.md`). (FR-002, 5.3)
3. THE system SHALL validate every nickname (create, join and rematch) as follows, and reject a failing value with `INVALID_NICKNAME` without creating or changing anything (CL-5, C-3):
   a. Trim leading and trailing Unicode white space (code points with the `White_Space` property).
   b. Reject the result if it is empty.
   c. Reject the result if it is longer than 24 Unicode code points (not UTF-16 units and not bytes).
   d. Reject the result if it contains any code point in Unicode general category `Cc` (U+0000 to U+001F and U+007F to U+009F), any bidirectional embedding, override or isolate control (U+202A to U+202E and U+2066 to U+2069), or malformed Unicode such as unpaired surrogates (RD-5). Other Unicode, including directional marks (U+200E, U+200F, U+061C), joiners (U+200C, U+200D), emoji sequences and combining characters, is legitimate text and SHALL be accepted (CH-1).
   e. Store and return the trimmed value exactly as accepted, with no case folding, normalisation or changes to interior characters.
   f. Permit duplicates, including two players in one game with the same nickname.
4. THE system SHALL return each token in plaintext only in the response that creates it, and SHALL store only token hashes (exception: R8.13).
5. THE system SHALL return nicknames only as JSON string values, with `Content-Type: application/json; charset=utf-8` and `X-Content-Type-Options: nosniff`, never as HTML, and SHALL NOT alter them on output. The API documentation SHALL instruct clients to escape nicknames for the display context and to render them in an isolated bidirectional context (for example an HTML `<bdi>` element or `dir="auto"` with `unicode-bidi: isolate`), so that mixed-direction names cannot reorder neighbouring text. Rejecting embedding, override and isolate controls (R1.3) is a server-side defence in depth, not a replacement for client escaping. (CH-1)

### R2: Joining

1. WHEN a client presents a valid, unused invitation token for the game and a valid nickname, THE system SHALL add the client as seat 2, consume the invitation, and return a new game access token. (FR-004, FR-015)
2. IF the game already has two players or the invitation is consumed, THEN THE system SHALL reject the join with `GAME_FULL`. (9.4)
3. IF the invitation token is invalid, unknown, or belongs to a different game, or the game does not exist (including after deletion), THEN THE system SHALL reject it with `INVALID_INVITATION` and the same response shape and status in each case. (7.4)
4. IF the invitation is valid and the game is expired but not yet deleted, THEN THE system SHALL reject the join with `410 GAME_EXPIRED` (C-7).
5. WHEN two clients join the same game at once, THE system SHALL admit exactly one. A database constraint SHALL backstop the limit of two players. (FR-024)

### R3: Secret code submission and privacy

1. WHEN a player submits a code of 4 symbols, each in 1..6, THE system SHALL store it encrypted (R10) for that player. (FR-006)
2. IF a code has the wrong length or a symbol outside 1..6, THEN THE system SHALL reject it without changing state. (9.2)
3. IF the player has already submitted a code, THEN THE system SHALL reject the request with `CODE_ALREADY_SET`. A code is immutable once set.
4. THE system SHALL accept a code from seat 1 before seat 2 has joined.
5. WHEN both players have joined and both have submitted codes, THE system SHALL change the game to `ACTIVE` in the same transaction as the second event. (FR-007)
6. THE response to a code submission SHALL NOT contain the submitted code. (OD-2)
7. THE system SHALL NOT return any secret code, own or opponent's, from any endpoint before the game is `COMPLETED`. Only the results endpoint returns codes. (OD-2, ND-1, 3.8)

### R4: Guessing and feedback

1. WHEN a player submits a valid guess to an `ACTIVE` game, THE system SHALL compare it with the opponent's secret code, store the guess encrypted (R10) with its plaintext feedback counts, increment that player's guess count and return the guess number and feedback. (FR-008, FR-009, ND-7)
2. THE feedback calculation SHALL count exact matches first, then count misplaced matches from the remaining symbols, and SHALL NOT count any symbol more often than it occurs in either code. (3.4)
3. THE feedback SHALL contain only the exact count and misplaced count, not per-position information. (3.3)
4. IF a guess is invalid (wrong length, symbol out of range, malformed body, missing or malformed idempotency key), THEN THE system SHALL reject it without changing the guess count or any other state. (FR-021)
5. IF the player has used 10 guesses, THEN THE system SHALL reject further guesses with `ATTEMPTS_EXHAUSTED`. (FR-020)
6. IF the player has already solved, THEN THE system SHALL reject further guesses with `ALREADY_SOLVED`.
7. IF the game is not `ACTIVE`, THEN THE system SHALL reject guesses with `GAME_NOT_ACTIVE`, `GAME_COMPLETED` or `GAME_EXPIRED` as appropriate. (FR-022)
8. WHEN a guess equals the opponent's code, THE system SHALL mark the player solved and record guesses used.
9. WHEN a player uses the tenth guess without solving, THE system SHALL mark the player exhausted.
10. THE system SHALL let a player guess only the opponent's code. No request form SHALL target the player's own code. (9.4)
11. THE system SHALL let each player guess independently, in any order and at any time. (3.6)

### R5: Idempotency and concurrency

1. THE guess endpoint SHALL require an `Idempotency-Key` header whose value is a UUID in canonical text form (8-4-4-4-12 hexadecimal digits, case-insensitive, any version). THE system SHALL reject a missing or malformed key with `INVALID_IDEMPOTENCY_KEY`. Clients SHOULD use UUIDv4. The rotation endpoint uses a stricter rule (R8.13). (OD-4)
2. THE scope of uniqueness SHALL be the triple (acting player, operation, key). A key is therefore unique per player and per game, because a player belongs to one game, and per operation. The same key value used by the other player, in another game or for another operation is unrelated and SHALL NOT conflict or leak information.
3. THE system SHALL recognise a duplicate by looking up (acting player, operation, key) inside the operation's transaction, after taking the game lock.
4. WHEN a duplicate key arrives with the same request fingerprint, THE system SHALL return the stored original status and body unchanged, with the header `Idempotent-Replay: true`, and SHALL NOT record a guess, change a count or change any other state.
5. WHEN a duplicate key arrives with a different fingerprint, THE system SHALL reject it with `409 IDEMPOTENCY_CONFLICT` and change nothing.
6. THE system SHALL store a key and its response only when the guess succeeded, in the same transaction as the guess. A rejected request (validation, state, attempts) stores nothing, so its key stays free for a corrected request.
7. THE system SHALL keep each key and response until the game is deleted (R11). With at most 10 guesses per player the storage is bounded, and keeping keys for the whole game means a late retry can never consume a second attempt.
8. THE replayed response SHALL be the original response, including the `gameState` and `guessesRemaining` values it carried when first produced, even when the game has since changed.
9. A replay SHALL be checked before game-state and attempt checks, so a retry of the completing guess still returns the original response after the game is `COMPLETED`. A replay still requires a valid credential for the game and a game that is not expired.
10. WHEN concurrent or duplicate requests arrive, THE system SHALL guarantee that no more than one attempt is consumed per distinct key, that guess numbers are contiguous from 1, that no guess follows a solving guess, and that the count never exceeds 10. Database constraints SHALL enforce these rules (CL-7): the unique key and range on guess numbers, a foreign key to the previous guess for contiguity and for "no guess after solved", and the primary key on idempotency records. (FR-023, FR-024)
11. WHEN a request fails part-way, THE system SHALL leave no partial update. All state changes for one request SHALL commit in one database transaction. (5.2)
12. THE request fingerprint SHALL be computed from the envelope `{"operation": <name>, "gameId": <lowercase uuid>, "body": <parsed request body>}` serialised with RFC 8785 JSON Canonicalization Scheme (JCS), so that equivalent bodies (key order, whitespace, escapes) give the same fingerprint. THE system SHALL reject request bodies with duplicate member names before fingerprinting. For guess requests the fingerprint SHALL be an HMAC-SHA-256 keyed from the key ring (RD-8), because an unkeyed hash of one of 1296 possible guesses could be reversed by a database reader. (CL-6)

### R6: Status and progress

1. WHEN an authorised player requests game status, THE system SHALL return the game state, both nicknames, whether each player has joined and has set a code, whether a rematch exists, the retention end, and the opponent's progress summary (R6.3). (FR-010)
2. WHEN an authorised player requests progress, THE system SHALL return that player's own guesses with feedback, guesses used, guesses remaining, and solved and exhausted flags. (FR-010)
3. THE opponent progress summary SHALL contain only the opponent's total guesses used, whether they solved, and whether they exhausted their attempts. THE system SHALL NOT return the opponent's individual guesses or feedback until the game is `COMPLETED`. (OD-3)
4. THE system SHALL NOT expose database identifiers, token hashes or other internal fields. (7.1)
5. THE system SHALL NOT require long-lived connections. Clients poll. (5.1, 12.3)

### R7: Completion and results

1. WHEN both players are finished, THE system SHALL change the game to `COMPLETED`, compute the outcome, set the retention end to completion time plus the completed-game period, and store the result, all in the same transaction as the final guess. (FR-011, 3.6)
2. THE outcome SHALL follow this table (3.7):

| Player 1 | Player 2 | Result |
|---|---|---|
| Solved in n | Solved in m, n < m | Player 1 wins |
| Solved in n | Solved in m, n > m | Player 2 wins |
| Solved in n | Solved in n | Draw |
| Solved | Exhausted | Player 1 wins |
| Exhausted | Solved | Player 2 wins |
| Exhausted | Exhausted | Draw |

3. THE system SHALL NOT end the game when only one player is finished. (3.6)
4. WHEN the game is `COMPLETED`, THE results response SHALL contain both secret codes, both players' guesses and feedback, guesses used, solved status, the outcome and the completion time. (3.8, ND-1)
5. IF results are requested while the game is not `COMPLETED`, THEN THE system SHALL reject the request with `GAME_NOT_COMPLETED` and SHALL NOT read any ciphertext, decrypt or reveal any code or guess. THE system SHALL verify within the request's snapshot that the game is `COMPLETED` before any secret-code ciphertext is read or decrypted (CR-1).
6. THE system SHALL retain enough data to reconstruct the game and its result until the retention end. (FR-013)

### R8: Credentials

1. THE system SHALL use three distinct credential types: game access token, invitation token and rematch capability. Each SHALL be accepted only by the operations that expect its type. The type is determined by the stored record and not by the token's visible prefix. (7.3)
2. THE system SHALL generate every credential from its own draw of at least 256 bits of cryptographically secure randomness, with no derivation between credentials, and SHALL store only its plain SHA-256 hash (ND-6). The sole exception is the temporary encrypted copy of a rotated token (R8.13). (5.3)
3. A game access token SHALL authorise exactly one player in exactly one game. It SHALL NOT authorise any other game, including a rematch of the same game. The acting player SHALL always be derived from the token.
4. An invitation token SHALL be single use and SHALL be consumed in the same transaction that creates the second player.
5. A rematch capability SHALL authorise creating at most one rematch of one completed game and SHALL grant no read or play access to any game.
6. WHEN a token is rotated, THE system SHALL create the new credential, revoke the old one, and revoke the player's unused rematch capability (RD-3), in a single transaction. After commit, the old token SHALL NOT authorise any operation except the replay in R8.13. (ND-4)
7. THE system SHALL verify the credential again inside the transaction of every state-changing operation, after taking the game lock, so that a revocation committed earlier cannot be bypassed. (CL-1)
8. THE system SHALL reject revoked, consumed, unknown, deleted and wrong-type credentials with an identical `401 INVALID_CREDENTIALS` response. A credential that would otherwise be accepted but belongs to a game that is expired and not yet deleted SHALL receive `410 GAME_EXPIRED`. Once the game and its credentials are deleted the response is `401`. THE system SHALL NOT keep credential records solely to preserve the `410` response. (C-7)
9. THE system SHALL NOT provide any mechanism to recover a lost credential. Without an account or independently verified identity, possession of the token is the only proof of identity. This limitation SHALL be documented in the API documentation and security assessment. (OD-7)
10. Credentials SHALL be invalid once the game is expired (`reference time >= expires_at`), whether or not cleanup has run.
11. EVERY authenticated operation SHALL decide credential validity authoritatively at one authorisation point inside its database transaction, using one reference time. Before that, the HTTP layer SHALL extract the token and the service SHALL perform a preliminary credential lookup that is non-authoritative: it is used only to find the player for rate limiting and to reject tokens that do not exist, and it SHALL NOT grant access. For state-changing operations the authoritative decision runs after the game-row lock. (CL-1, CR-2)
12. EVERY authenticated read operation SHALL proceed in this order (CR-2): (1) preliminary credential lookup, which grants nothing; (2) rate-limit update in a short autocommit transaction (R20); (3) begin a read-only `REPEATABLE READ` transaction; (4) authoritative credential validation as the first statement of that transaction; (5) read the requested data from the same snapshot. A credential revoked before step 4 fails at step 4 even if steps 1 and 2 passed. A read whose snapshot began before a rotation commits MAY succeed with the old token. A read that reaches step 3 after the commit SHALL NOT. Rate limiting never grants or denies credential validity.
13. THE rotation operation SHALL be idempotent so a lost response does not lock the player out (ND-4, CR-3, RD-11). It SHALL require an `Idempotency-Key` that is a version 4 UUID (random UUID, version nibble 4, variant bits `10`), which clients SHALL generate from a cryptographically secure random source, because for rotation the key acts as a replay secret with 122 bits of randomness. The server SHALL reject any other UUID version or a malformed key with `INVALID_IDEMPOTENCY_KEY`. Inside the rotation replay window (10 minutes by default, RD-3), THE system SHALL decrypt and return the replacement token again, with `Idempotent-Replay: true`, if and only if ALL of these hold: (a) the original, now revoked, access token is presented; (b) the original UUIDv4 idempotency key is presented; (c) the request fingerprint matches; (d) the replay window is still valid at the reference time; (e) the replacement token has not been revoked. Otherwise THE system SHALL return `401` (or `409 IDEMPOTENCY_CONFLICT` for a reused key with a different old token) and SHALL NOT decrypt anything. A replay SHALL change no state: it SHALL NOT restore, reactivate or un-revoke the old token, and the old token stays `REVOKED` for every other operation. The server SHALL hold the replacement token only as AES-256-GCM ciphertext under the key ring and SHALL clear it after the window. The replacement token SHALL NEVER appear in logs, diagnostics, metrics, traces or error responses. If the client loses the replacement token and the window has passed, the seat is lost: there is no other way to recover it (R8.9). This is the third, narrowly defined serialisation exception, for a credential and not for game data (R10.7, RD-11 approved).
14. THE results of a completed game SHALL remain readable by the player through the player's current access token after any number of rotations. A token revoked by rotation SHALL NOT read results. Rotation changes who may read, not what is stored.

### R9: Rematch

1. WHEN a participant of a `COMPLETED` game requests a rematch capability with their access token, THE system SHALL create a new capability, revoke any previous unused capability of that player for that game, and return the capability once. (ND-3)
2. WHEN a client presents a valid rematch capability and a valid nickname, THE system SHALL, in one transaction, consume the capability, create a new game linked to the original, create the requester as seat 1 with a new game access token, and create a new invitation token. (OD-7, ND-2)
3. THE new game SHALL have entirely new credentials. Tokens of the original game SHALL NOT authorise any operation on the new game, and the new game's tokens SHALL NOT authorise the original game.
4. THE system SHALL permit at most one rematch ever per original game, even after that rematch has expired or been deleted (RD-6). A rematch marker SHALL record it: a database row whose primary key is the original game id and whose reference to the rematch game does not depend on the rematch game's lifetime. Minting a capability once a marker exists SHALL receive `409 REMATCH_ALREADY_CREATED`. Creation through any other path that reaches the marker insert SHALL receive the same error. The primary key SHALL enforce the rule (CL-7, CR-8).
5. IF the original game is not `COMPLETED`, THEN THE system SHALL refuse to mint a capability with `GAME_NOT_COMPLETED`.
6. THE original game's status SHALL report only whether a rematch exists, never the new game's identifier or credentials.
7. THE system SHALL NOT re-issue tokens of the new game. The opponent obtains the invitation from the player who created the rematch, outside the API.
8. THE marker SHALL be created in the same transaction as the rematch game and SHALL live as long as the original game, being deleted with it. The reference from the marker to the rematch game SHALL be cleared (set to null) when the rematch game is deleted, and the marker SHALL remain. Deleting a rematch game SHALL NOT remove the marker, so the original can never have a second rematch. The rematch game's link to its original is derived from the marker, so it ends when the original is deleted. The rematch continues as an ordinary game. Capabilities belong to the original game and are deleted with it.
9. WHEN a rematch is created successfully, THE system SHALL, in the same transaction, revoke every unused rematch capability of the original game (reason `SUPERSEDED`), so that no capability remains usable (CH-3). A presenter of a revoked capability receives `401 INVALID_CREDENTIALS`, and the original's status shows `rematchCreated: true`. WHEN a rematch marker exists, an attempt to mint a capability SHALL receive `409 REMATCH_ALREADY_CREATED`. The marker's primary key remains the backstop if any other path reaches creation (R9.4).

### R10: Encryption and key management

1. THE system SHALL encrypt every stored secret code and every stored guess with AES-256-GCM using a unique random 96-bit nonce per encryption. Guess numbers, feedback counts and solved or exhausted flags MAY be stored in plaintext. (OD-6, ND-7)
2. THE system SHALL bind each ciphertext to its row through GCM additional authenticated data (AAD) that contains a purpose label, the key identifier, the game id, the player id, and for guesses the guess number, so a ciphertext copied elsewhere fails authentication. (CL-3)
3. THE system SHALL hold encryption keys outside PostgreSQL and outside database backups. Keys SHALL NOT appear in database records, migrations, logs, environment dumps or source control. (ND-9)
4. THE system SHALL support a key ring with an integer identifier per key, a status (`ACTIVE` for exactly one key, `STAGED` for a new key that is loaded and can decrypt but never encrypts, `DECRYPT_ONLY` for older keys) and creation date. Identifiers SHALL never be reused. Each ciphertext row SHALL record the key identifier that encrypted it. No two keys in the ring SHALL share the same key material, and the ring SHALL record a monotonic highest key identifier ever used, so a new key always gets a higher identifier and identifiers and key material are never reused even if an entry is later removed. Ring changes SHALL be made only by a dedicated key-management job, separate from the application, that writes key material directly to the protected ring and never prints or logs it, and that serialises every ring change with a single-writer lock and a version-checked write (CR-15). `keys:generate` SHALL write the new identifier and fingerprint into the separately backed-up ring history before registering it in the database, so an interrupted run never loses the record; a history entry left `PENDING` SHALL be marked `ABANDONED` and never reused. At load and before every encryption, the loaded material SHALL be checked against the ring history and against the registered fingerprint, so a key's material can never be used under another key's counter. The usage row of a retired key SHALL be kept permanently (CR-14). Registration SHALL be idempotent only for the same identifier with the same material: an identifier already registered with different material SHALL be rejected before any reservation, and a new identifier SHALL be above both the ring's highest identifier and the highest registered identifier in the database (CR-13). The ring loader and `keys:generate` SHALL reject duplicate material and a non-increasing identifier (a repeated key under a new identifier would bypass that key's usage budget, CR-11). The ring SHALL also keep, for ever, the fingerprint of every key ever registered, including retired keys, and the key usage table SHALL keep a unique fingerprint per key identifier and never delete it, so material that was once registered can never be registered again under a new identifier after its key is retired (CR-12).
5. THE system SHALL provide a re-encryption task that moves every ciphertext and keyed fingerprint to the active key. It SHALL process one whole game per transaction under the game lock, so a game is never partly migrated. It SHALL be safe to run repeatedly and while the service is live.
6. THE system SHALL refuse to start without a valid active key, and SHALL verify the key ring at start-up with a self-test that does **not encrypt**: it decrypts a known-answer value that `keys:generate` encrypted once when the key was created (`keys:generate` registers the key, reserves at least one unit, and only then encrypts it, so a new key's counter is at least 1, CR-12). An instance SHALL therefore be able to start, serve reads and decrypt existing data when the active key is sealed or at the hard stop, and SHALL answer every request that needs a fresh encryption with `503` (CR-11).
7. THE system SHALL decrypt a secret code or guess only in these paths (CR-1): (a) guess submission, which decrypts the opponent's code to compute feedback and serialises only the feedback; (b) progress, which decrypts the caller's own guesses and returns them with their feedback to the authenticated caller; (c) results, only after the game is verified `COMPLETED` and before any ciphertext is read, which decrypts both codes and all guesses and returns them with feedback to an authenticated participant. Exceptions (b) and (c) are the only cases in which a decrypted game value may be serialised into an API response. The one other permitted serialisation of decrypted data is the replacement token in a rotation replay, a credential and not game data, under the conditions of R8.13 (RD-11). A decrypted value SHALL NOT be written to logs, diagnostics, metrics, traces, error responses, crash output or any persistent plaintext storage (including stored idempotency responses and any column other than the ciphertext columns), SHALL NOT be assigned to long-lived state, and SHALL exist only inside the callback that uses it, with its buffer cleared afterwards as far as the runtime permits.
8. THE game engine SHALL receive decrypted codes and guesses only as function arguments and SHALL contain no cryptography. Decryption lives in the persistence layer. (R14)
9. THE documentation SHALL describe key generation, storage, backup, recovery, rotation, retirement and compromise response, including that losing every copy of a key makes the affected data unrecoverable. (`security-assessment.md`, `deployment.md`)
10. THE system SHALL keep one durable, authoritative usage counter row per encryption key and SHALL enforce these thresholds on its reserved total `R` (RD-10, RD-13, CR-9): a warning state at 2^27, a rotation-overdue state at 2^28 (critical alert and degraded admin health state, the key must be rotated, and reservations continue to be granted until the hard stop, RD-14 approved), and an inclusive hard stop at 2^30 (R may equal 2^30 exactly, and no reservation that would take it beyond is granted). The three terms are distinct: a *reserved unit* is one permitted encryption counted in `R`, an *encryption invocation* is one actual encryption and consumes one reserved unit held by the calling instance, and an *allowance* is the reserved units an instance holds unconsumed. The following SHALL hold:
    a. `R` SHALL never exceed 2^30. This SHALL be enforced by an atomic conditional reservation statement on the single counter row (so every reservation under a key, from every instance, is serialised) and, as a backstop, by a database constraint.
    b. A reservation SHALL be granted only if `R` plus the block does not exceed the configured hard stop, evaluated against the latest committed `R`. Otherwise it SHALL be refused whole and change nothing. Concurrent reservations from different instances SHALL NOT be able to pass the limit independently.
    c. A reservation SHALL be committed in its own short autocommit transaction before any unit from it is used, so it SHALL NOT be rolled back with an application transaction, an instance crash or a retry.
    d. Every encryption invocation SHALL consume one previously reserved unit, whether or not the surrounding transaction commits. An instance SHALL NOT encrypt when it holds no unit for the operation. The claim SHALL be checked and decremented in one synchronous step **after** any wait for a reservation, and the shortfall SHALL be recomputed from the allowance as it is at that moment, because other requests on the instance may have used it while the reservation was in progress (CR-12). After a refused reservation the instance SHALL check the current allowance once more before giving up, because other requests may have returned units (CR-13). The claim SHALL be taken **before** the pre-encryption check, which is the last step before the transaction begins, and SHALL be returned if the check fails (CR-13). If it cannot obtain units, the operation SHALL end with `503` at the point where a fresh encryption is needed, before anything is written. Operations that need no encryption (an idempotent replay including a rotation replay, a conflict, a rule rejection) SHALL still receive their normal answer (CR-11).
    e. All outstanding allowances are part of `R`, because a unit enters an allowance only after it has been added to `R`.
    f. `R` MAY overestimate the invocations (lost allowances, unknown outcomes) and SHALL NEVER underestimate them.
    g. The configured hard stop SHALL be at most 2^30 and a multiple of the block size, and the block size SHALL be at least 1, validated at start-up. A reservation SHALL be for a positive whole number of blocks, and the reservation statement SHALL match no row for a zero or negative request, so no statement can lower the counter. An operation that needs more units than the instance holds SHALL obtain as many whole blocks as it needs in one reservation, so a small block size can never leave an operation short while capacity remains.
    h. Before its transaction begins, an operation SHALL atomically **claim** the units it may need from the instance's allowance, and SHALL return the units it did not use afterwards, so that two concurrent requests on one instance can never both rely on the same unit and an operation never discovers inside its transaction that no unit is left.
    i. Each instance SHALL read the authoritative `key_usage` rows at start-up and at least every `KEY_USAGE_REFRESH_SECONDS` (default 30), without reserving, and update its metrics and admin health state, so that a threshold crossed by another instance is reported by all instances.
    j. An operation whose need depends on stored data (re-encryption of a game) SHALL recount what it must encrypt after taking the game lock and before encrypting or writing, and if the recount exceeds its claim SHALL roll back without effect, obtain a larger claim outside the transaction, and retry. No reservation SHALL be made inside the game transaction (CR-12).
    k. Health and alerts SHALL be evaluated by the role of the key: only the key that is `ACTIVE` in the ring can be `warning`, `degraded` or `critical`. A non-active sealed key reports `sealed`, which is expected after a rotation and raises no alert. A sealed key that the ring lists as `ACTIVE` is `critical` (CR-12).
    l. Every retry of a transaction (deadlock, serialisation failure, unique-violation backstop, re-encryption recount) SHALL be a fresh attempt: it SHALL take a new claim and run the pre-encryption check again before beginning, SHALL NOT reuse a unit consumed by an earlier attempt, and SHALL return only units it claimed and did not consume. An encryption invocation SHALL consume its unit before the cipher is called (CR-18).
11. A key SHALL be retired (removed from the ring) only when no database row references it and every backup that may contain data encrypted under it has expired or been destroyed. The earliest retirement date is the completion date of re-encryption plus the maximum backup retention (35 days). Until then the key stays in the ring as `DECRYPT_ONLY` and in the key backup. (ND-9)
12. THE system SHALL provide a key verification task that lists the key identifiers referenced by the database, confirms each is present in the ring, and test-decrypts every ciphertext, for use after restore and before key retirement.
13. AFTER a database restore from a backup, THE system SHALL NOT continue to encrypt under the key that was active before the restore, because its usage counter may have been rolled back and so underestimate real use (RD-13). Before the restore starts, every process that can encrypt (`app`, `cleanup`, `reencrypt` and all key jobs) SHALL be stopped and drained, and the pre-restore counters SHALL be read after that point if a lossless proof is attempted. The restore procedure SHALL use the **newest ring** (highest `generation`) and its `highestKeyId`, never a ring from the database backup date, generate a new key with an identifier above `highestKeyId`, make it the only `ACTIVE` key, mark the previous key `DECRYPT_ONLY`, and **seal exactly the key identifiers in the newest ring's permanent fingerprint history as it stands before the new key is added** (every key ever registered, including retired keys, CR-13; the new key is not sealed), including one whose `key_usage` row is absent from the restored database (sealing inserts a sealed row when none exists), meaning set its counter to the hard-stop value so that every further reservation under it is refused even if the ring were wrong. Database migrations SHALL be applied immediately after the backup is restored and before any later step of the procedure (CR-21). It SHALL complete abandonment, reconciliation of the admission gate and verification while every service is stopped, and SHALL then start the services once, as fresh processes, so that every in-memory allowance is discarded, all before the application accepts traffic (CR-20). A restore proved lossless MAY skip the new key and the sealing, and SHALL still start the services only at the end, as fresh processes. Lossless means: the stopped pre-restore database is still readable, and for **every key that can still encrypt** (the `ACTIVE` key and every `STAGED` key) the restored row exists, its sealed flag matches, and its counter is not lower than the pre-restore counter (CR-13). In addition, every identifier in the fingerprint history SHALL have its row present with the same fingerprint and sealed flag as before the restore. A `STAGED` key sealed by a lossy restore SHALL be abandoned, and activation SHALL refuse a sealed key (CR-14). A planned rotation SHALL seal the old key once every instance runs the new ring. Old keys SHALL remain in the ring for decryption of existing data until retired under R10.11. A key that has been `DECRYPT_ONLY` SHALL NEVER return to `ACTIVE`. The key verification task SHALL also check, for each key, that the number of ciphertext rows under it does not exceed its reserved total, and fail if it does.
14. WHEN a key stops being the active key, whether by a planned rotation (including one completed after the 2^28 threshold) or by a restore, THE system SHALL (RD-14, CR-10): (a) **stage** the new key on every instance first (registered, counter at least 1, loaded as `STAGED`, able to decrypt and never encrypting, every instance restarted), so that no instance can ever meet ciphertext it cannot decrypt, and SHALL NOT activate it until every **live reader**, meaning every process that holds a presence lock on a live database connection, has acknowledged it in the database, the number of live readers equals the expected count, and no read-only verifier is running. A key SHALL be activated with no reader running only through an explicit offline activation that refuses while any reader is live (CR-16, CR-17). After a restore the set of required keys SHALL be reconciled with the newest ring while no reader is running, after confirming that every key referenced by restored ciphertext is still in the ring (CR-19). Before reading the roster, activation SHALL commit the staged key into the set of keys every newly admitted reader must have, and every reader SHALL check that set immediately after taking its presence lock and refuse to serve if its ring lacks a required key (CR-18); then make it the only `ACTIVE` key and the previous key `DECRYPT_ONLY`, and restart every instance again, because the ring is read only at process start, the active key cannot change while a process runs, and no allowance is ever carried across a ring change; (b) keep the previous key `DECRYPT_ONLY`, so decryption of existing data continues; (c) once every instance runs the new ring, **seal** the previous key, which sets `sealed = true` and its counter to 2^30 and never lowers a counter; (d) make outstanding in-memory allowances for the previous key unusable, because every request that may encrypt SHALL run a pre-encryption check that the active key is not sealed before the request begins, so that no request beginning after the seal commits can encrypt under it. Every transaction that writes ciphertext SHALL, immediately before commit, re-read the key's sealed flag under a share lock (`FOR SHARE`), and SHALL roll back if the key is sealed. The seal is therefore ordered after every transaction already in that check and before every later one, so **no ciphertext under the previous key SHALL be committed after the seal has committed**. Units consumed by a transaction that rolls back stay counted (CR-13); (e) keep unused reserved units counted in the previous key's total; (f) NOT allow any instance to resume encryption under the previous key merely because it holds an allowance: an allowance is permission to use units that were already counted, never permission to use the key; (g) never return a key that has been `DECRYPT_ONLY` to `ACTIVE`. This SHALL be described identically in the key lifecycle (`security-assessment.md` 3.6), deployment (`deployment.md` 6.1, 6.3) and recovery documentation, with `database-schema.md` 6.3 as the single source.

### R11: Expiry, retention and cleanup

1. THE system SHALL read these periods from configuration, with defaults (OD-5, ND-8): unjoined games 7 days, games in progress 30 days, completed games 180 days.
2. THE system SHALL store a retention end (`expires_at`) on every game and maintain it as follows. On creation it is creation time plus the unjoined period and is not extended while the game is unjoined. On join and on every later state-changing request (ND-5) it is that time plus the in-progress period. On completion it is completion time plus the completed period and is not extended again. Reads, polling and idempotent replays do not extend it.
3. A game SHALL be expired when `reference time >= expires_at`. THE system SHALL apply this one rule in the authorisation point, in every operation and in cleanup (CL-2). WHEN a game is expired, THE system SHALL reject every operation on it with `410 GAME_EXPIRED` (credential holder) or the uniform response of R8.8, and SHALL NOT modify it. This applies at once, independent of cleanup. (9.4)
4. THE system SHALL treat every credential of an expired game as invalid. (R8.10)
5. THE cleanup task SHALL permanently delete every game with `reference time >= expires_at` together with its players (nicknames), encrypted secret codes, encrypted guesses, idempotency keys, rotation records, results and credentials. After deletion no record of the credentials remains (R8.8).
6. THE cleanup task SHALL be safe to repeat and to run concurrently with itself and with live traffic: it works in bounded batches, re-checks expiry on the locked row, skips rows locked by other transactions, and produces the same end state however often it runs.
7. A rematch SHALL keep working as a normal game when its original is deleted. (R9.8)
8. THE system SHALL log only counts and durations from cleanup, never nicknames, codes, guesses or tokens.
9. THE documentation SHALL state that deleted data persists in backups for at most the backup retention of 35 days, and that a restore SHALL be followed by cleanup before the service accepts traffic. (ND-8, 5.4)
10. THE system SHALL NOT provide a player-initiated deletion endpoint in MVP 1. (ND-8)
11. THE cleanup task SHALL also remove rate-limit rows idle for more than an hour and clear rotation token ciphertext past its replay window.

### R12: API conventions and errors

1. THE system SHALL serve all player endpoints under `/api/v1/` with JSON bodies. (7.1)
2. THE system SHALL return every error as `{ "error": { "code", "message", "requestId" } }` with a stable machine-readable `code` and a status that matches the error class. (7.4)
3. THE error codes and statuses SHALL be those defined in `openapi/openapi.yaml`, which covers every case listed in baseline 7.4.
4. THE system SHALL validate every body, path parameter and header on the server. Unknown body properties SHALL be rejected.
5. THE error `message` SHALL NOT echo request values, in particular submitted codes, guesses, nicknames or tokens.
6. THE OpenAPI 3.1 document SHALL be approved before implementation starts and SHALL be the contract for contract tests. (7.5, OD-8)
7. THE system SHALL expose `GET /healthz` reporting process, database and key ring readiness.

### R13: Security, privacy, logging and metrics

1. THE system SHALL apply rate limits as specified in R20. (5.3)
2. THE system SHALL NOT write secret codes, guesses, request or response bodies of code, guess, rotation and rematch endpoints, nicknames, tokens, token hashes, idempotency keys of rotation, `Authorization` headers, admin tokens, encryption keys, fingerprints or decrypted values to logs, metrics, traces, diagnostic output, crash reports or error responses, nor store decrypted values in any persistent plaintext form (R10.7). (OD-2, CR-1)
3. THE system SHALL be served over HTTPS in deployment, terminated at the reverse proxy.
4. THE system SHALL collect only nicknames and operational data needed to run a game. Nicknames SHALL NOT be shown outside their game. (5.4)
5. THE system SHALL keep administrative credentials separate from player credentials, and players SHALL have no administrative access. (5.3)
6. THE system SHALL NOT require accounts, passwords or personal information. (FR-018)
7. THE project SHALL document retention and deletion with UK GDPR in mind. (5.4)
8. THE metrics SHALL be privacy-safe: aggregate counts, gauges and histograms only. Labels SHALL come from bounded sets (route template, status class, error code, key identifier, operation). They SHALL NOT include game ids, player ids, nicknames, IP addresses, tokens or any value derived from them.
9. THE diagnostic logs SHALL be structured and limited to an allow-list of fields: time, level, request id, route template, status, duration, error code, operation name, counts, and game id (an identifier, not a credential) where needed. Client IP addresses SHALL NOT be written by the application.

### R14: Engine independence and verifiability

1. THE engine SHALL import no Oak, HTTP, database, crypto or I/O module, and an automated check SHALL enforce it. (6.3)
2. THE engine SHALL be deterministic: the same inputs always give the same outputs.
3. THE test suite SHALL include a reference feedback implementation that shares no code with production and SHALL compare both on all 1296 × 1296 secret and guess pairs and on seeded random cases. (3.4, 9.2)

### R15: Simulator

The simulator lives in `tools/simulator` and uses only the public REST API. Its behaviour is defined in `simulator-design.md`.

1. THE simulator SHALL support configurable game count, concurrency, strategy and seed, and SHALL create two independent players per game. (SIM-001 to SIM-005)
2. THE simulator SHALL check feedback against the reference implementation, check state transitions, detect unexpected responses, and verify idempotent guess retries and idempotent rotation retries including a simulated lost rotation response and the display-security rules for nicknames. (SIM-006 to SIM-008)
3. THE simulator SHALL record failures with seed and game number and SHALL replay one game from them. (SIM-009, 9.5)
4. THE simulator SHALL write JSON and a human-readable summary with the metrics listed in baseline 9.5, and SHALL run as `deno task simulate`. (SIM-010 to SIM-012)
5. THE simulator SHALL generate rotation idempotency keys deterministically in test deployments (CH-5): each key is a UUIDv4-compatible value (version and variant bits set) derived from the simulator seed, the game number, the player seat and the rotation index, so a replay of a game uses the same keys. Such keys are predictable by design. The simulator SHALL therefore refuse to run unless the operator passes an explicit test-deployment flag. Production clients SHALL always generate rotation keys from a cryptographically secure source.

### R16: Documentation and client tooling

1. THE repository SHALL include a Postman collection with creation, joining, code submission, guessing, status, results, rotation, rematch, error scenarios and a full two-player lifecycle, using variables and no real credentials. (8.3)
2. THE documentation SHALL include curl examples that play a whole game with separate credentials per player. (8.4)
3. THE documentation SHALL state the lost-token limitation (R8.9) and how to retry a rotation safely (R8.13).

### R17: Testing and CI

1. THE project SHALL include the test layers in `test-strategy.md`, and SHALL cover every negative case in baseline 9.4. (9.1, 9.4)
2. THE test suite SHALL include concurrency scenarios for simultaneous join, guess, token rotation, rematch creation and cleanup, in the combinations listed in `test-strategy.md`. (CL-8)
3. A pull request SHALL trigger format check, lint, type check, unit tests, API integration tests, security checks and build verification. Simulation and larger load tests MAY run as separate jobs. (9.7)
4. THE project SHALL measure API latency and report the 95th percentile against the 500 ms target. (5.1)

### R18: Deployment and operability

1. THE application SHALL be stateless and run as several instances without session affinity. All shared state, including rate-limit counters, SHALL be in PostgreSQL. (6.4)
2. THE project SHALL provide a Docker Compose deployment as described in `deployment.md`. (12.1)
3. THE project SHALL keep versioned database migrations and apply them in a controlled step. (5.6)
4. THE project SHALL keep development and production configuration separate and keep secrets and encryption keys out of source control. (5.6, 14.3)
5. THE system SHALL expose metrics for games created, active and completed, API request count and latency, subject to R13.8. (12.4)
6. THE reverse proxy SHALL be Caddy built from a pinned, reproducible, documented custom build that includes the selected rate-limit module: exact versions pinned (Caddy, module, Go toolchain, builder image digest), dependencies locked by a committed `go.sum`, a build that produces the same binary digest twice, a recorded build provenance, and a documented maintenance procedure (`deployment.md` section 4.3). (RD-1, CR-4)

### R19: Licensing, repository layout and specification set

1. THE repository layout SHALL follow baseline section 14.2 as amended by OD-1 (`design.md`). THE README SHALL show the same layout. (OD-1)
2. THE repository SHALL carry the full AGPL-3.0-only text in `LICENSE`, an `SPDX-License-Identifier: AGPL-3.0-only` header on source files, a `NOTICE` file and a `CONTRIBUTING.md` with contribution terms before any outside contribution is accepted. Proposed versions of these three files exist at the repository root for gate 6 review. (13.1, 13.4, CR-5)
3. THE project SHALL NOT assume that AGPL contributions grant commercial relicensing rights. (13.4)
4. THE project SHALL use original names, artwork and symbols. (3.1, 13.5)
5. THE specification artefacts SHALL reference one another, SHALL define each item once in the artefact that owns it, and SHALL be mapped in `traceability.md`.

### R20: Rate limiting

1. THE system SHALL limit request rates in two layers: coarse per-IP limits at the reverse proxy, and finer per-IP and per-player limits in the application (C-6, CL-4).
2. THE application layer SHALL keep its counters in PostgreSQL so that all instances share them. In-memory counters alone SHALL NOT be relied on. Redis SHALL NOT be required.
3. EACH limit SHALL be a token bucket (capacity and refill rate) updated by a single atomic statement, so concurrent instances cannot oversubscribe a bucket.
4. THE subject of an IP-based bucket SHALL be an HMAC of the client IP keyed by a secret, and the subject of a player-based bucket SHALL be a hash of the player id (CH-4). The player is found by the preliminary credential lookup (R8.11), so no bucket row is created for a token that does not exist. The application SHALL NOT store IP addresses or plaintext tokens (RD-9).
5. THE application SHALL trust a forwarded client IP only from configured proxy addresses (RD-9).
6. THE system SHALL reject a request over its limit with `429 RATE_LIMITED` and a `Retry-After` header, before the request's database transaction begins and before any other work.
7. IF the rate-limit store (PostgreSQL) is unavailable or a rate-limit statement fails, THEN THE system SHALL fail closed: the request SHALL be rejected with `503` and a `Retry-After` header, and SHALL NOT be processed without a rate-limit decision (RD-2).
8. THE values SHALL be configurable. Recommended starting values are in `deployment.md` section 4.2 and need owner approval before implementation. (C-6, RD-2)
9. EVERY rate-limit update SHALL run as its own short autocommit transaction before the request transaction begins, so that no rate-limit row lock is ever held together with a game lock or while waiting for one (`design.md` section 8). (CR-2)
10. THE documentation SHALL state the privacy implications, retention and key management of the stored IP HMACs (`security-assessment.md` section 6.2, RD-9): what is stored, that it remains personal data in pseudonymised form, that rows are deleted after one hour idle, that the key is a separate secret that is rotated by replacing it, and that the table is excluded from backups (CH-2).

### R21: Administration, scheduling, backup and restore

1. THE system SHALL provide two administrative interfaces only: metrics and cleanup. They SHALL be served on a separate admin listener reachable only on the internal network and SHALL NOT be routed by the public proxy (C-4, RD-4). They SHALL require the admin token.
2. THE scheduled cleanup SHALL be run hourly by a dedicated `cleanup` service that runs the cleanup task from the same codebase. Application instances SHALL NOT schedule cleanup themselves and cleanup SHALL NOT depend on an HTTP call. THE admin cleanup endpoint SHALL exist for manual and dry runs and SHALL call the same code. (ND-8)
3. THE system SHALL keep database backups for at most 35 days. (ND-8)
4. THE project SHALL document and drill a database restore procedure and a key recovery procedure (`deployment.md` sections 5 and 6) before production use, including: restore, supplying the key ring, activating a new key before traffic (R10.13), `keys:verify`, clearing rate-limit state, running cleanup before accepting traffic, and the effect of restore on credential state. No point-in-time recovery is provided in MVP 1. This is an accepted, documented operational risk to be reassessed before production deployment (RD-7, `deployment.md` section 12).
5. THE project SHALL document key generation, backup, rotation, retirement and compromise procedures (`security-assessment.md` section 3.3, `deployment.md` section 5). (ND-9)

## Out of scope for MVP 1

Web application, PWA, accounts, chat, matchmaking, leaderboards, tournaments, payments, advertising, AI opponents, native apps, multi-tenant infrastructure, white-label administration, custom domains, Kubernetes, microservices, multi-region deployment, mandatory Redis, WebSockets, token recovery, invitation preview, player-initiated deletion, point-in-time database recovery, cloud key management. (Sections 10, 11, 12.5, 16)

Future white-label support is an architectural constraint only.

## Review findings

### Resolved by owner decisions

- Repository layout conflict (OD-1). Own-code visibility (OD-2, ND-1). Secret-code and guess protection (OD-6, ND-7, ND-9). Token lifecycle, rotation and rematch handling (OD-7, ND-2 to ND-4). Retention and backups (ND-8). Expired-credential responses (C-7).

### Edge cases the design must cover

- A player solves on the tenth guess (solved, not exhausted).
- Both players finish at the same moment: one transaction computes the result exactly once.
- Retry of the completing guess after the game is `COMPLETED` (R5.9).
- A game expires while a request is in flight: the reference time at the authorisation point decides (R11.3).
- A rotated token used by a request that began before the rotation committed (R8.7, R8.12).
- A rotation whose response is lost (R8.13).
- Two rematch requests at once (R9.4).
- Cleanup deleting a game that has just been refreshed (R11.6).
- A restore resurrecting deleted games or revoked tokens (R21.4, RD-7).
- Replaying an idempotent request after the key ring has been rotated (R10.5).
- Presenting an old rotated token for any operation other than a keyed rotation replay (R8.13).
- Requesting a second rematch after the first rematch game was deleted (R9.4).
- A results request on a game that is not `COMPLETED`: no ciphertext is read (R7.5).
- An application transaction that encrypts and then fails or rolls back (the counter still counts the encryption, R10.10).
- A database restore that rolls the key usage counter back (R10.13).
- Two players presenting rematch capabilities at the same moment (the winner revokes the loser's capability, R9.9).
- The last reserved unit consumed by a rotation whose response is then lost: the replay needs no encryption and must still be answered (R10.10d).
- Restarting an instance while the active key is at the hard stop (R10.6).
- A restore that went back past the registration of a key that is still in the newest ring (R10.13).
- Two requests on one instance racing for the last unit (R10.10h), including while a reservation is in progress (R10.10).
- Retired key material offered again under a new identifier (R10.4).
- A rolling restart in which some instances write with the new key before others have it (R10.14a).
- A live token rotation adding ciphertext to a game between a re-encryption job's count and its lock (R10.10j).
- A restore procedure that, followed literally, would seal the key it has just generated (R10.13).

### Risks (see `security-assessment.md`)

- Code space is only 1296 codes, so guess limits and rate limits carry the security weight.
- Bearer tokens in URLs or logs leak. Credentials are carried only in headers or bodies.
- A hash of a guess is reversible, so request fingerprints are keyed (R5.12).
- Key loss destroys in-progress codes and guesses (R10.9).
- Lost tokens cannot be recovered (R8.9). The rotation replay window narrows but does not remove this for rotation only.
