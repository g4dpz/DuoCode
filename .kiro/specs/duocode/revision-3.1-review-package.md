# DuoCode Revision 3.1 Review Package (final for gate review, strict hard-stop correction)

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

**The reservation algorithm**
1. A key row is registered once: `INSERT INTO key_usage (key_id) VALUES ($1) ON CONFLICT DO NOTHING`.
2. Before an operation that may encrypt, the instance makes sure its allowance covers the operation's worst case. If not, it runs one statement in its own autocommit transaction on a separate connection:
   `UPDATE key_usage SET reserved = reserved + $block WHERE key_id = $1 AND reserved + $block <= $hard_stop RETURNING reserved;`
3. A returned row means the whole block was granted. No row means refused whole, nothing changed. The block joins the allowance only after the statement returns. An unknown outcome counts as refused.
4. Each encryption invocation consumes one allowance unit, whatever happens to the surrounding transaction. An empty allowance cannot encrypt. The only way to refill it is step 2.
5. `$hard_stop` is at most 2^30 and a multiple of the block (start-up validation), and the table has `CHECK (reserved <= 2^30)` as an absolute backstop.

**Guarantees** (G1 to G8 in the specification, each tested): `R` never exceeds 2^30. Every invocation consumes a reserved unit, including those in failed or rolled-back transactions. Outstanding allowances are inside `R`. No instance can obtain units that take `R` past the limit. Concurrent reservations cannot pass the limit independently, because they all update one row and a waiting update re-evaluates the limit against the latest committed total. An instance never encrypts with an exhausted allowance. A restore cannot let encryption resume under a key whose counter may have rolled back. `R` can overestimate, never underestimate.

**Exact threshold behaviour**

| Reserved units reach | Behaviour |
|---|---|
| 2^27 | Warning metric, one operational warning per key per process start, `/healthz` reports `warning`. Reservations continue |
| 2^28 | `ROTATION_OVERDUE`: critical alert, `/healthz` degraded (still HTTP 200), rotation is mandatory. **Reservations continue to be granted until the hard stop.** This is my proposal (RD-14), because refusing at 2^28 would turn a late rotation into an outage while the margin is still large |
| 2^30 | Hard stop. A block that would take `R` above 2^30 is refused whole. `R` can equal 2^30 exactly, so at most 2^30 encryptions ever happen. Once instances use the units they hold, no encryption occurs under the key and encrypting operations fail closed with `503`. Decryption is unaffected |

**Restore.** The restore procedure activates a new key as the only active key, **seals every older key** (`keys:seal` sets its counter to 2^30, so any reservation under it is refused even if the ring were wrong), and restarts every instance so no allowance survives, all before traffic. A planned rotation seals the old key once every instance runs the new ring.

**New decision for you: RD-14.** Reservations between 2^28 and 2^30 continue (proposed), and the limit 2^30 is inclusive. If you want refusal from 2^28, set `KEY_USAGE_HARD_STOP` equal to `KEY_USAGE_ROTATE_BY`, or tell me and I will change the rule. This is the only open technical decision.

**Files changed for CR-9:** `database-schema.md`, `design.md`, `security-assessment.md`, `deployment.md`, `test-strategy.md`, `requirements.md` (R10.10, R10.13, CR-9, RD-14, glossary), `traceability.md`, `tasks.md`, `verify-schema.py`, `check-consistency.py`, and this package.

## 4. Files (revision 3.1 branch, for history)

Added: `.kiro/specs/duocode/revision-3.1-review-package.md` (replaces the revision 3 package), `.kiro/specs/duocode/check-consistency.py`, `.kiro/specs/duocode/verify-schema.py`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE`.
Removed: `.kiro/specs/duocode/revision-3-review-package.md` (superseded).
Modified: `.github/copilot-instructions.md`, `.kiro/specs/duocode/` (`database-schema.md`, `deployment.md`, `design.md`, `requirements.md`, `security-assessment.md`, `simulator-design.md`, `state-machine.md`, `tasks.md`, `test-strategy.md`, `traceability.md`), `README.md`, `openapi/openapi.yaml`.
The two `.py` files are specification tooling (consistency and schema verification). They are not application code or migrations. The branch contains the exact file list in the final report.

## 5. Verification results (actual output)

### 5.1 OpenAPI

Redocly lint of `openapi/openapi.yaml`: **valid, 0 errors, 0 warnings.** The OpenAPI document is not changed by CR-9.

### 5.2 Database schema, constraint and reservation tests

`verify-schema.py` extracts the DDL, the reservation statement, the registration statement and the sealing statement **from `database-schema.md`**, so the tested SQL is the specified SQL. It applies them to a throwaway cluster and runs 37 tests.

| Server | Result |
|---|---|
| PostgreSQL 15.8 (Homebrew) | **37 of 37 passed**, three runs |
| PostgreSQL 16.16 embedded build | **37 of 37 passed**, two runs |
| **PostgreSQL 16.16 official `postgres:16` image (Debian, Docker Desktop)**, image digest `sha256:3950ad7c3148ca2175ef1b6c36c9efbf78957ae8fbe8b3a5d7c35af50500382f` | **37 of 37 passed**, one run. This closes the earlier "container image not tested" item |

The reservation tests (all use the real PostgreSQL statement and real concurrent connections, not a mocked counter):

| Required test | Result |
|---|---|
| Reservation that takes `R` exactly to the hard stop | Granted, `R` equals 2^30, the next one refused |
| Reservation that would go beyond the hard stop | Refused whole, `R` unchanged, also when `R` is not a multiple of the block. A direct write above 2^30 is rejected by the `CHECK` |
| Several instances reserving concurrently against the same key | 16 and 32 connections, started a few blocks below the limit: exactly the available blocks granted, `R` ends at exactly 2^30, and a sampler polling during the run never saw `R` above 2^30. Eight instances × 100 reservations: no lost increment |
| Instances holding outstanding allowances while another approaches the limit | A holds a block, B takes the last, C is refused. A and B use only their units. A further reservation is refused. Invocations equal units reserved since the start |
| Failed and rolled-back transactions still consume units | 60 simulated requests, each consuming a unit and then rolling back a real transaction: `R >= invocations`, rollbacks did not touch the counter. A reservation made while another connection's transaction is open and later rolled back, or aborted by an error, persisted |
| Instance crash and restart with unused allowance | The counter did not decrease, lost units stayed counted (over-count only), the restarted instance reserved a fresh block |
| Database restoration followed by a new key | The restored counter was lower than before the restore. The old key was sealed (counter set to 2^30) and a new key registered. Reservations under the sealed key were refused even though the model ring wrongly still listed it as active. The new key worked |
| No invocation beyond the limit | `invocations <= R <= 2^30` asserted in the tests above |
| Strictness of the statement | An interleaving test holds a reservation open on one session while a second one starts: the second **waited**, then was refused on the committed total |
| Negative control | The replaced shard design, run through the same kind of interleaving, ended at 2^30 plus one block. This is why it was replaced |
| Thresholds with the real statement | Warning and overdue states, reservations still granted in the overdue band, refusal at the hard stop |
| Sealing | Sealed key refused for ever. Sealing never lowers a counter |
| Start-up validation rule | Hard stop above 2^30, not a multiple of the block, or thresholds out of order are invalid |

The rest of the 37 tests are the constraint tests of the earlier run (seats, nicknames, bidirectional controls, joiners and Arabic accepted, guess chain, ten guesses, credential binding, one rematch ever, idempotency, rotation record, completion check, rate-limit bucket and its 40-way concurrency test, cleanup, maintenance statements, invariant check).

**Limits, stated plainly.** No application exists. The instance in these tests is a small model of the allowance rule. The reservations it makes go to real PostgreSQL. The tests prove the SQL, the constraints and the policy. They do not prove that a future vault follows the policy, which is why the (APP) tests in `test-strategy.md` are required in Phase 4.

### 5.3 Specification consistency checks

`check-consistency.py`, final run on the final file set. C23 and C24 are new for CR-9: C23 checks that the key usage design is the same everywhere (one row per key, `CHECK` at 2^30, defaults 2^27 / 2^28 / 2^30, the strict statement, terms defined, sharding mentioned only as replaced), and C24 checks that the test tool takes its SQL from the specification.

```
PASS C01 every requirement R1..R21 defined and in traceability matrix
PASS C02 every R<n>.<m> criterion reference exists
PASS C03 every TS group and TS-CONC id referenced is defined (18 groups, 22 concurrency scenarios)
PASS C04 every decision ID is defined in the register and none is unknown
PASS C05 no stale revision 2/3 identifiers or the email signature in the specification, README or licensing files
PASS C06 every "<file>.md section N" reference resolves to a heading
PASS C07 design.md API table matches OpenAPI paths and methods (13 operations)
PASS C08 every error code named anywhere exists in the OpenAPI ErrorCode enum (21 codes)
PASS C09 game states agree between OpenAPI, database enum and state machine
PASS C10 every `table.column` reference names a real column (12 tables in the DDL)
PASS C11 every configuration key named in the specification is in design.md section 13 (22 keys)
PASS C12 rate-limit scopes agree between design.md and deployment.md
PASS C13 licensing artefacts present, LICENSE is the FSF AGPL-3.0 text (sha256 0d96a4ff68ad6d4b...), NOTICE names AGPL-3.0-only
PASS C14 GitHub workflow files parse as YAML
PASS C15 no Phase 1 gate or task is marked approved in tasks.md
PASS C16 OpenAPI constrains codes to 4 symbols from 1..6
PASS C17 nickname forbidden character classes agree between OpenAPI and database CHECK (NUL aside)
PASS C18 OpenAPI rotation key pattern accepts v4 UUIDs and rejects v1 and wrong-variant values
PASS C19 every decision in the register has a row in the traceability decision map (67 decisions)
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
| (APP) counter tests: an instrumented vault, `kill -9` of a running instance, forced rollback after a real encryption, two to eight real instances | No application exists | TS-ENC and TS-CONC-20 to TS-CONC-22 in Phase 4 |
| Restore with a real key ring, `keys:seal` and `keys:verify` as tools, and the full restore drill | The tools, the ring and the backup job do not exist | TS-OPS and task 9.5. The SQL behaviour of the restore, the seal and the new key was tested above |
| A logical restore with `pg_dump` and `pg_restore` | The test used a physical (cold) backup, which shows the same counter rollback. Docker is now available, so a logical restore can be added | Phase 9, or add to `verify-schema.py` on request |
| Web Crypto details (HKDF, AES-GCM with the AAD layout), RFC 8785 library, Caddy build and reproducibility | No implementation or build | Tasks 4.5, 4.7, 9.3 |

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

1. **RD-14** (section 3A): reservations continue between 2^28 and 2^30, and the limit is inclusive. Needs your decision.
2. All six gates await your explicit sign-off. Nothing is signed off.
3. LI-1 to LI-4 (section 6).
4. The (APP) tests and the restore drill with real tools (section 5.4).
5. Drafting proposals not explicitly approved: proxy access-log retention (14 days, no IP by default), backup recipients, a named owner for the Caddy build, the 7-day target for critical proxy security upgrades, re-verification of the Caddy version pins at build time. The privacy notice and UK GDPR wording remain tasks.
