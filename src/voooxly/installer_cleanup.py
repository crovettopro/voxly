"""Cleans up the installer disk image left mounted after a drag-install.

macOS has no native prompt for this. The "move the Installer to the Trash?"
dialog people remember belongs to Installer.app, which a drag-to-Applications
DMG never invokes, so the volume stays mounted forever. This module offers the
equivalent once, on the first launch of an installed copy.

Detection goes through the backing .dmg reported by `hdiutil info`, never
through /Volumes/Voooxly: macOS renames a volume on collision, so a second
copy mounts as "Voooxly 1" and a path check would miss it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PREF_KEY = "installer_cleanup_done"


@dataclass(frozen=True)
class MountedInstaller:
    dmg_path: Path      # the .dmg backing the mounted volume
    device: str         # first dev-entry, kept for logs only
    mount_point: Path   # /Volumes/Voooxly 1


def parse_hdiutil_info(info: dict) -> list[MountedInstaller]:
    """Mounted Voooxly installers, from a parsed `hdiutil info -plist`.

    Pure on purpose: the interesting cases (APFS images with several
    dev-entries, colliding volume names, other people's installers) are all
    testable without touching a real disk image.
    """
    found: list[MountedInstaller] = []
    for img in info.get("images", []):
        path = img.get("image-path")
        if not path:
            continue
        name = Path(path).name.lower()
        if not (name.startswith("voooxly") and name.endswith(".dmg")):
            continue
        entities = img.get("system-entities", [])
        mount = next((e.get("mount-point") for e in entities if e.get("mount-point")), None)
        if not mount:
            continue  # attached but not mounted: nothing the user can see
        device = entities[0].get("dev-entry", "") if entities else ""
        found.append(MountedInstaller(Path(path), device, Path(mount)))
    return found


def should_offer(prefs: dict, bundle_path: str) -> bool:
    """Only from an installed copy, and only ever once.

    Running straight from the mounted DMG or from a dev checkout means there is
    nothing to clean up yet, and nagging on every launch would be worse than
    the leftover volume.
    """
    if prefs.get(PREF_KEY):
        return False
    return bundle_path.startswith("/Applications/")
