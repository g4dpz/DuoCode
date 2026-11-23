// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
// Architecture-rule fixture: the one module allowed to read credentials (see rules_test.ts).
export const lookupSql = `SELECT id FROM credentials WHERE token_hash = $1`;
