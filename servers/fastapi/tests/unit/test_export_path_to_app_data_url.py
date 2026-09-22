from utils.asset_directory_utils import filesystem_export_path_to_app_data_url


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
