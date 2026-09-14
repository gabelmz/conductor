"""Domain Router Registry for Conductor Backend.

Categorizes and registers all application routers in domain groups:
  - Core & System (chat, llama, ui, features, plugins, mcp, search)
  - Workflows & Automation (automation, bernie, asana_rules, brand_onboarding)
  - Data & Catalog (data, localsources, productpipeline, attributeaudit, bulkimport, flatfiles, dataset_store, hub, spine)
  - Integrations (keepa, supabase_sync, hf, brandcompare, svl)
  - Reports & Analytics (reports, guidelines, insights, mapping, report_presets, team_kpis, listing_content, kpi, wrangler)
  - Settings & People (settings_api, people)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def get_core_routers() -> list:
    """Core system, chat, assistant, plugins, MCP, and search routers."""
    from chat import router as chat_router
    from llama import router as llama_router
    from ui import router as ui_router
    from features import router as features_router
    from plugins import router as plugins_router
    from mcp_servers import router as mcp_router
    from search import router as search_router

    return [
        chat_router,
        llama_router,
        ui_router,
        features_router,
        plugins_router,
        mcp_router,
        search_router,
    ]


def get_workflow_routers() -> list:
    """Workflow execution, automation, canvas, and onboarding routers."""
    import automation
    import bernie
    import asana_rules
    from brand_onboarding import onboarding_router

    return [
        automation.router,
        bernie.router,
        asana_rules.router,
        onboarding_router,
    ]


def get_data_catalog_routers() -> list:
    """Product catalog, local sources, flatfiles, dataset store, hub, and spine routers."""
    from data import router as data_router
    from localsources import router as localsources_router
    from productpipeline import router as productpipeline_router
    from attributeaudit import router as attributeaudit_router
    from bulkimport import router as bulkimport_router
    from flatfiles import router as flatfiles_router
    from dataset_store import router as dataset_store_router
    from hub import router as hub_router
    from spine import router as spine_router

    return [
        data_router,
        localsources_router,
        productpipeline_router,
        attributeaudit_router,
        bulkimport_router,
        flatfiles_router,
        dataset_store_router,
        hub_router,
        spine_router,
    ]


def get_integration_routers() -> list:
    """External integrations (Keepa, Supabase, HuggingFace, SVL, Brand Compare)."""
    from keepa import router as keepa_router
    from supabase_sync import router as supabase_sync_router
    from hf import router as hf_router
    from brandcompare import router as brandcompare_router
    from svl import router as svl_router

    return [
        keepa_router,
        supabase_sync_router,
        hf_router,
        brandcompare_router,
        svl_router,
    ]


def get_report_analytics_routers() -> list:
    """Reporting, guidelines, insights, mapping presets, Asana KPIs, listing compare, and KPI wrangler routers."""
    from reports import router as reports_router
    from guidelines import router as guidelines_router
    from insights import router as insights_router
    from mapping import router as mapping_router
    from report_presets import router as report_presets_router
    from reporting.team_kpis import router as asana_kpis_router
    from reporting.listing_content import router as listing_compare_router
    from kpi import kpi_router, wrangler_router

    return [
        reports_router,
        guidelines_router,
        insights_router,
        mapping_router,
        report_presets_router,
        asana_kpis_router,
        listing_compare_router,
        kpi_router,
        wrangler_router,
    ]


def get_settings_people_routers() -> list:
    """Settings API and people/team management routers."""
    from settings_api import router as settings_api_router
    from people import router as people_router

    return [
        settings_api_router,
        people_router,
    ]


DOMAIN_ROUTER_GETTERS = {
    "core": get_core_routers,
    "workflows": get_workflow_routers,
    "data_catalog": get_data_catalog_routers,
    "integrations": get_integration_routers,
    "reports_analytics": get_report_analytics_routers,
    "settings_people": get_settings_people_routers,
}


def register_all_routers(app: FastAPI) -> None:
    """Register all domain-categorized routers on the provided FastAPI application instance."""
    for domain, getter in DOMAIN_ROUTER_GETTERS.items():
        for router in getter():
            app.include_router(router)
