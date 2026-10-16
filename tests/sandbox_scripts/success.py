"""Verify basic computation and writes to the sandbox's temporary filesystem."""

from pathlib import Path

result = [0, 1]
for _ in range(8):
    result.append(result[-1] + result[-2])
path = Path("/tmp/sandbox-check.txt")
path.write_text(",".join(map(str, result)), encoding="utf-8")
assert path.read_text(encoding="utf-8") == "0,1,1,2,3,5,8,13,21,34"
print("sandbox success:", result)
