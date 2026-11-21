DuoCode

Two players. Two secrets. One challenge.

DuoCode is a modern, browser-first social code-breaking game.

Challenge a friend by sharing an invitation link. Each player creates a secret code and attempts to discover the other’s. Play at your own pace, without needing to be online at the same time.

No mandatory registration. No installation. Just share a link and play.

DuoCode is the working product name. The project uses an original identity, artwork and visual design.

The Idea

DuoCode takes the familiar appeal of code-breaking puzzles and gives it a social twist.

Create a game and choose your secret code.
Share an invitation link with a friend.
Your friend joins and creates their secret code.
Both players attempt to crack each other’s codes.
Compare results and challenge each other again.
Games are asynchronous, so players can take their turns whenever convenient.

Product Goals

Simple invitation-based gameplay.
Two-player asynchronous challenges.
No mandatory user accounts.
Responsive mobile and desktop browser support.
Server-authoritative game rules.
Secure handling of secret codes and player identities.
API-first architecture.
Thorough automated testing and game simulation.
Future white-label and commercial deployment options.
Game Rules

The initial game configuration is:

Parameter

Value

Players

2

Code positions

4

Available symbols

6

Repeated symbols

Allowed

Maximum guesses

10 per player

Gameplay

Asynchronous

Feedback identifies exact matches and misplaced matches without revealing their positions.

Both players independently attempt to solve the opponent’s code.

The game concludes when both players have either solved their challenge or exhausted their attempts.

Technology

The initial architecture is deliberately simple and API-first.

Component

Technology

Language

TypeScript

Runtime

Deno

HTTP framework

Oak

Backend

REST API

API specification

OpenAPI 3.1

Database

PostgreSQL

Deployment

Docker Compose

Platform

Linux VPS

API testing

curl / Postman

Automated testing

Deno test framework

CI/CD

GitHub Actions

Technology choices may evolve through the design review process.

Development Philosophy

API first

The complete game must be playable through the REST API without a graphical interface.

Independent game engine

Game rules, code validation, feedback calculation and winner determination shall be independent of the HTTP framework and database.

Server authoritative

The server controls game state, validates moves and calculates feedback. Clients cannot determine or manipulate game outcomes.

Automated testing

Testing is part of the development process from the beginning.

Stateless architecture

Application instances shall be independently deployable and capable of horizontal scaling.

Incremental development

Build a reliable game first. Introduce additional platform capabilities only when justified.

Automated Testing and Simulation

DuoCode will include a dedicated automated game simulation tool.

The simulator will exercise the public REST API using two independent player identities.

Planned capabilities include:

Automated complete game play.
Random and systematic player strategies.
Logic-based code-breaking strategies.
Configurable numbers of games.
Concurrent game sessions.
Deterministic random seeds.
Independent feedback verification.
Reproducible failed games.
Machine-readable test results.
Example:

deno task simulate \
  --games 1000 \
  --seed 12345 \
  --concurrency 20
The simulator will complement unit tests, integration tests, API contract tests and load testing.

Architecture

The initial system comprises:

API Clients
   |
   | REST / HTTPS
   |
Deno / Oak API
   |
   +-- Game Engine
   |
   +-- Game Management
   |
   +-- Player Management
   |
   +-- Results Management
   |
PostgreSQL
The backend will be stateless, with PostgreSQL providing authoritative persistence.

The API will support future browser, Android and iOS clients without requiring changes to the underlying game engine.

White-label and Commercial Opportunities

White-label capability is an important future product objective.

The architecture will keep the game engine, API, presentation and tenant configuration independent.

Potential future capabilities include:

Custom branding and logos.
Custom colour schemes and visual themes.
Custom domains.
Configurable game rules.
Club and society editions.
Educational editions.
Corporate and promotional deployments.
Independently hosted or managed installations.
White-label functionality is not part of the initial MVP. The initial design will simply avoid architectural decisions that prevent it.

Licensing

DuoCode is intended to be released under the GNU Affero General Public License v3.0 only (AGPL-3.0-only).

The licence permits use, modification and distribution, including commercial use, subject to its terms.

Where modified software is offered as a network service, the applicable AGPL source-code disclosure requirements must be respected.

The project intends to preserve the possibility of separate commercial licensing, including white-label and proprietary deployments.

Commercial licensing will be subject to appropriate agreements with all relevant rights holders.

See LICENSE for the full licence text.

Development Status

Early development — requirements and architecture definition.

Planned development phases:

Requirements and architecture review.
Independent game engine.
REST API and PostgreSQL persistence.
API integration testing.
Automated game simulator.
Backend MVP acceptance.
Responsive browser application.
PWA and beta release.
Future white-label and commercial development.
The first milestone is a complete two-player game playable entirely through curl or Postman.

Repository Structure

The repository is expected to evolve towards:

duocode/
├── .github/
│   └── workflows/
├── .kiro/
│   └── specs/
│       └── duocode/
├── backend/
├── tools/
│   ├── game-simulator/
│   └── api-client/
├── postman/
├── openapi/
├── docs/
├── web/
├── deployment/
├── README.md
├── CONTRIBUTING.md
├── LICENSE
└── .gitignore
Collaboration

DuoCode is being developed collaboratively.

The project uses:

Kiro for requirements, architecture and implementation planning.
GitHub for source control, collaboration and pull requests.
GitHub Copilot for independent design and code reviews.
Automated CI for build and test verification.
Architectural and product decisions remain the responsibility of the project collaborators.

Project Status

The current priority is to establish a robust, thoroughly tested API-only game before developing the browser interface.

Build the game first. Prove the engine. Validate the API. Then build the experience.


DuoCode — Two players. Two secrets. One challenge.
