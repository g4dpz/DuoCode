# Copilot instructions for DuoCode

DuoCode is an API-first, two-player, asynchronous code-breaking game. Backend MVP only: Deno, TypeScript, Oak, PostgreSQL, Docker Compose.

## Read first
- Requirements and decisions: `.kiro/specs/duocode/requirements.md` (revision 3), traceability in `traceability.md`, open items in `revision-3-review-package.md`
- Design overview: `.kiro/specs/duocode/design.md`
- API contract: `openapi/openapi.yaml` (OpenAPI 3.1, the contract)
- Also in `.kiro/specs/duocode/`: `database-schema.md`, `state-machine.md`, `security-assessment.md`, `test-strategy.md`, `simulator-design.md`, `deployment.md`, `tasks.md`

## Status
No implementation is authorised until Phase 1 of `tasks.md` is signed off by both owners. Review specification changes for ambiguity, conflicts between documents, missing edge cases, security weaknesses, concurrency and data-integrity risks. Do not silently decide product or security questions. Record them as decisions in `requirements.md`.

## Rules to enforce in reviews and generated code
- Layout: `backend/`, `tools/` (with `tools/simulator/`), `openapi/`, `docs/`. No `frontend/` yet.
- `backend/src/engine` is pure: no Oak, HTTP, database, crypto or I/O imports. Feedback is tested against an independent reference implementation in `backend/tests/reference/` that shares no code with it.
- The server is authoritative. The acting player always comes from the credential, never from the request.
- Credential validity is decided in one place, the authorisation point (`design.md` section 5.1): writes recheck under the game-row lock, reads use one snapshot. The HTTP layer makes no credential decisions.
- Expiry is `reference time >= expires_at` everywhere, with one database-clock reference time per request. A valid credential of an expired, undeleted game gets `410`. After deletion it gets `401`. No credential records are kept after deletion.
- Three separate credential types: game access token (`dca_`), invitation token (`dci_`), rematch capability (`dcr_`). 256-bit random, stored only as SHA-256 hashes. No token recovery. Rotation and revocation are atomic. Rotation requires an `Idempotency-Key` and has a short, keyed replay window for a lost response (`state-machine.md` section 3.1).
- Secret codes and guesses are encrypted with AES-256-GCM from the same key ring (AAD binds game, player, key id and, for guesses, number and feedback). Keys stay outside the database and backups. Decrypt only in guess submission, progress (own guesses), results after `COMPLETED`, and rotation replay. Never return, log or echo a secret code, guess, nickname or token, including in error messages. Guess request fingerprints are keyed HMACs, never plain hashes.
- Guess submission and rotation need an `Idempotency-Key` UUID, scoped per player and operation. Fingerprints use RFC 8785 canonical JSON. Same key and body returns the stored original response. Same key and different body returns `409 IDEMPOTENCY_CONFLICT`. Rejected requests store nothing.
- Nicknames: trim, reject empty, at most 24 code points, reject control characters, store unchanged, allow duplicates.
- Every state-changing operation runs in one transaction that starts by locking the game row (`SELECT … FOR UPDATE`). Lock order is in `design.md` section 8.2. Attempts never exceed 10. Prefer database constraints for limits and uniqueness.
- Rate limits live in PostgreSQL token buckets shared by all instances, plus coarse per-IP limits at the proxy. No in-memory-only limiters and no mandatory Redis. Never store raw IPs or tokens in `rate_limits`.
- Admin metrics and cleanup are on a separate internal listener. Cleanup is scheduled by the dedicated `cleanup` service. Metrics and logs are privacy-safe: bounded labels, no game ids, player ids, nicknames, IPs or tokens as labels.
- Retention is driven by `games.expires_at`. Cleanup is bounded, repeatable and uses `FOR UPDATE SKIP LOCKED`.
- Parameterised SQL only. Validate all input server-side. `Math.random` is banned outside the simulator.
- The simulator uses only the public REST API and supports deterministic replay by `(seed, gameNumber)`.
- Tests first. Use a real PostgreSQL for integration and concurrency tests.
- Source files carry `SPDX-License-Identifier: AGPL-3.0-only`. Do not copy another game's branding or artwork.
- Do not commit binaries, secrets, `.env` files or key material.
- Do not add features beyond the current task or the specification (no accounts, WebSockets, Redis, multi-tenant code).
