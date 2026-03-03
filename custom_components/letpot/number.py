"""Support for LetPot number entities."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from letpot.deviceclient import LetPotDeviceClient
from letpot.models import CycleWateringMode, DeviceFeature, LetPotWateringSystemStatus

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PRECISION_WHOLE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LetPotConfigEntry, LetPotDeviceCoordinator
from .entity import LetPotEntity, LetPotEntityDescription, exception_handler

# Each change pushes a 'full' device status with the change. The library will cache
# pending changes to avoid overwriting, but try to avoid a lot of parallelism.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LetPotNumberEntityDescription(LetPotEntityDescription, NumberEntityDescription):
    """Describes a LetPot number entity."""

    max_value_fn: Callable[[LetPotDeviceCoordinator], float]
    value_fn: Callable[[LetPotDeviceCoordinator], float | None]
    set_value_fn: Callable[[LetPotDeviceClient, str, float], Coroutine[Any, Any, None]]
    available_fn: Callable[[LetPotDeviceCoordinator], bool] = lambda _: True


NUMBERS: tuple[LetPotNumberEntityDescription, ...] = (
    LetPotNumberEntityDescription(
        key="light_brightness_levels",
        name="Light brightness",
        value_fn=(
            lambda coordinator: (
                coordinator.device_client.get_light_brightness_levels(
                    coordinator.device.serial_number
                ).index(coordinator.data.light_brightness)
                + 1
                if hasattr(coordinator.data, "light_brightness")
                and coordinator.data.light_brightness is not None
                else None
            )
        ),
        set_value_fn=(
            lambda device_client, serial, value: device_client.set_light_brightness(
                serial,
                device_client.get_light_brightness_levels(serial)[int(value) - 1],
            )
        ),
        supported_fn=(
            lambda coordinator: (
                DeviceFeature.LIGHT_BRIGHTNESS_LEVELS
                in coordinator.device_client.device_info(
                    coordinator.device.serial_number
                ).features
            )
        ),
        native_min_value=float(1),
        max_value_fn=lambda coordinator: float(
            len(
                coordinator.device_client.get_light_brightness_levels(
                    coordinator.device.serial_number
                )
            )
        ),
        native_step=PRECISION_WHOLE,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
    LetPotNumberEntityDescription(
        key="plant_days",
        name="Plants age",
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda coordinator: coordinator.data.plant_days if hasattr(coordinator.data, "plant_days") else None,
        set_value_fn=(
            lambda device_client, serial, value: device_client.set_plant_days(
                serial, int(value)
            )
        ),
        supported_fn=lambda coordinator: hasattr(coordinator.data, "plant_days"),
        native_min_value=float(0),
        max_value_fn=lambda _: float(999),
        native_step=PRECISION_WHOLE,
        mode=NumberMode.BOX,
    ),
    LetPotNumberEntityDescription(
        key="pump_manual_duration",
        name="Manual watering duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda coordinator: (
            coordinator.data.pump_manual_duration
            if isinstance(coordinator.data, LetPotWateringSystemStatus)
            else None
        ),
        set_value_fn=(
            lambda device_client, serial, value: device_client.set_pump_manual_duration(
                serial, int(value)
            )
        ),
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
        native_min_value=float(1),
        max_value_fn=lambda _: float(1440),
        native_step=PRECISION_WHOLE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    LetPotNumberEntityDescription(
        key="pump_cycle_frequency",
        name="Watering interval",
        native_unit_of_measurement=UnitOfTime.HOURS,
        value_fn=lambda coordinator: (
            coordinator.data.pump_cycle_frequency
            if isinstance(coordinator.data, LetPotWateringSystemStatus)
            else None
        ),
        set_value_fn=(
            lambda device_client, serial, value: device_client.set_pump_cycle_frequency(
                serial, int(value)
            )
        ),
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
        native_min_value=float(1),
        max_value_fn=lambda _: float(168),
        native_step=PRECISION_WHOLE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    LetPotNumberEntityDescription(
        key="pump_cycle_duration",
        name="Cycle watering duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda coordinator: (
            coordinator.data.pump_cycle_duration
            if isinstance(coordinator.data, LetPotWateringSystemStatus)
            else None
        ),
        set_value_fn=(
            lambda device_client, serial, value: device_client.set_pump_cycle_duration(
                serial, int(value)
            )
        ),
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
        native_min_value=float(1),
        max_value_fn=lambda _: float(1440),
        native_step=PRECISION_WHOLE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    LetPotNumberEntityDescription(
        key="pump_cycle_workinginterval",
        name="Pump on time (intermittent)",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda coordinator: (
            coordinator.data.pump_cycle_workinginterval
            if isinstance(coordinator.data, LetPotWateringSystemStatus)
            else None
        ),
        set_value_fn=(
            lambda device_client, serial, value: device_client.set_pump_cycle_workinginterval(
                serial, int(value)
            )
        ),
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
        available_fn=lambda coordinator: (
            isinstance(coordinator.data, LetPotWateringSystemStatus)
            and coordinator.data.pump_cycle_mode == CycleWateringMode.INTERMITTENT
        ),
        native_min_value=float(1),
        max_value_fn=lambda _: float(3600),
        native_step=PRECISION_WHOLE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    LetPotNumberEntityDescription(
        key="pump_cycle_restinterval",
        name="Pump off time (intermittent)",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda coordinator: (
            coordinator.data.pump_cycle_restinterval
            if isinstance(coordinator.data, LetPotWateringSystemStatus)
            else None
        ),
        set_value_fn=(
            lambda device_client, serial, value: device_client.set_pump_cycle_restinterval(
                serial, int(value)
            )
        ),
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
        available_fn=lambda coordinator: (
            isinstance(coordinator.data, LetPotWateringSystemStatus)
            and coordinator.data.pump_cycle_mode == CycleWateringMode.INTERMITTENT
        ),
        native_min_value=float(1),
        max_value_fn=lambda _: float(3600),
        native_step=PRECISION_WHOLE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LetPotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up LetPot number entities based on a config entry and device status/features."""
    coordinators = entry.runtime_data
    async_add_entities(
        LetPotNumberEntity(coordinator, description)
        for description in NUMBERS
        for coordinator in coordinators
        if description.supported_fn(coordinator)
    )


class LetPotNumberEntity(LetPotEntity, NumberEntity):
    """Defines a LetPot number entity."""

    entity_description: LetPotNumberEntityDescription

    def __init__(
        self,
        coordinator: LetPotDeviceCoordinator,
        description: LetPotNumberEntityDescription,
    ) -> None:
        """Initialize LetPot number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{coordinator.device.serial_number}_{description.key}"

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        return super().available and self.entity_description.available_fn(self.coordinator)

    @property
    def native_max_value(self) -> float:
        """Return the maximum available value."""
        return self.entity_description.max_value_fn(self.coordinator)

    @property
    def native_value(self) -> float | None:
        """Return the number value."""
        return self.entity_description.value_fn(self.coordinator)

    @exception_handler
    async def async_set_native_value(self, value: float) -> None:
        """Change the number value."""
        return await self.entity_description.set_value_fn(
            self.coordinator.device_client,
            self.coordinator.device.serial_number,
            value,
        )
