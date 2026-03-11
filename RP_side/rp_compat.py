"""Compatibility helpers for Red Pitaya OS / hardware variations."""

from __future__ import annotations

import glob
import importlib
import inspect
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


FPGA_ROOT = Path("/opt/redpitaya/fpga")
OVERLAY_LOADER = Path("/opt/redpitaya/sbin/overlay.sh")
SYSFS_UIO_GLOB = "/sys/class/uio/uio*"

LEGACY_UIO_NAMES = ("clb", "gen", "osc", "scope", "la")


class OverlayLoadError(RuntimeError):
    """Raised when no usable Red Pitaya overlay backend could be loaded."""


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def discover_uio_devices() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for uio_path in sorted(Path(p) for p in glob.glob(SYSFS_UIO_GLOB)):
        index = uio_path.name.replace("uio", "")
        name = _safe_read_text(uio_path / "name")
        if name:
            mapping[name] = f"/dev/uio{index}"
    return mapping


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
    names = set(discover_uio_devices())
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
    except subprocess.CalledProcessError as exc:
        raise OverlayLoadError(
            f"Overlay loader failed for '{overlay_name}': {exc.stderr.strip() or exc.stdout.strip()}"
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


def load_overlay(preferred: Optional[str] = None):
    overlay_name = select_overlay_name(preferred)
    _run_overlay_loader(overlay_name)

    errors = []
    try:
        mercury_mod = importlib.import_module("redpitaya.overlay.mercury")
        mercury_cls = getattr(mercury_mod, "mercury")
        return _instantiate_overlay(mercury_cls, overlay_name), overlay_name
    except Exception as exc:
        errors.append(f"redpitaya.overlay.mercury: {exc}")

    for module_name in (f"redpitaya.overlay.{overlay_name}", "redpitaya.overlay"):
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
            continue

        for attr in (overlay_name, "mercury", "Overlay", "overlay"):
            overlay_cls = getattr(mod, attr, None)
            if overlay_cls is None or not callable(overlay_cls):
                continue
            try:
                return _instantiate_overlay(overlay_cls, overlay_name), overlay_name
            except Exception as exc:
                errors.append(f"{module_name}.{attr}: {exc}")

    raise OverlayLoadError(
        "Unable to import a compatible redpitaya overlay backend. "
        f"Tried overlay '{overlay_name}'. Errors: {'; '.join(errors[:4])}"
    )
