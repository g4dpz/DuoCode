# DuoCode Revision 3.1 Review Package (final for gate review)

Branch: `spec/revision-3.1-review`, created from the baseline `main` (commit `1b75326`, "Revision3 requirements"). `main` is not changed. The commit hash is reported with the branch, because a file cannot contain its own commit hash.

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
| RD-13 approved with conditions | **The mechanism changed.** The draft updated a counter at the end of the request transaction, which a rollback would undo. It is now a durable reservation: a block of encryptions is reserved in its own autocommit transaction before any encryption, each invocation consumes a unit, and an encryption without a reserved unit cannot happen. The counter can over-count, never under-count. After any restore, a new key is activated before traffic, the old key stays `DECRYPT_ONLY` for decryption and never becomes `ACTIVE` again | R10.10, R10.13, R21.4, `database-schema.md` 6.2, `design.md` 9.1, `deployment.md` 6.1 |
| RD-11 approved | Third serialisation exception with your five conditions. The replacement token never appears in logs, diagnostics, metrics, traces or error responses. Replay never reactivates the old token | R8.13, R10.7, R13.2, `state-machine.md` 3.1, TS-CRED, TS-SEC |
| RD-12 approved | Rotation revokes the player's unused rematch capability in the same transaction (already specified, now recorded as approved and tested) | R8.6 |
| CH-1 with qualification | Display-security tests added. New R1.5 (JSON string only, `nosniff`, clients must escape and isolate bidirectional context) | R1.5, TS-VAL |
| CH-2 | `rate_limits` excluded from backups, rate-limit key not backed up | `deployment.md` 5 |
| CH-3 with qualification | **Rule changed from my draft.** Creating a rematch revokes every other unused capability of the original in the same transaction. The loser then receives `401`. Minting after a marker exists still returns `409` | R9.9, `state-machine.md` 3, 4 |
| CH-4 with qualification | Player-keyed buckets. Rotation does not reset them (tested) | R20.4, TS-RATE |
| CH-5 with qualification | Deterministic rotation keys derived from seed, game number, seat and rotation index, UUIDv4 format. The simulator refuses to run without `--test-deployment` | R15.5, `simulator-design.md` |
| CH-6 | Module pinned to its exact commit. Reproducible build and provenance checks retained | `deployment.md` 4.3 |

Other changes in this round: the OpenAPI document was edited so lint reports 0 warnings (section 5.1). Lock levels were simplified to L0 (autocommit rate-limit and reservation statements), L1 (game row) and L2 (child rows). The key ring gains `generation` and `deactivatedAt`. The OD-1 to OD-10 table and decision-to-requirement rows for CH, LI and OD-9, OD-10 were added so the register and the traceability matrix agree. The register no longer has any pending technical decision.

## 4. Files

Added: `.kiro/specs/duocode/revision-3.1-review-package.md` (replaces the revision 3 package), `.kiro/specs/duocode/check-consistency.py`, `.kiro/specs/duocode/verify-schema.py`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE`.
Removed: `.kiro/specs/duocode/revision-3-review-package.md` (superseded).
Modified: `.github/copilot-instructions.md`, `.kiro/specs/duocode/` (`database-schema.md`, `deployment.md`, `design.md`, `requirements.md`, `security-assessment.md`, `simulator-design.md`, `state-machine.md`, `tasks.md`, `test-strategy.md`, `traceability.md`), `README.md`, `openapi/openapi.yaml`.
The two `.py` files are specification tooling (consistency and schema verification). They are not application code or migrations. The branch contains the exact file list in the final report.

## 5. Verification results (actual output)

### 5.1 OpenAPI

Redocly lint of `openapi/openapi.yaml`: **valid, 0 errors, 0 warnings.** The six earlier warnings were all resolved, and none is retained:
- localhost server URL: replaced with `https://{host}/api/v1` and a `host` server variable (default `localhost`),
- four tags without a description: descriptions added,
- `/healthz` without a 4xx response: `429` added (health checks are rate limited like every other public endpoint).

### 5.2 Database schema and constraint tests

`verify-schema.py` extracts the DDL from `database-schema.md`, applies it to a throwaway cluster, and runs 26 tests. It was run three times on PostgreSQL 15 and twice on PostgreSQL 16. Its first two runs reported failures that were mistakes in the test script itself (a wrong table count and a wrong block index for the cleanup statement, then a test session that exited early on an intended error). They were fixed in the script and the specification was not changed for them.

| Server | Result |
|---|---|
| PostgreSQL 15.8 (Homebrew) | **26 of 26 passed**, three runs |
| PostgreSQL 16.16 | **26 of 26 passed**, two runs |

What the 26 tests cover: the DDL applies; at most two seats; nickname length in code points (24 emoji accepted, 25 rejected), control characters rejected, bidirectional controls (U+202A to U+202E, U+2066 to U+2069) rejected, LRM, RLM, ALM, ZWNJ, ZWJ, emoji sequences and Arabic accepted; guess chain (no gap, no duplicate, nothing after a solving guess, eleventh guess rejected); credentials bound to their own game; one live access token; one rematch ever (also after the rematch game was deleted); marker removed with the original while the rematch survives; idempotency uniqueness; rotation record uniqueness; completion check; rate-limit bucket arithmetic and exactly 10 allowed of 40 parallel requests; cleanup statement (only expired games, cascade, repeatable); maintenance statements; key usage constraints.

Encryption counter tests (RD-10, RD-13), what was actually exercised:

| Behaviour | Test | Result |
|---|---|---|
| Failed or rolled-back application transactions | A transaction on one connection is open and rolled back while a reservation commits on another. Another case aborts the transaction with an error | The reservation persisted in both cases (PG 15 and 16) |
| Multiple application instances | Eight parallel sessions, 100 reservations each | Total exactly 8 × 100 × 1024, no lost increment |
| Never under-counts | A policy model (random interleavings of reserve, encrypt, rollback, crash and unknown-outcome reservations, 300 trials) | `reserved >= performed` held at every step, over-count stayed bounded |
| Thresholds | A policy model with small thresholds | Warn, rotate and permanent refusal at the hard stop behaved as specified |
| Invariant check | `rows under key <= reserved total`, then the counter was lowered by hand | Holds normally, detects the lowered counter |
| Database restoration | A cold (physical) backup, further reservations, restore | The restored total was lower than the pre-restore total (the hazard is real). The decision rule "new key unless proved lossless" returned the right answer in all three cases (lossy, lossless, unknown) |

**Limits of these results, stated plainly.** No application exists. The tests prove the SQL, the constraints and the policy on a real PostgreSQL. They do not prove that a future vault implementation follows the policy. The counter-under-failure tests that need the application (`kill -9` of a running instance, forced rollbacks after a real encryption, the instrumented vault, restore with a real key ring and `keys:verify`) are specified in `test-strategy.md` (TS-ENC, TS-CONC-20, TS-OPS) and **have not been run**.

### 5.3 Specification consistency checks

`check-consistency.py`, final run on the final file set:

```
PASS C01 every requirement R1..R21 defined and in traceability matrix
PASS C02 every R<n>.<m> criterion reference exists
PASS C03 every TS group and TS-CONC id referenced is defined (18 groups, 20 concurrency scenarios)
PASS C04 every decision ID is defined in the register and none is unknown
PASS C05 no stale revision 2/3 identifiers or the email signature in the specification, README or licensing files
PASS C06 every "<file>.md section N" reference resolves to a heading
PASS C07 design.md API table matches OpenAPI paths and methods (13 operations)
PASS C08 every error code named anywhere exists in the OpenAPI ErrorCode enum (21 codes)
PASS C09 game states agree between OpenAPI, database enum and state machine
PASS C10 every `table.column` reference names a real column (12 tables in the DDL)
PASS C11 every configuration key named in the specification is in design.md section 13 (22 keys)
PASS C12 rate-limit scopes agree between design.md and deployment.md
PASS C13 licensing artefacts present, LICENSE is the FSF AGPL-3.0 text, NOTICE names AGPL-3.0-only
PASS C14 GitHub workflow files parse as YAML
PASS C15 no Phase 1 gate or task is marked approved in tasks.md
PASS C16 OpenAPI constrains codes to 4 symbols from 1..6
PASS C17 nickname forbidden character classes agree between OpenAPI and database CHECK (NUL aside)
PASS C18 OpenAPI rotation key pattern accepts v4 UUIDs and rejects v1 and wrong-variant values
PASS C19 every decision in the register has a row in the traceability decision map (65 decisions)
PASS C20 no decision recorded as approved in the register is still described as pending elsewhere
PASS C21 no application code, database migration or implementation directory exists
PASS C22 OpenAPI lint (Redocly): valid with 0 errors and 0 warnings
22 of 22 checks passed (0 skipped)
```

The first run of the new checks C19 to C22 found two gaps (OD-9 and OD-10 had no traceability row), which were fixed before the final run. The checks are textual. They prove that identifiers, references and definitions agree. They cannot prove that the documents are right.

Requirements, decision register and traceability agree: C01, C02, C04, C19, C20.
No application code, migrations or implementation tasks: C21 checks every file in the repository by path and type, and C15 confirms no task is marked done. The only code-like files are the two specification tools and the CI skeleton added earlier at your request (`.github/workflows/*`), none of which contains application logic.

### 5.4 Not verified, and why

| Item | Reason | Exact procedure to complete it |
|---|---|---|
| **PostgreSQL 16 in the CI container image** | The Docker daemon is not running on this machine. PostgreSQL 16 was tested instead with an embedded server build (16.16, Maven Central `io.zonky.test.postgres:embedded-postgres-binaries-darwin-arm64v8:16.16.0`, jar sha256 `f8c8cbd962a25a15e918fe094813a9ad48e6c99e0c9e93a1cf98b986cb840dd7`) and a PostgreSQL 15 `psql` client. This is the same major version but not the `postgres:16` image CI uses | With Docker running, from the repository root: `docker run --rm -v "$PWD":/spec:ro postgres:16 bash -c "apt-get update -qq && apt-get install -y -qq python3 >/dev/null && su postgres -c 'python3 /spec/.kiro/specs/duocode/verify-schema.py --server-bin /usr/lib/postgresql/16/bin --psql /usr/lib/postgresql/16/bin/psql'"`. Expect `26 of 26 tests passed`. This command itself has not been run |
| Application-level counter tests (`kill -9`, real rollback after a real encryption, instrumented vault) | No application exists | TS-ENC, TS-CONC-20 in `test-strategy.md`, to run in Phase 4 |
| Restore with a real key ring and `keys:verify`, and the restore drill | No ring, no `keys:verify`, no backup job exist | TS-OPS restore drill and `deployment.md` section 6.1, task 9.5 |
| Web Crypto details (HKDF, AES-GCM with the AAD layout), RFC 8785 library, Caddy build and reproducibility, pinned versions' availability | No implementation or build | Tasks 4.5, 4.7, 9.3 |
| A logical restore with `pg_dump` | PostgreSQL 16 server binaries here include no `pg_dump`, and a version 15 `pg_dump` cannot dump a version 16 server. The restore test used a physical (cold) backup, which shows the same counter rollback | Run the TS-OPS drill with `pg_dump` and `pg_restore` of the same version in Phase 9 |

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

1. All six gates await your explicit sign-off. Nothing is signed off.
2. LI-1 to LI-4 (section 6).
3. PostgreSQL 16 container-image test and the application-level tests (section 5.4).
4. Drafting choices you may want to look at when reviewing, none of them open decisions: the Caddy pins other than the module commit were verified against upstream at specification time and need re-verifying at build time; the proxy access-log retention (14 days, no IP by default), the backup recipients, a named owner for the Caddy build and the 7-day target for critical proxy security upgrades are written in `deployment.md` as proposals and have not been explicitly approved; the privacy notice and UK GDPR wording remain tasks.
