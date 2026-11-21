# DuoCode Test Strategy (revision 3.1, final for gate review)

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
- Bidirectional embedding, override and isolate controls rejected wherever they appear (start, middle, end): U+202A, U+202B, U+202C, U+202D, U+202E, U+2066, U+2067, U+2068, U+2069 (RD-5).
- Legitimate Unicode accepted and preserved exactly: Arabic and Hebrew names including U+200F (RLM), U+200E (LRM) and U+061C (ALM), Persian text with U+200C (ZWNJ), emoji sequences with U+200D (ZWJ) such as a family emoji (counted per code point), combining marks, CJK, accented Latin in precomposed and decomposed form (CH-1).
- Malformed Unicode (an unpaired surrogate in the JSON string) is rejected.
- Accepted value is not normalised: a precomposed and a decomposed form are returned exactly as sent. No case folding.
- Duplicate nicknames accepted: two players in the same game with the same nickname, and across games.
- **Display-security tests (CH-1, R1.5).**
  - Every route that returns a nickname (create, join, status, results, rematch) sends `Content-Type: application/json; charset=utf-8` and `X-Content-Type-Options: nosniff`, and the value is returned byte for byte as accepted.
  - A nickname containing HTML (`<script>`, `<img onerror=…>`, `"`, `'`, `&`) is accepted as text (it is legitimate input) and returned unescaped inside the JSON string and never inside an HTML body. No endpoint returns `text/html`.
  - Bidirectional controls cannot enter by any input path: raw UTF-8, JSON `\uXXXX` escapes for each of U+202A to U+202E and U+2066 to U+2069, escaped surrogate pairs, and values that become a forbidden code point only after trimming adjacent white space. Each is rejected with `INVALID_NICKNAME`.
  - Legitimate right-to-left and mixed-direction text is accepted and unchanged (Arabic, Hebrew, Persian with ZWNJ, a Latin name inside Arabic text with LRM or RLM marks, ALM).
  - Look-alike input that is not a control character (fullwidth Latin, Cyrillic homoglyphs) is accepted. It is not a control and is outside RD-5. The test documents this so the behaviour is deliberate.
  - A client-side check in the Postman collection and `docs/API.md` shows the escape and `<bdi>` rule for display (documentation test, TS-DOC).
- Error messages never contain the submitted nickname.
- The database `CHECK` constraints reject over-long and control-character values inserted directly (backstop, TS-DB).

Other validation: unknown body properties rejected, duplicate member names rejected with `INVALID_REQUEST`, malformed UUID path returns `INVALID_GAME_ID`, bodies over `HTTP_MAX_BODY_BYTES` rejected, wrong content type rejected.
Rotation key validation (R8.13): a version 4 UUID is accepted in lower and upper case. Version 1, 3, 5 and 7 UUIDs, the nil UUID, a v4-looking string with a wrong variant, a UUID without hyphens and a non-UUID string are rejected with `INVALID_IDEMPOTENCY_KEY` before any state is read. The same values are accepted as guess keys except malformed ones (guess keys accept any version, R5.1).

## 4. TS-IDEM: idempotency and canonicalisation (R5)

Guess idempotency:
- Same key, same body, sequential: one guess stored, second response equals the first byte for byte, carries `Idempotent-Replay: true`, counts unchanged.
- Same key, different body: `409 IDEMPOTENCY_CONFLICT`, nothing changed.
- Same key by the other player, in another game, or on the rotation endpoint: independent, no conflict, no information leak. A v4 UUID used once for a guess and once for a rotation by the same player creates two unrelated records.
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
- Read order (CR-2): a test double records the sequence for every authenticated read: preliminary lookup, rate-limit update(s), `BEGIN READ ONLY ISOLATION LEVEL REPEATABLE READ`, authorise as the first statement in that transaction, data reads. Any other order fails the test. The preliminary lookup result is never used to authorise: revoke the credential between the preliminary lookup and the transaction (forced interleaving) and assert `401`. A token not found by the preliminary lookup yields `401` without creating any `rate_limits` row and consumes `ip:authfail`.
- Rotation: new token works, old token returns `401` afterwards. Rotation revokes an unused rematch capability of the same player. Rotation requires `Idempotency-Key`.
- Rotation replay (R8.13):
  - Same old token, same key, inside the window: same new token, `Idempotent-Replay: true`, no state change, `expires_at` unchanged.
  - Simulated lost response: perform rotation, discard the response, retry, and continue play with the returned token.
  - Wrong key, same old token: `401`. Different old token with same key: `409`.
  - After `ROTATION_REPLAY_SECONDS` (use a short test value): `401` even if the ciphertext is still stored. After cleanup the ciphertext is cleared.
  - Replay when the new token has itself been rotated away: `401`.
  - Replay returns the original response byte for byte (body identical, status `201`, `Idempotent-Replay: true`).
  - RD-11 conditions: the replacement token is returned only when all five hold. Test each failing in turn (wrong or absent old token, wrong key, a different fingerprint, a window that has passed, a replacement token revoked by a later rotation) and assert no decrypt call is made and the response is `401` or `409` with no token in it.
  - Canary (RD-11): across the whole run, the replacement token never appears in any log line, diagnostic output, metric, trace or error body, in the first response or in a replay (TS-SEC).
  - Rotation revokes the player's unused rematch capability in the same transaction (RD-12): mint a capability, rotate, assert the capability returns `401`, and that a failed rotation leaves the capability live.
  - Replay does not reactivate the old token: before and after the replay, a snapshot of every `credentials` row and every `token_rotations` row is identical, `revoked_at` and reason of the old token are unchanged, and the old token still fails status, guess, results, rotate-with-another-key and mint with `401`.
  - Replay on the first request after the window ends, with the ciphertext still present (cleanup not yet run): `401`. After cleanup: `401`.
  - Loss after the window: perform a rotation, discard the response, wait out the window, retry: `401`. The seat is unreachable by any request (assert no endpoint accepts the old token or the key).
  - Replay does not work for any operation other than rotation: the old token on guess, status and results returns `401`.
  - Parallel original and retry requests: exactly one new token results, both callers receive the same token.
- Results after rotation (R8.14): results readable with the new token, not with the old token, content identical before and after.
- Invitation: single use. Two parallel joins admit exactly one. Used invitation returns `GAME_FULL`. Invitation of another game returns the same `404` as an unknown game, same body shape. Invitation of an expired game returns `410`. Invitation of a deleted game returns `404`.
- Rematch: capability can only be minted when `COMPLETED` and when no rematch marker exists (`REMATCH_ALREADY_CREATED` afterwards). Minting twice revokes the first. Capability cannot read the game or play. Access token cannot create a rematch. Both players mint a capability, one creates the rematch: **every other unused capability of the original is revoked in the same transaction** (CH-3), so the other player's capability returns `401 INVALID_CREDENTIALS`, the status shows `rematchCreated: true`, and minting returns `409`. Old tokens do not authorise the new game. New tokens do not authorise the old game. The old invitation does not join the new game. Consumed capability reused returns `401`. Nickname rules apply.
- Rematch deletion and one rematch ever (R9.4, R9.8, RD-6): after a rematch exists, delete the rematch game (simulating cleanup of an unjoined rematch): the marker row remains with a null `rematch_game_id`, `rematchCreated` stays true, minting a capability returns `REMATCH_ALREADY_CREATED`, and no capability is usable. Delete the original: the marker and capabilities go with it and the rematch stays playable. A rematch of an original that cleanup is deleting at the same time results in either a complete rematch with its marker, or `401`, never a half-created game.
- Lost-token limitation: no endpoint issues a token without a credential. An OpenAPI check asserts the only token-issuing operations are create, join, rotate, mint and createRematch, each with its required credential.
- C-7: valid credential of an expired, not yet deleted game gives `410`. After cleanup the same token gives `401`. No `credentials` row remains for the deleted game.

## 6. TS-ENC: encryption (R10)

- Round trip for all 1296 codes and all 1296 guesses, and for token strings.
- Ciphertext length is 32 bytes for codes and guesses and 75 for tokens. Two encryptions of the same plaintext differ (random nonce).
- Nonce uniqueness: encrypt 1,000,000 values under one key in a test and assert no duplicate nonce. Counter metric increments per encryption. Alert threshold configuration test.
- Tamper tests: flip each byte of nonce, ciphertext and tag for codes, guesses and tokens, expect authentication failure.
- AAD binding: swap ciphertext between two rows, between two games, between guess numbers, and change `key_id` to another valid id and to an unknown id. Change `exact` or `misplaced` of a guess row in the database: decryption of that row fails.
- Serialisation exceptions (CR-1): a response-schema scan over every operation asserts that decrypted game values appear only in `getProgress` (caller's own guesses) and `getResults` (after `COMPLETED`), and that the rotation replay is the only response carrying a decrypted credential. Submit-guess, status, join, code submission, rotation (first response, a normal rotation returns a freshly generated token, not decrypted data), mint and rematch responses never contain a decrypted code or guess.
- Results gating (R7.5): for a game in every non-completed state, a results request reads zero rows from `secret_codes` and `guesses`, performs zero decrypts, and returns `GAME_NOT_COMPLETED` (repository and vault spies). The vault's results method cannot be called without a `CompletedGame` value (type test).
- No plaintext at rest: after submitting distinctive codes and guesses, dump the database (`pg_dump`) and assert no table stores them in plaintext (`secret_codes`, `guesses`, `idempotency_keys`, `token_rotations`). Plaintext feedback counts and guess numbers are expected.
- Key ring: startup fails with a missing file, wrong key length, no active key, two active keys, duplicate ids and a failing self-test. `/healthz` is not ready without a ring.
- Rotation of keys (seal): after the new ring is on every instance, `keys:seal` the old key and assert its counter equals 2^30 and every reservation under it is refused. Add a key, encrypt new rows with it, run `reencrypt`, confirm all rows (codes, guesses, rotation ciphertext, fingerprints) use the new key id and decrypt correctly, run it again (no changes), run it concurrently with guess traffic (no failed guesses, no corruption), kill it mid-run and confirm no game is half-migrated (each game is all old or all new), then verify with `keys:verify`.
- Key retirement: `keys:verify` reports any remaining reference to the old key. Removing a key that is still referenced makes start-up or `keys:verify` fail loudly.
- Backup recovery (R10.12, R21.4): restore a `pg_dump` into a clean database with the ring supplied, `keys:verify` passes, a game continues. Restore without the needed key: `keys:verify` fails and names the missing key id.
- Decrypt failure path returns `500 INTERNAL_ERROR` with a generic body and no detail, and the alert metric increments.
- Vault redaction: `JSON.stringify`, template strings and `Deno.inspect` of the wrapper never reveal the value.
- Decrypt only where allowed: a spy on the vault asserts decrypt calls occur only in guess submission, progress, results (after `COMPLETED`) and rotation replay, and zero calls for status, join, code submission, mint, rematch creation, cleanup, and for a results request on a non-completed game.
- Performance: decrypting 20 guesses and 2 codes for a results request is measured and reported (target well under 5 ms).
- Stored response check: every row of `idempotency_keys.response_body` and every database column other than the ciphertext columns is scanned for any code or guess played in the test game (R10.7).
- **Encryption usage counter and strict hard stop (RD-10, RD-13, CR-9, R10.10, R10.13).** Terms as in `database-schema.md` section 6.2: reserved units, encryption invocations, allowances. **Every test marked (PG) runs the reservation statement taken from `database-schema.md` against a real PostgreSQL, with real concurrent connections. None of them mocks the database.** Tests that also need the vault are marked (APP) and run against the instrumented vault when it exists. The tool `verify-schema.py` implements the (PG) tests today and extracts the statement from the specification, so the document and the test cannot drift apart.
  - (PG) Exactly to the limit: with `R` set to 2^30 minus one block, one reservation is granted, `R` equals 2^30 exactly, and the next reservation is refused with no row returned and no change.
  - (PG) Beyond the limit: with `R` set to 2^30 minus half a block (a value that is not a multiple of the block), a reservation is refused whole, `R` does not change, and a direct `UPDATE` to 2^30 plus 1 is rejected by the `CHECK` constraint.
  - (PG) Concurrency against the same key: 16 and then 32 concurrent connections reserve in a loop until refused, starting a few blocks below the 2^30 limit. The number of granted blocks equals exactly the blocks that were available, the final `R` equals the limit, and `R` is never observed above the limit by a sampler running during the test.
  - (PG) Outstanding allowances: instance A reserves and holds a block unused, instance B takes the last block, instance C is refused. A and B then consume only the units they hold. Any further reservation by A is refused. Total invocations equal the units reserved since the start, and never more.
  - (PG, with a model of the allowance) Failed and rolled-back transactions still consume units: each simulated request consumes a unit and then rolls back a real transaction. At the end `R >= invocations`. A reservation made while another connection holds an open transaction that is later rolled back is not undone.
  - (PG, with a model of the allowance) Crash and restart with unused allowance: an instance reserves, consumes part of its block, then is discarded. `R` is unchanged and still covers all invocations, and the lost units stay counted (over-count only).
  - (PG) Restore: a physical backup is restored, the restored `R` is lower than the pre-restore `R`, the procedure seals the old key (counter set to 2^30) and registers a new key. A reservation under the sealed key is refused, one under the new key is granted, even though the model ring is deliberately wrong and still lists the old key as active.
  - (PG) Rotation completed after the 2^28 threshold, stale allowances (RD-14, CR-10, `database-schema.md` 6.3): start with `R` above 2^28 for key 1, instance A holding an unused allowance. Register key 2 and seal key 1. Assert: A's pre-encryption check fails closed and A cannot start any encrypting request, reservations under key 1 are refused, A's unused units stay counted (`R` for key 1 is 2^30 and never lower than before), key 2 works from a fresh instance, and a request that had already passed the check before the seal may use its units, counted, and that is the only possible use after the seal.
  - (PG) Pre-encryption check and sealed flag: a registered unsealed key returns usable, a sealed key returns not usable, an unregistered key returns no row and is treated as unusable. Setting `sealed = true` without setting the counter to 2^30 is rejected by the `CHECK`. Sealing twice is harmless and never lowers the counter.
  - (PG) Zero and negative reservations (CR-11): a request for 0 or -1024 units matches no row and changes nothing, from any starting `R`. No statement can lower `R`.
  - (PG) Whole blocks sized to the operation (CR-11): with a block of 1, an operation needing 22 units obtains them in one statement (`R` rises by exactly 22). With `R` 10 units below the limit, the same request is refused whole and changes nothing.
  - (PG) Sealing a missing row (CR-11): sealing a key identifier that has no row inserts a sealed row at 2^30. A later registration does not reset it. Reservations and the pre-encryption check refuse it. Physical-restore scenario: a key registered after the backup is absent from the restored database, sealing it by its identifier from the newest ring makes it unusable.
  - (PG, with a model of the in-process claim) Atomic claims (CR-11): with one unit left and many concurrent requests on one instance, exactly one claims it, every other request receives an empty claim and defers, the claim is returned when unused, and no request ever consumes a unit it did not claim.
  - (APP) Replay after refusal (CR-11): a rotation consumes the last available unit, its response is lost, and the retry inside the window is answered with the original token although no unit is available. A repeated guess with the same key is answered with the stored response. A fresh guess in the same state returns `503` and nothing is written.
  - (APP) Restart at the hard stop (CR-11): with the active key sealed or at 2^30, an instance starts (the self-test decrypts the known-answer vector and does not encrypt), serves reads and decrypts, and answers every request needing a fresh encryption with `503`.
  - (APP) Ring validation (CR-11): the same key material under two identifiers is rejected at load and by `keys:generate` and `keys:verify`. A new identifier not above `highestKeyId` is rejected. `highestKeyId` never decreases.
  - (APP) Refresh (CR-11): instance A holds an allowance and makes no reservation while instance B crosses a threshold. A's metrics and admin health state reflect the new state within `KEY_USAGE_REFRESH_SECONDS`.
  - (PG) Fingerprint uniqueness and history (CR-12): registering key material whose fingerprint is already registered under another identifier is rejected by the database, also after the first key was sealed (retired) and its ring entry removed. New material is accepted. A sealing upsert for a missing row carries the ring's fingerprint and a later registration cannot reset it.
  - (PG) `keys:generate` order (CR-12): a reservation under an unregistered key is refused, so the tool registers first, reserves at least one unit second, encrypts the self-test third. A newly generated key has a counter of at least 1 at activation.
  - (PG) Restore seals exactly the pre-existing identifiers (CR-12): the set is captured from the newest ring before the new key is added, the new key is not in it, and after the procedure the new key is usable and every old key is not. A procedure that sealed the new key by mistake is detected by this test (the new key would be unusable).
  - (PG, model) Claim recheck after a reservation wait (CR-12): several requests race while a reservation is in progress (simulated wait). After it returns, no claim exceeds the allowance that really exists, the allowance never goes negative, and no unreserved unit is ever consumed. `R >= invocations` at the end.
  - (APP) Rolling rotation without unreadable ciphertext (CR-12): with the new key `STAGED` on some instances and not yet on others, nothing encrypts under it. The tool refuses to activate the key until every instance reports the staged generation. During the activation rolling restart, data written by an instance using the new key is read successfully by an instance still using the previous key, and the reverse. Run with traffic and assert zero decrypt failures.
  - (APP) Re-encryption recount (CR-12): a live token rotation adds ciphertext to a game between the job's count and its lock. The job recounts under the lock, rolls back without writing, obtains a larger claim outside the transaction and retries, and no reservation statement runs inside the game transaction.
  - (APP) Health by key role (CR-12): after a rotation the sealed, non-active key reports `sealed` with no alert, a sealed key that the ring lists as `ACTIVE` reports `critical`, and only the active key can report `warning`, `degraded` or `critical`.
  - (PG) Commit-time check orders ciphertext against the seal (CR-13): transaction T holds the key row `FOR SHARE` after writing, a concurrent seal waits for T, T commits, the seal then commits. A transaction that reaches the check after the seal reads `sealed = true` and rolls back. No ciphertext row under the key is committed after the seal.
  - (PG) Registration is idempotent only for the same material (CR-13): registering an existing identifier with the same fingerprint returns the row, with a different fingerprint returns no row and changes nothing, and the same fingerprint under a new identifier is rejected.
  - (PG) Restore seals every identifier in the fingerprint history (CR-13): a key retired early, absent from the ring and from the restored database, is sealed again from the history, its fingerprint row is restored, and re-registering its material under a new identifier is then refused by the database.
  - (PG) Lossless proof covers staged keys (CR-13): a restore in which the active key's counter matches but a staged key's row is missing or behind is not lossless.
  - (PG, model) Retry after a refused reservation (CR-13): a request whose reservation is refused, while another request returns an unused claim, claims the returned unit instead of failing.
  - (APP) Claim before check (CR-13): a request that claims, then fails the pre-encryption check, returns its claim. No request can pass the check with an empty claim and claim later.
  - (APP) No hot reload and no carried allowance: changing the ring file while a process runs does not change its active key. After a restart the allowance is zero. The ring `generation` is exposed per instance in the admin metrics and the rotation procedure refuses to seal while an instance reports the old generation unless forced.
  - No invocation beyond the limit: in every test above, `invocations <= R <= 2^30` is asserted at the end and at intervals.
  - (APP) An encryption without a reserved unit is impossible: with the allowance forced to zero and the database unavailable, the operation returns `503` and nothing is encrypted. An exhausted allowance cannot be used to encrypt. `kill -9` of a running instance mid-request, forced rollbacks after a real encryption, and two to eight real instances with parallel writers keep `sum` of invocations (instrumented) at or below `R`.
  - (APP) Threshold behaviour with small test values, in this order: warning state at the first threshold (metric, one log line per key per start, admin health `warning`), `ROTATION_OVERDUE` at the second (critical metric, admin health `degraded`, reservations still granted), refusal at the hard stop (new encrypting operations return `503`, decryption still works, admin health `critical`). In every state the public `/healthz` still returns `ok` and exposes no key usage information.
  - (APP) Start-up validation: `KEY_USAGE_HARD_STOP` above 2^30, not a multiple of `KEY_USAGE_BLOCK`, or `WARN > ROTATE_BY > HARD_STOP` stops the application.
  - Invariant check: `keys:verify` fails when the ciphertext rows under a key exceed its reserved total.
  - Restore with the application: see TS-OPS.

## 7. TS-SEC: secrecy and logging (R3, R13, OD-2)

- For a complete game, capture every response before completion and assert no secret code appears (search for any four-symbol array equal to a code in the game, including the caller's own code). Only `getResults` after `COMPLETED` returns codes.
- Code submission response contains no code. Progress responses contain only the caller's own guesses. The opponent's guesses and feedback appear only in results.
- Opponent progress contains only `guessesUsed`, `solved`, `exhausted`.
- Canary test: submit distinctive codes, guesses, nicknames, tokens, idempotency keys and a distinctive client IP, trigger validation errors, rule errors, rate-limit denials, a decrypt failure and an unhandled exception. Capture all log output, metrics output and error bodies. Assert none of the canary values, any token hash, any fingerprint or any IP appears.
- Replacement-token canary (RD-11): rotate, force each failing condition and a success, capture all logs, metrics, traces and error bodies, and assert the replacement token never appears in them. The only place it appears is the body of the successful rotation response and of a valid replay.
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
- Second marker for one original game (also after the first rematch game was deleted). Marker `rematch_game_id` cleared when the rematch game is deleted, with the marker row kept. Marker deleted when the original is deleted. Rematch game survives deletion of the original. Marker pointing at its own original rejected.
- Two live access tokens for one player. Two live capabilities for one player. Second invitation for a game.
- Credential for a player of another game.
- Second idempotency record with the same `(player_id, key)` or the same `guess_id`.
- Second rotation for the same key or the same old credential.
- Second result for a game.
- Nickname over 24 code points, containing a control character, or containing a bidirectional embedding, override or isolate control (U+202A to U+202E, U+2066 to U+2069). A nickname with U+200F, U+200D or U+200C is accepted.
- `key_usage`: one row per key; a negative count is rejected; a count above 2^30 is rejected by the `CHECK`; a second row for the same key is rejected by the primary key; the conditional reservation statement changes nothing when it would exceed the hard stop.
- Cascade: deleting a game removes every dependent row in every table.
- Migration immutability check in CI.

DDL syntax and the key constraint behaviours were exercised against PostgreSQL 15 during specification review. They must be re-tested in implementation with the real migration file.

## 10. TS-RATE: rate limiting (R20)

- Token bucket arithmetic: capacity, refill, denial leaves the bucket unchanged (statement in `database-schema.md` section 6), `Retry-After` value.
- Shared across instances: start two application instances against one database, spread requests over both, and assert the total allowed equals the configured capacity (in-memory limiters would allow twice as many).
- Concurrency: 200 parallel requests against a bucket of capacity 10 allow exactly 10.
- Each scope in `deployment.md` section 4 has a test that the limit applies, that the response is `429` with `Retry-After`, and that other subjects are unaffected.
- Failed credential checks consume `ip:authfail`. When it is empty, further requests from that IP get `429` before any credential lookup.
- Random tokens create no `pl:*` bucket rows (player buckets exist only after the preliminary lookup finds a credential).
- Sequence (CR-2, R20.9): for writes and reads, rate-limit updates occur as separate autocommit statements before the request transaction begins. A lock tracer asserts that no rate-limit row lock is ever held while a game lock is held or awaited, and that no `rate_limits` statement runs inside a request transaction.
- Player scope is keyed by player id: rotating a token does not reset `pl:*` buckets.
- Rate limiting never decides validity: a request with a revoked token that still passes the rate limiter fails with `401` at authorisation, and a valid token that is rate limited gets `429` without any credential state change.
- Forwarded headers from outside `TRUSTED_PROXY_CIDRS` do not change the IP subject.
- Subjects stored are 32-byte values. A scan asserts no raw IP, token or player id appears in `rate_limits`. IP subjects computed with a different HMAC key do not match (key rotation of the rate-limit secret resets buckets and old rows are pruned). `rate_limits` is excluded from the backup job (`pg_dump` output contains no rows of it).
- Configurable (RD-2): every capacity and refill rate in `deployment.md` section 4.2 can be overridden by configuration, and the override takes effect after restart. Invalid values stop start-up.
- Fail closed (RD-2): with the rate-limit statement failing for each reason (connection refused, timeout, permission error, lock timeout), every operation returns `503` with `Retry-After`, nothing is processed, no game state changes, and the response contains no database detail.
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
- Cleanup deletes the game and every dependent row (assert zero rows in every table for the game id, including `token_rotations`, `idempotency_keys`, `secret_codes` and `rematch_markers` of the original), leaves other games intact, and leaves a surviving rematch game playable with no link to the deleted original.
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
| TS-CONC-09 | Both players present rematch capabilities at once | One `201`. The winner's transaction revokes every other unused capability, so the loser gets `401`. Exactly one marker row |
| TS-CONC-10 | Rematch creation while the original is expiring and cleanup runs | Complete rematch with its marker, or `401`/`GAME_EXPIRED`, never a partial game |
| TS-CONC-11 | Cleanup while guesses run in other games and in a game being refreshed | No deadlock, no deleted live game, refreshed game survives |
| TS-CONC-12 | Two cleanup runs at once | Each expired game deleted once |
| TS-CONC-13 | Cleanup deleting an original while its rematch game is active, and cleanup deleting a rematch game while the original is active | Lock wait at most `lock_timeout`, no deadlock, rematch continues in the first case and the marker stays with a null link in the second |
| TS-CONC-14 | `reencrypt` running during guesses, results reads and rotation replay | All requests succeed with correct data. Each game fully old or fully new |
| TS-CONC-15 | Rate-limit bucket hit from many instances | Exactly capacity allowed |
| TS-CONC-16 | Read racing with completion | Read returns a consistent pre- or post-completion view, results never partial |
| TS-CONC-17 | Lock-order check | A test records lock acquisition order across all operations in the instrumented database and asserts it never violates the levels L0, L1, L2 of `design.md` section 8.2 |
| TS-CONC-18 | A token is revoked (rotation commits) between the preliminary lookup and the authoritative validation, for a write and for a read | `401` in both cases. No state change. A read whose snapshot began before the commit may complete with the old token |
| TS-CONC-19 | After the first rematch game was deleted, many attempts to mint a capability and to create a rematch race | Every mint returns `REMATCH_ALREADY_CREATED`. No capability is usable (`401`). Exactly one marker row remains |
| TS-CONC-20 | Many writing transactions on two or more instances, some rolled back or killed, reserve and consume encryptions against the real reservation statement | `invocations <= R <= 2^30` at every sample. No deadlock. The reservation holds the key row lock for one statement only and never while waiting for another lock |
| TS-CONC-21 | 16 to 32 instances reserve concurrently against one key starting a few blocks below 2^30 | Exactly the available blocks are granted, `R` ends at exactly 2^30 and is never above it, every other attempt is refused |
| TS-CONC-22 | An instance holds an outstanding allowance while another instance takes the last block and a third is refused | The holder may use only its units. No further reservation anywhere. `invocations <= R <= 2^30` |
| TS-CONC-23 | Requests run on an instance that holds an allowance while the old key is sealed (planned rotation, including after 2^28) | Requests that began before the seal commits may finish and their units are counted. Requests that begin after it fail the pre-encryption check with `503`. No instance encrypts under the old key afterwards. `invocations <= R <= 2^30` |
| TS-CONC-24 | Many requests on one instance race for the last claimable unit, and the last unit is consumed by a rotation whose retry arrives while no unit is left | Exactly one request claims the unit. Every other request defers and ends with `503` only if it needs a fresh encryption. The rotation retry is answered with the stored token. Nothing is written by a request that ends with `503` |
| TS-CONC-25 | Rolling restart rotation with traffic: instances restart one by one while a new key is staged and then activated | No instance ever fails to decrypt data written by another. Activation is refused until every instance has the staged key |
| TS-CONC-26 | Requests race on one instance while a reservation is in progress | After the reservation returns every claim is checked against the current allowance. No claim exceeds it. `invocations <= R <= 2^30` |
| TS-CONC-27 | Live token rotation adds ciphertext to a game that a re-encryption job has already counted | The job recounts under the lock, rolls back, enlarges its claim outside the transaction, retries, and never reserves inside the transaction |
| TS-CONC-28 | Seal of a key while many transactions are writing ciphertext under it | Each transaction either commits before the seal or rolls back at its commit-time check. After the seal commits, no ciphertext row under the key is added. No deadlock between seal, reservations and game transactions |

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
- Restore drill (automated in CI against a throwaway database, and run by hand with a real backup before production): stop and drain every encrypting process (including a running `reencrypt`), take `pg_dump`, record the `key_usage` total, run more writes, delete games by cleanup, restore using the newest ring and its `highestKeyId`. Assert the deleted games return and **the restored `key_usage` total is lower than before the restore** (the hazard). Then follow `deployment.md` section 6.1: activate a new key, **seal every identifier in the fingerprint history** (`keys:seal`, counter set to 2^30) and assert any reservation under it is refused even with a ring that still lists it as active, restart every instance so no allowance survives, check the previous key is `DECRYPT_ONLY` and still decrypts all restored data, `keys:verify` passes, the application refuses to start if a key whose `deactivatedAt` is set is marked `ACTIVE` again (ring check), run `cleanup` before traffic and assert the games are gone again, `rate_limits` is empty (excluded from backup), and a rotation made after the backup is reverted (documented behaviour). A restore proved lossless (restored total not below the pre-restore total, read after the drain) may skip the new key and the sealing, and the test covers that path with the proof step and asserts that every instance is still restarted. A second scenario restores a backup older than a key's registration and asserts that sealing that key by its identifier from the newest ring makes it unusable, and that a new key identifier is above `highestKeyId`.
- Start-up refuses missing secrets, invalid TTLs, missing trusted proxy list in production mode.
- Caddy build (RD-1, CH-6, R18.6): the build runs from the committed pins (module at its exact commit) and produces a binary. A second independent build gives the same sha256. `go mod verify` passes. `go version -m` matches `BUILD-PINS.md`. The Compose file references the proxy image by digest. The proxy configuration returns `404` for `/admin/*` and enforces the coarse limits. The Nginx fallback configuration passes the same limit tests.

## 15. TS-SIM and TS-LOAD

Defined in `simulator-design.md`. The CI simulation job runs 200 games with a fixed seed and must exit zero. It includes duplicate guess requests, lost-rotation-response retries, and rotation with the old token afterwards. A scheduled job runs 10,000 games at concurrency 50 and records p50, p95 and p99 latency against the 500 ms p95 target (R17.4). Load tests include parallel create, join, guess, retry storms, cleanup during load and a `reencrypt` run during load.

## 16. TS-DOC: documentation checks

- `traceability.md` lists every requirement, and every owning artefact and test group ID it names exists (script).
- Cross-references between specification files resolve.
- `docs/API.md` states the lost-token limitation and the rotation retry rules.
- The curl walk-through runs as a script in CI.
- `LICENSE` exists and its text matches the FSF AGPL-3.0 text (recorded sha256 in `revision-3.1-review-package.md`). `NOTICE` and `CONTRIBUTING.md` exist and `NOTICE` names AGPL-3.0-only. Every source file has the SPDX header once source exists.
- `README.md` contains no email or device signature text.

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
