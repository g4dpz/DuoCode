# Contributing to DuoCode

> **Approved by the owners at specification Gate 6 on 2026-11-22.** This file is not legal
> advice. The contribution terms in section 2 have not yet had a legal review (LI-3).
> External contributions stay closed (section 1).

DuoCode is licensed under the GNU Affero General Public License v3.0 only
(`AGPL-3.0-only`, see `LICENSE` and `NOTICE`). The founders may also offer the software
under separate commercial licences.

## 1. Current status: external contributions are closed

The project is in specification and approval mode. No application code exists yet.

**Pull requests from anyone other than the two founding collaborators will not be merged**
until the owners have added the mechanism that records each contributor's agreement to
the terms in section 2 (for example a tool that checks it on every pull request). No
separate contributor licence agreement is used (section 2). Issues and review comments on the
specification are welcome.

## 2. Contribution terms (proposal)

These terms exist because a plain AGPL contribution does not by itself give the project
the right to offer that contribution under a commercial licence. The project does not
assume that it does.

By submitting a contribution (code, tests, documentation, specification text or artwork)
you confirm that:

1. **You have the right to submit it.** You wrote it, or you have permission from the
   owner of every part you did not write, and your employer or school, if any, has
   waived or agreed to the contribution. You are not submitting anything you copied from
   another game's code, branding, artwork or distinctive visual presentation.
2. **Licence to the project.** You keep your copyright. You grant the DuoCode copyright
   holders a perpetual, worldwide, non-exclusive, royalty-free, irrevocable licence to
   use, copy, modify, distribute and sublicense your contribution, in source or object
   form, **including under `AGPL-3.0-only` and under separate commercial licence terms**.
3. **Patents.** You grant a corresponding patent licence for any patent claims you own
   that your contribution necessarily infringes.
4. **Public record.** You understand the contribution and a record of it, including your
   name and email address as given in the commit, may be kept and published indefinitely.
5. **Sign-off.** Every commit carries a `Signed-off-by:` line matching the
   [Developer Certificate of Origin 1.1](https://developercertificate.org/) (`git commit -s`).
   The DCO covers point 1 only. Points 2 and 3 need the agreement described in section 1.
6. **Tools.** If AI tools helped write your contribution, you are still responsible for
   it. You must have checked that it is yours to submit under these terms.

**No separate contributor licence agreement is required** (owner decision LI-2,
2026-11-22). The terms above are the contribution terms.

**Legal review outstanding** (LI-3). These terms have not been reviewed by a lawyer.
Because no separate agreement is used, the project's right to offer outside contributions
under commercial licence terms rests on point 2 alone. Obtain legal review before relying
on them.
A plain DCO sign-off does not on its own grant the rights in points 2 and 3.

## 3. How to work on the project

- Read `.kiro/specs/duocode/requirements.md` and the other files in that directory first.
  The specification is the source of truth. Behaviour changes start with a change to the
  specification, in the file that owns the topic (see the table in `requirements.md`).
- Do not decide product or security questions silently. Record them in the decision
  register in `requirements.md`.
- Work on a branch. Open a pull request. Required checks must pass. Changes to
  architecture, security, the OpenAPI contract or the database schema need a review from
  both founders. GitHub Copilot review is used as an independent check and is not a
  substitute for owner approval.
- Tests first. Use a real PostgreSQL for integration and concurrency tests.
- Every source file starts with the licence header shown in `NOTICE`.
- Never commit secrets, `.env` files, key material, compiled binaries or build output.
- Keep changes small and in scope. Do not add features outside the current task.

## 4. Reporting security problems

Do not open a public issue for a vulnerability. Write to the founders at
**96 Summerfields Avenue, Halesowen, B62 9NR**. Include steps to reproduce. Do not include
real tokens, codes or personal data.

## 5. Conduct

Be courteous. Assume good faith. Criticise ideas, not people.
