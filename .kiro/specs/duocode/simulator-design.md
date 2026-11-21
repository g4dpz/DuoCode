# DuoCode Simulator Design (revision 3.1, final for gate review)

Owns: simulator behaviour, options, determinism, strategies, checks, reports. Related: `requirements.md` (R15, R5, R8, R20), `test-strategy.md` (TS-SIM), `test-strategy.md` (CI jobs), `../../../openapi/openapi.yaml` (the only interface used), `state-machine.md` (expected transitions).

Location: `tools/simulator/`. Run with `deno task simulate`.

## 1. Constraints

- Uses only the public REST API through `tools/api-client`. It never touches the database, services or persistence, and never bypasses validation (R15, SIM-006).
- Imports from the backend are limited to type definitions of the wire contract and the reference feedback implementation in `backend/tests/reference/`. The simulator does not import `src/engine`, so it can detect engine errors.
- Because deterministic keys are predictable, the simulator refuses to start unless the operator passes `--test-deployment`, and prints a warning that the target must not be a production system.
- Test deployments raise the per-IP rate limits (the simulator uses one address), but player limits stay on so that retry and backoff paths are exercised.
- Credentials are held in memory per game, one set per player, never printed and never written to reports or replay files (R13.2).
- `Math.random` is banned in the simulator. All randomness comes from a seeded generator.

## 2. Options

```
deno task simulate \
  --games 1000 --seed 12345 --concurrency 20 \
  --base-url https://localhost/api/v1 \
  --strategy random|systematic|logic|mixed \
  --retry-rate 0.1 --rotate-rate 0.02 \
  --out report.json --summary
deno task simulate --replay 12345:417 --base-url …
```

| Option | Default | Meaning |
|---|---|---|
| `--games` | 100 | Number of games |
| `--concurrency` | 1 | Games in flight at once |
| `--seed` | required for CI, random otherwise (printed) | Master seed |
| `--strategy` | `mixed` | Strategy for both players, or a mix chosen per game from the seed |
| `--retry-rate` | 0 | Probability that a guess request is sent a second time with the same key (duplicate), also sometimes concurrently |
| `--test-deployment` | off, required | Acknowledges that the target is a test deployment, because rotation keys are deterministic and predictable (CH-5) |
| `--rotate-rate` | 0 | Probability a player rotates their access token between moves |
| `--lost-rotation-rate` | 0 | Of the rotations, the probability that the response is discarded and the rotation is retried with the old token and the same key |
| `--max-429-retries` | 5 | Retries with `Retry-After` backoff before a rate-limit denial counts as a failure |
| `--out` | stdout | JSON report path |
| `--replay seed:n` | none | Replays only game `n` of seed `seed` and prints a step trace |

The exact command-line interface is finalised during implementation (baseline 9.5). New options require a change to this file.

## 3. Determinism and replay (SIM-004, SIM-009)

- Each game's generator is `prng(hash(seed, gameNumber))` (for example mulberry32 seeded from a SHA-256 of the pair). It decides nicknames, secret codes, strategy choice, the interleaving of the two players' moves, retry and rotation events, and the idempotency keys (derived from the generator, not from `crypto.randomUUID`).
- Concurrency changes timing but not any game's decisions, because they depend only on `(seed, gameNumber)` and on the responses received. The server's responses are a deterministic function of the decisions, apart from tokens and timestamps, which the simulator does not use for decisions.
- A failed game is recorded as `{seed, gameNumber, step, reason}`. `--replay seed:gameNumber` reruns that single game against a fresh server state and prints each request and response summary, with tokens and codes masked, except secret codes chosen by the simulator itself in replay mode (`--show-secrets` flag, off by default, prints only simulator-generated codes and only when the game is complete).
- Replay needs the same strategy options as the original run. The report stores the full option set.

## 4. Game flow

Per game number `n`:

1. Player A creates a game with a nickname chosen from a seeded set that includes right-to-left, mixed-direction and joiner text. Record `accessToken`, `invitationToken`. Verify the nickname comes back byte for byte and the response carries the JSON content type and `nosniff`. Occasionally also send a nickname containing a bidirectional control (U+202E for example) and expect `INVALID_NICKNAME` with nothing created (CH-1, R1.5).
2. Player B joins with the invitation. Record the second token. Check the invitation cannot be reused (an occasional negative check).
3. Both players submit secret codes, order chosen by the generator. Check the game is `ACTIVE` only after both codes exist, and that responses never contain a code.
4. Interleave moves until both players are finished. For each move the strategy produces a guess. Send with a fresh `Idempotency-Key`.
   - With probability `retry-rate`, resend the same request with the same key and body, sometimes in parallel. Expect the identical response with `Idempotent-Replay: true` and no change in guess count.
   - Occasionally send the same key with a different body. Expect `409 IDEMPOTENCY_CONFLICT` and no change.
   - With probability `rotate-rate`, rotate the player's token using a fresh version 4 `Idempotency-Key` (**deterministic**, CH-5, R15.5: `key = uuidv4(first 16 bytes of HMAC-SHA-256(simulatorKey, "rotation" || seed || gameNumber || seat || rotationIndex))` with the version nibble set to 4 and the variant bits to `10`, where `simulatorKey` derives from the seed. The same game always produces the same keys, which makes replays exact. Such keys are predictable by design and are for test deployments only. Real clients must generate rotation keys from a cryptographically secure source, R8.13), persist the old token and the key first, and verify the old token then returns `401` for every operation and the new token works.
   - With probability `lost-rotation-rate`, discard the rotation response and retry with the old token and the same key. Expect the same new token and `Idempotent-Replay: true`. After a replay, verify the old token still fails every other operation (a replay never reactivates it). Also verify that a retry with a different key returns `401`, that a rotation key that is not a version 4 UUID is rejected with `INVALID_IDEMPOTENCY_KEY`, and that a retry after the replay window (test deployments use a short `ROTATION_REPLAY_SECONDS`) returns `401`.
5. After each response, fetch status and progress and check consistency.
6. When both are finished, fetch results. Check outcome, codes and guesses.
7. Optionally (low probability) request a rematch with capability, and verify new credentials and that old tokens do not work on the new game. Then verify that minting a second capability and creating a second rematch return `REMATCH_ALREADY_CREATED` (one rematch ever, RD-6). The simulator then stops following the rematch.

## 5. Strategies (SIM-005)

Each strategy is its own module with no shared helper code beyond the generator and the wire types, so a defect in one does not hide a defect in another.

| Strategy | Behaviour |
|---|---|
| Random | Uniformly random code each turn, repeats allowed |
| Systematic | Walks all 1296 codes in lexicographic order, resuming from the last guess |
| Logic | Keeps the set of codes consistent with all feedback so far and guesses one from it, chosen by the generator. Uses the reference feedback to filter the set |

A game's two players may use different strategies. `mixed` picks per player from the generator.

## 6. Checks (SIM-006 to SIM-008)

| Check | How |
|---|---|
| Feedback correct | Each response's feedback equals the reference implementation applied to the known secret and the guess |
| Attempt counts | `guessNumber` increments by one per accepted guess. Never above 10. `guessesRemaining` matches |
| Replay behaviour | Duplicates return the same body, header present, counts unchanged |
| State transitions | Observed states follow `state-machine.md`: activation only after both codes, completion only when both players finished, no regression |
| Secrecy | No response before completion contains any code of the game |
| Opponent progress | Only counts and flags, matches the opponent's real progress |
| Outcome | Server outcome equals the outcome recomputed from observed guess counts and solved flags |
| Status codes | Every status and error code is one the OpenAPI document allows for that operation |
| Credential behaviour | Old tokens after rotation fail except the keyed replay. Cross-game tokens fail. Results readable with the new token |
| Rotation replay | Replayed rotation returns the identical token and changes no state |
| Rate limits | A `429` carries `Retry-After`. After backoff the request succeeds. Denials are counted, never treated as game errors, and the retry never double-spends an idempotent request |
| Contract | Response bodies validate against the OpenAPI schemas |

An unexpected result records a failure with the check name, request summary and `(seed, gameNumber)`, continues with other games, and sets a non-zero exit code.

## 7. Report (SIM-010, SIM-011)

JSON (`schemaVersion` field) and text summary.

Metrics: rotation replays verified, rate-limit denials by scope, retries after `Retry-After`, games started, games completed, wins by seat, draws, solved counts, average and maximum guesses, API errors by code, invalid state transitions, retry replays verified, idempotency conflicts verified, rotations verified, latency percentiles (p50, p95, p99) per operation, concurrency failures (unexpected `409` or `5xx` under parallel load), unexpected outcomes, failed games with `(seed, gameNumber)`.

The report contains no tokens, no secret codes and no nicknames.

## 8. Exit codes

| Code | Meaning |
|---|---|
| 0 | All checks passed |
| 1 | One or more checks failed |
| 2 | Invalid options or the server was unreachable |

## 9. Use in CI and load

- CI `simulate` job: 200 games, fixed seed, `--strategy mixed --retry-rate 0.1 --rotate-rate 0.02`, concurrency 10, must exit 0.
- Scheduled load job: 10,000 games at concurrency 50, records latency percentiles against the 500 ms p95 target, and runs the cleanup endpoint once during the run.
- Simulator games use short-lived test data in the CI database. Production-like runs target a separate environment.
