from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QSettings

from app.shortcuts import get_default_shortcuts, get_shortcut_definitions
from app.ui.dayu_widgets.message import MMessage

if TYPE_CHECKING:
    from controller import ComicTranslate


class ShortcutController:
    SETTINGS_GROUP = "shortcuts"

    def __init__(self, main: "ComicTranslate"):
        self.main = main
        self._shortcuts: dict[str, QtGui.QShortcut] = {}
        self._register_shortcuts()

    def _register_shortcuts(self) -> None:
        # Clear existing shortcuts
        for sid, action in self._shortcuts.items():
            self.main.removeAction(action)
        self._shortcuts.clear()

        for definition in get_shortcut_definitions():
            action = QtGui.QAction(self.main)
            action.setShortcutContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(
                lambda checked=False, sid=definition.id: self._activate_shortcut(sid)
            )
            self.main.addAction(action)
            self._shortcuts[definition.id] = action

        self.apply_shortcuts()

    def apply_shortcuts(self) -> None:
        current_shortcuts = self.get_current_shortcuts()
        for shortcut_id, action in self._shortcuts.items():
            key = current_shortcuts.get(shortcut_id, "")
            action.setShortcut(QtGui.QKeySequence(key))

    def get_current_shortcuts(self) -> dict[str, str]:
        shortcuts = get_default_shortcuts()
        settings = QSettings("ComicLabs", "ComicTranslate")
        settings.beginGroup(self.SETTINGS_GROUP)
        for definition in get_shortcut_definitions():
            shortcuts[definition.id] = settings.value(
                definition.id,
                shortcuts[definition.id],
                type=str,
            )
        settings.endGroup()
        return shortcuts

    def _activate_shortcut(self, shortcut_id: str) -> None:
        handlers = {
            "undo": self._undo,
            "redo": self._redo,
            "delete_selected_box": self._delete_selected_box,
            "restore_text_blocks": self._restore_text_blocks,
            "toggle_compare": self._toggle_compare,
            "toggle_rect_clean": self._toggle_rect_clean,
            "toggle_inpaint_rect": self._toggle_inpaint_rect,
            "toggle_patch_restore": self._toggle_patch_restore,
        }
        handler = handlers.get(shortcut_id)
        if handler is not None:
            handler()

    def _toggle_compare(self) -> None:
        if self._is_text_input_focused():
            return
        # Toggle the compare mode button in UI
        current = self.main.compare_toggle.isChecked()
        self.main.compare_toggle.setChecked(not current)

    def _toggle_rect_clean(self) -> None:
        if self._is_text_input_focused():
            return
        new_tool = None if self.main.image_viewer.current_tool == "rect_clean" else "rect_clean"
        self.main.set_tool(new_tool)

    def _toggle_inpaint_rect(self) -> None:
        if self._is_text_input_focused():
            return
        new_tool = None if self.main.image_viewer.current_tool == "inpaint_rect" else "inpaint_rect"
        self.main.set_tool(new_tool)

    def _toggle_patch_restore(self) -> None:
        if self._is_text_input_focused():
            return
        new_tool = None if self.main.image_viewer.current_tool == "patch_restore" else "patch_restore"
        self.main.set_tool(new_tool)

    def _workspace_is_active(self) -> bool:
        try:
            return self.main._center_stack.currentWidget() is self.main.main_content_widget
        except Exception:
            return False

    def _is_text_input_focused(self) -> bool:
        focus_widget = QtWidgets.QApplication.focusWidget()
        editable_types = (
            QtWidgets.QLineEdit,
            QtWidgets.QTextEdit,
            QtWidgets.QPlainTextEdit,
            QtWidgets.QAbstractSpinBox,
            QtWidgets.QKeySequenceEdit,
        )
        return isinstance(focus_widget, editable_types)

    def _undo(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        stack = self.main.undo_group.activeStack()
        if stack is not None and stack.canUndo():
            self.main.undo_group.undo()

    def _redo(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        stack = self.main.undo_group.activeStack()
        if stack is not None and stack.canRedo():
            self.main.undo_group.redo()

    def _delete_selected_box(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        self.main.delete_selected_box()

    def _restore_text_blocks(self) -> None:
        if not self._workspace_is_active() or self._is_text_input_focused():
            return
        self.main.restore_text_blocks()
