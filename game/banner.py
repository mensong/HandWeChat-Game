"""启动横幅：字符画 LOGO 与启动信息块。"""
from __future__ import annotations

import os
import sys
import unicodedata
from collections.abc import Iterable, Sequence

SERVICE_TITLE = "微信群社交游戏服务"

LOGO_LINES = (
    r"__        __        ____  _             _    ____          _   ",
    r"\ \      / /  ___  / ___|| |__    __ _ | |_ | __ )   ___  | |_ ",
    r" \ \ /\ / /  / _ \| |    | '_ \  / _` || __||  _ \  / _ \ | __|",
    r"  \ V  V /  |  __|| |___ | | | || (_| || |_ | |_) || (_) || |_ ",
    r"   \_/\_/    \___| \____||_| |_| \__,_| \__||____/  \___/  \__|",
)

RESET = "\033[0m"
LOGO_COLOR = "\033[1;36m"
LABEL_COLOR = "\033[36m"
DIM = "\033[2m"
SEPARATOR = "-" * 66
INDENT = "  "


def use_color(stream=None) -> bool:
    """stdout 是终端时上色；重定向、NO_COLOR 或无法启用 VT 时降级。"""
    if os.environ.get("NO_COLOR"):
        return False
    stream = stream if stream is not None else sys.stdout
    try:
        if not stream.isatty():
            return False
    except (AttributeError, OSError, ValueError):
        return False
    if os.name == "nt":
        return _enable_windows_vt(stream)
    return True


def _enable_windows_vt(stream) -> bool:
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.windll.kernel32
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004
        if mode.value & enable_vt:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except (AttributeError, ImportError, OSError, ValueError):
        return False


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def render_logo(version: str, *, color: bool = False) -> str:
    lines = [INDENT + line for line in LOGO_LINES]
    lines.append("")
    title = f"{SERVICE_TITLE}  v{version}" if version else SERVICE_TITLE
    if color:
        lines = [f"{LOGO_COLOR}{line}{RESET}" if line else line
                 for line in lines]
        title = f"\033[1m{title}{RESET}"
    lines.append(INDENT + title)
    return "\n".join(lines)


def render_info(info: Sequence[tuple[str, str]], *, color: bool = False) -> str:
    rows = list(info)
    width = max((_display_width(k) for k, _ in rows), default=0)
    sep = f"{DIM}{SEPARATOR}{RESET}" if color else SEPARATOR
    lines = [sep]
    for key, value in rows:
        label = _pad(key, width)
        if color:
            label = f"{LABEL_COLOR}{label}{RESET}"
        lines.append(f"{INDENT}{label}  {value}")
    lines.append(sep)
    return "\n".join(lines)


def print_logo(version: str, stream=None) -> None:
    stream = stream if stream is not None else sys.stdout
    print(render_logo(version, color=use_color(stream)), file=stream, flush=True)


def print_info(info: Iterable[tuple[str, str]], stream=None) -> None:
    stream = stream if stream is not None else sys.stdout
    print(render_info(list(info), color=use_color(stream)), file=stream,
          flush=True)
