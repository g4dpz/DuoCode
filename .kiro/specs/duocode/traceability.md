# DuoCode Requirements Traceability Matrix (revision 3)

Owns: the mapping from every requirement to its owning artefact, API operation, database constraint, acceptance test and approval status. Related: `requirements.md` (the requirements and decision IDs), `test-strategy.md` (test group IDs `TS-xxx`), `database-schema.md`, `../../../openapi/openapi.yaml`, `tasks.md` (approval gates).

A script check (`TS-DOC`) verifies that every requirement R1 to R21 appears here, and that every artefact and test group named here exists. Update this file in the same change as any requirement, operation, constraint or test change.

## 1. Approval status legend

Nothing below is signed off. Gate sign-off is recorded in `tasks.md` Phase 1 and nowhere else.

| Code | Meaning |
|---|---|
| **A** | The owner approved the decision behind this requirement in the revision 3 review. The requirement text awaits gate sign-off |
| **A+RD** | As A, but the requirement also contains proposals listed as RD-n in `requirements.md`, pending owner decision |
| **B** | Derived from the baseline requirements without a separate decision. Awaits gate sign-off |

Gates: 1.1 requirements, 1.2 architecture, 1.3 OpenAPI, 1.4 database schema and state machine, 1.5 security assessment, 1.6 licensing and contributor arrangements. Current state of every gate: **not signed off**.

## 2. Matrix

| Req | Title | Owning artefacts | API operation(s) | Database constraint or mechanism | Acceptance tests | Gates | Status |
|---|---|---|---|---|---|---|---|
| R1 | Game creation, nickname rules | `requirements.md`, `openapi.yaml`, `database-schema.md` | `createGame` | `players.nickname` length and control-character `CHECK`; `credentials.token_hash` unique | TS-VAL, TS-API, TS-CRED, TS-DB | 1.1, 1.3, 1.4 | A+RD (RD-5) |
| R2 | Joining | `requirements.md`, `openapi.yaml`, `state-machine.md` | `joinGame` | `UNIQUE (game_id, seat)`, `seat IN (1,2)`, one-invitation-per-game partial index | TS-CRED, TS-STATE, TS-CONC-01, TS-CONC-02, TS-DB | 1.1, 1.3, 1.4 | A |
| R3 | Secret code submission and privacy | `requirements.md`, `openapi.yaml`, `security-assessment.md` | `submitSecretCode`, `getResults` | `secret_codes` primary key on `player_id` | TS-STATE, TS-SEC, TS-ENC, TS-DB | 1.1, 1.3, 1.5 | A |
| R4 | Guessing and feedback | `requirements.md`, `design.md`, `state-machine.md` | `submitGuess` | `guesses` range, `UNIQUE (player_id, guess_number)`, previous-guess foreign key | TS-ENG, TS-REF, TS-STATE, TS-IDEM, TS-DB | 1.1, 1.3, 1.4 | A |
| R5 | Idempotency and concurrency | `requirements.md`, `design.md` (section 8, 10), `state-machine.md`, `openapi.yaml` | `submitGuess`, `rotateAccessToken` | `idempotency_keys` primary key and `UNIQUE (guess_id)`, `token_rotations` unique keys, guess constraints | TS-IDEM, TS-CONC-03, TS-CONC-04, TS-CONC-05, TS-CONC-07, TS-CONC-08, TS-DB | 1.1, 1.2, 1.3, 1.4, 1.5 | A+RD (RD-8) |
| R6 | Status and progress | `requirements.md`, `openapi.yaml` | `getGameStatus`, `getProgress` | None (read snapshot, section 1.4 of `state-machine.md`) | TS-API, TS-SEC, TS-CRED, TS-CONC-16 | 1.1, 1.3 | A |
| R7 | Completion and results | `requirements.md`, `state-machine.md`, `openapi.yaml` | `getResults`, `submitGuess` (completing guess) | `game_results` primary key, `games` completion `CHECK` | TS-ENG, TS-STATE, TS-SEC, TS-CONC-05, TS-CONC-16, TS-DB | 1.1, 1.3, 1.4 | A |
| R8 | Credentials, rotation, authorisation point | `requirements.md`, `design.md` (section 5), `state-machine.md` (section 3), `security-assessment.md` (section 2), `openapi.yaml` | `rotateAccessToken`, all authenticated operations | `credentials` type, partial unique indexes, composite foreign key to player and game, `token_rotations` | TS-CRED, TS-CONC-06, TS-CONC-07, TS-CONC-08, TS-SEC, TS-DB | 1.1, 1.2, 1.3, 1.4, 1.5 | A+RD (RD-3) |
| R9 | Rematch | `requirements.md`, `state-machine.md` (sections 3, 4), `openapi.yaml` | `mintRematchCapability`, `createRematch` | `games.rematch_of` `UNIQUE` and `ON DELETE SET NULL`, one-live-capability partial index | TS-CRED, TS-CONC-09, TS-CONC-10, TS-CONC-13, TS-DB | 1.1, 1.3, 1.4 | A+RD (RD-6) |
| R10 | Encryption and key management | `requirements.md`, `security-assessment.md` (section 3), `design.md` (section 9), `deployment.md` (sections 5, 6) | none (internal), `getHealth` (key ring readiness) | `key_id` columns, fixed-length ciphertext `CHECK`s on `secret_codes`, `guesses`, `token_rotations` | TS-ENC, TS-CONC-14, TS-OPS, TS-SEC | 1.1, 1.2, 1.4, 1.5 | A+RD (RD-8, RD-10) |
| R11 | Expiry, retention, cleanup | `requirements.md`, `state-machine.md` (section 1.1), `database-schema.md` (sections 5, 7), `deployment.md` (section 7) | `runCleanup`, all operations (`GAME_EXPIRED`) | `games.expires_at` and index, cascade deletes, `SKIP LOCKED` cleanup statement | TS-RET, TS-CRED, TS-CONC-10 to TS-CONC-13, TS-OPS | 1.1, 1.4, 1.5 | A |
| R12 | API conventions and errors | `requirements.md`, `openapi.yaml` | All operations | None | TS-CONTRACT, TS-API, TS-VAL | 1.1, 1.3 | A |
| R13 | Security, privacy, logging, metrics | `requirements.md`, `security-assessment.md` (sections 4, 6), `design.md` (section 14) | `getMetrics`, `getHealth` | `rate_limits` stores HMACs only, no IP or token columns anywhere | TS-SEC, TS-RATE, TS-OPS | 1.1, 1.5 | A+RD (RD-9) |
| R14 | Engine independence and verifiability | `requirements.md`, `design.md` (section 4) | None | None | TS-ENG, TS-REF, CI import-boundary check | 1.1, 1.2 | B |
| R15 | Simulator | `requirements.md`, `simulator-design.md` | Public API only | None | TS-SIM | 1.1, 1.5 | B (extended by CL-6, ND-4) |
| R16 | Documentation and client tooling | `requirements.md`, `design.md` (section 3) | None | None | TS-DOC | 1.1 | B |
| R17 | Testing and CI | `requirements.md`, `test-strategy.md` | None | None | TS-DOC, CI job definitions (`test-strategy.md` section 17) | 1.1, 1.5 | A (CL-8) |
| R18 | Deployment and operability | `requirements.md`, `deployment.md`, `design.md` (section 13) | `getHealth` | Shared state in PostgreSQL, `rate_limits` | TS-OPS, TS-RATE, TS-LOAD | 1.1, 1.2 | B |
| R19 | Licensing, layout, specification set | `requirements.md`, `design.md` (section 3), `traceability.md`, README | None | None | TS-DOC | 1.1, 1.2, 1.6 | A (OD-1, OD-8). Licensing text pending gate 1.6 |
| R20 | Rate limiting | `requirements.md`, `design.md` (section 11), `database-schema.md` (section 6), `deployment.md` (section 4) | All operations (`RATE_LIMITED`, `SERVICE_UNAVAILABLE`) | `rate_limits` primary key and atomic upsert | TS-RATE, TS-CONC-15, TS-SEC | 1.1, 1.2, 1.4, 1.5 | A+RD (C-6 in principle, RD-1, RD-2, RD-9) |
| R21 | Administration, scheduling, backup, restore | `requirements.md`, `deployment.md` (sections 1, 5, 6, 7), `security-assessment.md` (section 3.6) | `getMetrics`, `runCleanup` (admin server entry) | None | TS-OPS, TS-ENC, TS-RET | 1.1, 1.2, 1.5 | A+RD (RD-4, RD-7) |

## 3. Criterion-level traceability for the highest-risk requirements

### R5 idempotency

| Criterion | Mechanism | Test |
|---|---|---|
| R5.1 key format | `INVALID_IDEMPOTENCY_KEY` validation | TS-IDEM |
| R5.2 scope (player, operation, key) | Primary key on `idempotency_keys`, `UNIQUE (player_id, idempotency_key)` on `token_rotations` | TS-IDEM, TS-DB |
| R5.3, R5.4 duplicate recognition and replay | Lookup under game lock, stored response | TS-IDEM, TS-CONC-03 |
| R5.5 conflict | Fingerprint mismatch gives `409` | TS-IDEM |
| R5.6 store only on success | Insert in the guess transaction | TS-IDEM |
| R5.7 retention until game deletion | Cascade delete only | TS-IDEM, TS-RET |
| R5.8, R5.9 original response, replay before state checks | Stored `response_body`, check order | TS-IDEM, TS-STATE |
| R5.10 no double attempts, contiguity | Constraints in `database-schema.md` section 3 | TS-DB, TS-CONC-04, TS-CONC-05 |
| R5.11 atomic | One transaction | TS-CONC-05 |
| R5.12 RFC 8785 and keyed fingerprint | `design.md` section 10 | TS-IDEM |

### R8 credentials

| Criterion | Mechanism | Test |
|---|---|---|
| R8.1, R8.3 types and binding | `credentials.type`, composite foreign key | TS-CRED, TS-DB |
| R8.2 256-bit, SHA-256 | Token generation and `token_hash` | TS-CRED |
| R8.4 invitation single use | Consumption in join transaction | TS-CRED, TS-CONC-01 |
| R8.5 rematch capability scope | Operation allow-list | TS-CRED |
| R8.6 atomic rotation | One transaction under game lock | TS-CRED, TS-CONC-06, TS-CONC-07 |
| R8.7 recheck under lock | `authorise` after lock | TS-CRED |
| R8.8 uniform responses, C-7 | `database-schema.md` section 4 | TS-CRED, TS-RET |
| R8.9 no recovery | OpenAPI inventory check | TS-CRED, TS-DOC |
| R8.10 expiry invalidates | `>=` rule | TS-RET |
| R8.11 authorisation point | Code scan | TS-CRED |
| R8.12 read consistency | Snapshot transaction | TS-CRED, TS-CONC-16 |
| R8.13 idempotent rotation | `token_rotations`, `state-machine.md` section 3.1 | TS-CRED, TS-CONC-08, TS-SIM |
| R8.14 results after rotation | Binding to player, not token | TS-CRED |

### R10, R11

| Criterion | Mechanism | Test |
|---|---|---|
| R10.1, R10.2 AES-256-GCM, AAD | `security-assessment.md` sections 3.2 to 3.4 | TS-ENC |
| R10.3 keys outside DB and backups | Deployment secrets | TS-ENC, TS-OPS |
| R10.4 key ring and identifiers | Ring format | TS-ENC |
| R10.5 transactional re-encryption | `security-assessment.md` section 3.8 | TS-ENC, TS-CONC-14 |
| R10.7 decrypt paths | Vault spy | TS-ENC |
| R10.10 nonce metric | Counter and alert | TS-ENC |
| R10.11, R10.12 retirement and verify | `keys:verify` | TS-ENC, TS-OPS |
| R11.2 clock rules | `database-schema.md` section 5 | TS-RET |
| R11.3 `>=` rule | Reference time | TS-RET, TS-CONC-10 |
| R11.5, R11.6 deletion and safe repeat | Cleanup statement | TS-RET, TS-CONC-11, TS-CONC-12 |
| R11.9 backups and restore | `deployment.md` section 6 | TS-OPS |

## 4. Decision to requirement map

| Decision | Requirements | Artefacts |
|---|---|---|
| OD-1 | R19.1 | `design.md` section 3, README |
| OD-2 | R3.6, R3.7, R13.2 | `security-assessment.md` section 4 |
| OD-3 | R6.3 | `openapi.yaml` `OpponentProgress` |
| OD-4 | R5 | `openapi.yaml` `submitGuess` |
| OD-5 | R11.1, R11.2 | `database-schema.md` section 5 |
| OD-6 | R10 | `security-assessment.md` section 3 |
| OD-7 | R8, R9 | `design.md` section 5, `state-machine.md` section 3 |
| OD-8 | R12.6, R19.5 | this file |
| ND-1 | R3.7, R7.4 | `openapi.yaml` `getResults` |
| ND-2, ND-3 | R9 | `state-machine.md` section 4 |
| ND-4 | R8.6, R8.13 | `state-machine.md` section 3.1, `security-assessment.md` section 2.2 |
| ND-5 | R11.2 | `database-schema.md` section 5 |
| ND-6 | R8.2 | `design.md` section 5 |
| ND-7 | R4.1, R10.1, R5.12 | `security-assessment.md` section 3.1 |
| ND-8 | R11.9, R11.10, R21.2, R21.3 | `deployment.md` sections 5 to 7 |
| ND-9 | R10.3, R10.4, R10.11, R21.5 | `security-assessment.md` section 3.6 |
| C-1 | R8 | `openapi.yaml` security schemes |
| C-2 | Out of scope | `requirements.md` |
| C-3 | R1.3 | `test-strategy.md` TS-VAL |
| C-4 | R21.1 | `openapi.yaml` admin server entries |
| C-5 | R8 | none (absence of a refresh operation) |
| C-6 | R20 | `deployment.md` section 4 |
| C-7 | R8.8, R2.4, R11.3 | `database-schema.md` section 4 |
| CL-1 | R8.7, R8.11, R8.12 | `design.md` section 5.1 |
| CL-2 | R11.3 | `state-machine.md` section 1.1 |
| CL-3 | R10.2, R10.4, R10.10, R10.11 | `security-assessment.md` sections 3.3 to 3.9 |
| CL-4 | R20 | `design.md` section 11 |
| CL-5 | R1.3 | `database-schema.md` players constraints |
| CL-6 | R5.12 | `design.md` section 10 |
| CL-7 | R5.10, R9.4 | `database-schema.md` section 3 |
| CL-8 | R17.2 | `design.md` section 8, `test-strategy.md` TS-CONC |
