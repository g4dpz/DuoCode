DuoCode

Two players. Two secrets. One challenge.

DuoCode is a modern, browser-first social code-breaking game for two players. Each player creates a secret code and challenges the other to crack it.

Games are asynchronous: players can make their moves whenever convenient, without needing to be online at the same time. An invitation link makes it easy to challenge a friend, colleague or group.

DuoCode is being developed as an API-first platform, with a responsive web application as its initial user interface and the possibility of additional clients and white-label deployments in the future.


Project status

🚧 Early development — API-first MVP

The first development milestone is a fully playable backend, accessible through its REST API. The game engine, persistence layer, API and automated test infrastructure will be validated before development of the graphical interface begins.

The project is currently at the specification stage: requirements, architecture, API contract, database schema, security assessment and licensing have been approved by the owners (Phase 1 in tasks.md), and Phase 2 (implementation) was authorised on 22 November 2026. No application code has been written yet. Product naming, visual identity and commercial arrangements remain subject to review.

The game

Two players each create a secret code and attempt to discover their opponent’s code.

Each player has an independent sequence of guesses and receives feedback after every attempt.

Initial game rules

Rule

Initial configuration

Players

2

Code length

4 positions

Available symbols

6

Repeated symbols

Permitted

Maximum guesses

10 per player

Feedback

Exact and misplaced matches

Feedback

Exact match: the correct symbol in the correct position.
Misplaced match: the correct symbol in the wrong position.
Feedback must account correctly for repeated symbols. Exact matches are counted first, and misplaced matches are calculated from the remaining unmatched symbols.

Winning conditions

Each player independently attempts to solve the opponent’s secret code.

If both players solve their codes, the player using fewer guesses wins.
If both solve in the same number of guesses, the result is a draw.
If only one player solves their opponent’s code, that player wins.
If neither player solves the code within the permitted attempts, the result is a draw.
Secret codes remain private until the game is complete.

The server is authoritative for game rules, feedback, state transitions and results.

Product objectives

DuoCode aims to provide:

A simple way to create and share a two-player challenge.
No account or application installation requirement for an invited opponent.
Asynchronous gameplay.
A responsive experience on desktop, tablet and mobile.
A reliable, independently testable game engine.
An API that can support future web, Android and iOS clients.
An architecture that can evolve towards configurable and white-label deployments.
Technology

The initial technology choices are:

Area

Technology

Language

TypeScript

Runtime

Deno

HTTP framework

Oak

API

REST

API specification

OpenAPI 3.1

Database

PostgreSQL

Deployment

Docker Compose

Reverse proxy

Caddy (pinned custom build with a rate-limit module; Nginx is the documented fallback)

Version control

Git

CI

GitHub Actions

These choices provide a relatively lightweight, maintainable architecture without introducing unnecessary infrastructure at the MVP stage.

Architecture

The application is designed around a modular structure, with the game engine independent of the HTTP framework and persistence implementation.

                  REST API
                     |
               API / Oak
                     |
        +------------+------------+
        |            |            |
    Game          Player       Results
  Management    Management   Management
        |            |            |
        +------------+------------+
                     |
                 Game Engine
                     |
                Persistence
                     |
                PostgreSQL
The game engine is responsible for the core rules, code comparison, feedback calculation, game progression and outcome determination.

The API provides access to these capabilities without exposing implementation details of the engine or database.

Application services should remain stateless, with PostgreSQL providing the authoritative persistent state.

Development approach

Development is deliberately divided into stages.
The roadmap stages below are product stages. The phases in `tasks.md` are authoritative for what "authorise Phase 2" means.

Phase 1 — Backend MVP

The first milestone is a complete game playable entirely through the REST API.

It will include:

Game creation and management.
Player identity and invitation handling.
Secret-code submission.
Guess submission and feedback.
Game-state management.
Results and completion handling.
PostgreSQL persistence.
OpenAPI documentation.
Postman collection and environment examples.
Curl-based usage examples.
No graphical user interface is required for this phase.

Phase 2 — Automated verification

Automated testing is a fundamental part of the project, not an activity deferred until the end.

Testing will cover:

Game-engine unit tests.
Feedback calculation, including duplicate symbols.
API integration tests.
Database persistence.
Game lifecycle and state transitions.
Invalid and malicious requests.
Concurrent guesses and duplicate submissions.
Security and secret-code protection.
Performance and load behaviour.
An independent reference implementation of the feedback algorithm will be used to verify the production implementation.

Phase 3 — Game simulation

A configurable simulator will exercise the public REST API, rather than bypassing the API or manipulating the database directly.

It will support:

Random guessing strategies.
Systematic guessing strategies.
Logic-based strategies.
Configurable numbers of games.
Concurrent games.
Deterministic random seeds and replay.
Machine-readable JSON output.
Human-readable reports.
Example:

deno task simulate \
  --games 1000 \
  --seed 12345 \
  --concurrency 20 \
  --test-deployment
The `--test-deployment` flag is mandatory: the simulator uses predictable rotation keys and must only be pointed at a test deployment, never at production.
Simulation results will include game completion statistics, wins and draws, average and maximum guesses, API errors, response latency, concurrency failures and unexpected outcomes.

The objective is to expose problems in game logic, API behaviour, persistence and concurrency before the web interface is introduced.

Phase 4 — Browser application

Once the backend has been validated, development will move to a responsive browser-based application.

The web application will provide:

Game creation.
Nickname selection.
Secret-code entry.
Invitation-link generation and sharing.
Guess entry and feedback presentation.
Game status and results.
Rematches.
The application will use the same REST API developed and tested in the earlier phases.

A Progressive Web App approach may be used where appropriate.

Phase 5 — Future development

Potential future capabilities include:

Additional game configurations.
Configurable code lengths and symbol sets.
Different game modes.
Leaderboards and statistics.
Clubs, societies and group challenges.
Android and iOS applications.
White-label and hosted commercial deployments.
These are future opportunities, not requirements for the initial MVP.

White-label and commercial direction

The architecture should avoid assumptions that would prevent future white-label deployments.

Potential customers could include clubs, societies, schools, corporations and organisations running promotional or event-based challenges.

A white-label deployment might provide:

Custom product name and logo.
Custom colours and visual theme.
Custom domain.
Configurable game rules.
Customer-specific welcome and information content.
Hosted or independently hosted deployments.
The initial release will remain a single-tenant application. Multi-tenancy will not be implemented prematurely, but the architecture should keep game logic, API, presentation and branding sufficiently separate to support it later.

Any future multi-tenant implementation must include server-side tenant validation and logical data isolation.

Security and privacy

Security is part of the initial design.

Key principles include:

Secret codes must never be exposed to the opposing player before game completion.
The server must validate all player actions.
Invalid requests must not consume attempts.
Game-state transitions must be controlled by the server.
Simultaneous requests must not corrupt game state.
Duplicate submissions must not result in repeated actions.
Game access tokens, invitation tokens and rematch capabilities are separate, random and stored only as hashes. A lost token cannot be recovered, because there are no accounts.
Secret codes and guesses are encrypted at rest (AES-256-GCM) with keys held outside the database and its backups, and are never written to logs or error responses.
Rate limits are shared across application instances through PostgreSQL, with coarse per-IP limits at the proxy.
Guess submissions require an Idempotency-Key, so retries never consume extra attempts. Token rotation is idempotent too, so a lost response does not lock a player out.
API access must not rely on client-side validation.
Games expire and are deleted automatically: unjoined 7 days, in progress 30 days, completed 180 days (configurable; approved defaults).
The implementation should follow secure development practices appropriate to a public-facing web service.

Repository structure

The repository layout is:

duocode/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── copilot-setup-steps.yml
│   └── copilot-instructions.md
├── .kiro/
│   └── specs/
│       └── duocode/
├── backend/
│   ├── migrations/
│   ├── src/
│   │   ├── engine/
│   │   ├── services/
│   │   ├── persistence/
│   │   ├── http/
│   │   ├── config/
│   │   ├── tasks/
│   │   └── main.ts
│   ├── tests/
│   └── deno.json
├── tools/
│   ├── simulator/
│   └── api-client/
├── openapi/
│   └── openapi.yaml
├── postman/
├── docs/
├── deployment/
│   └── caddy/
├── README.md
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
└── .gitignore

backend/ holds the API and application implementation. tools/ holds development and operational tools, including the game simulator in tools/simulator/. openapi/ holds the OpenAPI specification. docs/ holds supporting documentation.

A frontend/ directory will be added when browser application development begins.

The structure may evolve as the implementation develops, but separation of the game engine, API, persistence and testing tools should be maintained.

Development workflow

The project uses a specification-led and review-driven development process.

The intended workflow is:

Define and refine requirements using Kiro.
Produce architecture and implementation specifications.
Break work into manageable tasks.
Implement changes on Git branches.
Submit changes through GitHub pull requests.
Use independent review, including GitHub Copilot, to identify omissions and potential problems.
Run automated checks through CI.
Review and approve changes before merging.
The specification set is in .kiro/specs/duocode/ (requirements, design, database schema, state machine, security assessment, test strategy, simulator design, deployment and tasks), with the API contract in openapi/openapi.yaml. No implementation starts until the owners have approved the specification (Phase 1 in tasks.md).

GitHub Actions (.github/workflows/ci.yml) lints the OpenAPI document and checks the repository, and will run the backend checks and tests once the backend exists. Instructions for GitHub Copilot are in .github/copilot-instructions.md.

Kiro is used to support requirements, design and implementation. Independent reviews provide an additional check on architecture, security, testing and maintainability.

Important design decisions should be documented so that the project remains understandable and maintainable by both collaborators.

Licensing

The intended community licence is:

GNU Affero General Public License v3.0 only (AGPL-3.0-only).

The intention is to make the community version available under a strong copyleft licence, including the network-use provisions of the AGPL.

Commercial licensing may also be offered separately for organisations requiring proprietary modifications, closed-source integrations or deployments outside the terms of the community licence.

Any dual-licensing arrangement will depend on the project having the necessary rights to license all relevant contributions. Contributor and intellectual-property arrangements must therefore be established before accepting external contributions or offering commercial licences.

The AGPL licence does not grant rights to the DuoCode name, logo or other project branding.

The full AGPL licence text is in the repository’s LICENSE file. The LICENSE, NOTICE and CONTRIBUTING.md files were approved by the owners at specification Gate 6. External contributions are not yet accepted, and the contribution terms have not yet had a legal review (see CONTRIBUTING.md).

Contributing

The project is being developed collaboratively.

Contribution guidelines, coding standards, development setup instructions and issue-management procedures will be added as the implementation progresses.

Before submitting contributions, please ensure that you have the right to submit the work under the project’s licensing arrangements.

Current priorities

The immediate priorities are:

Complete the Phase 1 sign-off of the specification.
Implement the independent game engine.
Implement game and player management.
Introduce PostgreSQL persistence.
Build the automated test suite.
Develop the REST API and Postman collection.
Implement the simulator.
Validate complete games through the public API.
The browser application will follow once the backend and game behaviour have been thoroughly tested.


Project principle

Keep the game simple, the architecture clean and the implementation thoroughly tested.

DuoCode should be easy to play, straightforward to operate and flexible enough to grow beyond its initial two-player game.
