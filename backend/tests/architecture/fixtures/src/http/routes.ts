// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 The DuoCode authors (see NOTICE)
// Architecture-rule fixture: allowed: reaches persistence only through services (see rules_test.ts).
import { authorise } from "../services/authorise.ts";

export const routes = authorise;
