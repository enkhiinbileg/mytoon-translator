from PySide6 import QtCore, QtWidgets

class CompareController(QtCore.QObject):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.is_active = False
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("CompareController INITIALIZED - VERSION 3 - FINAL FIX")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        
    def toggle_compare_mode(self, enabled: bool):
        """Toggle side-by-side compare mode."""
        self.is_active = enabled
        if enabled:
            self.show_compare_view()
        else:
            self.hide_compare_view()
            
    def show_compare_view(self):
        """Setup and show the compare split view."""
        if not hasattr(self, 'compare_view'):
            from app.ui.canvas.compare_view import CompareView
            self.compare_view = CompareView(self.main)
            self.main.central_stack.addWidget(self.compare_view)
            
        # Store current scroll state
        self._pending_scroll_pos = None
        if self.main.webtoon_mode:
            self._pending_scroll_pos = self.main.image_viewer.verticalScrollBar().value()

        # Move main viewer to compare view
        self.compare_view.addWidget(self.main.image_viewer)
        self.main.image_viewer.show()
        
        # Ensure both sides are weighted equally
        self.compare_view.setStretchFactor(0, 1)
        self.compare_view.setStretchFactor(1, 1)
        
        self.main.central_stack.setCurrentWidget(self.compare_view)
        
        # Use a short delay to set sizes after layout has processed the new widget
        QtCore.QTimer.singleShot(100, self._sync_initial_sizes)
        
        self.compare_view.show()
        self.compare_view.update()
        self.sync_content()

    def _sync_initial_sizes(self):
        if not hasattr(self, 'compare_view') or not self.is_active:
            return
        width = self.compare_view.width()
        print(f"Finalizing splitter sizes. Width: {width}")
        if width > 100:
            self.compare_view.setSizes([width // 2, width // 2])
        else:
            self.compare_view.setSizes([500, 500])
        
        # Restore scroll position
        if self._pending_scroll_pos is not None:
            self.main.image_viewer.verticalScrollBar().setValue(self._pending_scroll_pos)
            # Also sync the original viewer's scroll
            self.compare_view.original_viewer.verticalScrollBar().setValue(self._pending_scroll_pos)
            self._pending_scroll_pos = None
            
        # Force a refresh of both viewers after a short delay to let layout settle
        QtCore.QTimer.singleShot(50, self._force_refresh_viewers)
        
    def _force_refresh_viewers(self):
        if not self.is_active:
            return
        print("Forcing refresh of viewers in Compare Mode")
        
        # In webtoon mode, poke the managers to update loaded pages for the new viewport
        if self.main.webtoon_mode:
            self.main.image_viewer.webtoon_manager._update_loaded_pages()
            self.compare_view.original_viewer.webtoon_manager._update_loaded_pages()
            
        self.main.image_viewer.fitInView()
        # Force the original viewer to match the main viewer's state
        self.compare_view.sync_viewports(self.main.image_viewer, self.compare_view.original_viewer)
            
        self.main.image_viewer.update()
        self.compare_view.original_viewer.update()

    def hide_compare_view(self):
        """Revert to single view mode."""
        if hasattr(self, 'compare_view'):
            print("Hiding compare view, moving main viewer back to central_stack index 1")
            # Remove styling added in CompareView
            self.main.image_viewer.setStyleSheet("")
            # Move main viewer back to central stack
            self.main.central_stack.insertWidget(1, self.main.image_viewer)
            self.main.central_stack.setCurrentWidget(self.main.image_viewer)
            
            # Restore normal lazy loading limits for main viewer
            if self.main.webtoon_mode:
                mgr = self.main.image_viewer.webtoon_manager
                mgr.max_loaded_pages = 5   # default
                mgr.viewport_buffer = 3000  # default
            
            # Refresh to ensure it fits the full screen again
            QtCore.QTimer.singleShot(50, self.main.image_viewer.fitInView)
            
    def sync_content(self):
        """Synchronize images and state between viewers."""
        if not self.is_active:
            return
        
        print(f"SYNCING CONTENT (V3) - ALIGNMENT FIX APPLIED")
            
        # Block signals to prevent one viewer's load/reset from affecting the other
        self.compare_view.original_viewer.blockSignals(True)
        self.main.image_viewer.blockSignals(True)
        self.compare_view.original_viewer.verticalScrollBar().blockSignals(True)
        self.main.image_viewer.verticalScrollBar().blockSignals(True)
        
        try:
            # Load original image into original_viewer
            if self.main.image_files and self.main.curr_img_idx >= 0:
                if self.main.webtoon_mode:
                    orig_viewer = self.compare_view.original_viewer
                    src_manager = self.main.image_viewer.webtoon_manager
                    tgt_manager = orig_viewer.webtoon_manager
                    
                    # Disable text loading — original viewer is reference only
                    tgt_manager.load_text_enabled = False
                    
                    # Increase loaded page limits to prevent black gaps in compare mode
                    tgt_manager.max_loaded_pages = 999  # Load all pages
                    tgt_manager.viewport_buffer = 50000  # Large buffer to load everything
                    
                    # Also ensure main viewer loads all pages while in compare mode
                    src_manager.max_loaded_pages = 999
                    src_manager.viewport_buffer = 50000
                    
                    # Use the proper full-initialization path
                    current_page = src_manager.layout_manager.current_page_index
                    tgt_manager.load_images_lazy(self.main.image_files, current_page)
                    
                    # Sync viewport AFTER images have had time to render
                    QtCore.QTimer.singleShot(300, self._delayed_viewport_sync)
                else:
                    # Regular mode: Load original from disk
                    path = self.main.image_files[self.main.curr_img_idx]
                    im = self.main.image_ctrl.load_image(path)
                    self.compare_view.original_viewer.display_image_array(im, fit=False)
                    self.compare_view.original_viewer.setTransform(self.main.image_viewer.transform())
        finally:
            self.compare_view.original_viewer.blockSignals(False)
            self.main.image_viewer.blockSignals(False)
            self.compare_view.original_viewer.verticalScrollBar().blockSignals(False)
            self.main.image_viewer.verticalScrollBar().blockSignals(False)

    def _delayed_viewport_sync(self):
        """Sync viewports after scene has had time to render."""
        if not self.is_active or not hasattr(self, 'compare_view'):
            return
        
        orig_viewer = self.compare_view.original_viewer
        
        # Step 1: Sync transform and scroll position
        self.compare_view.sync_viewports(self.main.image_viewer, orig_viewer)
        
        # Step 2: Trigger lazy loading for both viewers at the synced position
        # Multiple calls with increasing delays to ensure all visible pages load
        for delay in [200, 500, 1000]:
            QtCore.QTimer.singleShot(delay, self._trigger_both_load_pages)
    
    def _trigger_both_load_pages(self):
        """Trigger lazy page loading for both viewers."""
        if not self.is_active or not hasattr(self, 'compare_view'):
            return
        if self.main.webtoon_mode:
            self.main.image_viewer.webtoon_manager._update_loaded_pages()
            self.compare_view.original_viewer.webtoon_manager._update_loaded_pages()
