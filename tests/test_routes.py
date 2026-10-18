"""The HTTP surface is assembled from one router per area, and the split changed no path."""

from fastapi.routing import APIRoute

from logiops.api import create_app
from logiops.routes import account, agent, bookings, incidents, pages, scenario

EXPECTED = {
    ("GET", "/auth/config"), ("GET", "/demo"), ("GET", "/console"), ("GET", "/mcp-app/sandbox.html"), ("GET", "/assets/{name:path}"),
    ("GET", "/healthz"), ("POST", "/demo/reset"), ("POST", "/demo/inventory"), ("GET", "/alerts"), ("POST", "/alerts/{alert_id}/dismiss"),
    ("GET", "/incidents"), ("GET", "/metrics"), ("GET", "/incidents/{incident_id}"), ("POST", "/incidents/{incident_id}/investigate"),
    ("POST", "/incidents/{incident_id}/approvals"), ("POST", "/incidents/{incident_id}/execute"),
    ("GET", "/operator/preferences"), ("PUT", "/operator/preferences"), ("DELETE", "/operator/preferences"),
    ("POST", "/memory/turns"), ("GET", "/memory"), ("DELETE", "/memory"), ("GET", "/voice/config"), ("POST", "/voice/speech"),
    ("POST", "/incidents/{incident_id}/agent/investigate"), ("POST", "/incidents/{incident_id}/agent/investigate/stream"),
    ("POST", "/incidents/{incident_id}/agent/ask"), ("POST", "/agent/briefing"),
    ("GET", "/scenario/packs/builtin"), ("POST", "/scenario/packs"),
    ("POST", "/incidents/{incident_id}/bookings/quote"), ("POST", "/quotes/{quote_id}/confirm"), ("GET", "/bookings/{number}"),
    ("GET", "/bookings/{number}/receipt"),
}


def routes_of(app):
    found = set()

    def walk(items):
        for route in items:
            if isinstance(route, APIRoute):
                found.update((method, route.path) for method in route.methods)
            elif hasattr(route, "original_router"):
                walk(route.original_router.routes)
            elif hasattr(route, "routes") and not hasattr(route, "app"):
                walk(route.routes)

    walk(app.routes)
    return found


def test_every_route_is_still_there_and_each_router_owns_its_area(tmp_path):
    app = create_app(tmp_path / "routes.sqlite3")
    assert routes_of(app) == EXPECTED
    areas = {
        pages: {"/demo", "/console", "/healthz", "/assets/{name:path}", "/auth/config", "SANDBOX_PATH"},
        incidents: {"/incidents", "/incidents/{incident_id}", "/metrics", "/alerts", "/demo/reset"},
        account: {"/operator/preferences", "/memory", "/voice/speech"},
        agent: {"/agent/briefing", "/incidents/{incident_id}/agent/ask"},
        scenario: {"/scenario/packs", "/scenario/packs/builtin"},
        bookings: {"/quotes/{quote_id}/confirm", "/bookings/{number}/receipt"},
    }
    import inspect

    for module, paths in areas.items():
        source = inspect.getsource(module)
        for path in paths:
            assert f'"{path}"' in source or f"({path!r}" in source or path in source, (module.__name__, path)
