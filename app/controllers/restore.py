from __future__ import annotations
from typing import TYPE_CHECKING
from PySide6 import QtCore
from app.ui.dayu_widgets.message import MMessage
from app.ui.commands.inpaint import PatchRemoveCommand

if TYPE_CHECKING:
    from controller import ComicTranslate

class RestoreController(QtCore.QObject):
    def __init__(self, main: ComicTranslate):
        super().__init__(main)
        self.main = main

    def restore_current_page(self):
        """Restores the original image for the currently active page."""
        page_idx = self.main.curr_img_idx
        if not (0 <= page_idx < len(self.main.image_files)):
            return
        
        file_path = self.main.image_files[page_idx]
        self._restore_page_by_path(file_path, page_idx)
        
        MMessage.success(text=f"Restored original image for page {page_idx + 1}", parent=self.main)

    def restore_all_pages(self):
        """Restores the original images for all pages in the project."""
        if not self.main.image_files:
            return
            
        self.main.loading.setVisible(True)
        self.main.disable_hbutton_group()

        def run_restore_all():
            for idx, file_path in enumerate(self.main.image_files):
                self._restore_page_by_path(file_path, idx)
            return len(self.main.image_files)

        def on_finished(count):
            self.main.loading.setVisible(False)
            self.main.enable_hbutton_group()
            MMessage.success(text=f"Restored original images for all {count} pages", parent=self.main)

        # Run in thread if there are many pages to avoid UI freeze
        if len(self.main.image_files) > 5:
            self.main.run_threaded(run_restore_all, on_finished, self.main.default_error_handler)
        else:
            run_restore_all()
            on_finished(len(self.main.image_files))

    def _restore_page_by_path(self, file_path: str, page_idx: int):
        # 1. Clear image caches and history
        self.main.image_data.pop(file_path, None)
        self.main.in_memory_history.pop(file_path, None)
        self.main.image_history[file_path] = [file_path] # Reset history to only original file
        self.main.current_history_index[file_path] = 0
        
        # 2. Clear patches
        self.main.image_patches.pop(file_path, None)
        self.main.in_memory_patches.pop(file_path, None)
        
        # 3. Clear brush strokes state
        if file_path in self.main.image_states:
            self.main.image_states[file_path]['brush_strokes'] = []

        # 4. Reload and refresh if it's the current page
        if self.main.curr_img_idx == page_idx:
            # Refresh UI on main thread
            def refresh_ui():
                self.main.image_viewer.clear_brush_strokes(page_switch=True)
                if self.main.webtoon_mode:
                    manager = getattr(self.main.image_viewer, "webtoon_manager", None)
                    if manager:
                        manager.image_loader.unload_image(page_idx)
                        manager.load_images_lazy(self.main.image_files, page_idx)
                else:
                    img = self.main.image_ctrl.load_image(file_path)
                    self.main.image_ctrl.display_image_from_loaded(img, page_idx)
                self.main.image_viewer.update()

            QtCore.QTimer.singleShot(0, refresh_ui)
        
        self.main.mark_project_dirty()

    def handle_patch_restore(self, patch_item):
        """Removes a specific patch when clicked with the patch_restore tool."""
        page_idx = patch_item.data(1) # PAGE_INDEX_KEY
        
        if page_idx is None:
            # Fallback to current page if not set
            page_idx = self.main.curr_img_idx
            
        if not (0 <= page_idx < len(self.main.image_files)):
            return
            
        file_path = self.main.image_files[page_idx]
        
        # Use PatchRemoveCommand for Undo/Redo support
        command = PatchRemoveCommand(self.main, patch_item, file_path)
        self.main.push_command(command)
        
        MMessage.success(text="Removed patch", parent=self.main)
