# DuoCode Revision 3 Review Package

Prepared for the owner. Implementation is **not authorised**. This package contains no application code, no database migrations and no implementation tasks. Nothing here is signed off.

## 1. Gate status

| Gate | Task | Subject | Status |
|---|---|---|---|
| 1 | 1.1 | Requirements | Not signed off |
| 2 | 1.2 | Architecture | Not signed off |
| 3 | 1.3 | OpenAPI specification | Not signed off |
| 4 | 1.4 | Database schema and state machine | Not signed off |
| 5 | 1.5 | Security assessment | Not signed off |
| 6 | 1.6 | Licensing files and contributor arrangements | Not signed off |
| Sign-off | 1.9 | Phase 1 complete, Phase 2 authorised | Not authorised |

## 2. What to read for each gate

| Gate | Read |
|---|---|
| 1 Requirements | `requirements.md` (decision register, R1 to R21), `traceability.md` |
| 2 Architecture | `design.md`, `deployment.md` |
| 3 OpenAPI | `openapi/openapi.yaml` |
| 4 Schema and state machine | `database-schema.md`, `state-machine.md` |
| 5 Security | `security-assessment.md` (especially sections 2.2, 3.1, 3.6 to 3.9, 7), `test-strategy.md`, `simulator-design.md` |
| 6 Licensing | Nothing new in this revision. Task 1.6 in `tasks.md` lists what to confirm |

All files are in `.kiro/specs/duocode/` except `openapi/openapi.yaml` and `README.md`.

## 3. Summary of changes from revision 2

### 3.1 Decisions applied

| Your decision | What changed |
|---|---|
| ND-1 approved | Recorded as approved. No design change |
| ND-2, ND-3 approved | Recorded as approved. Rematch deletion and foreign-key behaviour clarified (R9.8, `database-schema.md`) |
| ND-4 amended: idempotent rotation | Rotation now requires an `Idempotency-Key`. For a 10-minute window the revoked old token plus the same key returns the same new token. New `token_rotations` table, new state-machine section 3.1, new security analysis in `security-assessment.md` section 2.2, new OpenAPI behaviour and tests |
| ND-5, ND-6 approved | Recorded. ND-6 wording clarified: each token is an independent draw |
| ND-7 amended: encrypt guesses | Guesses stored as AES-256-GCM ciphertext under the same key ring. Feedback counts, guess numbers and solved flags stay plaintext. Impact assessed in `security-assessment.md` section 3.1. Fingerprints for guess requests are now keyed HMACs (see 4.1) |
| ND-8 approved | Retention, hourly cleanup, 35-day backups, no player deletion endpoint. Cleanup scheduling and restore specified |
| ND-9 approved with amendment | Key ring format with statuses. Old keys stay until no backup can need them (R10.11). Generation, backup, recovery, rotation, retirement and compromise procedures added |
| C-1 to C-5 approved | Recorded. C-2 (no invitation preview) was already applied |
| C-6 in principle | Recommended numeric values in `deployment.md` section 4.2 for your approval |
| C-7 with clarification | `410` for valid credentials of expired, not yet deleted games. `401` after deletion. No credential records kept for the `410` (R8.8, `database-schema.md` section 4) |

### 3.2 Engineering clarifications applied

| Clarification | Where |
|---|---|
| Authorisation point, revocation checks, reads | `design.md` section 5.1. Writes recheck under the game lock. Reads run in one `REPEATABLE READ` read-only snapshot (R8.11, R8.12, `state-machine.md` section 1.4) |
| Expiry `currentTime >= expiresAt` | One rule, one reference time per request, applied in authorisation, operations and cleanup (R11.3, `state-machine.md` section 1.1) |
| Encryption documentation | Key identifiers, nonce uniqueness and budget, AAD layout, transactional re-encryption, backup recovery, key retirement: `security-assessment.md` section 3 |
| Shared rate limiting | PostgreSQL token buckets plus coarse Caddy limits, no Redis (R20, `design.md` section 11, `database-schema.md` section 6) |
| Nickname validation | Seven rules in R1.3, DB backstop constraints, tests in TS-VAL |
| Canonicalisation | RFC 8785 JCS envelope, keyed HMAC for guesses (R5.12, `design.md` section 10) |
| Database integrity | Constraint catalogue in `database-schema.md` section 3, including contiguity and "no guess after solved" through a self-referencing foreign key |
| Lock ordering | `design.md` section 8.2 (levels L0 to L3, rules, foreign-key side effect). Races tabulated in `state-machine.md` section 6. Scenarios TS-CONC-01 to TS-CONC-17 |

### 3.3 Additional requirements you asked to clarify

| Topic | Answer |
|---|---|
| Results after token rotation | Readable with the current token only. A revoked token cannot read results. Rotation changes who may read, not what is stored (R8.14) |
| Rematch foreign key and deletion | `rematch_of` is a unique foreign key with `ON DELETE SET NULL`. Deleting the original clears the link and the rematch continues. Deleting the rematch lets the original have another one (R9.8, RD-6) |
| Admin cleanup and metrics interfaces | Two operations on a separate internal admin listener, not routed by the proxy, admin token required (R21.1, RD-4) |
| Cleanup scheduling | A dedicated `cleanup` Compose service runs the task hourly. Application instances never schedule it. The admin endpoint is for manual and dry runs (R21.2) |
| Restore and key recovery | `deployment.md` sections 6.1 and 6.2 (restore steps, `keys:verify`, cleanup before traffic, consequences). Key retirement in `security-assessment.md` section 3.9 |
| Privacy-safe metrics and logging | Allow-listed log fields, no client IPs, no nicknames, bounded metric labels (R13.8, R13.9, `security-assessment.md` section 4) |

### 3.4 New artefacts

- `traceability.md`: matrix of R1 to R21 to artefact, API operation, database constraint, acceptance test group and approval status, plus criterion-level maps for R5, R8, R10 and R11 and a decision-to-requirement map.
- `revision-3-review-package.md`: this file.
- Requirements R20 (rate limiting) and R21 (administration, scheduling, backup and restore) are new. R1 to R19 keep their numbers.

### 3.5 Other files changed

`README.md` (statements on guess encryption and rate limiting added, sentences kept otherwise), `openapi/openapi.yaml` (version 1.0.0-draft.3), `.github/copilot-instructions.md` (rules updated to revision 3), `tasks.md`, `test-strategy.md`, `simulator-design.md`, `deployment.md`, `design.md`, `database-schema.md`, `state-machine.md`, `security-assessment.md`.

## 4. Findings from the assessments you asked for

### 4.1 Encrypting guesses (ND-7)

- The objective is met: with database-only access, the reader sees feedback counts, guess numbers, solved flags, timing and ciphertext. Feedback counts without the guesses do not identify the code.
- **A trap this exposed:** request fingerprints for idempotency were plain hashes of the request body. One of 1296 possible guesses can be recovered from its hash instantly, which would have defeated ND-7. Guess fingerprints are now HMAC-SHA-256 keyed from the key ring and are re-keyed during re-encryption (RD-8).
- Decryption is now also needed for progress (the caller's own guesses) and results. Cost is negligible (a few `crypto.subtle` calls on 4-byte values) and will be measured in load tests.
- Database constraints still enforce guess limits and contiguity because guess numbers and solved flags stay plaintext. Symbol validity cannot be a database constraint any more. It stays in the application.
- Feedback counts and guess number are part of the authenticated data, so tampering with them in the database is detected on decrypt.
- Key loss now also destroys guesses, not just codes.

### 4.2 Rotation idempotency (ND-4)

- Recommended design: replay for 10 minutes with the old token plus the same key, stored as encrypted ciphertext. Full implication table in `security-assessment.md` section 2.2.
- Weaknesses that remain, stated plainly: the first rotator wins if a token has been stolen, and a lost response after the window still loses the seat. Both are limits of bearer tokens without accounts.
- Rotation also revokes the player's unused rematch capability (RD-3), because a thief who had a token could have minted one.

### 4.3 Things discovered that you did not ask about

- Stock Caddy has no rate-limit module (RD-1).
- Restoring a database backup revives deleted games and old tokens and drops recent rotations. The procedure and its consequences are documented, and cleanup runs before traffic (RD-7).
- Deleting an original game updates its rematch row through the foreign key, which can wait on a lock. This is bounded by a lock timeout and cannot deadlock (`design.md` section 8.2).
- An unjoined rematch is deleted after 7 days, which frees the original for another rematch (RD-6).

## 5. Remaining decisions requiring your approval

| ID | Decision | Proposal | Needed for gate |
|---|---|---|---|
| RD-1 | How to get per-IP rate limiting at the proxy | Custom Caddy build with the `caddy-ratelimit` module. Fallback Nginx `limit_req` | 2 |
| RD-2 | Numerical rate limits (`deployment.md` 4.2), fail closed with `503` if the limiter store is down, throttle bucket replaces the earlier 5-minute block | As written in `deployment.md` section 4.2 | 1, 2 |
| RD-3 | Rotation replay window (10 minutes) and rotation revoking the player's unused rematch capability | Yes to both | 1, 5 |
| RD-4 | Admin interfaces on a separate internal listener not routed by the proxy | Yes | 2 |
| RD-5 | Nickname character scope: reject category `Cc` and malformed Unicode only. Format characters such as bidirectional overrides are allowed | As proposed, unless you want category `Cf` rejected too | 1 |
| RD-6 | Deleted rematch frees the original for a new rematch | Yes | 1, 4 |
| RD-7 | No point-in-time recovery in MVP 1. Restores revert credential state | Accept, document, revisit before production | 2, 5 |
| RD-8 | Keyed HMAC fingerprints for guess requests, re-keyed on key rotation | Yes (required by ND-7) | 4, 5 |
| RD-9 | Client IP from the proxy header only from trusted addresses. Store an HMAC of the IP with a separate secret, never the IP | Yes | 2, 5 |
| RD-10 | Nonce safety: random 96-bit nonces, alert and rotate at 2^28 encryptions per key | Yes | 5 |

Also needs your confirmation, as written in the drafts:
- Proxy access log retention of 14 days with no client IP by default (`deployment.md` section 4.1).
- Backup encryption to both owners with `age` or GPG, stored off the VPS (`deployment.md` section 5).
- Privacy notice wording and UK GDPR items (`security-assessment.md` section 6). Tasks, not decided here.

## 6. Verification performed during preparation

| Check | Result |
|---|---|
| OpenAPI 3.1 lint (Redocly) | Valid, 6 style warnings (localhost server URL, a few missing 4xx responses). No errors |
| DDL in `database-schema.md` applied to a scratch PostgreSQL 15 database | Applied without error. The scratch cluster was deleted. No migration file was created |
| Constraint behaviour tested in the scratch database | Third seat rejected, nickname over 24 code points and control characters rejected, guess without predecessor rejected, guess after a solving guess rejected, duplicate guess number rejected, second rematch rejected, credential for a player of another game rejected, second live access token rejected, deleting an original cleared the rematch link and removed players |
| Rate-limit upsert and cleanup statements run in the scratch database | Bucket allowed three requests, denied the fourth, allowed again after refill. Cleanup deleted only expired games and pruned idle rows |
| Cross-reference script over the specification set | Run as described in section 7 |

Not verified (cannot be before implementation): behaviour under concurrency in the real application, Web Crypto details (HKDF, AES-GCM with the AAD layout), Caddy rate-limit module configuration, RFC 8785 library choice, PostgreSQL behaviour on versions other than 15 (the CI uses 16).

## 7. Consistency checks

Run at the time of preparation:
- Every requirement R1 to R21 is present in `traceability.md`.
- Every `TS-xxx` group named in `traceability.md` and `tasks.md` is defined in `test-strategy.md`.
- Every `TS-CONC-nn` named exists in section 12 of `test-strategy.md`.
- Every `deployment.md`, `design.md` and `security-assessment.md` section number cited from another file exists.
- Every decision ID cited in the specification set exists in the decision register.
- No stale revision 2 identifiers (`Q1` to `Q13`) remain.

The results are in the response that delivered this package. The `TS-DOC` task (2.7) turns these checks into a CI job.

## 8. Risks to keep in view

1. Plaintext feedback counts, nicknames and state flags are readable by a database reader. Accepted under ND-7.
2. Key loss is unrecoverable by design. Two people must hold the ring backup (R10.9).
3. First rotator wins, and a lost response after the replay window loses the seat.
4. A restore reverts credentials and revives deleted data until cleanup.
5. The spec set is large. `traceability.md` and the `TS-DOC` check exist to keep it consistent. They only work if updated in the same change as any edit.
