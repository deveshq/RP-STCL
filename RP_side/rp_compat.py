"""Compatibility helpers for Red Pitaya OS / hardware variations."""

from __future__ import annotations

import glob
import importlib
import inspect
import os
import subprocess
import sys
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


FPGA_ROOT = Path("/opt/redpitaya/fpga")
OVERLAY_LOADER = Path("/opt/redpitaya/sbin/overlay.sh")
SYSFS_UIO_GLOB = "/sys/class/uio/uio*"

LEGACY_UIO_NAMES = ("clb", "gen", "osc", "scope", "la")

KNOWN_REDPITAYA_PYTHON_PATHS = (
    Path("/opt/redpitaya/lib/python"),
    Path("/opt/redpitaya/lib/python3"),
    Path("/opt/redpitaya/lib/python3.10"),
    Path("/opt/redpitaya/lib/python3.11"),
    Path("/opt/redpitaya/lib/python3.12"),
    Path("/opt/redpitaya/lib/python/site-packages"),
)

KNOWN_REDPITAYA_PYTHON_PATHS = (
    Path("/opt/redpitaya/lib/python"),
    Path("/opt/redpitaya/lib/python3"),
    Path("/opt/redpitaya/lib/python3.10"),
    Path("/opt/redpitaya/lib/python3.11"),
    Path("/opt/redpitaya/lib/python3.12"),
    Path("/opt/redpitaya/lib/python/site-packages"),
)


class OverlayLoadError(RuntimeError):
    """Raised when no usable Red Pitaya overlay backend could be loaded."""


def ensure_redpitaya_python_path() -> List[str]:
    """Inject likely Red Pitaya python package paths into sys.path.

    On some OS images, the bundled `redpitaya` python package is installed in
    `/opt/redpitaya/...` but not exposed through PYTHONPATH for plain SSH
    shells. This helper discovers those directories and prepends them to
    `sys.path` so imports work regardless of the shell startup context.
    """

    added: List[str] = []

    def _add(path: Path) -> None:
        as_str = str(path)
        if path.is_dir() and as_str not in sys.path:
            sys.path.insert(0, as_str)
            added.append(as_str)

    for candidate in KNOWN_REDPITAYA_PYTHON_PATHS:
        _add(candidate)

    for root in (Path("/opt/redpitaya/lib"), Path("/opt/redpitaya")):
        if not root.exists():
            continue
        for site_pkg in sorted(root.glob("python*/site-packages")):
            _add(site_pkg)
        for dist_pkg in sorted(root.glob("python*/dist-packages")):
            _add(dist_pkg)

    return added


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def detect_board_type() -> str:
    candidates = (
        Path("/sys/firmware/devicetree/base/model"),
        Path("/proc/device-tree/model"),
    )
    for candidate in candidates:
        text = _safe_read_text(candidate)
        if text:
            return text.replace("\x00", "")
    return "unknown"


def ensure_redpitaya_python_path() -> List[str]:
    """Inject likely Red Pitaya python package paths into sys.path."""

    added: List[str] = []

    def _add(path: Path) -> None:
        as_str = str(path)
        if path.is_dir() and as_str not in sys.path:
            sys.path.insert(0, as_str)
            added.append(as_str)

    for candidate in KNOWN_REDPITAYA_PYTHON_PATHS:
        _add(candidate)

    for root in (Path("/opt/redpitaya/lib"), Path("/opt/redpitaya")):
        if not root.exists():
            continue
        for site_pkg in sorted(root.glob("python*/site-packages")):
            _add(site_pkg)
        for dist_pkg in sorted(root.glob("python*/dist-packages")):
            _add(dist_pkg)

    return added


def describe_uio_devices() -> List[Tuple[str, str]]:
    devices: List[Tuple[str, str]] = []
    for uio_path in sorted(Path(p) for p in glob.glob(SYSFS_UIO_GLOB)):
        index = uio_path.name.replace("uio", "")
        name = _safe_read_text(uio_path / "name") or "<unknown>"
        devices.append((name, f"/dev/uio{index}"))
    return devices


def discover_uio_devices() -> Dict[str, str]:
    return {name: dev for name, dev in describe_uio_devices()}


def ensure_legacy_uio_symlinks() -> Dict[str, str]:
    created: Dict[str, str] = {}
    mapping = discover_uio_devices()
    if not mapping:
        return created

    dev_uio_dir = Path("/dev/uio")
    try:
        dev_uio_dir.mkdir(parents=False, exist_ok=True)
    except OSError:
        return created

    for legacy in LEGACY_UIO_NAMES:
        if legacy not in mapping:
            continue
        link = dev_uio_dir / legacy
        target = mapping[legacy]
        try:
            if link.is_symlink() and os.readlink(link) == target:
                created[legacy] = target
                continue
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(target)
            created[legacy] = target
        except OSError:
            continue
    return created


def calibration_available() -> bool:
    names = {name for name, _ in describe_uio_devices()}
    return any("clb" in name.lower() for name in names)


def _overlay_dirs() -> List[Tuple[str, Path]]:
    dirs: List[Tuple[str, Path]] = []
    if not FPGA_ROOT.exists():
        return dirs
    for model_dir in sorted(FPGA_ROOT.iterdir()):
        if not model_dir.is_dir():
            continue
        for overlay_dir in sorted(model_dir.iterdir()):
            if overlay_dir.is_dir():
                dirs.append((model_dir.name, overlay_dir))
    return dirs


def available_overlay_names() -> List[str]:
    return list(dict.fromkeys(overlay.name for _, overlay in _overlay_dirs()))


def candidate_overlay_paths(overlay_name: str) -> List[Path]:
    paths: List[Path] = []
    for model, _ in _overlay_dirs():
        root = FPGA_ROOT / model / overlay_name
        paths.extend(
            [
                root,
                root / "fpga.bit",
                root / "fpga.bit.bin",
                root / "git_info.txt",
                root / "metadata" / "git_info.txt",
            ]
        )
    paths.extend(
        [
            FPGA_ROOT / overlay_name,
            FPGA_ROOT / overlay_name / "fpga.bit",
            FPGA_ROOT / overlay_name / "fpga.bit.bin",
            Path("/opt/redpitaya") / overlay_name,
            Path("/opt/redpitaya") / "overlay" / overlay_name,
            Path("/opt/redpitaya") / "fpga" / overlay_name,
        ]
    )
    # remove duplicates while preserving order
    uniq: List[Path] = []
    seen = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(path)
    return uniq


def print_overlay_path_diagnostics(overlay_name: str) -> List[Tuple[str, bool]]:
    print(f"[rp_compat] Overlay requested: {overlay_name}")
    checked: List[Tuple[str, bool]] = []
    for path in candidate_overlay_paths(overlay_name):
        exists = path.exists()
        checked.append((str(path), exists))
        print(f"[rp_compat] overlay path check: {path} -> {'EXISTS' if exists else 'MISSING'}")
        if not exists:
            parent = path.parent
            print(f"[rp_compat]   parent search root: {parent}")
            try:
                if parent.exists() and parent.is_dir():
                    children = sorted(p.name for p in parent.iterdir())[:15]
                    print(f"[rp_compat]   parent entries ({len(children)} shown): {children}")
                else:
                    print("[rp_compat]   parent directory does not exist")
            except OSError as exc:
                print(f"[rp_compat]   could not list parent directory: {exc}")
    return checked


def select_overlay_name(preferred: Optional[str] = None) -> str:
    if preferred:
        return preferred

    env_name = os.environ.get("RP_OVERLAY_NAME")
    if env_name:
        return env_name

    names = available_overlay_names()
    if "mercury" in names:
        return "mercury"

    versioned = sorted(name for name in names if name.startswith("v"))
    if versioned:
        return versioned[-1]

    return "mercury"


def _run_overlay_loader(overlay_name: str) -> None:
    print(f"[rp_compat] overlay loader script: {OVERLAY_LOADER}")
    print(f"[rp_compat] overlay loader exists: {OVERLAY_LOADER.exists()}")
    if not OVERLAY_LOADER.exists():
        return
    try:
        subprocess.run(
            [str(OVERLAY_LOADER), overlay_name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        print(f"[rp_compat] overlay loader executed successfully for '{overlay_name}'")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        print(f"[rp_compat] overlay loader failed stdout: {stdout}")
        print(f"[rp_compat] overlay loader failed stderr: {stderr}")
        raise OverlayLoadError(
            f"Overlay loader failed for '{overlay_name}': {stderr or stdout}"
        ) from exc


def _instantiate_overlay(overlay_cls, overlay_name: str):
    signature = inspect.signature(overlay_cls)
    kwargs = {}
    if "overlay" in signature.parameters:
        kwargs["overlay"] = overlay_name
    if "load" in signature.parameters:
        kwargs["load"] = True
    try:
        return overlay_cls(**kwargs)
    except TypeError:
        return overlay_cls()


def startup_diagnostics(preferred_overlay: Optional[str] = None) -> Dict[str, object]:
    added_paths = ensure_redpitaya_python_path()
    overlay_name = select_overlay_name(preferred_overlay)
    board = detect_board_type()
    uio_devices = describe_uio_devices()

    print("[rp_compat] ===== Red Pitaya startup diagnostics =====")
    print(f"[rp_compat] board type: {board}")
    print(f"[rp_compat] selected overlay name: {overlay_name}")
    print(f"[rp_compat] python executable: {sys.executable}")
    print(f"[rp_compat] added python search paths: {added_paths}")
    print("[rp_compat] full sys.path for redpitaya import resolution:")
    for idx, path in enumerate(sys.path):
        print(f"[rp_compat]   sys.path[{idx}] = {path}")

    print("[rp_compat] detected UIO devices:")
    if not uio_devices:
        print("[rp_compat]   none found under /sys/class/uio")
    for name, dev in uio_devices:
        print(f"[rp_compat]   {dev} name={name}")

    overlay_paths = print_overlay_path_diagnostics(overlay_name)
    print("[rp_compat] ===== end startup diagnostics =====")

    return {
        "board_type": board,
        "overlay_name": overlay_name,
        "uio_devices": uio_devices,
        "overlay_paths": overlay_paths,
        "sys_path": list(sys.path),
        "added_paths": added_paths,
    }


def load_overlay(preferred: Optional[str] = None):
    diagnostics = startup_diagnostics(preferred)
    overlay_name = diagnostics["overlay_name"]
    _run_overlay_loader(overlay_name)

    errors = []
    attempted_modules: List[str] = []

    for module_name, class_name in (
        ("redpitaya.overlay.mercury", "mercury"),
        ("overlay.mercury", "mercury"),
        ("mercury", "mercury"),
    ):
        attempted_modules.append(module_name)
        print(f"[rp_compat] import attempt: module={module_name}, class={class_name}")
        print(f"[rp_compat] import resolution sys.path: {sys.path}")
        try:
            mercury_mod = importlib.import_module(module_name)
            mercury_cls = getattr(mercury_mod, class_name)
            print(f"[rp_compat] import success: {module_name}.{class_name}")
            return _instantiate_overlay(mercury_cls, overlay_name), overlay_name
        except Exception as exc:
            print(f"[rp_compat] import failed: {module_name} -> {exc}")
            errors.append(f"{module_name}: {exc}")

    for module_name in (
        f"redpitaya.overlay.{overlay_name}",
        "redpitaya.overlay",
        f"overlay.{overlay_name}",
        "overlay",
    ):
        attempted_modules.append(module_name)
        print(f"[rp_compat] import attempt: module={module_name}")
        print(f"[rp_compat] import resolution sys.path: {sys.path}")
        try:
            mod = importlib.import_module(module_name)
            print(f"[rp_compat] import success: {module_name}")
        except Exception as exc:
            print(f"[rp_compat] import failed: {module_name} -> {exc}")
            errors.append(f"{module_name}: {exc}")
            continue

        for attr in (overlay_name, "mercury", "Overlay", "overlay"):
            overlay_cls = getattr(mod, attr, None)
            if overlay_cls is None or not callable(overlay_cls):
                continue
            try:
                print(f"[rp_compat] trying overlay class: {module_name}.{attr}")
                return _instantiate_overlay(overlay_cls, overlay_name), overlay_name
            except Exception as exc:
                print(f"[rp_compat] overlay class failed: {module_name}.{attr} -> {exc}")
                errors.append(f"{module_name}.{attr}: {exc}")

    checked_paths = diagnostics.get("overlay_paths", [])
    checked_msg = "; ".join(
        f"{path}={'EXISTS' if exists else 'MISSING'}" for path, exists in checked_paths
    )
    module_msg = ", ".join(attempted_modules)
    raise OverlayLoadError(
        "Unable to import/load a compatible Red Pitaya overlay backend. "
        f"Board: {diagnostics.get('board_type', 'unknown')}. "
        f"Overlay: '{overlay_name}'. "
        f"Attempted modules: {module_msg}. "
        f"Overlay filesystem checks: {checked_msg}. "
        f"Import errors: {'; '.join(errors[:12])}."
    )
