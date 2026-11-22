# Copilot instructions for DuoCode

DuoCode is an API-first, two-player, asynchronous code-breaking game. Backend MVP only: Deno, TypeScript, Oak, PostgreSQL, Docker Compose.

## Read first
- Requirements and decisions: `.kiro/specs/duocode/requirements.md` (revision 3.1, final for gate review), traceability in `traceability.md`, open items in `revision-3.1-review-package.md`
- Design overview: `.kiro/specs/duocode/design.md`
- API contract: `openapi/openapi.yaml` (OpenAPI 3.1, the contract)
- Also in `.kiro/specs/duocode/`: `database-schema.md`, `state-machine.md`, `security-assessment.md`, `test-strategy.md`, `simulator-design.md`, `deployment.md`, `tasks.md`

## Status
Phase 1 is signed off and Phase 2 is authorised (`tasks.md` 1.9, 2026-11-22). Implementation follows the phases in `tasks.md` in order. Each gate needs an explicit statement from one owner, and one owner is enough (RD-15, `requirements.md`). Review specification changes for ambiguity, conflicts between documents, missing edge cases, security weaknesses, concurrency and data-integrity risks. Do not silently decide product or security questions. Record them as decisions in `requirements.md`.

## Rules to enforce in reviews and generated code
- Layout: `backend/`, `tools/` (with `tools/simulator/`), `openapi/`, `docs/`. No `frontend/` yet.
- `backend/src/engine` is pure: no Oak, HTTP, database, crypto or I/O imports. Feedback is tested against an independent reference implementation in `backend/tests/reference/` that shares no code with it.
- The server is authoritative. The acting player always comes from the credential, never from the request.
- Credential errors: access and rematch credentials fail with `401 INVALID_CREDENTIALS`. Join is the exception: a consumed invitation gets `409 GAME_FULL`, and an unknown invitation or deleted game gets `404 INVALID_INVITATION`, with identical bodies (T11).
- Credential validity is decided in one place, the authorisation point (`design.md` section 5.1). Order for every authenticated request: validate, non-authoritative preliminary lookup (grants nothing), rate-limit updates in separate autocommit statements, then the transaction with the authoritative check (writes: after the game-row lock. reads: first statement of a read-only `REPEATABLE READ` transaction). The HTTP layer makes no credential decisions.
- Expiry is `reference time >= expires_at` everywhere, with one database-clock reference time per request. A valid credential of an expired, undeleted game gets `410`. After deletion it gets `401`. No credential records are kept after deletion.
- Three separate credential types: game access token (`dca_`), invitation token (`dci_`), rematch capability (`dcr_`). 256-bit random, stored only as SHA-256 hashes. No token recovery. Rotation and revocation are atomic. Rotation requires an `Idempotency-Key` that is a **version 4 UUID from a CSPRNG** and has a 10-minute keyed replay window for a lost response. A replay returns the original response and never reactivates the old token. Losing the replacement token after the window loses the seat (`state-machine.md` section 3.1).
- Secret codes and guesses are encrypted with AES-256-GCM from the same key ring (AAD binds game, player, key id and, for guesses, number and feedback). Keys stay outside the database and backups. Decrypt only in these API paths: guess submission (only feedback leaves), progress (own guesses may be returned) and results (both codes and all guesses may be returned, only after `COMPLETED` is verified and before any ciphertext is read), plus the rotation replay token (approved RD-11, only when the old token, the original UUIDv4 key, a matching fingerprint, a valid window and an unrevoked replacement token are all present, and the token never appears in logs, diagnostics, metrics or error responses). Those two are the only API serialisation exceptions for game data. Controlled maintenance decryption (`reencrypt`, `keys:verify`) is allowed and produces no plaintext output. No decrypted value in logs, diagnostics, metrics, traces, errors or persistent plaintext. Never log or echo a secret code, guess, nickname or token, and never return one in diagnostics, error messages or any response outside the contract (progress and results above are the contract). Guess request fingerprints are keyed HMACs, never plain hashes.
- Guess submission and rotation need an `Idempotency-Key` UUID, scoped per player and operation. Fingerprints use RFC 8785 canonical JSON. Same key and body returns the stored original response. Same key and different body returns `409 IDEMPOTENCY_CONFLICT`. Rejected requests store nothing.
- Nicknames: trim, reject empty, at most 24 code points, reject `Cc` control characters and bidirectional embedding, override and isolate controls (U+202A to U+202E, U+2066 to U+2069), preserve other Unicode exactly, allow duplicates.
- Rematch: at most one rematch ever per original game, recorded in `rematch_markers`, which survives deletion of the rematch game. Creating a rematch revokes every other unused capability of the original in the same transaction.
- Encryption usage is counted by durable reservations made in a separate autocommit transaction before any encryption (`database-schema.md` 6.2). The counter may over-count and must never under-count, including for rolled-back transactions. Thresholds: warn 2^27, rotate by 2^28, hard stop 2^30. After a database restore, fresh processes always start, and a new key is activated and the old ones sealed before traffic. The active key is kept only after the complete lossless proof (R10.13, `deployment.md` 6.1).
- Rate-limit store failure fails closed with `503`. Rotation keys in the simulator are deterministic UUIDv4-format values for test deployments only. Production keys always use a CSPRNG.
- Every state-changing operation runs in one transaction that starts by locking the game row (`SELECT … FOR UPDATE`). Lock order is in `design.md` section 8.2. Attempts never exceed 10. Prefer database constraints for limits and uniqueness.
- Rate limits live in PostgreSQL token buckets shared by all instances, plus coarse per-IP limits at the proxy. No in-memory-only limiters and no mandatory Redis. Player buckets are keyed by player id after the preliminary lookup. Never store raw IPs or tokens in `rate_limits`. The proxy is a pinned, reproducible Caddy custom build (`deployment.md` section 4.3).
- Admin metrics and cleanup are on a separate internal listener. Cleanup is scheduled by the dedicated `cleanup` service. Metrics and logs are privacy-safe: bounded labels, no game ids, player ids, nicknames, IPs or tokens as labels.
- Retention is driven by `games.expires_at`. Cleanup is bounded, repeatable and uses `FOR UPDATE SKIP LOCKED`.
- Parameterised SQL only. Validate all input server-side. `Math.random` is banned outside the simulator.
- The simulator uses only the public REST API and supports deterministic replay by `(seed, gameNumber)`.
- Tests first. Use a real PostgreSQL for integration and concurrency tests.
- Source files carry `SPDX-License-Identifier: AGPL-3.0-only`. Do not copy another game's branding or artwork.
- Do not commit binaries, secrets, `.env` files or key material.
- Do not add features beyond the current task or the specification (no accounts, WebSockets, Redis, multi-tenant code).
