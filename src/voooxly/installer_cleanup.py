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
import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


def find_installer() -> MountedInstaller | None:
    """First mounted Voooxly installer, or None."""
    try:
        out = subprocess.run(["hdiutil", "info", "-plist"],
                             capture_output=True, timeout=10, check=True).stdout
        found = parse_hdiutil_info(plistlib.loads(out))
    except Exception:
        log.debug("hdiutil info failed", exc_info=True)
        return None
    return found[0] if found else None


def eject(inst: MountedInstaller) -> bool:
    """Detach by mount point: an APFS image has several dev-entries."""
    for extra in ([], ["-force"]):
        try:
            subprocess.run(["hdiutil", "detach", str(inst.mount_point), *extra],
                           capture_output=True, timeout=30, check=True)
            return True
        except Exception:
            continue
    log.warning("Could not eject %s (%s)", inst.mount_point, inst.device)
    return False


def move_to_trash(path: Path) -> bool:
    """The real Trash, so the user can put it back. Never rm."""
    try:
        from Foundation import NSURL, NSFileManager

        ok, _, err = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            NSURL.fileURLWithPath_(str(path)), None, None)
        if not ok:
            log.warning("Could not trash %s: %s", path, err)
        return bool(ok)
    except Exception:
        log.warning("Could not trash %s", path, exc_info=True)
        return False


def ask_user(dmg_name: str) -> bool:
    """True if the user chose to get rid of the installer. Main thread only."""
    from AppKit import NSAlert

    alert = NSAlert.alloc().init()
    alert.setMessageText_("Voooxly is installed")
    alert.setInformativeText_(
        f"The installer disk image is still mounted. "
        f"Eject it and move {dmg_name} to the Trash?")
    alert.addButtonWithTitle_("Move to Trash")
    alert.addButtonWithTitle_("Keep")
    return alert.runModal() == 1000  # NSAlertFirstButtonReturn


def maybe_clean_up(prefs: dict, save_prefs: Callable[[dict], None], bundle_path: str) -> None:
    """Offer once to eject the installer and bin it. Never raises.

    Nothing mounted means nothing is remembered: the volume may well be there
    on the next launch, and that launch deserves its own chance to ask.
    """
    try:
        if not should_offer(prefs, bundle_path):
            return
        inst = find_installer()
        if inst is None:
            return
        if inst.dmg_path.exists():
            if ask_user(inst.dmg_path.name):
                eject(inst)
                move_to_trash(inst.dmg_path)
        else:
            # The .dmg is already gone and the volume outlived it. Tidy up
            # without asking: there is no decision left to make.
            eject(inst)
        prefs[PREF_KEY] = True
        save_prefs(prefs)
    except Exception:
        log.warning("Installer cleanup failed", exc_info=True)
