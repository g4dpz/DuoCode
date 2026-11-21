# Contributing to DuoCode

> **DRAFT FOR OWNER REVIEW (specification Gate 6).** This file is a proposal prepared for
> the two founding collaborators. It is not legal advice. Items in square brackets are
> inputs the owners still have to give. Nothing has been assumed for them:
>
> - LI-1 exact copyright holder names (see `NOTICE`),
> - LI-2 whether a contributor licence agreement is required (section 2),
> - LI-3 legal review of the contribution terms (section 2),
> - LI-4 the security contact address (section 4).
>
> Remove this notice when the owners approve the file.

DuoCode is licensed under the GNU Affero General Public License v3.0 only
(`AGPL-3.0-only`, see `LICENSE` and `NOTICE`). The founders may also offer the software
under separate commercial licences.

## 1. Current status: external contributions are closed

The project is in specification and approval mode. No application code exists yet.

**Pull requests from anyone other than the two founding collaborators will not be merged**
until the owners have approved the contribution terms in section 2 and added the
mechanism that records each contributor's agreement (for example a signed agreement or a
tool that checks it on every pull request). Issues and review comments on the
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

**[LI-2: the owners decide whether a separate contributor licence agreement is required, or whether the terms above are enough.]**
**[LI-3: these terms have not been reviewed by a lawyer. Obtain legal review before relying on them.]**
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

Do not open a public issue for a vulnerability. Email the founders at **[LI-4: security contact
address, to be provided by the owners before the repository becomes public]**. Include steps to reproduce. Do not include real
tokens, codes or personal data.

## 5. Conduct

Be courteous. Assume good faith. Criticise ideas, not people.
