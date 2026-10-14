"""Entity selection and device management for HomeKit Plus.

Modified from Home Assistant Core's homekit integration (Apache-2.0);
see LICENSE.md and NOTICE.
"""
from collections.abc import Iterable
from copy import deepcopy
import random
import re
import string
from typing import Any

import probatio
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow, SOURCE_IMPORT
from homeassistant.const import CONF_ENTITIES, CONF_ENTITY_ID, CONF_NAME, CONF_PORT, CONF_TYPE, EntityStateAttribute
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENTITY_CONFIG, CONF_EXCLUDE_ACCESSORY_MODE, CONF_FILTER, CONF_HOMEKIT_MODE,
    CONF_SUPPORT_AUDIO, CONF_VIDEO_CODEC, DEFAULT_CONFIG_FLOW_PORT, DOMAIN,
    HOMEKIT_MODE_ACCESSORY, HOMEKIT_MODE_BRIDGE, SHORT_BRIDGE_NAME,
    TYPE_HEATER_COOLER, TYPE_THERMOSTAT, VIDEO_CODEC_COPY,
)
from .models import HomeKitEntryData
from .selection import CONF_INCLUDE_ENTITIES, CONF_PARENT_ENTRY_ID, candidate_entities, exact_filter_config
from .util import async_find_next_available_port

CONF_CAMERA_AUDIO = 'camera_audio'
CONF_CAMERA_COPY = 'camera_copy'
CLIMATE_TYPE_AUTOMATIC = 'automatic'
CLIMATE_ACCESSORY_NAMES = {'Thermostat': 'Thermostat', 'HeaterCooler': 'Heater Cooler'}


def entity_schema(candidates: list[str], selected: list[str], multiple: bool = True) -> probatio.Schema:
    return probatio.Schema({
        probatio.Optional(CONF_ENTITIES, default=selected if multiple else (selected[0] if selected else None)):
            selector.EntitySelector(selector.EntitySelectorConfig(
                multiple=multiple, include_entities=candidates,
            )),
    })


class HomeKitPlusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a distinct bridge with explicit entity selections."""
    VERSION = 1

    def __init__(self) -> None:
        self.hk_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        candidates = candidate_entities(self.hass)
        selected = list(user_input.get(CONF_ENTITIES, [])) if user_input else []
        errors = {}
        if user_input is not None:
            if set(selected).difference(candidates):
                errors['base'] = 'invalid_entities'
            else:
                self.hk_data = {
                    CONF_HOMEKIT_MODE: HOMEKIT_MODE_BRIDGE,
                    CONF_FILTER: exact_filter_config(selected),
                    CONF_EXCLUDE_ACCESSORY_MODE: True,
                }
                return await self.async_step_pairing()
        return self.async_show_form(
            step_id='user', data_schema=entity_schema(candidates, selected), errors=errors,
        )

    async def async_step_pairing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.hk_data[CONF_PORT] = async_find_next_available_port(self.hass, DEFAULT_CONFIG_FLOW_PORT)
            return self.async_create_entry(
                title=f'{self.hk_data[CONF_NAME]}:{self.hk_data[CONF_PORT]}', data=self.hk_data,
            )
        self.hk_data[CONF_NAME] = self._async_available_name(SHORT_BRIDGE_NAME)
        return self.async_show_form(
            step_id='pairing', description_placeholders={CONF_NAME: self.hk_data[CONF_NAME]},
        )

    async def async_step_accessory(self, accessory_input: dict[str, Any]) -> ConfigFlowResult:
        entity_id = accessory_input[CONF_ENTITY_ID]
        state = self.hass.states.get(entity_id)
        if state is None:
            return self.async_abort(reason='entity_not_found')
        name = self._async_available_name(
            'HomeKit Plus ' + (state.attributes.get(EntityStateAttribute.FRIENDLY_NAME) or entity_id)
        )
        data = {
            CONF_PORT: accessory_input[CONF_PORT], CONF_NAME: name,
            CONF_HOMEKIT_MODE: HOMEKIT_MODE_ACCESSORY,
            CONF_FILTER: exact_filter_config([entity_id]),
        }
        if CONF_PARENT_ENTRY_ID in accessory_input:
            data[CONF_PARENT_ENTRY_ID] = accessory_input[CONF_PARENT_ENTRY_ID]
        if entity_id.startswith('camera.'):
            data[CONF_ENTITY_CONFIG] = {entity_id: {CONF_VIDEO_CODEC: VIDEO_CODEC_COPY}}
        return self.async_create_entry(title=f'{name}:{data[CONF_PORT]}', data=data)

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        if any(entry.data.get(CONF_PORT) == import_data[CONF_PORT]
               or entry.data.get(CONF_NAME) == import_data[CONF_NAME]
               for entry in self._async_current_entries(include_ignore=False)):
            return self.async_abort(reason='port_name_in_use')
        return self.async_create_entry(
            title=f'{import_data[CONF_NAME]}:{import_data[CONF_PORT]}', data=import_data,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the selected entities from the existing bridge's menu."""
        entry = self._get_reconfigure_entry()
        if entry.source == SOURCE_IMPORT:
            return self.async_abort(reason='yaml_managed')

        current = list(entry.options.get(CONF_FILTER, {}).get(CONF_INCLUDE_ENTITIES, []))
        accessory = entry.options.get(CONF_HOMEKIT_MODE) == HOMEKIT_MODE_ACCESSORY
        owned = bool(entry.data.get(CONF_PARENT_ENTRY_ID))
        candidates = current if owned else candidate_entities(self.hass, current)
        selected = (
            probatio.EnsureList()(user_input.get(CONF_ENTITIES, []))
            if user_input is not None else current
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            if accessory and len(selected) != 1:
                errors['base'] = 'one_entity_required'
            elif set(selected).difference(candidates):
                errors['base'] = 'invalid_entities'
            else:
                options = deepcopy(dict(entry.options))
                options[CONF_FILTER] = exact_filter_config(selected)
                options.pop('devices', None)
                # The existing update listener reloads this same bridge.
                self.hass.config_entries.async_update_entry(entry, options=options)
                return self.async_abort(reason='reconfigure_successful')

        return self.async_show_form(
            step_id='reconfigure',
            data_schema=entity_schema(candidates, selected, multiple=not accessory),
            errors=errors,
        )

    @callback
    def _async_available_name(self, requested_name: str) -> str:
        names = {entry.data.get(CONF_NAME) for integration in (DOMAIN, 'homekit')
                 for entry in self.hass.config_entries.async_entries(integration)}
        base = re.sub('[^A-Za-z0-9 ]+', ' ', requested_name).strip()[:20] or SHORT_BRIDGE_NAME
        if base not in names:
            return base
        while True:
            candidate = base + ' ' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
            if candidate not in names:
                return candidate

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Edit the entity allowlist directly without category or exclusion pages."""
    def __init__(self) -> None:
        self.hk_options: dict[str, Any] = {}
        self.included_cameras: list[str] = []
        self.included_climates: list[str] = []
        self._climate_choices: dict[str, str] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.source == SOURCE_IMPORT:
            return self.async_show_form(step_id='yaml') if user_input is None else self.async_create_entry(
                title='', data=dict(self.config_entry.options),
            )
        self.hk_options = deepcopy(dict(self.config_entry.options))
        current = self.hk_options.get(CONF_FILTER, {}).get(CONF_INCLUDE_ENTITIES, [])
        accessory = self.hk_options.get(CONF_HOMEKIT_MODE) == HOMEKIT_MODE_ACCESSORY
        owned = bool(self.config_entry.data.get(CONF_PARENT_ENTRY_ID))
        candidates = current if owned else candidate_entities(self.hass, current)
        selected = probatio.EnsureList()(user_input.get(CONF_ENTITIES, [])) if user_input is not None else current
        errors = {}
        if user_input is not None:
            if accessory and len(selected) != 1:
                errors['base'] = 'one_entity_required'
            elif set(selected).difference(candidates):
                errors['base'] = 'invalid_entities'
            else:
                self.hk_options[CONF_FILTER] = exact_filter_config(selected)
                self.hk_options.pop('devices', None)
                # Camera settings belong to their separately paired accessory entries.
                self.included_cameras = [eid for eid in selected if eid.startswith('camera.')] if accessory else []
                self.included_climates = [eid for eid in selected if eid.startswith('climate.')]
                return await self.async_step_cameras()
        return self.async_show_form(
            step_id='init', data_schema=entity_schema(candidates, selected, multiple=not accessory), errors=errors,
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(title='', data=self.hk_options)

    async def async_step_climate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the accessory type for climate entities."""
        if not self.included_climates:
            return await self.async_step_finish()

        hk_options = self.hk_options
        all_entity_config: dict[str, dict[str, Any]]

        if user_input is not None:
            all_entity_config = hk_options[CONF_ENTITY_CONFIG]
            for label, entity_id in self._climate_choices.items():
                entity_config = all_entity_config.setdefault(entity_id, {})

                if (choice := user_input[label]) == CLIMATE_TYPE_AUTOMATIC:
                    entity_config.pop(CONF_TYPE, None)
                else:
                    entity_config[CONF_TYPE] = choice

                if not entity_config:
                    all_entity_config.pop(entity_id)

            if not all_entity_config:
                del hk_options[CONF_ENTITY_CONFIG]

            return await self.async_step_finish()

        # Field labels come from the schema keys, so key the form by the
        # friendly name and map back to the entity id on submit. The
        # accessory a bridged entity currently uses is shown so Automatic
        # is not a mystery.
        current_accessories = self._async_current_climate_accessories()
        self._climate_choices = {}
        for entity_id in self.included_climates:
            state = self.hass.states.get(entity_id)
            label = f"{state.name} ({entity_id})" if state else entity_id
            if current := current_accessories.get(entity_id):
                label = f"{label} [{current}]"
            self._climate_choices[label] = entity_id

        all_entity_config = hk_options.setdefault(CONF_ENTITY_CONFIG, {})
        type_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    CLIMATE_TYPE_AUTOMATIC,
                    TYPE_THERMOSTAT,
                    TYPE_HEATER_COOLER,
                ],
                translation_key="climate_accessory_type",
            )
        )
        data_schema = probatio.Schema(
            {
                probatio.Required(
                    label,
                    default=all_entity_config.get(entity_id, {}).get(
                        CONF_TYPE, CLIMATE_TYPE_AUTOMATIC
                    ),
                ): type_selector
                for label, entity_id in self._climate_choices.items()
            }
        )
        return self.async_show_form(step_id="climate", data_schema=data_schema)

    @callback
    def _async_current_climate_accessories(self) -> dict[str, str]:
        """Map bridged climate entities to their current accessory name."""
        entry_data: HomeKitEntryData | None = getattr(
            self.config_entry, "runtime_data", None
        )
        if entry_data is None:
            return {}
        homekit = entry_data.homekit
        accessories: Iterable[Any]
        if homekit.bridge is not None:
            accessories = homekit.bridge.accessories.values()
        elif homekit.driver is not None and homekit.driver.accessory is not None:
            accessories = [homekit.driver.accessory]
        else:
            return {}
        return {
            entity_id: CLIMATE_ACCESSORY_NAMES[accessory_name]
            for accessory in accessories
            if (entity_id := getattr(accessory, "entity_id", None)) is not None
            and (accessory_name := type(accessory).__name__) in CLIMATE_ACCESSORY_NAMES
        }

    async def async_step_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose camera config."""
        if not self.included_cameras:
            return await self.async_step_climate()

        hk_options = self.hk_options
        all_entity_config: dict[str, dict[str, Any]]

        if user_input is not None:
            all_entity_config = hk_options[CONF_ENTITY_CONFIG]
            for entity_id in self.included_cameras:
                entity_config = all_entity_config.setdefault(entity_id, {})

                if entity_id in user_input[CONF_CAMERA_COPY]:
                    entity_config[CONF_VIDEO_CODEC] = VIDEO_CODEC_COPY
                elif CONF_VIDEO_CODEC in entity_config:
                    del entity_config[CONF_VIDEO_CODEC]

                if entity_id in user_input[CONF_CAMERA_AUDIO]:
                    entity_config[CONF_SUPPORT_AUDIO] = True
                elif CONF_SUPPORT_AUDIO in entity_config:
                    del entity_config[CONF_SUPPORT_AUDIO]

                if not entity_config:
                    all_entity_config.pop(entity_id)

            return await self.async_step_climate()

        cameras_with_audio = []
        cameras_with_copy = []
        all_entity_config = hk_options.setdefault(CONF_ENTITY_CONFIG, {})
        for entity in self.included_cameras:
            entity_config = all_entity_config.get(entity, {})
            if entity_config.get(CONF_VIDEO_CODEC) == VIDEO_CODEC_COPY:
                cameras_with_copy.append(entity)
            if entity_config.get(CONF_SUPPORT_AUDIO):
                cameras_with_audio.append(entity)

        data_schema = probatio.Schema(
            {
                probatio.Optional(
                    CONF_CAMERA_COPY, default=cameras_with_copy
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        multiple=True,
                        include_entities=(self.included_cameras),
                    )
                ),
                probatio.Optional(
                    CONF_CAMERA_AUDIO, default=cameras_with_audio
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        multiple=True,
                        include_entities=(self.included_cameras),
                    )
                ),
            }
        )
        return self.async_show_form(step_id="cameras", data_schema=data_schema)

