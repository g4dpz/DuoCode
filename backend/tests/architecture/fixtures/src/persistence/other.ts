// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
// Architecture-rule fixture: deliberately violates one rule (see rules_test.ts).
export const sneaky = `
  SELECT id
  FROM
    "public"."credentials"
  WHERE id = $1`;
