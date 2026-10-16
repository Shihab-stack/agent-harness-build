# Systematic Debugging

Use this workflow when investigating a bug, failing test, crash, or unexpected
behavior. Do not guess at fixes or claim a cause before gathering evidence.

1. **Define the failure.** Restate the observed behavior, expected behavior, and
   the smallest concrete reproduction available. Ask for missing error output
   only when it is necessary to proceed.
2. **Collect evidence before editing.** Read the relevant code and tests, inspect
   the complete traceback or tool result, and identify the failing boundary.
   Separate observed facts from assumptions.
3. **State a hypothesis.** Name one likely cause and explain which observation
   supports it. If multiple causes are plausible, rank them and test them one at
   a time.
4. **Reproduce safely.** Prefer a focused existing test or a minimal local
   reproduction. Use the Python sandbox only for a self-contained Python
   experiment; it has no project files or network access, so do not claim it
   reproduced project imports or integration behavior. Do not run arbitrary
   untrusted code.
5. **Make the smallest root-cause fix.** Preserve unrelated behavior and avoid
   speculative changes. If the evidence contradicts the hypothesis, revise the
   hypothesis before editing.
6. **Verify the exact failure.** Rerun the reproducer and relevant tests, then
   inspect the resulting diff. Report commands run, outcomes, and any
   verification that could not be performed.

Never hide a failed test, invent tool output, or present an unverified
hypothesis as a confirmed root cause.
