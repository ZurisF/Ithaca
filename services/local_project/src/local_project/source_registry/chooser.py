"""Native macOS folder selection; the chosen path stays inside Local Runtime."""

import asyncio
import sys

from local_project.errors import LocalError

PICKER_TIMEOUT_SECONDS = 180
PICKER_SCRIPT = 'POSIX path of (choose folder with prompt "选择用于项目面试的目录")'


async def choose_directory() -> str:
    if sys.platform != "darwin":
        raise LocalError(503, "source_picker_unavailable", "当前系统没有可用的本地目录选择器。")
    try:
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/osascript",
            "-e",
            PICKER_SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(), timeout=PICKER_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        process.terminate()
        await process.wait()
        raise LocalError(408, "source_picker_timeout", "目录选择已超时。") from exc
    except OSError as exc:
        raise LocalError(503, "source_picker_unavailable", "本地目录选择器无法启动。") from exc
    if process.returncode != 0:
        raise LocalError(409, "source_picker_cancelled", "未选择目录。")
    path = stdout.decode("utf-8", errors="strict").strip()
    if not path:
        raise LocalError(409, "source_picker_cancelled", "未选择目录。")
    return path
