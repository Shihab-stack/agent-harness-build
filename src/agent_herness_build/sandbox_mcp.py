"""MCP server for running Python in disposable, network-isolated containers."""

import asyncio
import os
import secrets
import shutil
import subprocess
import threading
import time
from typing import BinaryIO

from mcp.server.mcpserver import MCPServer

IMAGE = "agent-harness-python:3.13"
MAX_SCRIPT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
RUN_TIMEOUT_SECONDS = 30
CONTROL_TIMEOUT_SECONDS = 5


def _docker_command(container_name: str) -> list[str]:
    """Build the fixed Docker command; user input is sent only over stdin."""
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI not found. Install Docker Desktop and retry.")
    return [
        docker,
        "run",
        "--pull=never",
        "--name",
        container_name,
        "--rm",
        "--interactive",
        "--network=none",
        "--cpus=0.5",
        "--memory=256m",
        "--memory-swap=256m",
        "--pids-limit=64",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--workdir=/tmp",
        IMAGE,
        "python",
        "-I",
        "-",
    ]


def _kill_container(docker: str, container_name: str) -> str | None:
    try:
        result = subprocess.run(
            [docker, "kill", container_name],
            check=False,
            capture_output=True,
            timeout=CONTROL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        result = None
    if result is not None and result.returncode == 0:
        return None

    try:
        cleanup = subprocess.run(
            [docker, "rm", "--force", "--time", "0", container_name],
            check=False,
            capture_output=True,
            timeout=CONTROL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "Docker did not respond while stopping the sandbox container"
    if cleanup.returncode:
        detail = cleanup.stderr.decode("utf-8", errors="replace").strip()
        return f"Could not stop sandbox container: {detail or cleanup.returncode}"
    return None


def run_script(python_code: str) -> str:
    """Execute Python code in a fresh Docker container with strict limits."""
    if not isinstance(python_code, str) or not python_code.strip():
        return "error: python_code must be a non-empty string"
    try:
        script_bytes = python_code.encode("utf-8")
    except UnicodeEncodeError:
        return "error: python_code must contain valid Unicode text"
    if len(script_bytes) > MAX_SCRIPT_BYTES:
        return f"error: python_code exceeds the {MAX_SCRIPT_BYTES}-byte limit"

    try:
        command = _docker_command(f"agent-harness-{secrets.token_hex(12)}")
    except RuntimeError as exc:
        return f"error: {exc}"

    docker = command[0]
    container_name = command[command.index("--name") + 1]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return f"error: could not start Docker: {exc}"
    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        return "error: Docker process pipes could not be created"

    output = {"stdout": bytearray(), "stderr": bytearray()}
    output_size = 0
    output_lock = threading.Lock()
    output_limit_reached = threading.Event()

    def drain(name: str, stream: BinaryIO) -> None:
        nonlocal output_size
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with output_lock:
                available = max(0, MAX_OUTPUT_BYTES - output_size)
                output[name].extend(chunk[:available])
                output_size += min(len(chunk), available)
                if len(chunk) > available:
                    output_limit_reached.set()

    def write_input(stream: BinaryIO) -> None:
        try:
            stream.write(script_bytes)
            stream.close()
        except (BrokenPipeError, OSError, AttributeError):
            pass

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
        threading.Thread(target=write_input, args=(process.stdin,), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    termination_reason: str | None = None
    stop_error: str | None = None
    while process.poll() is None:
        if output_limit_reached.is_set():
            termination_reason = "output limit exceeded"
            stop_error = _kill_container(docker, container_name)
            break
        if time.monotonic() >= deadline:
            termination_reason = f"execution timed out after {RUN_TIMEOUT_SECONDS} seconds"
            stop_error = _kill_container(docker, container_name)
            break
        time.sleep(0.05)

    try:
        return_code = process.wait(timeout=CONTROL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            return_code = process.wait(timeout=CONTROL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait()
    for reader in readers:
        reader.join(timeout=CONTROL_TIMEOUT_SECONDS)

    stdout = bytes(output["stdout"]).decode("utf-8", errors="replace")
    stderr = bytes(output["stderr"]).decode("utf-8", errors="replace")
    if termination_reason:
        detail = f"\n{stop_error}" if stop_error else ""
        if stderr:
            detail += f"\n{stderr}"
        return f"error: {termination_reason}{detail}"
    if return_code == 137:
        return (
            "error: container exited with code 137 "
            "(likely the memory limit was exceeded)"
        )

    result = f"exit_code: {return_code}\nstdout:\n{stdout}"
    if stderr:
        result += f"\nstderr:\n{stderr}"
    if output_limit_reached.is_set():
        result += f"\noutput truncated at {MAX_OUTPUT_BYTES} bytes"
    return result


server = MCPServer(name="agent-harness-python-sandbox")
server.add_tool(run_script)


if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
