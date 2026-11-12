"""Non-blocking Tkinter `after()` flood progression animation controller."""

from __future__ import annotations

import tkinter as tk
from typing import Callable


class FloodAnimationController:
    """Drives timestep playback over Phase 3 results without blocking the GUI thread."""

    def __init__(
        self,
        widget: tk.Misc,
        on_step_changed: Callable[[int], None],
        on_state_changed: Callable[[str], None] | None = None,
    ) -> None:
        self._widget = widget
        self._on_step_changed = on_step_changed
        self._on_state_changed = on_state_changed

        self._total_steps: int = 0
        self._current_index: int = 0  # 0-based index into simulation steps
        self._is_playing: bool = False
        self._is_paused: bool = False
        self._speed_multiplier: float = 1.0
        self._base_interval_ms: int = 650
        self._after_id: str | None = None

    @property
    def total_steps(self) -> int:
        return self._total_steps

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    def configure_steps(self, total_steps: int, start_index: int = 0) -> None:
        self.stop(notify=False)
        self._total_steps = max(0, int(total_steps))
        self._current_index = max(0, min(start_index, max(0, self._total_steps - 1)))
        self._emit_state("Stopped")

    def start(self) -> None:
        if self._total_steps <= 0:
            return
        if self._current_index >= self._total_steps - 1:
            self._current_index = 0
            self._on_step_changed(self._current_index)
        self._is_playing = True
        self._is_paused = False
        self._emit_state("Playing")
        self._schedule_next()

    def pause(self) -> None:
        if not self._is_playing:
            return
        self._cancel_pending()
        self._is_playing = False
        self._is_paused = True
        self._emit_state("Paused")

    def resume(self) -> None:
        if self._total_steps <= 0:
            return
        if self._is_paused or not self._is_playing:
            self._is_playing = True
            self._is_paused = False
            self._emit_state("Playing")
            self._schedule_next()

    def stop(self, notify: bool = True) -> None:
        self._cancel_pending()
        self._is_playing = False
        self._is_paused = False
        self._current_index = 0
        if notify:
            if self._total_steps > 0:
                self._on_step_changed(self._current_index)
            self._emit_state("Stopped")

    def next_step(self) -> int:
        if self._total_steps <= 0:
            return 0
        if self._current_index < self._total_steps - 1:
            self._current_index += 1
            self._on_step_changed(self._current_index)
        return self._current_index

    def prev_step(self) -> int:
        if self._total_steps <= 0:
            return 0
        if self._current_index > 0:
            self._current_index -= 1
            self._on_step_changed(self._current_index)
        return self._current_index

    def seek(self, index: int) -> int:
        if self._total_steps <= 0:
            return 0
        clamped = max(0, min(int(index), self._total_steps - 1))
        if clamped != self._current_index:
            self._current_index = clamped
            self._on_step_changed(self._current_index)
        return self._current_index

    def set_speed(self, multiplier: float) -> None:
        self._speed_multiplier = max(0.25, min(8.0, float(multiplier)))
        if self._is_playing:
            self._cancel_pending()
            self._schedule_next()

    def _interval_ms(self) -> int:
        return max(90, int(self._base_interval_ms / self._speed_multiplier))

    def _schedule_next(self) -> None:
        self._cancel_pending()
        self._after_id = self._widget.after(self._interval_ms(), self._tick)

    def _cancel_pending(self) -> None:
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _tick(self) -> None:
        self._after_id = None
        if not self._is_playing:
            return
        if self._current_index < self._total_steps - 1:
            self._current_index += 1
            self._on_step_changed(self._current_index)
            self._schedule_next()
        else:
            self._is_playing = False
            self._is_paused = False
            self._emit_state("Completed")

    def _emit_state(self, state: str) -> None:
        if self._on_state_changed is not None:
            self._on_state_changed(state)
