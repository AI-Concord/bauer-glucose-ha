"""Persisted insulin dose log for one Bauer Glucose config entry.

Kept outside the recorder/history system deliberately: HA purges recorder
history after a default retention window, but a dosing history is exactly
the kind of thing you want to keep correlating against glucose for months,
not days. Backed by HA's own Store helper (a JSON file under
.storage/), so it survives restarts without any extra database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import MAX_STORED_DOSES

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "bauer_glucose_doses"


@dataclass
class DoseRecord:
    timestamp: datetime
    insulin_type: str  # "long" or "short"
    units: float
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "insulin_type": self.insulin_type,
            "units": self.units,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DoseRecord":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            insulin_type=data["insulin_type"],
            units=data["units"],
            note=data.get("note"),
        )


class DoseStore:
    """Loads/saves a capped list of DoseRecords for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry_id}")
        self._doses: list[DoseRecord] = []

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self._doses = [DoseRecord.from_json(d) for d in data.get("doses", [])]

    async def async_add_dose(
        self,
        insulin_type: str,
        units: float,
        note: str | None = None,
        timestamp: datetime | None = None,
    ) -> DoseRecord:
        record = DoseRecord(
            timestamp=timestamp or datetime.now(timezone.utc),
            insulin_type=insulin_type,
            units=units,
            note=note,
        )
        self._doses.append(record)
        self._doses.sort(key=lambda d: d.timestamp)
        self._doses = self._doses[-MAX_STORED_DOSES:]
        await self._store.async_save({"doses": [d.to_json() for d in self._doses]})
        return record

    @property
    def doses(self) -> list[DoseRecord]:
        return list(self._doses)

    @property
    def last_dose(self) -> DoseRecord | None:
        return self._doses[-1] if self._doses else None
