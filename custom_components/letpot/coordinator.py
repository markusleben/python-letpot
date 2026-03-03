"""Coordinator for the LetPot integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from letpot.deviceclient import LetPotDeviceClient
from letpot.exceptions import LetPotAuthenticationException, LetPotException
from letpot.models import LetPotDevice, LetPotDeviceStatus

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import REQUEST_UPDATE_TIMEOUT

_LOGGER = logging.getLogger(__name__)

CONSECUTIVE_FAILURES_FOR_RECONNECT = 3

type LetPotConfigEntry = ConfigEntry[list[LetPotDeviceCoordinator]]


class LetPotDeviceCoordinator(DataUpdateCoordinator[LetPotDeviceStatus]):
    """Class to handle data updates for a specific garden."""

    config_entry: LetPotConfigEntry

    device: LetPotDevice
    device_client: LetPotDeviceClient
    _consecutive_failures: int

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: LetPotConfigEntry,
        device: LetPotDevice,
        device_client: LetPotDeviceClient,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"LetPot {device.serial_number}",
            update_interval=timedelta(minutes=10),
        )
        self.device = device
        self.device_client = device_client
        self._consecutive_failures = 0

    def _handle_status_update(self, status: LetPotDeviceStatus) -> None:
        """Distribute status update to entities."""
        self.async_set_updated_data(data=status)

    async def _async_setup(self) -> None:
        """Set up subscription for coordinator."""
        try:
            await self.device_client.subscribe(
                self.device.serial_number, self._handle_status_update
            )
        except LetPotAuthenticationException as exc:
            raise ConfigEntryAuthFailed from exc

    async def _async_update_data(self) -> LetPotDeviceStatus:
        """Request an update from the device and wait for a status update or timeout."""
        try:
            async with asyncio.timeout(REQUEST_UPDATE_TIMEOUT):
                await self.device_client.get_current_status(self.device.serial_number)
        except LetPotAuthenticationException as exc:
            self._consecutive_failures = 0
            raise ConfigEntryAuthFailed from exc
        except (LetPotException, TimeoutError) as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= CONSECUTIVE_FAILURES_FOR_RECONNECT:
                _LOGGER.warning(
                    "LetPot %s: %i consecutive update failures, forcing reconnection",
                    self.device.serial_number,
                    self._consecutive_failures,
                )
                self._consecutive_failures = 0
                try:
                    await self.device_client.reconnect()
                except Exception:
                    _LOGGER.exception(
                        "LetPot %s: Reconnection failed",
                        self.device.serial_number,
                    )
            raise UpdateFailed(exc) from exc

        self._consecutive_failures = 0

        # The subscription task will have updated coordinator.data, so return that data.
        # If we don't return anything here, coordinator.data will be set to None.
        return self.data
