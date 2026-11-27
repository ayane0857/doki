"""Undo snapshots for the contour editor, independent of its Qt widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from doki.analysis.core import Profiles
    from doki.gui.profile_editor import ProfileEditorDialog

_MAX_UNDO = 200


@dataclass(eq=False)
class _EditorSnapshot:
    samples: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    edits: tuple[set[int], set[int]]
    axis_x: float
    baseline: tuple[np.ndarray, np.ndarray, np.ndarray]
    profiles: Profiles

    @classmethod
    def capture(cls, editor: ProfileEditorDialog) -> _EditorSnapshot:
        return cls(
            (
                editor.sample_y.copy(),
                editor.inner_values.copy(),
                editor.outer_values.copy(),
                editor.original_inner_values.copy(),
                editor.original_outer_values.copy(),
            ),
            (editor.edited_inner_indices.copy(), editor.edited_outer_indices.copy()),
            editor.axis_x,
            (editor.baseline_y.copy(), editor.baseline_inner.copy(), editor.baseline_outer.copy()),
            editor.corrected_profiles,
        )

    def matches(self, other: _EditorSnapshot) -> bool:
        return (
            self.axis_x == other.axis_x
            and self.profiles is other.profiles
            and self.edits == other.edits
            and all(
                np.array_equal(a, b)
                for a, b in zip(
                    self.samples + self.baseline, other.samples + other.baseline, strict=True
                )
            )
        )

    def restore(self, editor: ProfileEditorDialog) -> None:
        (
            editor.sample_y,
            editor.inner_values,
            editor.outer_values,
            editor.original_inner_values,
            editor.original_outer_values,
        ) = (values.copy() for values in self.samples)
        editor.edited_inner_indices, editor.edited_outer_indices = (
            indices.copy() for indices in self.edits
        )
        editor.axis_x = self.axis_x
        editor.baseline_y, editor.baseline_inner, editor.baseline_outer = (
            values.copy() for values in self.baseline
        )
        editor.corrected_profiles = self.profiles


class ProfileEditorHistory:
    def __init__(self, editor: ProfileEditorDialog) -> None:
        self._last = _EditorSnapshot.capture(editor)
        self._undo: list[_EditorSnapshot] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def commit(self, editor: ProfileEditorDialog) -> None:
        current = _EditorSnapshot.capture(editor)
        if not current.matches(self._last):
            self._undo.append(self._last)
            if len(self._undo) > _MAX_UNDO:
                del self._undo[0]
            self._last = current

    def undo(self, editor: ProfileEditorDialog) -> bool:
        if not self._undo:
            return False
        self._last = self._undo.pop()
        self._last.restore(editor)
        return True
