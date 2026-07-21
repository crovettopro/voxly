from pathlib import Path

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
