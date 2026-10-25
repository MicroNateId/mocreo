"""MOCREO IoT Platform Integration for Home Assistant."""
import asyncio
import importlib
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MocreoApiClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register static path and inject extra JS url into frontend HTML once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend_registered"):
        return

    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig

        loop = asyncio.get_running_loop()
        card_path = await loop.run_in_executor(
            None, hass.config.path, "custom_components/mocreo/mocreo-card.js"
        )
        if getattr(hass, "http", None) is not None:
            if hasattr(hass.http, "async_register_static_paths"):
                await hass.http.async_register_static_paths(
                    [
                        StaticPathConfig(
                            "/mocreo_static/mocreo-card.js",
                            card_path,
                            cache_headers=False,
                        )
                    ]
                )
            elif hasattr(hass.http, "register_static_path"):
                hass.http.register_static_path(
                    "/mocreo_static/mocreo-card.js",
                    card_path,
                    cache_headers=False,
                )
        add_extra_js_url(hass, "/mocreo_static/mocreo-card.js")
        add_extra_js_url(hass, "/local/mocreo-card.js")
        domain_data["frontend_registered"] = True
    except Exception as err:
        _LOGGER.warning("Error registering extra JS url for frontend: %s", err)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the MOCREO component."""
    await _async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MOCREO IoT Platform from a config entry."""
    api_key = entry.data["api_key"]
    asset_id = entry.data["asset_id"]
    session = async_get_clientsession(hass)
    client = MocreoApiClient(api_key, asset_id, session=session)

    async def async_update_data():
        """Fetch data from MOCREO API."""
        try:
            return await client.async_get_devices()
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Pre-import platform modules in thread executor to prevent event loop blocking warnings
    loop = asyncio.get_running_loop()
    for platform in PLATFORMS:
        await loop.run_in_executor(
            None, importlib.import_module, f"custom_components.{DOMAIN}.{platform}"
        )

    await _async_register_frontend(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
