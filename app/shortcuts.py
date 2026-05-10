from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QT_TRANSLATE_NOOP


@dataclass(frozen=True)
class ShortcutDefinition:
    id: str
    label: str
    description: str
    default: str


SHORTCUT_DEFINITIONS: tuple[ShortcutDefinition, ...] = (
    ShortcutDefinition(
        id="undo",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Undo"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Undo the last editing action."),
        default="Ctrl+Z",
    ),
    ShortcutDefinition(
        id="redo",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Redo"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Redo the previously undone action."),
        default="Ctrl+Y",
    ),
    ShortcutDefinition(
        id="delete_selected_box",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Delete Selected Box"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Delete the currently selected text box."),
        default="Delete",
    ),
    ShortcutDefinition(
        id="restore_text_blocks",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Restore Text Blocks"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Draw saved text blocks back onto the image for editing."),
        default="Ctrl+Shift+R",
    ),
    ShortcutDefinition(
        id="toggle_compare",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle Compare Mode"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle side-by-side compare mode."),
        default="Z",
    ),
    ShortcutDefinition(
        id="toggle_rect_clean",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle Rect Clean Tool"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Activate the rectangular cleaning tool."),
        default="R",
    ),
    ShortcutDefinition(
        id="toggle_inpaint_rect",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle Inpaint Rect Tool"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Activate the AI-based rectangular cleaning tool."),
        default="S",
    ),
    ShortcutDefinition(
        id="toggle_patch_restore",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle Patch Restore Tool"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Activate the interactive restoration tool."),
        default="K",
    ),
    ShortcutDefinition(
        id="increase_outline_width",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Increase Outline Width"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Increase the outline thickness of selected text."),
        default="]",
    ),
    ShortcutDefinition(
        id="decrease_outline_width",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Decrease Outline Width"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Decrease the outline thickness of selected text."),
        default="[",
    ),
    ShortcutDefinition(
        id="toggle_outline",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle Outline"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle text outline on/off for selected text."),
        default="Shift+O",
    ),
    ShortcutDefinition(
        id="outline_white",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "White Outline"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Apply a white outline to selected text."),
        default="Ctrl+Shift+W",
    ),
    ShortcutDefinition(
        id="outline_black",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Black Outline"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Apply a black outline to selected text."),
        default="Ctrl+Shift+B",
    ),
    ShortcutDefinition(
        id="outline_color_picker",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Outline Color Picker"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Open the color picker for the text outline."),
        default="Ctrl+Shift+O",
    ),
    ShortcutDefinition(
        id="copy_style",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Copy Style"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Copy the font style and outline of the selected text."),
        default="Ctrl+Shift+C",
    ),
    ShortcutDefinition(
        id="paste_style",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Paste Style"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Paste the copied style onto the selected text."),
        default="Ctrl+Shift+V",
    ),
)


def get_shortcut_definitions() -> tuple[ShortcutDefinition, ...]:
    return SHORTCUT_DEFINITIONS


def get_default_shortcuts() -> dict[str, str]:
    return {definition.id: definition.default for definition in SHORTCUT_DEFINITIONS}
