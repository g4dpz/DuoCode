# DuoCode Implementation Tasks (Backend MVP 1), revision 3.1 (final for gate review)

Follows `requirements.md` (R#, decision IDs), `traceability.md` and the specification set listed in `requirements.md`. Test-first throughout. Test group IDs (`TS-xxx`) are defined in `test-strategy.md`.

**No implementation is authorised.** Phases 2 onward start only after every Phase 1 gate (1.1 to 1.6) has been explicitly signed off by the owner and the sign-off recorded here. No application code, database migration or backend CI job may be added before task 1.9 is complete. (Specification-only workflow files added earlier at the owner's request, `.github/workflows/*` and `.github/copilot-instructions.md`, contain no application logic and their backend jobs stay inactive until Phase 2.)

## Phase 1: Specification approval gates (no code)

Specification artefacts are drafted. These tasks are the owner's approvals. To sign off a gate, mark it `[x]` and append the date and approver. A gate is signed off only by an explicit owner statement.

Revision 3.1 review package: `revision-3.1-review-package.md` (change summary from revision 3, verification results, remaining decisions). No gate below is signed off.

- [ ] 1.1 **Gate 1: Owner approval of the revised requirements.** Review `requirements.md` revision 3.1 and `traceability.md`. All technical decisions (OD, ND, C, CL, CR, RD-1 to RD-13, CH-1 to CH-6) are recorded as approved. Confirm the approval status of every requirement R1 to R21. (All requirements)
- [ ] 1.2 **Gate 2: Owner approval of the revised architecture.** Review `design.md` and `deployment.md`: layers, credential model and authorisation point, the preliminary-lookup, rate-limit, encryption-reservation and transaction sequence, lock ordering, the approved rate-limit values, the pinned Caddy build, key ring handling, restore with new-key activation, scheduling, backups, accepted operational risks. (R8, R18, R20, R21)
- [ ] 1.3 **Gate 3: Approval of the OpenAPI specification.** Review `openapi/openapi.yaml` against the requirements: operations, credentials, idempotent rotation with the UUIDv4 key, error codes, status codes, nickname rules, admin server entries, one-rematch-ever behaviour, privacy of codes and the two decrypted-value responses. Redocly lint passes. No handler is written before approval. (R12, R5, R8, R9)
- [ ] 1.4 **Gate 4: Approval of the database schema and state machine.** Review `database-schema.md` and `state-machine.md`: tables, constraints (including encrypted guesses, the previous-guess foreign key, `rematch_markers` and `key_usage`), retention clock, cleanup and rate-limit SQL, expiry rule, read and write order, transition tables, credential lifecycle, idempotent rotation. (R5, R8, R9, R11)
- [ ] 1.5 **Gate 5: Review of the security assessment.** Review `security-assessment.md`: threats T1 to T35, guess encryption assessment, serialisation exceptions (two for game data, one for the rotation replay token), rotation implications, nonce thresholds with the durable reservation counter and the restore rule, IP HMAC privacy, logging and metrics rules, residual risks, and the owner checklist in section 7. Review `test-strategy.md` and `simulator-design.md` for coverage of the same. (R10, R13)
- [ ] 1.6 **Gate 6: Confirmation of the licensing files and contributor arrangements.** The proposed `LICENSE`, `NOTICE` and `CONTRIBUTING.md` exist at the repository root. They contain placeholders for the inputs the owners still have to give: LI-1 exact copyright holder names, LI-2 whether a contributor licence agreement is required, LI-3 legal review of the contribution terms, LI-4 security contact address. Confirm the AGPL-3.0-only text in `LICENSE` (FSF text, checksum in the review package) and the SPDX header form. Confirm that the owners' separate collaboration and IP agreement covers authority to grant commercial licences. Record outstanding legal items. (R19)
- [ ] 1.7 Confirm the README matches the approved layout and statements. (R19.1, OD-1)
- [ ] 1.8 Request an independent GitHub Copilot review of the specification set. Record findings and owner dispositions.
- [ ] 1.9 **Phase 1 sign-off.** Possible only when 1.1 to 1.6 are all signed off. The owner records approval and authorises Phase 2 in writing here.

## Phase 2: Repository scaffold and CI

- [ ] 2.1 Create the directory layout in `design.md`, section 3 (`backend/`, `tools/`, `openapi/`, `docs/`, `deployment/`, `postman/`). No `frontend/` yet. (R19.1)
- [ ] 2.2 Verify that `LICENSE`, `NOTICE`, `CONTRIBUTING.md` and `.gitignore` (including `.env`, `secrets/`, key files) are present exactly as approved at gate 6, and add the SPDX header check. They already exist as proposals. (R19.2)
- [ ] 2.3 Create `backend/deno.json` with tasks `fmt`, `lint`, `check`, `test`, `migrate`, `cleanup`, `reencrypt`, `keys:generate`, `keys:verify`, and the `tools/simulator` task `simulate`. Pin imports and commit `deno.lock`. (R18)
- [ ] 2.4 Typed configuration module with start-up validation of every key in `design.md`, section 13 (non-positive TTLs, replay window and rate limits rejected, secrets never printed, trusted proxies required in production). (R11.1, R18.4)
- [ ] 2.5 Finish and verify GitHub Actions per `test-strategy.md`, section 17: `check`, `test`, `openapi`, `docs`, `simulate`, `audit`, `build`. The workflow skeleton, the OpenAPI and hygiene jobs, `copilot-setup-steps.yml` and `.github/copilot-instructions.md` already exist and must be updated for revision 3 rules. (R17.3)
- [ ] 2.6 Lint and CI rules: engine import boundary (no Oak, HTTP, database, crypto, I/O), SPDX headers, banned `Math.random` outside the simulator, migration immutability, scan that only `services/authorise` reads credentials for decisions. (R14.1, R8.11)
- [ ] 2.7 `TS-DOC` script: traceability completeness and cross-reference check. (R19.5)

## Phase 3: Game engine (no HTTP, no database, no crypto)

- [ ] 3.1 Types, `GameConfig`, constants. (R14)
- [ ] 3.2 Tests then `parseCode`, with errors that never include the input. (R3.2, R4.4, R12.5) (TS-ENG)
- [ ] 3.3 Reference feedback implementation in `backend/tests/reference/`, a different algorithm, no imports from `src/engine`. (R14.3) (TS-REF)
- [ ] 3.4 Feedback tests (all baseline 9.2 cases and known cases), then `computeFeedback`. (R4.2)
- [ ] 3.5 Exhaustive 1296 × 1296 comparison and seeded random comparison with the reference. (R14.3)
- [ ] 3.6 `applyGuess`, `isSolved`, `isExhausted` with boundary tests (solve on guess 10, exhaust on guess 10, no guess 11). (R4.5, R4.8, R4.9)
- [ ] 3.7 `determineOutcome`: every row of R7.2 plus equal-count draw. (R7.2)
- [ ] 3.8 Pure game-state transition function, tested over every cell of `state-machine.md`, section 1.2. (R3.5, R7.1)

## Phase 4: Persistence, cryptography and rate limiting

- [ ] 4.1 Migration runner with advisory lock and `schema_migrations`. Tests: empty database, re-run, concurrent starts. (R18.3) (TS-DB)
- [ ] 4.2 `0001_init.sql` matching `database-schema.md`. A constraint test for every rule in section 3 of that file, including the previous-guess foreign key, nickname checks (including bidi controls), `rematch_markers` (one ever, survives rematch deletion), `key_usage` and cascades. (R5.10, R8, R9.4, R11) (TS-DB)
- [ ] 4.3 PostgreSQL pool and transaction helper: game-lock first, `lock_timeout`, `statement_timeout`, `idle_in_transaction_session_timeout`, single retry on deadlock, serialisation failure or unique-violation backstop. Lock-order instrumentation for TS-CONC-17. (R5.11)
- [ ] 4.4 Credential generation (`dca_`, `dci_`, `dcr_`, 256 bits, independent draws), SHA-256 hashing, constant-time comparison for the admin token. Tests for format, uniqueness and hash-only storage. (R8.1, R8.2) (TS-CRED)
- [ ] 4.5 Key ring loader (status, ids, `generation`, `deactivatedAt` rule, self-test), HKDF key derivation, `SecretCodeVault` (`sealCode`, `sealGuess`, `sealToken`, `use`, `fingerprint`, results method that requires a `CompletedGame` value), AES-256-GCM with AAD as in `security-assessment.md` section 3.4, redacting wrapper, and the strict reservation counter of `database-schema.md` section 6.2: one authoritative row per key, the single atomic conditional reservation statement exactly as specified, `ensureAllowance` before `BEGIN`, `consume` at every invocation that throws on an empty allowance, thresholds warning, rotation overdue and hard stop, fail closed with `503`, the pre-encryption sealed check before every encrypting request, atomic claims of units before the transaction with return of unused units, reservations in whole blocks sized to the operation, deferred refusal so replays and rule rejections are still answered, a start-up self-test that decrypts a known-answer vector and never encrypts, refresh of key usage state from the authoritative row, ring validation that rejects duplicate or previously used key material (permanent fingerprint history in the ring, unique `key_usage.fingerprint`) and non-increasing identifiers, the `STAGED` ring status with a rotation tool that refuses to activate a key until every instance has it staged, recount of data-dependent claims under the game lock, health evaluated by key role, no hot reload of the ring and no allowance carried across a restart, start-up validation of the threshold and block settings. Tests: round trip, tamper, AAD swap, unknown key id, redaction, nonce uniqueness, results gating, the full counter test list in TS-ENC and TS-CONC-20 to TS-CONC-22 against real PostgreSQL, start-up refusal. (R10) (TS-ENC)
- [ ] 4.6 `keys:generate` (records the identifier and fingerprint in the backed-up ring history as `PENDING` first, then registers, reserves, encrypts one self-test value and stages the key; recovers interrupted runs as `ABANDONED`; rejects duplicate key material and a non-increasing identifier; maintains `highestKeyId`), `keys:activate` (refuses a sealed or not `REGISTERED` key), `reencrypt` (one game per transaction, includes guesses, rotation ciphertext and fingerprints) and `keys:verify` (key presence, test decryption, and the invariant rows-under-key not above reserved total) and `keys:seal` (inserts or updates the row to `sealed = true` with the counter at the hard-stop value, so a missing row is sealed too). Tests: rotation, repeatability, concurrency with traffic, kill mid-run, missing key detection, counter rollback detection. (R10.5, R10.11, R10.12, R10.13) (TS-ENC, TS-CONC-14)
- [ ] 4.7 RFC 8785 canonicaliser and fingerprint functions, with RFC test vectors and property tests. (R5.12) (TS-IDEM)
- [ ] 4.8 Rate limiter: atomic token-bucket upsert as separate autocommit statements before the request transaction, subject hashing (HMAC of IP, hash of player id), preliminary credential lookup, trusted-proxy IP extraction, fail-closed behaviour. Tests as TS-RATE. (R20)
- [ ] 4.9 Repositories behind interfaces: games, players, credentials, secret codes, guesses, idempotency keys, token rotations, results, rate limits. Tested against PostgreSQL. (R7.6)

## Phase 5: Services

- [ ] 5.1 `authorise` (the authoritative authorisation point): reference time, lookup, type, revocation, expiry, rotation-replay option. Write path under the game lock, read path as the first statement of a read-only `REPEATABLE READ` transaction. Preliminary lookup as a separate non-authoritative step. Tests for TS-CRED including forced interleavings (TS-CONC-18). (R8.7, R8.8, R8.10 to R8.12)
- [ ] 5.2 Nickname validation shared by create, join and rematch (trim, empty, 24 code points, `Cc`, bidi controls, malformed Unicode, preserve). (R1.3) (TS-VAL)
- [ ] 5.3 `createGame` with tests (state, tokens shown once, hashes stored, `expires_at`). (R1)
- [ ] 5.4 `joinGame`: invitation consumption, full game, bad invitation (same response as unknown or deleted game), expired game `410`, parallel joins. (R2) (TS-CONC-01, TS-CONC-02)
- [ ] 5.5 `submitSecretCode`: encryption, no echo, once only, activation on second code, parallel submissions. (R3, R10)
- [ ] 5.6 `submitGuess` per `design.md`, section 8.3: keyed fingerprint, idempotent replay, conflict, check order from `state-machine.md`, section 1.3, completion in the same transaction. Every case in `test-strategy.md`, section 4. (R4, R5, R7.1) (TS-IDEM, TS-CONC-03 to TS-CONC-05)
- [ ] 5.7 `getStatus` (opponent progress summary only), `getProgress` (decrypts the caller's own guesses), `getResults` (verifies `COMPLETED`, then reads ciphertext, then decrypts). Tests for secrecy, the decrypt spy and zero ciphertext reads before completion. (R6, R7, R3.7, R10.7) (TS-SEC, TS-ENC)
- [ ] 5.8 `rotateAccessToken` with the UUIDv4 key rule, idempotency and replay window that never reactivates the old token, revoking the player's unused capability. Tests for lost response, loss after the window, replay rules and TS-CONC-06 to TS-CONC-08. (R8.6, R8.13, R8.14)
- [ ] 5.9 `mintRematchCapability` and `createRematch` per `state-machine.md`, sections 3 and 4: marker insert in the rematch transaction, revocation of every other unused capability on success (CH-3), `REMATCH_ALREADY_CREATED` on mint after a marker exists even after the rematch game is deleted, deletion behaviour. TS-CRED rematch cases and TS-CONC-09, TS-CONC-10, TS-CONC-19. (R9)
- [ ] 5.10 Expiry evaluation and `expires_at` maintenance per `database-schema.md`, section 5, with the `>=` rule. Tests with an injected clock. (R11.2 to R11.4) (TS-RET)
- [ ] 5.11 Cleanup task per `database-schema.md`, section 7, with dry run, rotation ciphertext clearing and rate-limit pruning. Tests for repeatability, concurrency, re-check and lock timeouts. (R11.5 to R11.8, R11.11) (TS-RET, TS-CONC-10 to TS-CONC-13)

## Phase 6: HTTP API

- [ ] 6.1 Oak apps (public and admin listeners): request id, structured logging with allow-listed fields, no bodies and no IPs, body size limit, central error mapper with fixed messages. (R12.2, R12.5, R13.2, R13.9)
- [ ] 6.2 Validation layer for bodies, path parameters and headers, rejecting unknown and duplicate properties. (R12.4)
- [ ] 6.3 Token extraction and IP rate limit middleware (no credential decisions). Admin middleware on the admin listener. (R8.11, R13.5, R20)
- [ ] 6.4 Routes for every operation in `openapi/openapi.yaml`. (R1 to R9)
- [ ] 6.5 `/healthz`, `/admin/metrics` (privacy-safe labels), `/admin/cleanup`. (R12.7, R13.8, R18.5, R21.1)
- [ ] 6.6 Contract tests against the OpenAPI document and the operation coverage script. (R12.6) (TS-CONTRACT)
- [ ] 6.7 Logging and metrics canary tests, error snapshot tests. (R13.2, R3.6) (TS-SEC)

## Phase 7: API tests and client tooling

- [ ] 7.1 Typed API client in `tools/api-client`.
- [ ] 7.2 Full-lifecycle integration test with two independent tokens, covering every row of the outcome table. (R17.1) (TS-API)
- [ ] 7.3 Negative test suite for baseline 9.4 and the table-driven state-machine tests. (R17.1) (TS-STATE)
- [ ] 7.4 Security tests: secrecy, type confusion, enumeration uniformity, token hash-only storage, lost-token limitation checks, plaintext-at-rest scans. (R13, R8) (TS-SEC)
- [ ] 7.5 Concurrency suite TS-CONC-01 to TS-CONC-17, with barriers to force interleavings. (R17.2)
- [ ] 7.6 Postman collection and example environments with variables only, including rotation with retry. (R16.1)
- [ ] 7.7 `docs/API.md` with a curl walk-through (run as a script in CI), the lost-token limitation, the credential model and safe retry rules for guesses and rotation. (R16.2, R16.3)

## Phase 8: Simulator (`tools/simulator`)

- [ ] 8.1 CLI skeleton, options, seeded generator per `(seed, gameNumber)`. (R15.1)
- [ ] 8.2 Random strategy. (R15.1)
- [ ] 8.3 Systematic strategy, independently written. (R15.1)
- [ ] 8.4 Logic-based strategy, independently written. (R15.1)
- [ ] 8.5 Game runner and all checks in `simulator-design.md`, section 6, including idempotent guess retries, deterministic rotation keys (`--test-deployment` required), rotation with lost responses, nickname display-safety checks and `429` backoff. (R15.2, R15.5)
- [ ] 8.6 Concurrency, metrics, JSON and text reports. (R15.4)
- [ ] 8.7 Failure recording and `--replay seed:gameNumber`, with a test proving identical decisions on replay. (R15.3)
- [ ] 8.8 Exit codes, CI `simulate` job. (R17.3)

## Phase 9: Deployment

- [ ] 9.1 Dockerfile (non-root, read-only root, minimal Deno permissions). (R18.1)
- [ ] 9.2a `keymgmt` and `keyverify` jobs per `deployment.md` 2.1. `keymgmt`: own database role, writable ring directory, backup-store secret, ring single-writer lock, version-checked write and publication, online and offline activation, no key material in output. `keyverify`: read-only database role and read-only ring only, no writable ring, no backup store, no publication (CR-17). Presence locks, the admission check against `ring_state` and reports in `app`, `cleanup` and `reencrypt`. Bounded lock waits for `keymgmt`, shared try-lock and hard deadline for `keyverify`. Retries in the transaction helper as fresh attempts with new claims (CR-18). `keys:reconcile-gate` for restores, and `ring_state` rights for each role (CR-19). (R10.4, R10.14, CR-15, CR-16, CR-17)
- [ ] 9.2 `deployment/docker-compose.yml` with `proxy`, `app` (public and admin listeners), `db`, `migrate`, `cleanup`, `backup`, secrets for the key ring and the rate-limit key, networks per `deployment.md` section 1. (R18.2, R21.1, R21.2)
- [ ] 9.3 Caddy custom build per `deployment.md` section 4.3: re-verify and record pins in `BUILD-PINS.md`, commit `go.mod`, `go.sum`, `main.go`, `Dockerfile`, build twice in CI and compare digests, attest provenance, generate an SBOM, run `govulncheck`, reference the image by digest in Compose, write `BUILD-RECORD.md`, document maintenance and the Nginx fallback. Configuration with the approved limits and `/admin/*` returning `404`. (R18.6, R20.1) (TS-OPS)
- [ ] 9.4 `.env.example`, `secrets.example/`, configuration and operations docs including key generation, ring backup, rotation, retirement, compromise and recovery procedures. (R10.9, R18.4, R21.5)
- [ ] 9.5 Backup job and the restore and key-recovery drills in `deployment.md` section 6, including new-key activation (R10.13) and the demonstration that restored counters are behind, with the key ring supplied separately. (R11.9, R21.4) (TS-OPS)
- [ ] 9.6 Key rotation drill per `deployment.md` 6.4 (three phases: stage, activate, seal), run once with a key below 2^27 and once with a key past 2^28, with traffic running: stage the key on every instance, activate it by a rolling restart with zero decrypt failures, check the ring generation, `keys:seal` the previous key only, show that a transaction reaching its commit-time check after the seal rolls back, show a reservation under it is refused and that a request on an instance still holding an allowance fails the pre-encryption check, unused units stay counted, health shows `sealed` with no alert, `reencrypt`, `keys:verify`, no failed requests. (R10.5, R10.12, R10.13, R10.14)
- [ ] 9.7 Deploy to the development Linux environment and meet the acceptance list in `deployment.md`, section 11.

## Phase 10: Load, security review and MVP acceptance

- [ ] 10.1 Load runs at increasing concurrency with two or more `app` instances, including cleanup and `reencrypt` during load. Record p95 against the 500 ms target and resource use. (R17.4) (TS-LOAD)
- [ ] 10.2 Re-review `security-assessment.md` against the implementation. Fix gaps. Record disposition of each residual risk.
- [ ] 10.3 Demonstrate a complete game, a rotation with a lost response, a rematch, a cleanup and a restore drill through two independent curl or Postman sessions. (Baseline 8.2)
- [ ] 10.4 Walk through baseline 17.1 Definition of Done and attach evidence. Update `traceability.md` status to implemented and tested.
- [ ] 10.5 Request an independent Copilot review of the final implementation. Owners approve MVP acceptance.
- [ ] 10.6 **Before production deployment:** reassess the absence of point-in-time recovery (RD-7, `deployment.md` section 12) and record the owner's decision to accept it again or to add WAL archiving. Reassess the other accepted operational risks in the same section.

## Deferred (separate specs when started)

Web application and PWA, white-label and multi-tenant work, native clients, invitation preview (C-2), player-initiated deletion, point-in-time database recovery (RD-7), cloud key management (ND-9 alternative), trademark clearance, dual-licensing terms and contributor agreement text beyond 1.6.
