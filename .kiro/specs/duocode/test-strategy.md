# DuoCode Test Strategy (revision 3)

Owns: test layers, required cases, test group IDs, CI jobs. Related: `requirements.md`, `traceability.md` (maps requirements to the group IDs below), `state-machine.md` (transition tables to cover), `database-schema.md`, `security-assessment.md` (threat IDs T1 to T32), `simulator-design.md`, `../../../openapi/openapi.yaml` (contract).

Approach: test-first. Each task in `tasks.md` starts with failing tests. Tests run against a real PostgreSQL (CI service container). The database is never mocked in integration, concurrency or schema tests.

Test group IDs (`TS-xxx`) are stable and are the acceptance-test identifiers used in `traceability.md`. A test case within a group is referred to as `TS-xxx-nn` and numbered in the order listed in the section.

## 1. Layers

| Layer | Location | Groups |
|---|---|---|
| Engine unit | `backend/tests/engine/` | TS-ENG |
| Reference comparison | `backend/tests/reference/` | TS-REF |
| Validation (nickname, bodies) | `backend/tests/unit/` | TS-VAL |
| Idempotency and canonicalisation | `backend/tests/idempotency/` | TS-IDEM |
| Credentials, rotation, rematch | `backend/tests/credentials/` | TS-CRED |
| Vault and crypto | `backend/tests/crypto/` | TS-ENC |
| Schema and repository | `backend/tests/db/` | TS-DB |
| Rate limiting | `backend/tests/ratelimit/` | TS-RATE |
| Expiry, retention, cleanup | `backend/tests/retention/` | TS-RET |
| State machine and negative cases | `backend/tests/integration/` | TS-STATE |
| API integration | `backend/tests/integration/` | TS-API |
| Contract | `backend/tests/contract/` | TS-CONTRACT |
| Security and logging | `backend/tests/security/` | TS-SEC |
| Concurrency | `backend/tests/concurrency/` | TS-CONC |
| Administration, scheduling, restore | `backend/tests/ops/` | TS-OPS |
| Simulation | `tools/simulator` | TS-SIM |
| Load | simulator at scale | TS-LOAD |
| Documentation checks | CI scripts | TS-DOC |

## 2. TS-ENG and TS-REF: engine and reference (R14)

Engine cases: exact matches, misplaced matches, no matches, all four exact, duplicates in the secret, duplicates in the guess, mixed duplicates, invalid length, invalid symbols, attempt limits (solve on guess 10, exhaust on guess 10, no guess 11), outcome table (every row of R7.2 plus equal-count draw), state-transition function (every cell of the table in `state-machine.md`, section 1.2).

Known feedback cases include `1122` vs `2211` giving `0,4`; `1123` vs `1111` giving `2,0`; `1234` vs `4321` giving `0,4`; `1111` vs `1111` giving `4,0`; `1122` vs `1212` giving `2,2`.

Reference: a different algorithm (mark-and-remove over arrays), imports nothing from `src/engine`. A test enforces the import rule. Comparison covers all 6^4 × 6^4 pairs and 10,000 seeded random pairs. The import check also bans crypto, I/O and Oak imports in `src/engine` (R14.1).

## 3. TS-VAL: validation (R1.3, R12.4)

Nickname cases (applied to create, join and rematch, each expecting `INVALID_NICKNAME` and no state change on rejection):
- Leading and trailing white space is trimmed: `"  Ann  "` is stored and returned as `"Ann"`. Unicode white space is trimmed too (no-break space, ideographic space).
- Interior white space is preserved exactly: `"A  n"` stays `"A  n"`.
- Empty string, white space only, and trimmed-empty values are rejected.
- Exactly 24 code points accepted, 25 rejected. Counts are in code points: 24 emoji (each one code point, two UTF-16 units) accepted, 24 combining sequences counted by code point. A 24-character value of 4-byte characters is accepted (not counted in bytes).
- Control characters rejected: U+0000, U+0009, U+000A, U+001F, U+007F, U+0080, U+009F. A value with only the control character after trimming is also rejected.
- Malformed Unicode (an unpaired surrogate in the JSON string) is rejected.
- Accepted value is not normalised: a precomposed and a decomposed form are returned exactly as sent. No case folding.
- Duplicate nicknames accepted: two players in the same game with the same nickname, and across games.
- Error messages never contain the submitted nickname.
- The database `CHECK` constraints reject over-long and control-character values inserted directly (backstop, TS-DB).

Other validation: unknown body properties rejected, duplicate member names rejected with `INVALID_REQUEST`, malformed UUID path returns `INVALID_GAME_ID`, bodies over `HTTP_MAX_BODY_BYTES` rejected, wrong content type rejected.

## 4. TS-IDEM: idempotency and canonicalisation (R5)

Guess idempotency:
- Same key, same body, sequential: one guess stored, second response equals the first byte for byte, carries `Idempotent-Replay: true`, counts unchanged.
- Same key, different body: `409 IDEMPOTENCY_CONFLICT`, nothing changed.
- Same key by the other player, in another game, or on the rotation endpoint: independent, no conflict, no information leak.
- Missing key, malformed key, uppercase UUID (accepted, same key as lowercase), non-UUID string (rejected): `INVALID_IDEMPOTENCY_KEY`, counts unchanged.
- Rejected request (invalid guess, wrong state, attempts exhausted) stores no key. The same key can then be used for a corrected request.
- Replay of the completing guess after the game is `COMPLETED`: original response returned.
- Replay while the credential is valid but the game has expired: `GAME_EXPIRED`. Replay with a revoked token: `401`.
- Key retention: keys remain until the game is deleted. A replay after many later guesses and a re-encryption pass still returns the original response.
- Same guess with a new key consumes a second attempt.
- Backstop: attempt to insert a duplicate `(player_id, guess_number)` or `(player_id, key)` directly and assert the database rejects it.
- Consistency check after every concurrency test: `players.guesses_used` equals the count of `guesses` rows, guess numbers are 1..n without gaps.

Canonicalisation (R5.12):
- RFC 8785 test vectors for the subset of JSON this API uses (objects, arrays, integers, strings including escapes and non-ASCII).
- Property test: random permutations of member order and random insignificant whitespace give the same fingerprint. Any change to a symbol, to the operation name or to the game id changes it.
- Duplicate member names are rejected before fingerprinting.
- Guess fingerprint is keyed: the same body with a different key id gives a different value. Brute-force test: given all 1296 possible fingerprints computed without the key, none matches the stored value (proves it is not a plain hash).
- Fingerprint comparison is constant time (code review check plus unit test of the compare helper).
- Fingerprint after re-encryption: replay of an old request after `reencrypt` still matches (the fingerprint was re-keyed and the comparison uses the recorded key id).

## 5. TS-CRED: credentials, rotation, rematch (R8, R9)

- Hash-only storage: after creating a game, no column contains the plaintext token or its base64 form, except the encrypted rotation ciphertext (TS-ENC).
- Entropy and format: generated tokens have the prefix and 43 base64url characters. No two tokens in 100,000 generated values are equal. Tokens generated in one request show no derivation relationship (no shared prefix beyond the type prefix, statistical check).
- Type confusion: every credential type presented to every operation that expects another type returns `401`. A `dca_`-prefixed string stored as a different type is judged by the record, not the prefix.
- Cross-game: an access token for game A on game B's path returns `401`.
- Authorisation point: a code scan test asserts that no module outside `services/authorise` reads the `credentials` table for decisions, and that the HTTP layer performs no credential lookup (R8.11).
- Write recheck: a write request that has passed validation and rate limiting before a rotation commits fails with `401` after it (forced interleaving with a barrier in the test).
- Read snapshot: a read that began before a rotation commit finishes consistently (old token accepted for that read), and a read started after fails. Within one read, credential validity and the data cannot disagree (no half-updated view).
- Rotation: new token works, old token returns `401` afterwards. Rotation revokes an unused rematch capability of the same player. Rotation requires `Idempotency-Key`.
- Rotation replay (R8.13):
  - Same old token, same key, inside the window: same new token, `Idempotent-Replay: true`, no state change, `expires_at` unchanged.
  - Simulated lost response: perform rotation, discard the response, retry, and continue play with the returned token.
  - Wrong key, same old token: `401`. Different old token with same key: `409`.
  - After `ROTATION_REPLAY_SECONDS` (use a short test value): `401` even if the ciphertext is still stored. After cleanup the ciphertext is cleared.
  - Replay when the new token has itself been rotated away: `401`.
  - Replay does not work for any operation other than rotation: the old token on guess, status and results returns `401`.
  - Parallel original and retry requests: exactly one new token results, both callers receive the same token.
- Results after rotation (R8.14): results readable with the new token, not with the old token, content identical before and after.
- Invitation: single use. Two parallel joins admit exactly one. Used invitation returns `GAME_FULL`. Invitation of another game returns the same `404` as an unknown game, same body shape. Invitation of an expired game returns `410`. Invitation of a deleted game returns `404`.
- Rematch: capability can only be minted when `COMPLETED`. Minting twice revokes the first. Capability cannot read the game or play. Access token cannot create a rematch. Two players creating rematches in parallel: one `201`, one `REMATCH_ALREADY_CREATED`. Old tokens do not authorise the new game. New tokens do not authorise the old game. The old invitation does not join the new game. Status of the original shows only `rematchCreated: true`. Consumed capability reused returns `401`. Nickname rules apply.
- Rematch deletion (R9.8): delete the original, and the rematch stays playable with a null link. Delete the rematch while the original exists, and a new capability can create another rematch. A rematch of an original that cleanup is deleting at the same time results in either a complete rematch with a cleared link, or `401`, never a half-created game.
- Lost-token limitation: no endpoint issues a token without a credential. An OpenAPI check asserts the only token-issuing operations are create, join, rotate, mint and createRematch, each with its required credential.
- C-7: valid credential of an expired, not yet deleted game gives `410`. After cleanup the same token gives `401`. No `credentials` row remains for the deleted game.

## 6. TS-ENC: encryption (R10)

- Round trip for all 1296 codes and all 1296 guesses, and for token strings.
- Ciphertext length is 32 bytes for codes and guesses and 75 for tokens. Two encryptions of the same plaintext differ (random nonce).
- Nonce uniqueness: encrypt 1,000,000 values under one key in a test and assert no duplicate nonce. Counter metric increments per encryption. Alert threshold configuration test.
- Tamper tests: flip each byte of nonce, ciphertext and tag for codes, guesses and tokens, expect authentication failure.
- AAD binding: swap ciphertext between two rows, between two games, between guess numbers, and change `key_id` to another valid id and to an unknown id. Change `exact` or `misplaced` of a guess row in the database: decryption of that row fails.
- No plaintext at rest: after submitting distinctive codes and guesses, dump the database (`pg_dump`) and assert no table stores them in plaintext (`secret_codes`, `guesses`, `idempotency_keys`, `token_rotations`). Plaintext feedback counts and guess numbers are expected.
- Key ring: startup fails with a missing file, wrong key length, no active key, two active keys, duplicate ids and a failing self-test. `/healthz` is not ready without a ring.
- Rotation of keys: add a key, encrypt new rows with it, run `reencrypt`, confirm all rows (codes, guesses, rotation ciphertext, fingerprints) use the new key id and decrypt correctly, run it again (no changes), run it concurrently with guess traffic (no failed guesses, no corruption), kill it mid-run and confirm no game is half-migrated (each game is all old or all new), then verify with `keys:verify`.
- Key retirement: `keys:verify` reports any remaining reference to the old key. Removing a key that is still referenced makes start-up or `keys:verify` fail loudly.
- Backup recovery (R10.12, R21.4): restore a `pg_dump` into a clean database with the ring supplied, `keys:verify` passes, a game continues. Restore without the needed key: `keys:verify` fails and names the missing key id.
- Decrypt failure path returns `500 INTERNAL_ERROR` with a generic body and no detail, and the alert metric increments.
- Vault redaction: `JSON.stringify`, template strings and `Deno.inspect` of the wrapper never reveal the value.
- Decrypt only where allowed: a spy on the vault asserts decrypt calls occur only in guess submission, progress, results (after `COMPLETED`) and rotation replay, and zero calls for status, join, code submission, mint, rematch creation, cleanup, and for a results request on a non-completed game.
- Performance: decrypting 20 guesses and 2 codes for a results request is measured and reported (target well under 5 ms).

## 7. TS-SEC: secrecy and logging (R3, R13, OD-2)

- For a complete game, capture every response before completion and assert no secret code appears (search for any four-symbol array equal to a code in the game, including the caller's own code). Only `getResults` after `COMPLETED` returns codes.
- Code submission response contains no code. Progress responses contain only the caller's own guesses. The opponent's guesses and feedback appear only in results.
- Opponent progress contains only `guessesUsed`, `solved`, `exhausted`.
- Canary test: submit distinctive codes, guesses, nicknames, tokens, idempotency keys and a distinctive client IP, trigger validation errors, rule errors, rate-limit denials, a decrypt failure and an unhandled exception. Capture all log output, metrics output and error bodies. Assert none of the canary values, any token hash, any fingerprint or any IP appears.
- Metrics label audit: every label name and value in `/admin/metrics` belongs to the allowed bounded sets (R13.8). No game id, player id, nickname, IP or token (R13.9).
- Error messages are fixed strings (snapshot test over all error codes).
- The proxy access log excludes headers and query strings.
- Admin endpoints are not reachable through the public listener or the proxy (TS-OPS).

## 8. TS-STATE: state machine and negative cases

Table-driven tests iterate over every cell of the action-by-state table in `state-machine.md` and assert the documented response code and that nothing changed on rejection. Order-of-checks tests assert the first failing check decides the response.

Negative cases from baseline 9.4: third player cannot join a full game; cross-player access impossible; no early code access; no guess against own code (no such request form exists, asserted against the OpenAPI); invalid guesses do not consume attempts; attempts cannot exceed 10; completed game rejects guesses; invalid invitation rejected; expired game cannot be modified; repeated request does not duplicate guesses; concurrent submissions do not corrupt state.

Additional edge cases: solve on guess 10 is `SOLVED`; both players finish at once yields one result; one player finishing does not end the game; first player's code before the second joins; join after the first code; second code activates the game.

## 9. TS-DB: schema and constraints (CL-7)

Apply all migrations to an empty database, then again (no-op). Concurrent runner starts (advisory lock). For every rule in `database-schema.md` section 3, a test that violates it directly with SQL and asserts the database rejects it:

- Third player or seat 3.
- Second code for a player.
- Guess number 0, 11, duplicate, gap (guess 2 without guess 1), guess after a solving guess.
- Second rematch of one game. Rematch link cleared when the original is deleted. Rematch game deletion leaves the original intact.
- Two live access tokens for one player. Two live capabilities for one player. Second invitation for a game.
- Credential for a player of another game.
- Second idempotency record with the same `(player_id, key)` or the same `guess_id`.
- Second rotation for the same key or the same old credential.
- Second result for a game.
- Nickname over 24 code points or containing a control character.
- Cascade: deleting a game removes every dependent row in every table.
- Migration immutability check in CI.

DDL syntax and the key constraint behaviours were exercised against PostgreSQL 15 during specification review. They must be re-tested in implementation with the real migration file.

## 10. TS-RATE: rate limiting (R20)

- Token bucket arithmetic: capacity, refill, denial leaves the bucket unchanged (statement in `database-schema.md` section 6), `Retry-After` value.
- Shared across instances: start two application instances against one database, spread requests over both, and assert the total allowed equals the configured capacity (in-memory limiters would allow twice as many).
- Concurrency: 200 parallel requests against a bucket of capacity 10 allow exactly 10.
- Each scope in `deployment.md` section 4 has a test that the limit applies, that the response is `429` with `Retry-After`, and that other subjects are unaffected.
- Failed credential checks consume `ip:authfail`. When it is empty, further requests from that IP get `429` before any credential lookup.
- Random tokens create no `tok:*` bucket rows (credential buckets exist only after a credential is found).
- Subjects stored are 32-byte values. A scan asserts no raw IP or token appears in `rate_limits`.
- Forwarded IP: trusted from a configured proxy address, ignored from any other source (a spoofed `X-Forwarded-For` does not change the subject).
- Fail closed: with the rate-limit statement failing (database error injected), requests return `503`.
- Cleanup removes idle rows and leaves active ones.
- A rate-limit denial does not hold or wait for a game lock.

## 11. TS-RET: expiry, retention, cleanup (R11, CL-2)

Uses an injectable database clock offset for service tests and direct `expires_at` updates for database tests.

- `expires_at` after create, join, code, guess, rotation, completion matches `database-schema.md` section 5. Reads, polling, replays, mint and rematch creation do not change it.
- Boundary: at `expires_at - 1 ms` an operation succeeds. At exactly `expires_at` and after it every operation returns `GAME_EXPIRED` (`>=`). Test every operation, in authorisation, in the in-transaction recheck and in cleanup (cleanup deletes a game whose `expires_at` equals the reference time).
- A request whose authorisation point ran before expiry but whose transaction would commit after it: the single reference time decides, the request succeeds consistently or fails consistently, never a mixed state.
- Credentials of an expired game fail at once, before cleanup runs, with `410`. After cleanup, `401` and zero credential rows.
- Cleanup deletes the game and every dependent row (assert zero rows in every table for the game id, including `token_rotations`, `idempotency_keys` and `secret_codes`), leaves other games intact, and clears `rematch_of` on a surviving rematch.
- Repeatability: run twice, second run deletes nothing. Batch size smaller than the number of expired games loops to completion. Interrupt a run (kill between batches) and rerun.
- Cleanup also clears expired rotation ciphertext and idle rate-limit rows.
- Dry run deletes nothing and reports the count.
- Configuration: TTLs from environment override defaults. Invalid values (zero, negative, non-numeric) stop start-up.
- Logs from cleanup contain only counts.
- No endpoint deletes a game on behalf of a player (R11.10).

## 12. TS-CONC: concurrency scenarios (CL-8)

Each scenario runs many iterations with randomised ordering and barriers to force interleavings. After every scenario assert: no deadlock, no unexpected `5xx`, and database invariants hold (counts equal rows, contiguous guess numbers, one result at most, one live access token per player).

| ID | Scenario | Expected |
|---|---|---|
| TS-CONC-01 | Two clients join the same game at once | One `201`, one `GAME_FULL` |
| TS-CONC-02 | Join racing with seat 1's code submission | Both succeed in either order, game `WAITING_FOR_CODES` or consistent next state |
| TS-CONC-03 | 50 parallel requests with the same guess key and body | One guess, 50 identical responses |
| TS-CONC-04 | 50 parallel requests with distinct keys from one player | Guess numbers 1..10 contiguous, 40 `ATTEMPTS_EXHAUSTED` |
| TS-CONC-05 | Both players guess in parallel, last guesses simultaneous | One result row, correct outcome, no lost guess |
| TS-CONC-06 | Guess racing with rotation of the same token | Guess commits before rotation (success) or fails `401`. Never both tokens live |
| TS-CONC-07 | Two rotations with different keys from the same token | One rotates, the other `401` or `409` |
| TS-CONC-08 | Rotation request and its retry in parallel (same key) | One rotation, same token returned to both |
| TS-CONC-09 | Both players request a rematch at once | One `201`, one `REMATCH_ALREADY_CREATED` |
| TS-CONC-10 | Rematch creation while the original is expiring and cleanup runs | Complete rematch with cleared link, or `401`/`GAME_EXPIRED`, never a partial game |
| TS-CONC-11 | Cleanup while guesses run in other games and in a game being refreshed | No deadlock, no deleted live game, refreshed game survives |
| TS-CONC-12 | Two cleanup runs at once | Each expired game deleted once |
| TS-CONC-13 | Cleanup deleting an original while its rematch game is active | Lock wait at most `lock_timeout`, no deadlock, rematch continues |
| TS-CONC-14 | `reencrypt` running during guesses, results reads and rotation replay | All requests succeed with correct data. Each game fully old or fully new |
| TS-CONC-15 | Rate-limit bucket hit from many instances | Exactly capacity allowed |
| TS-CONC-16 | Read racing with completion | Read returns a consistent pre- or post-completion view, results never partial |
| TS-CONC-17 | Lock-order check | A test records lock acquisition order across all operations in the instrumented database and asserts it never violates L0, L1, L2, L3 of `design.md` section 8.2 |

## 13. TS-API and TS-CONTRACT (R12)

- Full-lifecycle integration test with two independent tokens covering every row of the outcome table.
- Every response in integration tests validates against `openapi/openapi.yaml`.
- Every operation and every documented status code appears in at least one test (coverage script over the spec).
- Error body shape for every error code. Malformed UUID path returns `400 INVALID_GAME_ID`.
- OpenAPI lint (Redocly) runs in CI.
- Admin operations appear only under the admin server entry in the specification.

## 14. TS-OPS: administration, scheduling, restore (R21)

- Admin listener is bound to the configured internal address. The public listener and the proxy return `404` for `/admin/*`.
- Admin token required: missing and wrong token get `401`, comparison is constant time, player tokens never pass.
- Metrics and cleanup endpoints behave as specified. Cleanup endpoint and the CLI task share code (same results on the same data).
- The `cleanup` service runs on the configured interval. Application instances never run it (test: start instances without the service, nothing is deleted).
- Restore drill (automated in CI against a throwaway database): take `pg_dump`, delete games by cleanup, restore, assert deleted games return, run `cleanup` before traffic and assert they are gone again. Rate-limit table cleared after restore. Rotation after the backup is reverted by the restore (documented behaviour).
- Start-up refuses missing secrets, invalid TTLs, missing trusted proxy list in production mode.

## 15. TS-SIM and TS-LOAD

Defined in `simulator-design.md`. The CI simulation job runs 200 games with a fixed seed and must exit zero. It includes duplicate guess requests, lost-rotation-response retries, and rotation with the old token afterwards. A scheduled job runs 10,000 games at concurrency 50 and records p50, p95 and p99 latency against the 500 ms p95 target (R17.4). Load tests include parallel create, join, guess, retry storms, cleanup during load and a `reencrypt` run during load.

## 16. TS-DOC: documentation checks

- `traceability.md` lists every requirement, and every owning artefact and test group ID it names exists (script).
- Cross-references between specification files resolve.
- `docs/API.md` states the lost-token limitation and the rotation retry rules.
- The curl walk-through runs as a script in CI.

## 17. CI (R17.3)

GitHub Actions jobs on every pull request:

| Job | Steps |
|---|---|
| `check` | `deno fmt --check`, `deno lint`, `deno check`, SPDX header check, import-boundary check (engine), banned `Math.random`, migration immutability check |
| `test` | All TS groups except simulation and load, with a PostgreSQL service container and a generated test key ring. Coverage report |
| `openapi` | Redocly lint and the operation coverage script |
| `docs` | TS-DOC checks |
| `simulate` | 200 games, fixed seed, all strategies, retries and rotation faults injected |
| `audit` | Dependency review, lockfile integrity |
| `build` | Container image build and start-up smoke test with a generated test key ring |

Scheduled or manual: large simulation and load run.

Merge requires `check`, `test`, `openapi`, `docs`, `build` and `simulate` to pass.
