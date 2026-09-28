
from services.icon_finder_service import IconFinderService
from utils.icon_weights import (
    extract_icon_type_from_settings,
    normalize_icon_type,
)


def test_icon_type_settings_prefer_icon_type_and_support_weight_alias():
    assert extract_icon_type_from_settings({"icon_type": "duotone"}) == "duotone"
    assert (
        extract_icon_type_from_settings({"icon_type": "bold", "icon_weight": "thin"})
        == "bold"
    )
    assert extract_icon_type_from_settings({"icon_weight": "light"}) == "light"
    assert normalize_icon_type("regular") == "regular"


def test_icon_finder_builds_weighted_static_urls(monkeypatch):
    service = IconFinderService()
    monkeypatch.setattr(
        "services.icon_finder_service.get_resource_path",
        lambda path: f"/app/{path}",
    )
    monkeypatch.setattr(
        "services.icon_finder_service.os.path.isfile",
        lambda path: True,
    )

    regular_url = service._icon_url_for_weight(
        "chart-line-up-bold||chart growth",
        "regular",
    )
    thin_url = service._icon_url_for_weight("chart-line-up-bold", "thin")

    assert regular_url.endswith("/static/icons/regular/chart-line-up.svg")
    assert thin_url.endswith("/static/icons/thin/chart-line-up-thin.svg")


def test_icon_finder_falls_back_to_bold_when_weighted_icon_missing(monkeypatch):
    service = IconFinderService()
    monkeypatch.setattr(
        "services.icon_finder_service.get_resource_path",
        lambda path: f"/app/{path}",
    )
    monkeypatch.setattr(
        "services.icon_finder_service.os.path.isfile",
        lambda path: False,
    )

    icon_url = service._icon_url_for_weight("chart-line-up-bold", "thin")

    assert icon_url.endswith("/static/icons/bold/chart-line-up-bold.svg")


