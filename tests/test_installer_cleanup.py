from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from voooxly import installer_cleanup as ic


def hdiutil_info(*images):
    return {"framework": "418.0.2", "revision": "718.0.1", "vendor": "Apple", "images": list(images)}


def image(path, entities):
    return {"image-path": path, "image-type": "read-only", "system-entities": entities}


SIMULATOR = image(
    "/System/Library/AssetsV2/094-56039-099.dmg",
    [{"dev-entry": "/dev/disk4"},
     {"dev-entry": "/dev/disk5s1", "mount-point": "/Library/Developer/CoreSimulator/Volumes/iOS_23F77"}],
)
WHISPERNOTES = image(
    "/Users/someone/Downloads/WhisperNotes-latest.dmg",
    [{"dev-entry": "/dev/disk10s1", "mount-point": "/Volumes/WhisperNotes Installer"}],
)
# APFS image: several dev-entries, only the last one is mounted.
VOOOXLY = image(
    "/Users/someone/Downloads/Voooxly.dmg",
    [{"dev-entry": "/dev/disk8"},
     {"dev-entry": "/dev/disk8s1"},
     {"dev-entry": "/dev/disk9"},
     {"dev-entry": "/dev/disk9s1", "mount-point": "/Volumes/Voooxly 1"}],
)


def test_picks_the_voooxly_image_out_of_a_crowded_machine():
    found = ic.parse_hdiutil_info(hdiutil_info(SIMULATOR, WHISPERNOTES, VOOOXLY))
    assert len(found) == 1
    assert found[0].dmg_path == Path("/Users/someone/Downloads/Voooxly.dmg")
    assert found[0].mount_point == Path("/Volumes/Voooxly 1")


def test_keeps_the_first_dev_entry_for_logging():
    found = ic.parse_hdiutil_info(hdiutil_info(VOOOXLY))
    assert found[0].device == "/dev/disk8"


def test_matches_the_versioned_filename_too():
    versioned = image("/Users/someone/Desktop/Voooxly-1.0.0.dmg",
                      [{"dev-entry": "/dev/disk9s1", "mount-point": "/Volumes/Voooxly 2"}])
    assert len(ic.parse_hdiutil_info(hdiutil_info(versioned))) == 1


def test_ignores_images_that_are_attached_but_not_mounted():
    detached = image("/Users/someone/Downloads/Voooxly.dmg", [{"dev-entry": "/dev/disk8"}])
    assert ic.parse_hdiutil_info(hdiutil_info(detached)) == []


def test_ignores_other_peoples_installers():
    assert ic.parse_hdiutil_info(hdiutil_info(SIMULATOR, WHISPERNOTES)) == []


def test_survives_an_empty_or_odd_plist():
    assert ic.parse_hdiutil_info({}) == []
    assert ic.parse_hdiutil_info({"images": [{"system-entities": []}]}) == []


def test_offers_from_an_installed_copy():
    assert ic.should_offer({}, "/Applications/Voooxly.app") is True


def test_stays_quiet_when_running_from_the_dmg_or_a_dev_checkout():
    assert ic.should_offer({}, "/Volumes/Voooxly 1/Voooxly.app") is False
    assert ic.should_offer({}, "/Users/someone/Desktop/code-edu/voooxly") is False


def test_never_asks_twice():
    assert ic.should_offer({ic.PREF_KEY: True}, "/Applications/Voooxly.app") is False


class Spy:
    """Records the side effects so the orchestration can be asserted on."""

    def __init__(self, dmg_exists=True, answer=True):
        self.dmg_exists, self.answer = dmg_exists, answer
        self.ejected, self.trashed, self.asked = [], [], []

    def install(self, stack, inst):
        stack.enter_context(patch.object(ic, "find_installer", return_value=inst))
        stack.enter_context(patch.object(ic, "eject", side_effect=lambda i: self.ejected.append(i) or True))
        stack.enter_context(patch.object(ic, "move_to_trash", side_effect=lambda p: self.trashed.append(p) or True))
        stack.enter_context(patch.object(ic, "ask_user", side_effect=lambda n: self.asked.append(n) or self.answer))
        stack.enter_context(patch.object(Path, "exists", lambda _self: self.dmg_exists))


def run_cleanup(spy, inst, prefs=None):
    prefs = {} if prefs is None else prefs
    saved = []
    with ExitStack() as stack:
        spy.install(stack, inst)
        ic.maybe_clean_up(prefs, saved.append, "/Applications/Voooxly.app")
    return prefs, saved


INSTALLER = ic.MountedInstaller(Path("/Users/someone/Downloads/Voooxly.dmg"),
                                "/dev/disk8", Path("/Volumes/Voooxly 1"))


def test_move_to_trash_ejects_then_trashes_and_remembers():
    spy = Spy(answer=True)
    prefs, saved = run_cleanup(spy, INSTALLER)
    assert spy.asked == ["Voooxly.dmg"]
    assert spy.ejected == [INSTALLER]
    assert spy.trashed == [INSTALLER.dmg_path]
    assert prefs[ic.PREF_KEY] is True
    assert saved == [prefs]


def test_keep_leaves_the_volume_alone_but_never_asks_again():
    spy = Spy(answer=False)
    prefs, _ = run_cleanup(spy, INSTALLER)
    assert spy.ejected == [] and spy.trashed == []
    assert prefs[ic.PREF_KEY] is True


def test_ghost_volume_is_ejected_silently():
    """The .dmg was already trashed by hand; the volume outlived it."""
    spy = Spy(dmg_exists=False)
    prefs, _ = run_cleanup(spy, INSTALLER)
    assert spy.asked == []
    assert spy.ejected == [INSTALLER]
    assert spy.trashed == []
    assert prefs[ic.PREF_KEY] is True


def test_nothing_mounted_means_nothing_remembered():
    """Next launch should still get its chance."""
    spy = Spy()
    prefs, saved = run_cleanup(spy, None)
    assert spy.asked == [] and prefs == {} and saved == []


def test_the_guard_short_circuits_before_touching_hdiutil():
    with patch.object(ic, "find_installer") as find:
        ic.maybe_clean_up({ic.PREF_KEY: True}, lambda p: None, "/Applications/Voooxly.app")
    find.assert_not_called()
