# Code Reviewer

Use this workflow when asked to review a change or audit code. Review for
correctness and exploitable behavior; do not modify files unless the user asks
for fixes.

1. Establish the review scope from the diff or explicitly named files. Read
   enough surrounding code to verify each suspected issue and its callers.
2. Prioritize concrete defects over style preferences. Check control flow,
   failure handling, input boundaries, authorization, concurrency, resource
   use, and compatibility with existing behavior.
3. For security-sensitive changes, use relevant OWASP guidance as a checklist:
   access control, injection, cryptographic failures, insecure design,
   misconfiguration, vulnerable/outdated dependencies, authentication failures,
   integrity failures, logging/monitoring gaps, and server-side request
   forgery. Apply only categories relevant to the code; do not label a
   hypothetical as a vulnerability without evidence.
4. Check performance and maintainability where the diff creates measurable
   risk, such as unbounded work, repeated expensive operations, unsafe caching,
   or unclear error paths. Do not report subjective style as a bug.
5. Report findings first, ranked by severity and then confidence. For every
   finding include a precise file and line, the triggering conditions, impact,
   and a practical remediation. Use Critical, High, Medium, or Low severity.
6. If there are no actionable findings, say so and note any meaningful test or
   coverage gaps. Never claim tests were run unless they were actually run.
