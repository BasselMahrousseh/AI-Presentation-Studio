"""The Studio backend serves exactly the routes the GenAI Workspace calls.

Studio is only the backend behind the Workspace UI and orchestrator. A new route, or a removed one,
must be a deliberate change to this list (and to the Workspace client that calls it), not a
leftover from the upstream standalone app or an accidental deletion.
"""
from fastapi.routing import APIRoute

from api.main import app

EXPECTED_ROUTES = {
    # new deck
    ("POST", "/api/v1/ppt/files/upload"),
    ("POST", "/api/v1/ppt/files/decompose"),
    ("POST", "/api/v1/ppt/template/extract-color-palette"),
    ("POST", "/api/v1/ppt/presentation/create"),
    ("GET", "/api/v1/ppt/presentation/operations/{operation_id}"),
    # outline
    ("GET", "/api/v1/ppt/outlines/stream/{id}"),
    ("GET", "/api/v1/ppt/outlines/{id}"),
    ("PUT", "/api/v1/ppt/outlines/{id}"),
    ("POST", "/api/v1/ppt/outlines/{id}/quality-flags/acknowledge"),
    # deck generation, editor, dashboard
    ("GET", "/api/v1/ppt/presentation/stream/{id}"),
    ("GET", "/api/v1/ppt/presentation/{id}"),
    ("GET", "/api/v1/ppt/presentation/all"),
    ("DELETE", "/api/v1/ppt/presentation/{id}"),
    ("POST", "/api/v1/ppt/presentation/{id}/duplicate"),
    ("PATCH", "/api/v1/ppt/presentation/{id}/favorite"),
    ("PATCH", "/api/v1/ppt/presentation/update"),
    ("PATCH", "/api/v1/ppt/presentation/slide_update"),
    ("POST", "/api/v1/ppt/slide/edit-html"),
    ("GET", "/api/v1/ppt/icons/search"),
    # images
    ("POST", "/api/v1/ppt/images/upload"),
    ("GET", "/api/v1/ppt/images/uploaded"),
    ("GET", "/api/v1/ppt/images/generated"),
    ("GET", "/api/v1/ppt/images/generate"),
    ("DELETE", "/api/v1/ppt/images/{id}"),
    # deck chat
    ("GET", "/api/v1/ppt/chat/conversations"),
    ("GET", "/api/v1/ppt/chat/history"),
    ("DELETE", "/api/v1/ppt/chat/conversation"),
    ("POST", "/api/v1/ppt/chat/message/stream"),
    # feedback
    ("GET", "/api/v1/ppt/feedback/{presentation_id}"),
    ("PUT", "/api/v1/ppt/feedback/{presentation_id}/{stage}"),
    ("GET", "/api/v1/admin/feedback"),
    # export
    ("POST", "/api/v1/ppt/presentation/{id}/export"),
    ("POST", "/api/v1/ppt/presentation/export/chart-capture"),
    ("POST", "/api/v1/ppt/presentation/export/table-capture"),
}


def test_registered_routes_are_exactly_the_workspace_contract():
    registered = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert registered - EXPECTED_ROUTES == set(), "unexpected routes"
    assert EXPECTED_ROUTES - registered == set(), "missing routes"


def test_static_assets_are_mounted():
    mounts = {route.path for route in app.routes if not isinstance(route, APIRoute)}
    assert "/static" in mounts
