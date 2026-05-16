from __future__ import annotations
import os
from typing import TYPE_CHECKING, List, Dict
from PySide6 import QtCore

if TYPE_CHECKING:
    from controller import ComicTranslate

class BatchChapterController(QtCore.QObject):
    finished = QtCore.Signal()
    progress = QtCore.Signal(int, int, str) # current, total, chapter_name

    def __init__(self, main: ComicTranslate):
        super().__init__(main)
        self.main = main
        self.queue: List[Dict] = []
        self.current_idx = -1
        self.dest_folder = ""
        self.auto_process = False
        self.fast_mode = False
        self._is_running = False
        self._old_on_batch_finished = None

    def start_batch_import(self, data: Dict):
        self.queue = data["chapters"]
        self.dest_folder = data["dest"]
        self.auto_process = data["auto_process"]
        self.fast_mode = data.get("fast_mode", False)
        self.current_idx = 0
        self._is_running = True
        
        if not os.path.exists(self.dest_folder):
            os.makedirs(self.dest_folder, exist_ok=True)
            
        self._process_next()

    def _process_next(self):
        if not self._is_running:
            return
            
        if self.current_idx >= len(self.queue):
            self._is_running = False
            # Show final message
            from app.ui.messages import Messages
            Messages.show_info(self.main, self.main.tr("Batch Import Complete"), self.main.tr("All chapters have been processed."))
            self.finished.emit()
            return

        chapter = self.queue[self.current_idx]
        self.progress.emit(self.current_idx + 1, len(self.queue), chapter["name"])
        
        # 1. Load images for this chapter
        image_files = []
        try:
            for f in os.listdir(chapter["path"]):
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                    image_files.append(os.path.join(chapter["path"], f))
        except Exception as e:
            print(f"Error reading chapter folder {chapter['path']}: {e}")
            self.current_idx += 1
            self._process_next()
            return
            
        if not image_files:
            self.current_idx += 1
            self._process_next()
            return

        # 2. Setup project state
        self.main.image_ctrl.clear_state()
        # Use our new finished_callback in thread_load_images
        self.main.image_ctrl.thread_load_images(image_files, finished_callback=self._on_images_loaded)

    def _on_images_loaded(self):
        # This is called when TaskRunner finishes load_initial_image
        chapter = self.queue[self.current_idx]
        project_file = os.path.join(self.dest_folder, f"{chapter['name']}.ctpr")
        
        # 3. Save Project
        self.main.project_ctrl.run_save_proj(project_file)
        
        # 4. Start Batch if requested
        if self.auto_process:
            # Monkeypatch on_batch_process_finished to move to next chapter
            if self._old_on_batch_finished is None:
                self._old_on_batch_finished = self.main.on_batch_process_finished
            
            self.main.on_batch_process_finished = self._on_batch_finished_proxy
            
            # Start batch process
            # We need to make sure the UI is ready
            QtCore.QTimer.singleShot(500, lambda: self.main.start_batch_process(fast_mode=self.fast_mode))
        else:
            self.current_idx += 1
            QtCore.QTimer.singleShot(500, self._process_next)

    def _on_batch_finished_proxy(self):
        # Call original if it was set
        if self._old_on_batch_finished:
            self._old_on_batch_finished()
        
        # Restore original (optional, but good for cleanliness)
        # self.main.on_batch_process_finished = self._old_on_batch_finished
        
        # Move to next chapter
        self.current_idx += 1
        QtCore.QTimer.singleShot(1000, self._process_next)
