# Git Commit Writer

Use this workflow to propose a Conventional Commit message for staged changes.
Do not stage, unstage, discard, or commit changes unless the user explicitly
asks for that action.

1. Inspect `git status --short` and the staged diff (`git diff --cached`).
   Review unstaged changes only to understand context; do not describe them as
   part of the commit.
2. If nothing is staged, say so and ask whether the user wants a message based
   on all changes or wants to stage specific files. Never stage files
   automatically.
3. Summarize the user-visible intent of the staged diff. Choose the narrowest
   accurate type: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, or
   `chore`.
4. Write `type(scope): imperative summary` when a useful scope is clear.
   Keep the subject concise, imperative, and focused on the main change.
   Include a body only when it adds important context; describe breaking
   changes with a `BREAKING CHANGE:` footer.
5. Ensure the message does not claim work absent from the staged diff. Present
   the proposed message in a copyable code block and briefly explain its type.
   Do not claim to have committed anything unless a commit was explicitly
   requested and successfully created.
