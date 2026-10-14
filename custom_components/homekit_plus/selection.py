"""Exact entity selection and ownership of accessory-mode children."""
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryDisabler
from homeassistant.const import CONF_ENTITY_ID, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entityfilter import EntityFilter, FILTER_SCHEMA

from .const import (
    CONF_ENTITY_CONFIG, CONF_FILTER, CONF_HOMEKIT_MODE, DOMAIN,
    DEFAULT_CONFIG_FLOW_PORT, HOMEKIT_MODE_ACCESSORY, HOMEKIT_MODE_BRIDGE,
)
from .util import async_find_next_available_port, state_needs_accessory_mode

CONF_PARENT_ENTRY_ID = 'parent_entry_id'
CONF_PAUSED_BY_PARENT = 'paused_by_parent'
CONF_INCLUDE_ENTITIES = 'include_entities'
SUPPORTED_DOMAINS = [
    'alarm_control_panel', 'automation', 'binary_sensor', 'button', 'camera',
    'climate', 'cover', 'device_tracker', 'fan', 'humidifier', 'input_boolean',
    'input_button', 'input_select', 'light', 'lock', 'media_player', 'person',
    'remote', 'scene', 'script', 'select', 'sensor', 'switch', 'vacuum',
    'lawn_mower', 'water_heater', 'valve',
]


def exact_filter_config(entities: list[str]) -> dict[str, list[str]]:
    """Store an explicit allowlist. The wildcard denies everything else."""
    return {
        CONF_INCLUDE_ENTITIES: sorted(set(entities)),
        'exclude_entity_globs': ['*'],
    }


def selected_entity_filter(config: Mapping[str, Any]) -> EntityFilter:
    """Never interpret an empty selection as exposing every entity."""
    return FILTER_SCHEMA(exact_filter_config(config.get(CONF_INCLUDE_ENTITIES, [])))


def candidate_entities(hass: HomeAssistant, current: list[str] = ()) -> list[str]:
    """Offer supported entity domains and preserve selected offline entities."""
    candidates = {
        state.entity_id for state in hass.states.async_all(set(SUPPORTED_DOMAINS))
    }
    candidates.update(
        entity_id for entity_id in current
        if entity_id.partition('.')[0] in SUPPORTED_DOMAINS
    )
    return sorted(candidates)


async def async_sync_accessories(hass: HomeAssistant, parent: ConfigEntry) -> None:
    """Synchronize only this bridge's selected accessory-mode entities.

    Deselecting pauses an owned child instead of deleting pairing information.
    A manual disable is respected when a child has not been paused by the parent.
    """
    if parent.options.get(CONF_HOMEKIT_MODE) != HOMEKIT_MODE_BRIDGE:
        return
    selected = set(parent.options.get(CONF_FILTER, {}).get(CONF_INCLUDE_ENTITIES, []))
    children = {
        child.options.get(CONF_FILTER, child.data.get(CONF_FILTER, {}))
            .get(CONF_INCLUDE_ENTITIES, [''])[0]: child
        for child in hass.config_entries.async_entries(DOMAIN)
        if child.data.get(CONF_PARENT_ENTRY_ID) == parent.entry_id
    }

    for entity_id, child in children.items():
        if entity_id not in selected:
            if child.disabled_by is None:
                hass.config_entries.async_update_entry(
                    child, data={**child.data, CONF_PAUSED_BY_PARENT: True}
                )
                await hass.config_entries.async_set_disabled_by(
                    child.entry_id, ConfigEntryDisabler.USER
                )
        elif child.data.get(CONF_PAUSED_BY_PARENT):
            data = dict(child.data)
            data.pop(CONF_PAUSED_BY_PARENT, None)
            hass.config_entries.async_update_entry(child, data=data)
            await hass.config_entries.async_set_disabled_by(child.entry_id, None)

    for entity_id in sorted(selected):
        state = hass.states.get(entity_id)
        if entity_id in children or state is None or not state_needs_accessory_mode(state):
            continue
        port = async_find_next_available_port(hass, DEFAULT_CONFIG_FLOW_PORT)
        await hass.config_entries.flow.async_init(
            DOMAIN, context={'source': 'accessory'},
            data={CONF_ENTITY_ID: entity_id, CONF_PORT: port,
                  CONF_PARENT_ENTRY_ID: parent.entry_id},
        )


async def async_remove_children(hass: HomeAssistant, parent: ConfigEntry) -> None:
    """Remove owned child entries when the user removes their bridge."""
    for child in list(hass.config_entries.async_entries(DOMAIN)):
        if child.data.get(CONF_PARENT_ENTRY_ID) == parent.entry_id:
            await hass.config_entries.async_remove(child.entry_id)
