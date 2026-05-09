from __future__ import annotations
import os
from PySide6 import QtCore, QtWidgets

class BatchImportDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Batch Multi-Chapter Import"))
        self.resize(600, 450)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Source Root Folder
        source_group = QtWidgets.QGroupBox(self.tr("Source Folder (Containing Chapters)"))
        source_layout = QtWidgets.QHBoxLayout(source_group)
        self.source_edit = QtWidgets.QLineEdit()
        self.source_edit.setPlaceholderText(self.tr("Select folder containing chapter subfolders..."))
        self.source_browse = QtWidgets.QPushButton(self.tr("Browse"))
        self.source_browse.clicked.connect(self._browse_source)
        source_layout.addWidget(self.source_edit)
        source_layout.addWidget(self.source_browse)
        layout.addWidget(source_group)
        
        # Destination Folder
        dest_group = QtWidgets.QGroupBox(self.tr("Destination Folder (For Project Files)"))
        dest_layout = QtWidgets.QHBoxLayout(dest_group)
        self.dest_edit = QtWidgets.QLineEdit()
        self.dest_edit.setPlaceholderText(self.tr("Select where to save .ctpr files..."))
        self.dest_browse = QtWidgets.QPushButton(self.tr("Browse"))
        self.dest_browse.clicked.connect(self._browse_dest)
        dest_layout.addWidget(self.dest_edit)
        dest_layout.addWidget(self.dest_browse)
        layout.addWidget(dest_group)
        
        # Options
        self.auto_process_cb = QtWidgets.QCheckBox(self.tr("Automatically start OCR/Translation for each chapter"))
        self.auto_process_cb.setChecked(True)
        
        self.fast_mode_cb = QtWidgets.QCheckBox(self.tr("Fast Mode (OCR + Translation only, skip Inpainting/Rendering)"))
        self.fast_mode_cb.setChecked(False)
        
        layout.addWidget(self.auto_process_cb)
        layout.addWidget(self.fast_mode_cb)
        
        # Chapter List
        layout.addWidget(QtWidgets.QLabel(self.tr("Detected Chapters:")))
        self.chapter_list = QtWidgets.QListWidget()
        layout.addWidget(self.chapter_list)
        
        # Bottom Buttons
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        
        self.source_edit.textChanged.connect(self._scan_chapters)

    def _browse_source(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, self.tr("Select Source Root Folder"))
        if folder:
            self.source_edit.setText(folder)

    def _browse_dest(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, self.tr("Select Destination Folder"))
        if folder:
            self.dest_edit.setText(folder)

    def _scan_chapters(self):
        self.chapter_list.clear()
        root = self.source_edit.text().strip()
        if not root or not os.path.isdir(root):
            return
            
        try:
            subdirs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
            subdirs.sort()
            for d in subdirs:
                # Check if it contains images
                full_path = os.path.join(root, d)
                images = [f for f in os.listdir(full_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))]
                if images:
                    item = QtWidgets.QListWidgetItem(f"{d} ({len(images)} images)")
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, full_path)
                    self.chapter_list.addItem(item)
        except Exception as e:
            print(f"Error scanning chapters: {e}")

    def get_data(self):
        chapters = []
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            chapters.append({
                "name": item.text().split(" (")[0],
                "path": item.data(QtCore.Qt.ItemDataRole.UserRole)
            })
        return {
            "source": self.source_edit.text().strip(),
            "dest": self.dest_edit.text().strip(),
            "auto_process": self.auto_process_cb.isChecked(),
            "fast_mode": self.fast_mode_cb.isChecked(),
            "chapters": chapters
        }
