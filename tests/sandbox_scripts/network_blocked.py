"""Verify the sandbox cannot establish an external HTTPS connection."""

import urllib.error
import urllib.request

try:
    urllib.request.urlopen("https://example.com", timeout=5)
except (urllib.error.URLError, TimeoutError, OSError) as exc:
    print(f"network blocked: {type(exc).__name__}")
else:
    raise SystemExit("network unexpectedly available")
