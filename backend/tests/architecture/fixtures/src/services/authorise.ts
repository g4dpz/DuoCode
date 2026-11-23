// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
// Architecture-rule fixture: allowed importer of credential_lookup (see rules_test.ts).
import { lookupSql } from "../persistence/credential_lookup.ts";

export const authorise = () => lookupSql;
