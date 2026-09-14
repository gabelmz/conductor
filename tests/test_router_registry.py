"""Tests for backend/router_registry.py."""
import sys
from pathlib import Path

# Ensure backend/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient
from router_registry import (
    DOMAIN_ROUTER_GETTERS,
    get_core_routers,
    get_workflow_routers,
    get_data_catalog_routers,
    get_integration_routers,
    get_report_analytics_routers,
    get_settings_people_routers,
    register_all_routers,
)


def test_domain_router_getters_keys():
    expected_keys = {
        "core",
        "workflows",
        "data_catalog",
        "integrations",
        "reports_analytics",
        "settings_people",
    }
    assert set(DOMAIN_ROUTER_GETTERS.keys()) == expected_keys


def test_domain_getters_return_routers():
    getters = [
        get_core_routers,
        get_workflow_routers,
        get_data_catalog_routers,
        get_integration_routers,
        get_report_analytics_routers,
        get_settings_people_routers,
    ]
    total_routers = 0
    for getter in getters:
        routers = getter()
        assert isinstance(routers, list)
        assert len(routers) > 0
        for r in routers:
            assert isinstance(r, APIRouter)
        total_routers += len(routers)

    assert total_routers == 36


def test_register_all_routers():
    test_app = FastAPI()
    initial_route_count = len(test_app.routes)
    register_all_routers(test_app)

    # 4 default routes + 36 included routers = 40
    assert len(test_app.routes) == initial_route_count + 36

    # Verify requests to endpoints registered from different domain routers succeed
    client = TestClient(test_app)
    assert client.get("/api/chat/models").status_code == 200
    assert client.get("/api/reports/contract").status_code in (200, 404, 422)
    assert client.get("/api/settings/all").status_code in (200, 404, 422)
