"""Track the accepted→running→terminal lifecycle for one Player action at a time."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "rejected"}
ACTIVE_STATUSES = {"accepted", "running"}


@dataclass
class ActionRecord:
    action_id: str
    actor: str
    action: str
    parameters: Dict[str, object]
    submitted_at: float = field(default_factory=time.monotonic)
    status: str = "pending"
    history: List[str] = field(default_factory=list)
    last_message: str = ""
    terminated_at: Optional[float] = None
    completed: asyncio.Event = field(default_factory=asyncio.Event)

    def apply(self, status: str, message: str = "") -> None:
        self.status = status
        self.last_message = message
        self.history.append(status)
        if status in TERMINAL_STATUSES:
            self.terminated_at = time.monotonic()
            self.completed.set()

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


class ActionAlreadyActive(RuntimeError):
    """Raised when a new action is requested while one is still in-flight."""


class ActionTracker:
    """Serializes Player actions and correlates lifecycle results by ActionId."""

    def __init__(self) -> None:
        self._active: Optional[ActionRecord] = None
        self._by_id: Dict[str, ActionRecord] = {}
        self._lock = asyncio.Lock()
        self._listeners: List[Callable[[ActionRecord], None]] = []

    def subscribe(self, listener: Callable[[ActionRecord], None]) -> None:
        self._listeners.append(listener)

    @property
    def active(self) -> Optional[ActionRecord]:
        return self._active

    def get(self, action_id: str) -> Optional[ActionRecord]:
        return self._by_id.get(action_id)

    async def submit(self, record: ActionRecord) -> ActionRecord:
        async with self._lock:
            is_cancel = record.action == "Cancel"
            if (
                not is_cancel
                and self._active is not None
                and not self._active.is_terminal
            ):
                raise ActionAlreadyActive(
                    f"Action '{self._active.action_id}' ({self._active.status}) is still in flight"
                )
            self._by_id[record.action_id] = record
            if not is_cancel:
                self._active = record
            return record

    def apply_result(self, result: Dict[str, object]) -> Optional[ActionRecord]:
        action_id = str(result.get("ActionId") or "")
        status = str(result.get("Status") or "").lower()
        message = str(result.get("Message") or "")
        if not action_id or not status:
            return None

        record = self._by_id.get(action_id)
        if record is None:
            return None

        record.apply(status, message)
        if record.is_terminal and self._active is record:
            self._active = None

        for listener in list(self._listeners):
            try:
                listener(record)
            except Exception:  # noqa: BLE001
                pass
        return record

    async def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        record = self._active
        if record is None or record.is_terminal:
            return True
        try:
            await asyncio.wait_for(record.completed.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True
