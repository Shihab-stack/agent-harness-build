# Environment Doctor

Use this workflow when an application will not start, a dependency cannot be
found, a service is unreachable, or a port/environment setup is suspected.

1. Define the failing command, working directory, expected behavior, and full
   error. Distinguish host, virtual environment, container, and remote-service
   contexts.
2. Inspect runtime and dependency state with available tools. Prefer
   project-declared versions and lockfiles over assumptions; report exact
   versions and commands actually checked.
3. Check required environment variable **names** and whether they are set, but
   never print, copy, or ask the user to paste secret values. Check the
   relevant configuration file without disclosing credentials.
4. For a suspected port conflict, inspect listeners with an available
   read-only diagnostic (for example `lsof -nP -iTCP:<port> -sTCP:LISTEN` on
   macOS/Linux). Explain which process owns the port. Never kill a process,
   change firewall settings, or alter machine-wide configuration without
   explicit user approval.
5. Test connectivity from the same environment where the app runs. A host
   connection does not prove a container can connect, and sandboxed Python has
   no network by design.
6. Rank causes by evidence, suggest the least disruptive correction, and
   verify it. If shell or diagnostic tools are unavailable, state that limit
   and give the user a specific command to run; do not invent results.
