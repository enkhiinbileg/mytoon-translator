from PySide6 import QtCore, QtWidgets, QtGui

class CompareView(QtWidgets.QSplitter):
    def __init__(self, main):
        super().__init__(QtCore.Qt.Horizontal, main)
        self.main = main
        self._syncing = False
        
        # Original/Reference Viewer (Left)
        from app.ui.canvas.image_viewer import ImageViewer
        self.original_viewer = ImageViewer(main)
        self.original_viewer.setObjectName("original_viewer")
        
        # Style the original viewer to distinguish it
        self.original_viewer.setStyleSheet("border: 2px solid #555;")
        
        # Add to splitter
        self.addWidget(self.original_viewer)
        
        # The main viewer (Edited) will be added by CompareController
        
        # Install event filters to capture scroll/zoom events
        self.original_viewer.viewport().installEventFilter(self)
        # Note: self.main.image_viewer's filter will be installed in CompareController
        # or we can do it here if it's already available
        if hasattr(self.main, 'image_viewer'):
            self.main.image_viewer.viewport().installEventFilter(self)

    def sync_viewports(self, source_viewer, target_viewer):
        """Force target_viewer to match source_viewer's transformation and scroll."""
        if self._syncing: return
        self._syncing = True
        try:
            # 1. Sync scene rect and layout data - CRITICAL for scrollbar ranges
            if source_viewer.webtoon_mode and target_viewer.webtoon_mode:
                s_manager = source_viewer.webtoon_manager.layout_manager
                t_manager = target_viewer.webtoon_manager.layout_manager
                
                # Copy layout dimensions
                t_manager.total_height = s_manager.total_height
                t_manager.webtoon_width = s_manager.webtoon_width
                if len(s_manager.image_positions) == len(t_manager.image_positions):
                    t_manager.image_positions = s_manager.image_positions.copy()
                    t_manager.image_heights = s_manager.image_heights.copy()
                    t_manager.page_bottoms = s_manager.page_bottoms.copy()
                
                target_viewer.setSceneRect(source_viewer.sceneRect())
            
            # 2. Sync transformation (Zoom/Scale)
            source_transform = source_viewer.transform()
            target_viewer.setTransform(source_transform)
            
            # 3. Use scene center for perfect alignment
            scene_center = source_viewer.mapToScene(source_viewer.viewport().rect().center())
            
            # Block signals to prevent feedback loops
            target_viewer.verticalScrollBar().blockSignals(True)
            target_viewer.horizontalScrollBar().blockSignals(True)
            try:
                # Align using centerOn
                target_viewer.centerOn(scene_center)
                
                # Double-check scrollbar values
                s_vbar = source_viewer.verticalScrollBar()
                t_vbar = target_viewer.verticalScrollBar()
                if s_vbar.maximum() > 0:
                    t_vbar.setValue(s_vbar.value())
                
                s_hbar = source_viewer.horizontalScrollBar()
                t_hbar = target_viewer.horizontalScrollBar()
                if s_hbar.maximum() > 0:
                    t_hbar.setValue(s_hbar.value())
            finally:
                target_viewer.verticalScrollBar().blockSignals(False)
                target_viewer.horizontalScrollBar().blockSignals(False)
            
            # Logging for debugging
            t_center = target_viewer.mapToScene(target_viewer.viewport().rect().center())
            print(f"Sync Matrix: Scale={source_transform.m11():.4f} | Viewports: Src Y={scene_center.y():.2f}, Tgt Y={t_center.y():.2f}")
            
            if target_viewer.webtoon_mode:
                target_viewer.webtoon_manager._update_loaded_pages()
            target_viewer.update()
        finally:
            self._syncing = False

    def eventFilter(self, source, event):
        """Intercept wheel events from either viewer and apply to both."""
        if event.type() == QtCore.QEvent.Wheel:
            if not self._syncing:
                self._syncing = True
                try:
                    # Apply to both viewers
                    for viewer in [self.original_viewer, self.main.image_viewer]:
                        viewer.event_handler.handle_wheel(event)
                        
                    # Force sync original to match edited
                    self._syncing = False
                    self.sync_viewports(self.main.image_viewer, self.original_viewer)
                    self._syncing = True
                finally:
                    self._syncing = False
                return True
        return super().eventFilter(source, event)

    def resizeEvent(self, event):
        """Handle splitter resize and ensure viewers are updated."""
        super().resizeEvent(event)
        if not self._syncing:
            # Force a refresh of the layout
            QtCore.QTimer.singleShot(50, self._force_sync_after_resize)

    def _force_sync_after_resize(self):
        if hasattr(self.main, 'image_viewer') and self.original_viewer:
            print(f"CompareView resize sync. Width: {self.width()}")
            self.sync_viewports(self.main.image_viewer, self.original_viewer)
