"""Support for LetPot sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from letpot.models import DeviceFeature, LetPotDeviceStatus, LetPotWateringSystemStatus, TemperatureUnit

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import LetPotConfigEntry, LetPotDeviceCoordinator
from .entity import LetPotEntity, LetPotEntityDescription

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


LETPOT_TEMPERATURE_UNIT_HA_UNIT = {
    TemperatureUnit.CELSIUS: UnitOfTemperature.CELSIUS,
    TemperatureUnit.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
}

WATERING_REASON_MAP: dict[int, str] = {
    0: "None",
    1: "Cycle disabled",
    2: "Manual",
    3: "Cycle",
    4: "Scheduled",
}


def _decode_4byte_uint32(data: list[int]) -> int:
    """Decode a 4-byte big-endian uint32."""
    return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]


def _decode_pump_countdown_end_time(status: LetPotDeviceStatus) -> datetime | None:
    """Decode pump countdown to estimated end time as UTC timestamp."""
    if not isinstance(status, LetPotWateringSystemStatus):
        return None
    seconds = _decode_4byte_uint32(status.pump_countdown)
    if seconds == 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _decode_relative_past(data: list[int]) -> datetime | None:
    """Decode a 4-byte big-endian duration (seconds ago) to an absolute timestamp."""
    seconds = _decode_4byte_uint32(data)
    if seconds == 0:
        return None
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _decode_relative_future(data: list[int]) -> datetime | None:
    """Decode a 4-byte big-endian duration (seconds from now) to an absolute timestamp."""
    seconds = _decode_4byte_uint32(data)
    if seconds == 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


@dataclass(frozen=True, kw_only=True)
class LetPotSensorEntityDescription(LetPotEntityDescription, SensorEntityDescription):
    """Describes a LetPot sensor entity."""

    native_unit_of_measurement_fn: Callable[[LetPotDeviceStatus], str | None]
    value_fn: Callable[[LetPotDeviceStatus], StateType | datetime]


SENSORS: tuple[LetPotSensorEntityDescription, ...] = (
    LetPotSensorEntityDescription(
        key="temperature",
        value_fn=lambda status: status.temperature_value,
        native_unit_of_measurement_fn=(
            lambda status: LETPOT_TEMPERATURE_UNIT_HA_UNIT[
                status.temperature_unit or TemperatureUnit.CELSIUS
            ]
        ),
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        supported_fn=(
            lambda coordinator: (
                DeviceFeature.TEMPERATURE
                in coordinator.device_client.device_info(
                    coordinator.device.serial_number
                ).features
            )
        ),
    ),
    LetPotSensorEntityDescription(
        key="water_level",
        name="Water level",
        value_fn=lambda status: status.water_level,
        native_unit_of_measurement_fn=lambda _: PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        supported_fn=(
            lambda coordinator: (
                DeviceFeature.WATER_LEVEL
                in coordinator.device_client.device_info(
                    coordinator.device.serial_number
                ).features
            )
        ),
    ),
    LetPotSensorEntityDescription(
        key="pump_countdown",
        name="Watering time remaining",
        value_fn=_decode_pump_countdown_end_time,
        native_unit_of_measurement_fn=lambda _: None,
        device_class=SensorDeviceClass.TIMESTAMP,
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
    ),
    LetPotSensorEntityDescription(
        key="pump_works_latest_reason",
        name="Last watering trigger",
        value_fn=lambda status: (
            WATERING_REASON_MAP.get(status.pump_works_latest_reason)
            if isinstance(status, LetPotWateringSystemStatus)
            else None
        ),
        native_unit_of_measurement_fn=lambda _: None,
        device_class=SensorDeviceClass.ENUM,
        options=list(WATERING_REASON_MAP.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
    ),
    LetPotSensorEntityDescription(
        key="pump_works_latest_time",
        name="Last watering time",
        value_fn=lambda status: (
            _decode_relative_past(status.pump_works_latest_time)
            if isinstance(status, LetPotWateringSystemStatus)
            else None
        ),
        native_unit_of_measurement_fn=lambda _: None,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
    ),
    LetPotSensorEntityDescription(
        key="pump_works_next_time",
        name="Next watering time",
        value_fn=lambda status: (
            _decode_relative_future(status.pump_works_next_time)
            if isinstance(status, LetPotWateringSystemStatus)
            else None
        ),
        native_unit_of_measurement_fn=lambda _: None,
        device_class=SensorDeviceClass.TIMESTAMP,
        supported_fn=lambda coordinator: isinstance(coordinator.data, LetPotWateringSystemStatus),
    ),
    LetPotSensorEntityDescription(
        key="pump_cycle_skip_water",
        name="Skip watering duration",
        value_fn=lambda status: (
            status.pump_cycle_skip_water
            if isinstance(status, LetPotWateringSystemStatus)
            and status.pump_cycle_skip_water is not None
            else None
        ),
        native_unit_of_measurement_fn=lambda _: UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        supported_fn=lambda coordinator: (
            isinstance(coordinator.data, LetPotWateringSystemStatus)
            and coordinator.data.pump_cycle_skip_water is not None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LetPotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up LetPot sensor entities based on a device features."""
    coordinators = entry.runtime_data
    async_add_entities(
        LetPotSensorEntity(coordinator, description)
        for description in SENSORS
        for coordinator in coordinators
        if description.supported_fn(coordinator)
    )


class LetPotSensorEntity(LetPotEntity, SensorEntity):
    """Defines a LetPot sensor entity."""

    entity_description: LetPotSensorEntityDescription
    _cached_timestamp: datetime | None = None

    def __init__(
        self,
        coordinator: LetPotDeviceCoordinator,
        description: LetPotSensorEntityDescription,
    ) -> None:
        """Initialize LetPot sensor entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{coordinator.device.serial_number}_{description.key}"
        # Compute initial cached value for timestamp sensors
        if description.device_class == SensorDeviceClass.TIMESTAMP:
            self._cached_timestamp = description.value_fn(coordinator.data)

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Cache timestamp values at update time to prevent drift between updates
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            self._cached_timestamp = self.entity_description.value_fn(
                self.coordinator.data
            )
        super()._handle_coordinator_update()

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the native unit of measurement."""
        return self.entity_description.native_unit_of_measurement_fn(
            self.coordinator.data
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state of the sensor."""
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            return self._cached_timestamp
        return self.entity_description.value_fn(self.coordinator.data)
