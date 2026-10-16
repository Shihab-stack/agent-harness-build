"""Attempt a 1 GiB allocation; the sandbox should reject or kill it."""

try:
    allocation = bytearray(1024 * 1024 * 1024)
except MemoryError:
    print("memory allocation rejected")
else:
    del allocation
    raise SystemExit("1 GiB allocation unexpectedly succeeded")
