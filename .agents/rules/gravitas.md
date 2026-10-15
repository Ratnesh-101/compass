# Slash Command: /gravitas

When the user starts a prompt with `/gravitas` or mentions `/gravitas`:
1. **Explicit Trigger**: Treat `/gravitas` as an explicit command to activate and strictly adhere to the `gravitas` skill (`SKILL.md`).
2. **The 6 Invariants**:
   - **Ground before mutating**: Inspect target files, related dependencies, and existing tests before making any edits.
   - **Stay in declared scope**: Only modify files within the declared scope.
   - **Completion needs evidence**: Only claim a task or bug is resolved when verified by actual test/command output run *after* the mutation.
   - **Never exact-retry a failure**: When an approach fails, change diagnosis, context, or strategy before re-attempting.
   - **Satisfy the contract**: All acceptance criteria and validators must pass.
   - **Say what you can't verify**: Be transparent about any assumptions or untestable states.
3. **Policy Record**: For non-trivial engineering tasks, declare the planning level (`direct` | `compact` | `full`) and verification depth (`local` | `impact` | `full`) before making changes.
