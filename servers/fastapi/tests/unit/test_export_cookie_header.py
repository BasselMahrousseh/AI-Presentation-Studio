from starlette.requests import Request

from api.v1.ppt.endpoints.presentation import _build_export_cookie_header


def _request(*, headers: dict[str, str]) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/ppt/presentation/x/export",
            "headers": [
                (name.lower().encode(), value.encode())
                for name, value in headers.items()
            ],
        }
    )
    return request


def test_bearer_caller_gets_its_workspace_jwt_as_the_export_cookie():
    request = _request(headers={"Authorization": "Bearer workspace-jwt"})
    request.state.export_cookie_header = "studio_token=workspace-jwt"

    assert _build_export_cookie_header(request) == "studio_token=workspace-jwt"


def test_browser_cookie_wins_over_the_bearer_derived_cookie():
    cookie_header = "studio_token=browser-jwt; theme=dark"
    request = _request(
        headers={"Cookie": cookie_header, "Authorization": "Bearer workspace-jwt"}
    )
    request.state.export_cookie_header = "studio_token=workspace-jwt"

    assert _build_export_cookie_header(request) == cookie_header


def test_no_credentials_means_no_export_cookie():
    assert _build_export_cookie_header(_request(headers={})) is None
