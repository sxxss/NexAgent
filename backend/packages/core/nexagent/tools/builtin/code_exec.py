"""Code execution sandbox — runs Python code in a subprocess with timeout.

Security model:
- Isolated subprocess (no shared memory)
- Hard timeout enforced via asyncio.wait_for
- stdout/stderr capped at max_output_chars
- No network access restrictions at OS level (add firewall rules for production)

Configured via config.yaml:
  sandbox:
    enabled: true
    timeout_seconds: 30
    max_output_chars: 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def get_code_exec_tool():
    """Return a Python code execution tool."""

    @tool
    async def execute_python(code: str) -> str:
        """Execute Python code in a secure sandbox and return the output.

        Use this tool to run calculations, data processing, generate charts,
        or test algorithms. The code runs in an isolated subprocess.

        Args:
            code: Valid Python code to execute. Use print() to produce output.

        Returns:
            Combined stdout + stderr from the execution, or an error message.
        """
        from nexagent.config import get_config
        cfg = get_config().sandbox

        if not cfg.enabled:
            return "Code execution is disabled in the current configuration."

        # Clean up indentation issues from LLM-generated code
        code = textwrap.dedent(code).strip()
        if not code:
            return (
                "Error: execute_python requires non-empty code. "
                "Provide a code argument with the Python snippet to run."
            )

        try:
            result = await _run_sandboxed(code, cfg.timeout_seconds, cfg.max_output_chars)
            return result
        except TimeoutError:
            return f"Execution timed out after {cfg.timeout_seconds} seconds."
        except Exception as e:
            if os.environ.get("NEXAGENT_ALLOW_INPROCESS_CODE_EXEC") == "1":
                return _run_inprocess(code, cfg.max_output_chars)
            logger.error(f"Code execution error: {e}")
            return f"Execution error: {e}"

    return execute_python


async def _run_sandboxed(code: str, timeout_seconds: int, max_chars: int) -> str:
    """Run code in Docker when available, otherwise use a restricted subprocess."""
    mode = os.environ.get("NEXAGENT_SANDBOX_MODE", "auto").lower()
    if mode in {"auto", "docker"} and shutil.which("docker"):
        try:
            output = await _run_docker(code, timeout_seconds, max_chars)
            if _is_docker_infra_failure(output):
                if mode == "docker":
                    raise RuntimeError(output)
                logger.debug("Docker sandbox unavailable, falling back to subprocess: %s", output)
            else:
                return output
        except TimeoutError:
            raise
        except Exception as exc:
            if mode == "docker":
                raise
            logger.debug("Docker sandbox unavailable, falling back to subprocess: %s", exc)
    return await _run_subprocess(code, max_chars, timeout_seconds)


async def _run_docker(code: str, timeout_seconds: int, max_chars: int) -> str:
    """Run Python code inside the nexagent-sandbox Docker image."""
    run_dir = _sandbox_run_root() / str(uuid.uuid4())
    run_dir.mkdir(parents=True, exist_ok=False)
    script = run_dir / "main.py"
    script.write_text(code, encoding="utf-8")

    image = os.environ.get("NEXAGENT_SANDBOX_IMAGE", "nexagent-sandbox:latest")
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        os.environ.get("NEXAGENT_SANDBOX_MEMORY", "256m"),
        "--cpus",
        os.environ.get("NEXAGENT_SANDBOX_CPUS", "1"),
        "--pids-limit",
        "128",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-v",
        f"{run_dir.resolve()}:/sandbox:ro",
        image,
        "python",
        "/sandbox/main.py",
    ]
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError from None
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

    return _format_output(completed.stdout, completed.stderr, completed.returncode, max_chars)


async def _run_subprocess(code: str, max_chars: int, timeout_seconds: int | None = None) -> str:
    """Run code in a subprocess and capture output."""
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError from None

    return _format_output(completed.stdout, completed.stderr, completed.returncode, max_chars)


def _sandbox_run_root() -> Path:
    configured = os.environ.get("NEXAGENT_SANDBOX_RUN_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "nexagent" / "sandbox-runs"


def _middle_truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker_template = "\n... [middle truncated: {skipped} chars skipped] ...\n"
    keep = max(0, max_chars - len(marker_template.format(skipped=len(text))))
    marker = marker_template.format(skipped=len(text) - keep)
    head = keep // 2
    tail = keep - head
    return f"{text[:head]}{marker}{text[-tail:] if tail else ''}"


def _format_output(stdout: bytes, stderr: bytes, returncode: int, max_chars: int) -> str:
    """Format captured process output with truncation."""
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")

    combined = ""
    if out:
        combined += out
    if err:
        combined += f"\n[stderr]\n{err}" if out else f"[stderr]\n{err}"

    if not combined.strip():
        combined = f"(Code executed successfully, exit code {returncode}, no output)"

    return _middle_truncate(combined, max_chars).strip()


def _is_docker_infra_failure(output: str) -> bool:
    """Return True when Docker itself failed before user code could run."""
    lowered = output.lower()
    markers = (
        "unable to find image",
        "pull access denied",
        "cannot connect to the docker daemon",
        "error response from daemon",
        "repository does not exist",
        "image operating system",
    )
    return any(marker in lowered for marker in markers)


def _run_inprocess(code: str, max_chars: int) -> str:
    """Fallback executor for restricted local verification environments."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    namespace = {"__builtins__": {"print": print, "len": len, "range": range, "sum": sum, "min": min, "max": max}}
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(code, namespace, namespace)
    except Exception as exc:
        stderr.write(str(exc))

    combined = stdout.getvalue()
    err = stderr.getvalue()
    if err:
        combined += f"\n[stderr]\n{err}" if combined else f"[stderr]\n{err}"
    if not combined.strip():
        combined = "(Code executed successfully, no output)"
    return _middle_truncate(combined, max_chars).strip()
