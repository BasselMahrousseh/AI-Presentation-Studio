import os
import sys

import pytest

from utils.asset_directory_utils import (
    filesystem_export_path_to_app_data_url,
    filesystem_image_path_to_app_data_url,
)


def test_maps_a_real_export_file_to_its_app_data_url(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.delenv("NEXT_PUBLIC_FAST_API", raising=False)
    exported = tmp_path / "exports" / "users" / "owner-1" / "My Deck.pptx"

    url = filesystem_export_path_to_app_data_url(str(exported))

    assert url == "/app_data/exports/users/owner-1/My Deck.pptx"


def test_prefixes_with_the_public_fastapi_base_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("NEXT_PUBLIC_FAST_API", "http://127.0.0.1:8011/")
    exported = tmp_path / "exports" / "users" / "owner-1" / "deck.pdf"

    url = filesystem_export_path_to_app_data_url(str(exported))

    assert url == "http://127.0.0.1:8011/app_data/exports/users/owner-1/deck.pdf"


def test_leaves_a_path_outside_the_exports_root_untouched(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.delenv("NEXT_PUBLIC_FAST_API", raising=False)
    outside = tmp_path / "images" / "users" / "owner-1" / "photo.png"

    url = filesystem_export_path_to_app_data_url(str(outside))

    assert url == str(outside)


def test_rejects_a_traversal_attempt_that_resolves_outside_the_exports_root(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.delenv("NEXT_PUBLIC_FAST_API", raising=False)
    traversal = str(tmp_path / "exports" / ".." / "images" / "users" / "owner-1" / "photo.png")

    url = filesystem_export_path_to_app_data_url(traversal)

    assert url == traversal


def test_passes_through_an_already_app_data_relative_path(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_FAST_API", "http://127.0.0.1:8011")

    url = filesystem_export_path_to_app_data_url(
        "/app_data/exports/users/owner-1/deck.pptx"
    )

    assert url == "http://127.0.0.1:8011/app_data/exports/users/owner-1/deck.pptx"


def test_passes_through_an_http_url_unchanged():
    assert (
        filesystem_export_path_to_app_data_url("https://cdn.example.com/deck.pptx")
        == "https://cdn.example.com/deck.pptx"
    )


def test_returns_the_stripped_path_unchanged_when_app_data_directory_is_unset(monkeypatch):
    monkeypatch.delenv("APP_DATA_DIRECTORY", raising=False)

    url = filesystem_export_path_to_app_data_url("  /tmp/exports/deck.pptx  ")

    assert url == "/tmp/exports/deck.pptx"


@pytest.mark.skipif(sys.platform == "win32", reason="os.symlink needs elevated privilege on Windows")
def test_resolves_correctly_when_app_data_directory_is_reached_through_a_symlink(
    monkeypatch, tmp_path
):
    # Reproduces the real failure live-hit under run_studio.sh: APP_DATA_DIRECTORY=/tmp/studio-appdata,
    # but macOS's /tmp is itself a symlink to /private/tmp, and the export subprocess's own returned
    # path comes back already resolved through it. Comparing unresolved abspaths (the previous
    # implementation) made every real export "outside" its own exports root and silently returned the
    # raw filesystem path unconverted - which is exactly the 404 observed on a live export.
    real_root = tmp_path / "real_appdata"
    real_root.mkdir()
    (real_root / "exports").mkdir()
    symlinked_root = tmp_path / "appdata_symlink"
    os.symlink(real_root, symlinked_root)

    monkeypatch.setenv("APP_DATA_DIRECTORY", str(symlinked_root))
    monkeypatch.delenv("NEXT_PUBLIC_FAST_API", raising=False)

    # The "export subprocess" returns a path already resolved through the symlink, same as the real
    # bug - not one built by joining onto the (symlinked) APP_DATA_DIRECTORY env value.
    exported = real_root / "exports" / "Comparing-Large-Language-Models_b6fd4956.pptx"

    url = filesystem_export_path_to_app_data_url(str(exported))

    assert url == "/app_data/exports/Comparing-Large-Language-Models_b6fd4956.pptx"


@pytest.mark.skipif(sys.platform == "win32", reason="os.symlink needs elevated privilege on Windows")
def test_image_url_helper_has_the_same_symlink_fix(monkeypatch, tmp_path):
    real_root = tmp_path / "real_appdata"
    real_root.mkdir()
    (real_root / "images").mkdir()
    symlinked_root = tmp_path / "appdata_symlink"
    os.symlink(real_root, symlinked_root)

    monkeypatch.setenv("APP_DATA_DIRECTORY", str(symlinked_root))
    monkeypatch.delenv("NEXT_PUBLIC_FAST_API", raising=False)

    image = real_root / "images" / "users" / "owner-1" / "slide.png"

    url = filesystem_image_path_to_app_data_url(str(image))

    assert url == "/app_data/images/users/owner-1/slide.png"
