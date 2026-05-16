import os
import re
import numpy as np
import imkit as imk
from typing import TYPE_CHECKING
from PySide6 import QtCore, QtGui
from app.ui.dayu_widgets.message import MMessage
from modules.rendering.render import pyside_word_wrap, is_vertical_block, get_language_code
from modules.utils.image_utils import get_smart_text_color

if TYPE_CHECKING:
    from controller import ComicTranslate

class BatchTextEditorController(QtCore.QObject):
    def __init__(self, main: ComicTranslate):
        super().__init__(main)
        self.main = main

    def _is_close(self, a, b, tol):
        return abs(a - b) <= tol

    def _find_item_for_blk(self, blk, live_items, page_num=None, blk_idx=None):
        if not live_items:
            return None
            
        # 0. STRICT PAGE ISOLATION (Webtoon Mode)
        # Filter live_items to only those physically on the target page
        if getattr(self.main, "webtoon_mode", False) and page_num is not None:
            manager = self.main.image_viewer.webtoon_manager
            layout = manager.layout_manager
            if page_num < len(layout.image_positions):
                p_y = layout.image_positions[page_num]
                p_h = layout.image_heights[page_num]
                
                isolated_items = []
                for item in live_items:
                    iy = item.scenePos().y()
                    # Boundary check with 10px buffer
                    if p_y - 10 <= iy <= p_y + p_h + 10:
                        isolated_items.append(item)
                live_items = isolated_items
                if not live_items:
                    print(f"DIAGNOSTIC Page {page_num}: No live items found in page boundaries.")
                    return None

        # 1. Try matching by Stable block_id (ID Priority)
        target_id = getattr(blk, 'block_id', -1)
        if target_id >= 0:
            for item in live_items:
                if getattr(item, 'block_id', -1) == target_id:
                    return item

        # 2. Try matching by UUID
        target_uuid = getattr(blk, 'uuid', None)
        if target_uuid:
            for item in live_items:
                if getattr(item, 'uuid', None) == target_uuid:
                    return item

        # 3. Fallback to index-based matching (Stored in UserRole)
        if blk_idx is not None:
            for item in live_items:
                if item.data(QtCore.Qt.UserRole) == blk_idx:
                    return item

        # 4. Fallback to fuzzy position matching (Geometric Search)
        import math
        bx, by = blk.xyxy[0], blk.xyxy[1]
        
        # Calculate expected scene coordinates for the block
        if getattr(self.main, "webtoon_mode", False) and page_num is not None:
            manager = self.main.image_viewer.webtoon_manager
            layout = manager.layout_manager
            by += layout.image_positions[page_num]
            loader = manager.image_loader
            if page_num in loader.image_items:
                bx += loader.image_items[page_num].pos().x()

        best_match = None
        min_dist = 60.0  # Slightly larger fuzzy radius
        
        for item in live_items:
            item_pos = item.scenePos()
            dist = math.sqrt((item_pos.x() - bx)**2 + (item_pos.y() - by)**2)
            if dist < min_dist:
                min_dist = dist
                best_match = item
        
        if best_match:
            print(f"POSITIONAL MATCH Page {page_num}: Found item for block {target_id} via fuzzy distance ({min_dist:.1f}px)")
            return best_match

        return None

    def clean_blocks_by_ids(self, page_idx: int, blk_ids: list[int]):
        """Runs fast solid cleaning for specific blocks on a page."""
        if not (0 <= page_idx < len(self.main.image_files)):
            return
            
        print(f"DEBUG: clean_blocks_by_ids called for page {page_idx}, IDs: {blk_ids}")

        file_path = self.main.image_files[page_idx]
        state = self.main.image_states.get(file_path, {})
        blks = state.get("blk_list", [])
        
        if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_idx:
            blks = self.main.blk_list or []

        # Find actual target blocks to ensure they exist
        targets = [b for b in blks if getattr(b, 'block_id', -1) in blk_ids]
        if not targets:
            print(f"DEBUG: No target blocks found for IDs {blk_ids} on page {page_idx}")
            return

        self.main.loading.setVisible(True)
        self.main.disable_hbutton_group()

        def clean_worker():
            try:
                self._fast_solid_clean(page_idx, blk_ids)
            except Exception as e:
                print(f"DEBUG: Error in clean_worker: {e}")

        def on_finished(_=None):
            self.main.loading.setVisible(False)
            self.main.enable_hbutton_group()
            self.main.mark_project_dirty()
            self.main.on_manual_finished()

        self.main.run_threaded(
            clean_worker,
            on_finished,
            self.main.default_error_handler
        )

    def _fast_solid_clean(self, page_idx: int, blk_ids: list[int]):
        """Fast cleaning using flood-fill from bbox center, stopping at strokes/borders."""
        print(f"DEBUG: Starting _fast_solid_clean for page {page_idx}, blocks: {blk_ids}")
        file_path = self.main.image_files[page_idx]
        
        image = self.main.image_data.get(file_path)
        if image is None:
            print(f"DEBUG: Image not in cache, loading: {file_path}")
            try:
                image = imk.read_image(file_path)
                if image is not None:
                    self.main.image_data[file_path] = image
            except Exception as e:
                print(f"DEBUG: Error loading image with imkit: {e}")
                image = None
        
        if image is None:
            print(f"DEBUG: Failed to load image for page {page_idx}")
            return

        print(f"DEBUG: Image loaded successfully for page {page_idx}. Shape: {image.shape}")
        
        state = self.main.image_states.get(file_path, {})
        targets = []
        for idx, b in enumerate(blks):
            b_id = getattr(b, 'block_id', -1)
            # Match by ID or by sequence index (1-based)
            if b_id in blk_ids or (idx + 1) in blk_ids:
                targets.append(b)
        
        print(f"DEBUG: Found {len(targets)} target blocks to clean on page {page_idx}.")
        
        patches = []
        h, w = image.shape[:2]

        for blk in targets:
            try:
                if getattr(self.main, "webtoon_mode", False):
                    manager = self.main.image_viewer.webtoon_manager
                    local_xyxy = manager.coordinate_converter.clip_textblock_to_page(blk, page_idx)
                    if local_xyxy is None:
                        continue
                    x1, y1, x2, y2 = [int(v) for v in local_xyxy]
                else:
                    x1, y1, x2, y2 = [int(v) for v in blk.xyxy]
                
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                
                # Vectorized Radial Ray Detection (Instant & Perfect)
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                gray_full = np.mean(image, axis=2)
                
                # Parameters
                num_rays = 120
                max_r = int(max(x2 - x1, y2 - y1) * 1.5)
                max_r = min(max(max_r, 80), 400)
                
                angles = np.linspace(0, 2 * np.pi, num_rays, endpoint=False)
                radii = np.arange(5, max_r)
                
                # Vectorized coordinate calculation for all rays at once
                # rays_x/y shape: (num_rays, len(radii))
                cos_a = np.cos(angles)[:, None]
                sin_a = np.sin(angles)[:, None]
                
                rays_x = (cx + cos_a * radii).astype(int)
                rays_y = (cy + sin_a * radii).astype(int)
                
                # Clip to image bounds
                rays_x = np.clip(rays_x, 0, w - 1)
                rays_y = np.clip(rays_y, 0, h - 1)
                
                # Color-based border detection (The most robust way)
                # We look for the first index where bubble color truly ends
                sampled_rgb = image[rays_y, rays_x].astype(float)
                sampled_gray = np.mean(sampled_rgb, axis=2)
                
                # Get local background color from ROI center
                roi_to_fill = image[fy1:fy2, fx1:fx2]
                bg_color_f = np.median(roi_to_fill[roi_h_f//4:3*roi_h_f//4, roi_w_f//4:3*roi_w_f//4], axis=(0,1)).astype(float) if roi_h_f > 10 else np.array([255,255,255], dtype=float)
                
                color_dist = np.sqrt(np.sum((sampled_rgb - bg_color_f)**2, axis=2))
                is_bg = color_dist < 40
                
                # Find border: skip first 40px, look for stroke (gray < 80) or color drop
                hits = []
                for i in range(num_rays):
                    stroke_idx = np.where(sampled_gray[i, 40:] < 80)[0]
                    drop_idx = np.where(color_dist[i, 40:] > 60)[0]
                    
                    h_val = len(radii) - 1
                    if stroke_idx.size > 0:
                        h_val = min(h_val, stroke_idx[0] + 40)
                    if drop_idx.size > 0:
                        h_val = min(h_val, drop_idx[0] + 40)
                    hits.append(h_val)
                    
                hits = np.array(hits)
                hits = np.clip(hits - 2, 0, len(radii) - 1)
                
                # Convert hits back to global coordinates
                final_radii = radii[hits]
                border_px = cx + np.cos(angles) * final_radii
                border_py = cy + np.sin(angles) * final_radii
                
                # Create mask using polygon fill logic
                fx1, fy1 = max(0, int(np.min(border_px))), max(0, int(np.min(border_py)))
                fx2, fy2 = min(w, int(np.max(border_px)) + 1), min(h, int(np.max(border_py)) + 1)
                
                roi_h_f, roi_w_f = fy2 - fy1, fx2 - fx1
                if roi_h_f <= 0 or roi_w_f <= 0: continue
                
                local_points = np.stack([border_px - fx1, border_py - fy1], axis=1)
                
                # Vectorized scanline fill for polygon
                poly_mask = np.zeros((roi_h_f, roi_w_f), dtype=bool)
                for row in range(roi_h_f):
                    # Intersections of this row with all polygon edges
                    x_a, y_a = local_points[:, 0], local_points[:, 1]
                    x_b, y_b = np.roll(x_a, -1), np.roll(y_a, -1)
                    
                    # Find edges that cross this row
                    valid = ((y_a <= row) & (y_b > row)) | ((y_b <= row) & (y_a > row))
                    if not np.any(valid): continue
                    
                    intersections = x_a[valid] + (row - y_a[valid]) * (x_b[valid] - x_a[valid]) / (y_b[valid] - y_a[valid])
                    intersections.sort()
                    
                    for k in range(0, len(intersections) - 1, 2):
                        poly_mask[row, int(intersections[k]):int(intersections[k+1])+1] = True

                # Apply cleaning
                roi_to_fill = image[fy1:fy2, fx1:fx2].copy()
                bg_color = np.median(roi_to_fill[roi_h_f//4:3*roi_h_f//4, roi_w_f//4:3*roi_w_f//4], axis=(0,1)).astype(np.uint8) if roi_h_f > 10 else np.array([255,255,255], dtype=np.uint8)
                roi_to_fill[poly_mask] = bg_color
                image[fy1:fy2, fx1:fx2] = roi_to_fill
                
                patches.append({
                    'x': fx1, 'y': fy1, 'w': fx2 - fx1, 'h': fy2 - fy1,
                    'bbox': [fx1, fy1, fx2 - fx1, fy2 - fy1],
                    'image': roi_to_fill,
                    'page_index': page_idx
                })
            except Exception as e:
                print(f"DEBUG Error cleaning block: {e}")
                import traceback
                traceback.print_exc()
                continue

        if patches:
            print(f"DEBUG: Emitting {len(patches)} patches for page {page_idx}")
            if getattr(self.main, "webtoon_mode", False):
                manager = self.main.image_viewer.webtoon_manager
                for patch in patches:
                    scene_pos = manager.coordinate_converter.page_local_to_scene_position(QtCore.QPointF(patch['x'], patch['y']), page_idx)
                    patch['scene_pos'] = [scene_pos.x(), scene_pos.y()]
            
            self.main.patches_processed.emit(patches, file_path)
        print(f"DEBUG: Finished _fast_solid_clean for page {page_idx}")



    def solid_fill_clean(self, scene_rect: QtCore.QRectF, color: QtGui.QColor):
        """Fills a scene rectangle with a solid color."""
        # 1. Determine page index
        page_idx = -1
        if getattr(self.main, "webtoon_mode", False):
            layout = self.main.image_viewer.webtoon_manager.layout_manager
            page_idx = layout.get_page_at_position(scene_rect.center().y())
        else:
            page_idx = self.main.curr_img_idx
            
        if page_idx < 0 or page_idx >= len(self.main.image_files):
            return
            
        file_path = self.main.image_files[page_idx]
        
        # 2. Convert scene rect to page local rect
        if getattr(self.main, "webtoon_mode", False):
            manager = self.main.image_viewer.webtoon_manager
            converter = manager.coordinate_converter
            top_left = converter.scene_to_page_local_position(scene_rect.topLeft(), page_idx)
            bottom_right = converter.scene_to_page_local_position(scene_rect.bottomRight(), page_idx)
            if top_left and bottom_right:
                local_rect = QtCore.QRectF(top_left, bottom_right)
            else:
                local_rect = None
        else:
            local_rect = scene_rect # In regular mode, they are same (mostly)

        if not local_rect:
            return

        x, y, w, h = int(local_rect.x()), int(local_rect.y()), int(local_rect.width()), int(local_rect.height())
        if w <= 0 or h <= 0:
            return

        # 3. Create solid color image
        fill_img = np.full((h, w, 3), [color.red(), color.green(), color.blue()], dtype=np.uint8)
        
        patch = {
            'x': x, 'y': y, 'w': w, 'h': h,
            'bbox': [x, y, w, h],
            'image': fill_img,
            'page_index': page_idx
        }

        # Map to scene position for webtoon mode
        if getattr(self.main, "webtoon_mode", False):
            manager = self.main.image_viewer.webtoon_manager
            scene_pos = manager.coordinate_converter.page_local_to_scene_position(QtCore.QPointF(x, y), page_idx)
            patch['scene_pos'] = [scene_pos.x(), scene_pos.y()]

        self.main.patches_processed.emit([patch], file_path)
        self.main.mark_project_dirty()

    def inpaint_rect_clean(self, scene_rect: QtCore.QRectF):
        """Cleans a scene rectangle using AI inpainting."""
        print(f"DEBUG: Starting inpaint_rect_clean for rect {scene_rect}")
        # 1. Determine page index
        page_idx = -1
        if getattr(self.main, "webtoon_mode", False):
            layout = self.main.image_viewer.webtoon_manager.layout_manager
            page_idx = layout.get_page_at_position(scene_rect.center().y())
        else:
            page_idx = self.main.curr_img_idx
            
        if page_idx < 0 or page_idx >= len(self.main.image_files):
            return
            
        file_path = self.main.image_files[page_idx]
        
        # 2. Convert scene rect to page local rect
        if getattr(self.main, "webtoon_mode", False):
            manager = self.main.image_viewer.webtoon_manager
            converter = manager.coordinate_converter
            top_left = converter.scene_to_page_local_position(scene_rect.topLeft(), page_idx)
            bottom_right = converter.scene_to_page_local_position(scene_rect.bottomRight(), page_idx)
            if top_left and bottom_right:
                local_rect = QtCore.QRectF(top_left, bottom_right)
            else:
                local_rect = None
        else:
            local_rect = scene_rect

        if not local_rect:
            return

        x, y, w, h = int(local_rect.x()), int(local_rect.y()), int(local_rect.width()), int(local_rect.height())
        if w <= 0 or h <= 0:
            return

        # 3. Create a mask from the rect
        # We need the full image shape for the mask
        main_img = self.main.image_data.get(file_path)
        if main_img is None:
            return
            
        mask = np.zeros(main_img.shape[:2], dtype=np.uint8)
        mask[y:y+h, x:x+w] = 255
        
        # 4. Capture rendered image on main thread (thread-safe)
        rendered_image = self.main.pipeline.inpainting._get_page_image_for_inpainting(page_idx)
        if rendered_image is None:
            rendered_image = main_img

        # 5. Perform inpainting in background thread to avoid UI lag
        self.main.loading.setVisible(True)
        self.main.disable_hbutton_group()

        def inpaint_worker():
            # AI part runs in background with pre-captured image
            return self.main.pipeline.inpainting.get_patches_for_mask(page_idx, mask, image=rendered_image)
            
        def on_finished(result):
            # Applying patches runs in main thread
            self.main.loading.setVisible(False)
            self.main.enable_hbutton_group()
            
            if result:
                patches, f_path = result
                if patches and f_path:
                    # Enrich on main thread to avoid freezes
                    self.main.pipeline.inpainting.enrich_patches_with_scene_pos(patches, page_idx)
                    self.main.image_ctrl.on_inpaint_patches_processed(patches, f_path)
            self.main.mark_project_dirty()
            self.main.on_manual_finished()
            
        # Execute threaded
        self.main.run_threaded(
            inpaint_worker, 
            on_finished, 
            self.main.default_error_handler
        )

    def tap_to_clean(self, data):
        """Cleans based on either a text block item or a raw scene position."""
        if not data:
            return
            
        item = data.get('item')
        scene_pos = data.get('pos')
        
        if not scene_pos:
            return

        # 1. Determine page index
        page_idx = -1
        if getattr(self.main, "webtoon_mode", False):
            layout = self.main.image_viewer.webtoon_manager.layout_manager
            page_idx = layout.get_page_at_position(scene_pos.y())
        else:
            page_idx = self.main.curr_img_idx
            
        if page_idx < 0:
            return
            
        print(f"DEBUG: tap_to_clean at pos {scene_pos} on page {page_idx}")

        self.main.loading.setVisible(True)
        self.main.disable_hbutton_group()

        def clean_worker():
            try:
                # Convert scene pos to page-local pos
                local_pos = scene_pos
                if getattr(self.main, "webtoon_mode", False):
                    manager = self.main.image_viewer.webtoon_manager
                    local_pos = manager.coordinate_converter.scene_to_page_local_position(scene_pos, page_idx)
                
                self._fast_solid_clean_pos(page_idx, int(local_pos.x()), int(local_pos.y()))
            except Exception as e:
                print(f"DEBUG: Error in clean_worker: {e}")

        def on_finished(_=None):
            self.main.loading.setVisible(False)
            self.main.enable_hbutton_group()
            self.main.mark_project_dirty()
            self.main.on_manual_finished()

        self.main.run_threaded(
            clean_worker,
            on_finished,
            self.main.default_error_handler
        )

    def _fast_solid_clean_pos(self, page_idx: int, cx: int, cy: int):
        """Cleans a bubble starting from a specific local (cx, cy) coordinate."""
        file_path = self.main.image_files[page_idx]
        image = self.main.image_data.get(file_path)
        if image is None:
            image = self.main.image_ctrl.load_image(file_path)
            if image is not None:
                self.main.image_data[file_path] = image
        
        if image is None:
            print(f"DEBUG: Failed to load image for page {page_idx} at {file_path}")
            return
        
        h, w = image.shape[:2]
        if not (0 <= cx < w and 0 <= cy < h):
            print(f"DEBUG: Click position ({cx}, {cy}) is out of image bounds ({w}x{h})")
            return
            
        # 1. Sample background color at click point
        y1_s, y2_s = max(0, cy - 2), min(h, cy + 2)
        x1_s, x2_s = max(0, cx - 2), min(w, cx + 2)
        bg_sample = image[y1_s:y2_s, x1_s:x2_s]
        bg_color = np.median(bg_sample, axis=(0,1)).astype(np.uint8) if bg_sample.size > 0 else np.array([255,255,255], dtype=np.uint8)
        
        # 2. Simplified Radial Ray logic for "Solid Fill"
        gray = np.mean(image.astype(float), axis=2)
        num_rays = 120
        max_r = 450
        angles = np.linspace(0, 2 * np.pi, num_rays, endpoint=False)
        radii = np.arange(1, max_r)
        
        cos_a = np.cos(angles)[:, None]
        sin_a = np.sin(angles)[:, None]
        
        rx = np.clip((cx + cos_a * radii).astype(int), 0, w - 1)
        ry = np.clip((cy + sin_a * radii).astype(int), 0, h - 1)
        
        sampled_gray = gray[ry, rx]
        
        # Border detection: Skip first 40px (text), then find first dark pixel (gray < 80)
        hits = []
        for i in range(num_rays):
            # Find first truly dark pixel (stroke) after the skip
            # We use a stricter threshold (80) to avoid stopping at shadows
            dark_indices = np.where(sampled_gray[i, 40:] < 80)[0]
            if dark_indices.size > 0:
                h_idx = dark_indices[0] + 40
            else:
                h_idx = len(radii) - 1
            hits.append(h_idx)
            
        hits = np.array(hits)
        # RETRACT 2px for safety to avoid eating the border
        hits = np.clip(hits - 2, 0, len(radii) - 1)
        
        final_radii = radii[hits]
        border_px = cx + np.cos(angles) * final_radii
        border_py = cy + np.sin(angles) * final_radii
        
        fx1, fy1 = max(0, int(np.min(border_px))), max(0, int(np.min(border_py)))
        fx2, fy2 = min(w, int(np.max(border_px)) + 1), min(h, int(np.max(border_py)) + 1)
        
        roi_h_f, roi_w_f = fy2 - fy1, fx2 - fx1
        if roi_h_f <= 0 or roi_w_f <= 0: return
            
        local_points = np.stack([border_px - fx1, border_py - fy1], axis=1)
        poly_mask = np.zeros((roi_h_f, roi_w_f), dtype=bool)
        
        for row in range(roi_h_f):
            x_a, y_a = local_points[:, 0], local_points[:, 1]
            x_b, y_b = np.roll(x_a, -1), np.roll(y_a, -1)
            valid = ((y_a <= row) & (y_b > row)) | ((y_b <= row) & (y_a > row))
            if not np.any(valid): continue
            intersections = np.sort(x_a[valid] + (row - y_a[valid]) * (x_b[valid] - x_a[valid]) / (y_b[valid] - y_a[valid]))
            for k in range(0, len(intersections) - 1, 2):
                poly_mask[row, int(intersections[k]):int(intersections[k+1])+1] = True

        roi_to_fill = image[fy1:fy2, fx1:fx2].copy()
        roi_to_fill[poly_mask] = bg_color
        image[fy1:fy2, fx1:fx2] = roi_to_fill
        
        patches = [{
            'x': fx1, 'y': fy1, 'w': fx2 - fx1, 'h': fy2 - fy1,
            'bbox': [fx1, fy1, fx2 - fx1, fy2 - fy1],
            'image': roi_to_fill,
            'page_index': page_idx
        }]
        
        if getattr(self.main, "webtoon_mode", False):
            manager = self.main.image_viewer.webtoon_manager
            scene_pos = manager.coordinate_converter.page_local_to_scene_position(QtCore.QPointF(fx1, fy1), page_idx)
            patches[0]['scene_pos'] = [scene_pos.x(), scene_pos.y()]
            
        self.main.patches_processed.emit(patches, file_path)
        print(f"DEBUG: Patch emitted for bubble at {fx1}, {fy1}")

    def magic_wand_clean(self):
        """Parses the clipboard for block IDs and runs cleaning for all of them."""
        text_content = QtGui.QGuiApplication.clipboard().text()
        if not text_content:
            MMessage.warning(text="Clipboard is empty", parent=self.main)
            return

        page_headers = re.findall(r"(?:###\s*)?PAGE (\d+): (.*?)(?:\s*###)?", text_content)
        page_splits = re.split(r"(?:###\s*)?PAGE \d+: .*?(?:\s*###)?", text_content)
        
        if not page_headers:
            MMessage.error(text="Invalid format. Could not find any page headers (e.g. PAGE 1: ...)", parent=self.main)
            return

        content_parts = page_splits[1:]
        block_header_re = r"\[#(\d+) (.*?)(?: UUID:([a-fA-F0-9-]+))?\]"
        
        total_cleaned = 0
        self.main.loading.setVisible(True)
        self.main.disable_hbutton_group()

        def run_batch_clean():
            count = 0
            for header, content in zip(page_headers, content_parts):
                page_num = int(header[0]) - 1
                if not (0 <= page_num < len(self.main.image_files)):
                    continue
                
                block_matches = re.findall(block_header_re, content)
                clean_ids = [int(m[0]) for m in block_matches]
                
                if clean_ids:
                    self.clean_blocks_by_ids(page_num, clean_ids)
                    count += len(clean_ids)
            return count

        def on_clean_finished(count):
            self.main.loading.setVisible(False)
            self.main.enable_hbutton_group()
            if count > 0:
                MMessage.success(text=f"Magic Wand: Successfully cleaned {count} blocks.", parent=self.main, duration=1)
            else:
                MMessage.info(text="No blocks were found to clean.", parent=self.main)

        self.main.run_threaded(
            run_batch_clean,
            on_clean_finished,
            self.main.default_error_handler
        )

    def magic_wand_all(self):
        """Cleans all text blocks across all pages without needing the clipboard."""
        if not self.main.image_files:
            MMessage.warning(text="No images loaded", parent=self.main)
            return

        self.main.loading.setVisible(True)
        self.main.disable_hbutton_group()

        def run_batch_clean_all():
            count = 0
            is_webtoon = getattr(self.main, "webtoon_mode", False)
            
            for page_idx, file_path in enumerate(self.main.image_files):
                blks = []
                
                if is_webtoon:
                    # In Webtoon mode: filter global blk_list by this page's Y boundary
                    try:
                        layout = self.main.image_viewer.webtoon_manager.layout_manager
                        p_y = layout.image_positions[page_idx]
                        p_h = layout.image_heights[page_idx]
                        blks = [b for b in self.main.blk_list 
                                if p_y - 5 <= b.xyxy[1] <= p_y + p_h + 5]
                    except Exception:
                        blks = []
                    
                    # Fallback to image_states for off-screen pages
                    if not blks:
                        state = self.main.image_states.get(file_path, {})
                        blks = state.get("blk_list", [])
                else:
                    # Regular mode: use live list for active page, states for others
                    if self.main.curr_img_idx == page_idx:
                        blks = self.main.blk_list or []
                    else:
                        state = self.main.image_states.get(file_path, {})
                        blks = state.get("blk_list", [])
                
                if not blks:
                    print(f"magic_wand_all: Page {page_idx + 1} has no blocks, skipping.")
                    continue

                # Ensure stable IDs and collect them (skip SFX/text_free blocks)
                blk_ids = []
                for idx, blk in enumerate(blks):
                    if getattr(blk, 'block_id', -1) < 0:
                        blk.block_id = idx + 1
                    # Skip SFX blocks - only clean dialogue bubbles
                    text_class = getattr(blk, 'text_class', getattr(blk, 'box_label', 'text_bubble'))
                    if text_class == 'text_free':
                        print(f"magic_wand_all: Skipping SFX block {blk.block_id} on page {page_idx + 1}")
                        continue
                    blk_ids.append(blk.block_id)
                
                if blk_ids:
                    print(f"magic_wand_all: Cleaning {len(blk_ids)} bubble blocks on page {page_idx + 1}")
                    self._fast_solid_clean(page_idx, blk_ids)
                    count += len(blk_ids)
            return count

        def on_clean_finished(count):
            self.main.loading.setVisible(False)
            self.main.enable_hbutton_group()
            if count > 0:
                MMessage.success(text=f"Magic Wand All: Cleaned {count} blocks across all pages.", parent=self.main, duration=2)
            else:
                MMessage.info(text="No blocks were found to clean.", parent=self.main)

        self.main.run_threaded(
            run_batch_clean_all,
            on_clean_finished,
            self.main.default_error_handler
        )


    def export_all_text(self):
        if not self.main.image_files:
            MMessage.warning(text="No images loaded", parent=self.main)
            return

        # Ensure live changes are saved to states in webtoon mode before exporting
        if self.main.webtoon_mode:
            manager = self.main.image_viewer.webtoon_manager
            manager.scene_item_manager.save_loaded_scene_items_to_states()

        output = []
        for page_idx, file_path in enumerate(self.main.image_files):
            basename = os.path.basename(file_path)
            output.append(f"### PAGE {page_idx + 1}: {basename} ###")
            
            # GET BLOCKS FOR THIS PAGE
            blks = []
            if getattr(self.main, "webtoon_mode", False):
                # In Webtoon mode, find blocks belonging to this page's vertical range
                layout = self.main.image_viewer.webtoon_manager.layout_manager
                p_y = layout.image_positions[page_idx]
                p_h = layout.image_heights[page_idx]
                # Filter from the global live list
                blks = [b for b in self.main.blk_list if p_y - 5 <= b.xyxy[1] <= p_y + p_h + 5]
                # If nothing in live list, try image_states (for off-screen non-rendered pages)
                if not blks:
                    state = self.main.image_states.get(file_path) or {}
                    blks = state.get("blk_list") or []
            else:
                # Regular mode
                if self.main.curr_img_idx == page_idx:
                    blks = self.main.blk_list or []
                else:
                    state = self.main.image_states.get(file_path) or {}
                    blks = state.get("blk_list") or []

            # CONSISTENT ORDERING: Sort by Y coordinate (top-to-bottom) and assign IDs
            # This ensures '#1' = topmost block, '#2' = second, etc.
            blks.sort(key=lambda b: b.xyxy[1])
            for idx, blk in enumerate(blks):
                blk.block_id = idx + 1  # Always overwrite to ensure consistency
            
            # Export each block
            for idx, blk in enumerate(blks):
                # Map internal classes to user-friendly labels
                raw_label = getattr(blk, "text_class", getattr(blk, "box_label", "Dialogue"))
                if raw_label == "text_bubble":
                    label = "Dialogue/Bubble"
                elif raw_label == "text_free":
                    label = "SFX/Free Text"
                else:
                    label = raw_label

                source_text = getattr(blk, "text", "")
                translation = getattr(blk, "translation", source_text)
                stable_id = getattr(blk, "block_id", idx + 1)
                
                output.append(f"[#{stable_id} {label}]")
                # Split translation into lines and prefix each with //
                for line in translation.splitlines():
                    output.append(f"// {line}")
                output.append("") # Extra newline for spacing
            output.append("\n")
            print(f"DIAGNOSTIC: Exported Page {page_idx + 1} with {len(blks)} blocks.")
            
        text_content = "\n".join(output)
        QtGui.QGuiApplication.clipboard().setText(text_content)
        MMessage.success(text="All text copied to clipboard in batch format!", parent=self.main, duration=1)

    def export_current_page_text(self):
        if self.main.curr_img_idx < 0:
            MMessage.warning(text="No page selected", parent=self.main)
            return

        # Ensure live changes are saved to states in webtoon mode before exporting
        if self.main.webtoon_mode:
            manager = self.main.image_viewer.webtoon_manager
            manager.scene_item_manager.save_loaded_scene_items_to_states()
            # Reload immediately so items don't disappear for the user
            manager.scene_item_manager._clear_all_scene_items()
            for p_idx in list(manager.loaded_pages):
                manager.scene_item_manager.load_page_scene_items(p_idx)

        page_idx = self.main.curr_img_idx
        file_path = self.main.image_files[page_idx]
        basename = os.path.basename(file_path)
        
        output = [f"### PAGE {page_idx + 1}: {basename} ###"]
        
        state = self.main.image_states.get(file_path) or {}
        blks = state.get("blk_list") or []
        
        if not getattr(self.main, "webtoon_mode", False):
            blks = self.main.blk_list or []

        for idx, blk in enumerate(blks):
            if getattr(blk, 'block_id', -1) < 0:
                blk.block_id = idx + 1
        
        for idx, blk in enumerate(blks):
            raw_label = getattr(blk, "text_class", getattr(blk, "box_label", "Dialogue"))
            if raw_label == "text_bubble":
                label = "Dialogue/Bubble"
            elif raw_label == "text_free":
                label = "SFX/Free Text"
            else:
                label = raw_label

            translation = getattr(blk, "translation", getattr(blk, "text", ""))
            stable_id = getattr(blk, "block_id", idx + 1)
            
            output.append(f"[#{stable_id} {label}]")
            # Standardize: Split translation into lines and prefix each with //
            for line in translation.splitlines():
                output.append(f"// {line}")
            output.append("")
            
        text_content = "\n".join(output)
        QtGui.QGuiApplication.clipboard().setText(text_content)
        MMessage.success(text=f"Text from Page {page_idx + 1} copied to clipboard!", parent=self.main, duration=1)

    def _parse_clipboard_blocks(self, content):
        """Robustly parses clipboard blocks and handles optional // comment lines."""
        # Regex for block header: [#1 Dialogue UUID:uuid-string]
        # Group 1: Index, Group 2: Class/Label, Group 3: Optional UUID
        block_header_re = r"\[#(\d+)\s+(.*?)(?:\s+UUID:([a-fA-F0-9-]+))?\]"
        
        # This regex captures the header and then looks for content until next block or empty line
        full_pattern = block_header_re + r"\s*\n(.*?)(?=\n\s*\n|\n\[#|$)"
        matches = re.findall(full_pattern, content, re.DOTALL)
        
        results = []
        for blk_id_str, blk_label, blk_uuid, blk_content in matches:
            blk_id = int(blk_id_str)
            
            # Extract text: if lines start with //, use only the content after //
            # Otherwise use the whole line.
            lines = blk_content.splitlines()
            extracted_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("//"):
                    extracted_lines.append(stripped[2:].strip())
                else:
                    extracted_lines.append(stripped)
            
            final_text = "\n".join(extracted_lines).strip()
            results.append({
                'id': blk_id,
                'label': blk_label,
                'uuid': blk_uuid,
                'text': final_text
            })
        return results

    def import_all_text(self):
        text_content = QtGui.QGuiApplication.clipboard().text()
        if not text_content:
            MMessage.warning(text="Clipboard is empty", parent=self.main)
            return

        # 1. Parse page headers
        page_splits = re.split(r"(?:###\s*)?PAGE \d+: .*?(?:\s*###)?", text_content)
        page_headers = re.findall(r"(?:###\s*)?PAGE (\d+): (.*?)(?:\s*###)?", text_content)
        
        if not page_headers:
            MMessage.error(text="Invalid format. Could not find any page headers (e.g. PAGE 1: ...)", parent=self.main)
            return

        content_parts = page_splits[1:]
        updated_count = 0
        missing_reports = []
        
        # 2. Get global settings from UI
        try:
            render_settings = self.main.text_ctrl.render_settings()
            max_font_size = self.main.settings_page.get_max_font_size()
            min_font_size = self.main.settings_page.get_min_font_size()
            alignment = self.main.button_to_alignment[render_settings.alignment_id]
            font_family = render_settings.font_family
            line_spacing = float(render_settings.line_spacing)
            outline_width = float(render_settings.outline_width)
            target_lang = self.main.lang_mapping.get(self.main.t_combo.currentText(), None)
            trg_lng_cd = get_language_code(target_lang)
        except Exception as e:
            print(f"Batch typeset setup error: {e}")
            render_settings = None

        # CRITICAL FOR WEBTOON: Force load all pages to ensure live items exist for Hard Anchor
        if getattr(self.main, "webtoon_mode", False):
            print("DIAGNOSTIC: Force loading all pages for consistent batch update...")
            manager = self.main.image_viewer.webtoon_manager
            # Keep track of what was originally loaded to restore later if needed, 
            # though usually it's fine to keep them loaded for the refresh.
            for p_idx in range(len(self.main.image_files)):
                if p_idx not in manager.loaded_pages:
                    manager.scene_item_manager.load_page_scene_items(p_idx)
                    manager.loaded_pages.add(p_idx)

        # 0. Coordinate Sanitizer: Clean up any corrupted (scene-relative) coordinates
        # from previous failed operations to ensure a clean slate across the project.
        if getattr(self.main, "webtoon_mode", False):
            manager = self.main.image_viewer.webtoon_manager
            layout = manager.layout_manager
            for p_idx, f_path in enumerate(self.main.image_files):
                st = self.main.image_states.get(f_path)
                if not st: continue
                p_y = layout.image_positions[p_idx]
                p_h = layout.image_heights[p_idx]
                
                # Sanitize blk_list
                # Only sanitize if coordinates are clearly in scene-space (p_y > 0 and y >= p_y)
                for b in st.get("blk_list", []):
                    if p_y > 0 and b.xyxy[1] >= p_y:
                        print(f"SANITIZER Page {p_idx}: Fixing scene coordinates for block {getattr(b, 'block_id', '?')}")
                        new_xyxy = list(b.xyxy)
                        new_xyxy[1] -= p_y
                        new_xyxy[3] -= p_y
                        b.xyxy = new_xyxy
                
                # Sanitize text_items_state
                tis = st.get('viewer_state', {}).get('text_items_state', [])
                for props in tis:
                    pos = props.get('position', [0, 0])
                    if p_y > 0 and pos[1] >= p_y:
                        print(f"SANITIZER Page {p_idx}: Fixing scene position in text_items_state")
                        new_pos = list(pos)
                        new_pos[1] -= p_y
                        props['position'] = new_pos

        # 3. Process the content page by page
        for header, content in zip(page_headers, content_parts):
            page_num = int(header[0]) - 1
            if page_num < 0 or page_num >= len(self.main.image_files):
                continue
                
            file_path = self.main.image_files[page_num]
            if file_path not in self.main.image_states:
                self.main.image_states[file_path] = {'blk_list': [], 'viewer_state': {'text_items_state': []}}
            
            state = self.main.image_states[file_path]
            viewer_state = state.setdefault('viewer_state', {})
            text_items_state = viewer_state.setdefault('text_items_state', [])
            
            # GET BLOCKS - same source logic as export_all_text for consistency
            if getattr(self.main, "webtoon_mode", False):
                # Webtoon: filter global blk_list by this page's Y boundary (scene-space)
                try:
                    layout = self.main.image_viewer.webtoon_manager.layout_manager
                    p_y = layout.image_positions[page_num]
                    p_h = layout.image_heights[page_num]
                    blks = [b for b in self.main.blk_list 
                            if p_y - 5 <= b.xyxy[1] <= p_y + p_h + 5]
                except Exception as e:
                    print(f"IMPORT: Failed to filter by page boundary for page {page_num}: {e}")
                    blks = []
                # Fallback to image_states if main.blk_list had nothing for this page
                if not blks:
                    blks = state.get("blk_list", [])
            else:
                # Regular mode: use live list for active page, states for others
                if page_num == self.main.curr_img_idx:
                    blks = self.main.blk_list or []
                else:
                    blks = state.get("blk_list", [])
            
            # CONSISTENT ORDERING: Sort by Y coordinate (top-to-bottom), same as export
            # This ensures clipboard '#1' maps to the topmost block, not an arbitrary one.
            blks.sort(key=lambda b: b.xyxy[1])
            for idx, blk in enumerate(blks):
                blk.block_id = idx + 1  # Always re-derive from Y order to match export
                
            # Sync text_items_state with blks to ensure correct indexing
            # but preserve existing content at all costs
            new_tis = []
            for blk in blks:
                # 1. Try to find existing props by UUID
                found = next((p for p in text_items_state if p.get('uuid') == getattr(blk, 'uuid', None)), None)
                
                # 2. Fallback to block_id if UUID didn't match
                if not found and getattr(blk, 'block_id', -1) != -1:
                    found = next((p for p in text_items_state if p.get('block_id') == blk.block_id), None)
                
                # 3. Create only if truly new, and use blk.translation as default to avoid 'disappearing'
                if not found:
                    found = {
                        'block_id': blk.block_id, 
                        'uuid': getattr(blk, 'uuid', None), 
                        'text': getattr(blk, 'translation', getattr(blk, 'text', '')),
                        'translation': getattr(blk, 'translation', getattr(blk, 'text', ''))
                    }
                new_tis.append(found)
            viewer_state['text_items_state'] = new_tis
            text_items_state = new_tis

            # Parse blocks for this page
            block_matches = self._parse_clipboard_blocks(content)
            clean_ids = []
            page_updated_count = 0

            for b_data in block_matches:
                blk_id = b_data['id']
                blk_uuid = b_data['uuid']
                final_text = b_data['text']
                if "CLEAN" in b_data['label'].upper() or "WAND" in b_data['label'].upper():
                    clean_ids.append(blk_id)
                
                # Find target block
                target_blk = None
                if blk_id >= 0:
                    target_blk = next((b for b in blks if getattr(b, 'block_id', -1) == blk_id), None)
                if not target_blk and blk_uuid:
                    target_blk = next((b for b in blks if getattr(b, 'uuid', None) == blk_uuid), None)
                if not target_blk and 0 <= (blk_id - 1) < len(blks):
                    target_blk = blks[blk_id - 1]
                
                if target_blk:
                    # EMPTY TEXT PROTECTION: Do not update if final_text is empty
                    if not final_text.strip():
                        print(f"DIAGNOSTIC Page {page_num}: Skipping block {blk_id} - translation is empty.")
                        continue

                    blk = target_blk
                    blk_idx = blks.index(blk)
                    updated_count += 1
                    page_updated_count += 1
                    
                    # Typesetting
                    final_font_size = None
                    vertical = False
                    if render_settings:
                        try:
                            final_text, final_font_size, vertical = typeset_text(
                                final_text, blk.xywh[2], blk.xywh[3],
                                font_family, min_font_size, max_font_size,
                                alignment, line_spacing, trg_lng_cd
                            )
                        except Exception as e:
                            print(f"Typeset error for block {blk_id} on page {page_num}: {e}")

                    # Update Block State
                    blk.translation = final_text
                    blk.text = final_text
                    if final_font_size: blk.font_size = final_font_size
                    blk.target_lang = self.main.t_combo.currentText()
                    blk.source_lang = self.main.s_combo.currentText()
                    
                    # Update Persistence State
                    if 0 <= blk_idx < len(text_items_state):
                        props = text_items_state[blk_idx]
                        props.update({
                            'text': final_text, 'translation': final_text,
                            'block_id': blk.block_id, 'uuid': blk.uuid,
                            'target_lang': blk.target_lang, 'source_lang': blk.source_lang
                        })
                        if final_font_size: props['font_size'] = final_font_size
                        if render_settings:
                            smart_color = get_smart_text_color(blk.font_color, QtGui.QColor(render_settings.color))
                            props.update({
                                'alignment': int(alignment), 'font_family': font_family,
                                'bold': render_settings.bold, 'italic': render_settings.italic,
                                'underline': render_settings.underline, 'line_spacing': line_spacing,
                                'text_color': smart_color.name(), 'vertical': vertical,
                                'outline': render_settings.outline
                            })
                            if render_settings.outline:
                                props['outline_color'] = render_settings.outline_color
                                props['outline_width'] = outline_width
                    
                    # Update Live View (Force Load ensures items exist for all pages in webtoon mode)
                    live_items = self.main.image_viewer.text_items
                    item = self._find_item_for_blk(blk, live_items, page_num, blk_idx)
                    if item:
                        # Capture current scene CENTER for the "Hard Anchor"
                        # Centering is better for speech bubbles as text expands from the middle
                        original_scene_center = item.mapToScene(item.boundingRect().center())
                        print(f"DIAGNOSTIC Page {page_num}: Block {blk_id} updated. Scene Center Y: {original_scene_center.y()}")
                        
                        try:
                            if render_settings:
                                smart_color = get_smart_text_color(blk.font_color, QtGui.QColor(render_settings.color))
                                item.font_family = font_family
                                item.font_size = final_font_size or item.font_size
                                item.text_color = smart_color
                                item.alignment = alignment
                                item.line_spacing = line_spacing
                                item.bold = render_settings.bold
                                item.italic = render_settings.italic
                                item.underline = render_settings.underline
                                if render_settings.outline:
                                    item.outline = True
                                    item.outline_color = QtGui.QColor(render_settings.outline_color)
                                    item.outline_width = outline_width
                                else:
                                    item.outline = False
                            
                            item.set_vertical(vertical)
                            # CLEAN TEXT: Ensure we only set the translation, not the metadata headers
                            display_text = final_text
                            if display_text.startswith("[") and "]" in display_text[:20]:
                                display_text = display_text.split("]", 1)[-1].strip()
                            
                            item.set_text(display_text, blk.xywh[2])
                            angle = item.rotation()
                            item.setCenterTransform()
                            item.setRotation(angle)
                            
                            # FINAL POSITION LOCK: Restore precisely to the original scene CENTER
                            new_scene_center = item.mapToScene(item.boundingRect().center())
                            delta = original_scene_center - new_scene_center
                            if not delta.isNull():
                                item.setPos(item.pos() + delta)
                                print(f"CENTER LOCK Page {page_num}: Restored item {blk_id} by {delta.x()},{delta.y()}")
                            
                            # CRITICAL SYNC: Update main.blk_list to prevent overwriting during save
                            if getattr(self.main, "webtoon_mode", False):
                                for live_blk in self.main.blk_list:
                                    if getattr(live_blk, 'block_id', -1) == blk.block_id:
                                        live_blk.translation = final_text
                                        live_blk.text = final_text
                                        if final_font_size: live_blk.font_size = final_font_size
                                        break
                        except Exception as e:
                            print(f"Error updating live item {blk_id} on page {page_num}: {e}")
                    else:
                        # Fallback for truly off-screen (should be rare with force load)
                        print(f"DIAGNOSTIC Page {page_num}: Block {blk_id} NOT found in live items.")
                        if blk.xyxy[1] >= 1000 and getattr(self.main, "webtoon_mode", False):
                                # Emergency fix for off-screen blocks that might have been corrupted
                                p_y = self.main.image_viewer.webtoon_manager.layout_manager.image_positions[page_num]
                                if blk.xyxy[1] >= p_y:
                                    print(f"DIAGNOSTIC Page {page_num}: Sanitizing off-screen block {blk_id} Y={blk.xyxy[1]}")
                                    new_xyxy = list(blk.xyxy)
                                    new_xyxy[1] -= p_y
                                    new_xyxy[3] -= p_y
                                    blk.xyxy = new_xyxy
                                    if 0 <= blk_idx < len(text_items_state):
                                        tis_pos = list(text_items_state[blk_idx].get('position', [0, 0]))
                                        tis_pos[1] -= p_y
                                        text_items_state[blk_idx]['position'] = tis_pos
                else:
                    missing_reports.append(f"Page {page_num + 1}: [#{blk_id}]")
            
            if clean_ids:
                self.clean_blocks_by_ids(page_num, clean_ids)
 
        # 4. Final Refresh
        if self.main.webtoon_mode:
            manager = self.main.image_viewer.webtoon_manager
            # This will now save the UPDATED main.blk_list
            manager.scene_item_manager.save_loaded_scene_items_to_states()
            manager.scene_item_manager._clear_all_scene_items()
            for p_idx in list(manager.loaded_pages):
                manager.scene_item_manager.load_page_scene_items(p_idx)
        else:
            self.main.image_ctrl.save_current_image_state()
            if self.main.curr_img_idx >= 0:
                self.main.image_ctrl.display_image(self.main.curr_img_idx, switch_page=False)
        
        # 5. Report Results
        if updated_count > 0:
            msg = f"Successfully updated {updated_count} blocks across {len(page_headers)} pages."
            if missing_reports:
                msg += "\n\nThe following IDs could not be matched:\n" + "\n".join(missing_reports)
            MMessage.success(text=msg, duration=2, parent=self.main)
        elif missing_reports:
            msg = "Could not match any IDs from the text.\n\nMissing IDs:\n" + "\n".join(missing_reports)
            MMessage.warning(text=msg, duration=2, parent=self.main)
        else:
            MMessage.info(text="No blocks were updated.", parent=self.main)

    def import_current_page_text(self):
        if self.main.curr_img_idx < 0:
            MMessage.warning(text="No page selected", parent=self.main)
            return

        text_content = QtGui.QGuiApplication.clipboard().text()
        if not text_content:
            MMessage.warning(text="Clipboard is empty", parent=self.main)
            return

        page_num = self.main.curr_img_idx
        file_path = self.main.image_files[page_num]
        
        # 1. Identify content for current page if headers exist
        # We search for the PAGE X header and extract its section
        page_headers = re.findall(r"(?:###\s*)?PAGE (\d+): (.*?)(?:\s*###)?", text_content)
        if page_headers:
            page_splits = re.split(r"(?:###\s*)?PAGE \d+: .*?(?:\s*###)?", text_content)
            content_parts = page_splits[1:]
            
            target_content = ""
            for header, content in zip(page_headers, content_parts):
                if int(header[0]) - 1 == page_num:
                    target_content = content
                    break
            
            if not target_content:
                MMessage.warning(text=f"Clipboard contains multiple pages, but none match Page {page_num + 1}.", parent=self.main)
                return
            content_to_parse = target_content
        else:
            content_to_parse = text_content

        # 2. Setup state and live lists
        if file_path not in self.main.image_states:
            self.main.image_states[file_path] = {'blk_list': [], 'viewer_state': {'text_items_state': []}}
        
        state = self.main.image_states[file_path]
        blks = state.setdefault("blk_list", [])
        
        # IMPORTANT FIX: Use live blk_list if it's the active page and not in webtoon mode
        # This ensures we are matching against the blocks currently seen on screen
        if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_num:
            blks = self.main.blk_list or []

        viewer_state = state.setdefault('viewer_state', {})
        text_items_state = viewer_state.setdefault('text_items_state', [])
        
        is_active_page = True # This is 'import_current_page_text', so it's always the active page
        live_blks = self.main.blk_list
        live_items = self.main.image_viewer.text_items

        # 3. Pre-assign stable IDs to blocks if they don't have them
        for idx, blk in enumerate(blks):
            if getattr(blk, 'block_id', -1) < 0:
                blk.block_id = idx + 1

        # 4. Get settings from UI for typesetting
        try:
            render_settings = self.main.text_ctrl.render_settings()
            max_font_size = self.main.settings_page.get_max_font_size()
            min_font_size = self.main.settings_page.get_min_font_size()
            alignment = self.main.button_to_alignment[render_settings.alignment_id]
            font_family = render_settings.font_family
            line_spacing = float(render_settings.line_spacing)
            outline_width = float(render_settings.outline_width)
        except:
            render_settings = None

        print(f"DEBUG: Starting import_current_page_text for Page {page_num + 1}")
        print(f"DEBUG: content_to_parse length: {len(content_to_parse)}")
        
        # 5. Parse blocks using the robust helper
        block_matches = self._parse_clipboard_blocks(content_to_parse)
        print(f"DEBUG: Found {len(block_matches)} block matches in clipboard")
        
        updated_count = 0
        clean_ids = []

        for b_data in block_matches:
            blk_id = b_data['id']
            blk_label = b_data['label']
            blk_uuid = b_data['uuid']
            final_text = b_data['text']
            print(f"DEBUG: Processing block ID: {blk_id}, label: {blk_label}, UUID: {blk_uuid}")
            
            # Clean if requested (Magic Wand logic)
            if "CLEAN" in blk_label.upper() or "WAND" in blk_label.upper():
                clean_ids.append(blk_id)

            # Find target block
            target_blk = None
            if blk_id >= 0:
                target_blk = next((b for b in blks if getattr(b, 'block_id', -1) == blk_id), None)
            if not target_blk and blk_uuid:
                target_blk = next((b for b in blks if getattr(b, 'uuid', None) == blk_uuid), None)
            if not target_blk and 0 <= (blk_id - 1) < len(blks):
                target_blk = blks[blk_id - 1]

            if target_blk:
                blk = target_blk
                blk_idx = blks.index(blk)
                updated_count += 1
                print(f"DEBUG: Found target_blk at index {blk_idx}. Current translation: {getattr(blk, 'translation', 'N/A')[:20]}...")
                
                # Apply typesetting if possible
                final_font_size = None
                vertical = False
                if render_settings:
                    try:
                        target_lang = self.main.lang_mapping.get(self.main.t_combo.currentText(), None)
                        trg_lng_cd = get_language_code(target_lang)
                        vertical = is_vertical_block(blk, trg_lng_cd)

                        w, h = blk.xywh[2], blk.xywh[3]
                        wrapped_text, font_size = pyside_word_wrap(
                            final_text, font_family, w, h, line_spacing, outline_width,
                            render_settings.bold, render_settings.italic, render_settings.underline,
                            alignment, render_settings.direction, max_font_size, min_font_size,
                            vertical=vertical
                        )
                        final_text = wrapped_text
                        final_font_size = font_size
                        print(f"DEBUG: Typesetting complete. New text length: {len(final_text)}, Vertical: {vertical}")
                    except Exception as e:
                        print(f"DEBUG: Typesetting error: {e}")

                # Update Block Object Properties
                blk.translation = final_text
                blk.text = final_text # Keep source synced for manual editing consistency
                if final_font_size: blk.font_size = final_font_size
                blk.target_lang = self.main.t_combo.currentText()
                blk.source_lang = self.main.s_combo.currentText()
                
                # Update Image State (for persistence)
                if 0 <= blk_idx < len(text_items_state):
                    props = text_items_state[blk_idx]
                    props['text'] = final_text
                    props['translation'] = final_text
                    props['block_id'] = blk.block_id
                    props['uuid'] = blk.uuid
                    if final_font_size: props['font_size'] = final_font_size
                    if render_settings:
                        smart_color = get_smart_text_color(blk.font_color, QtGui.QColor(render_settings.color))
                        props['alignment'] = int(alignment)
                        props['font_family'] = font_family
                        props['bold'] = render_settings.bold
                        props['italic'] = render_settings.italic
                        props['underline'] = render_settings.underline
                        props['line_spacing'] = line_spacing
                        props['text_color'] = smart_color.name()
                        props['vertical'] = vertical
                        props['outline'] = render_settings.outline
                        if render_settings.outline:
                            props['outline_color'] = render_settings.outline_color
                            props['outline_width'] = outline_width
                    print(f"DEBUG: Updated text_items_state[{blk_idx}]")

                # Update live blocks (for sidebars/lists)
                if live_blks and 0 <= blk_idx < len(live_blks):
                    lblk = live_blks[blk_idx]
                    lblk.translation = final_text
                    lblk.text = final_text
                    if final_font_size: lblk.font_size = final_font_size
                    print(f"DEBUG: Updated live_blks[{blk_idx}]")

                # Update live items (for immediate visual feedback in viewer)
                item = self._find_item_for_blk(blk, live_items, page_num, blk_idx)
                if item:
                    # Capture current scene position for the "Hard Anchor"
                    current_scene_top_left = item.mapToScene(QtCore.QPointF(0, 0))

                    try:
                        if render_settings:
                            smart_color = get_smart_text_color(blk.font_color, QtGui.QColor(render_settings.color))
                            item.font_family = font_family
                            item.font_size = final_font_size or item.font_size
                            item.text_color = smart_color
                            item.alignment = alignment
                            item.line_spacing = line_spacing
                            item.bold = render_settings.bold
                            item.italic = render_settings.italic
                            item.underline = render_settings.underline
                            item.set_vertical(vertical)
                            if render_settings.outline:
                                item.outline = True
                                item.outline_color = QtGui.QColor(render_settings.outline_color)
                                item.outline_width = outline_width
                            else:
                                item.outline = False

                        # Update item properties
                        item.set_vertical(vertical)
                        item.set_text(final_text, blk.xywh[2])
                        
                        # Apply rotation and origin
                        angle = item.rotation()
                        item.setCenterTransform()
                        item.setRotation(angle)
                        
                        # FINAL POSITION LOCK: Restore precisely to the original scene top-left
                        new_scene_top_left = item.mapToScene(QtCore.QPointF(0, 0))
                        delta = current_scene_top_left - new_scene_top_left
                        if not delta.isNull():
                            item.setPos(item.pos() + delta)
                            print(f"FINAL POSITION LOCK: Restored live item for block {blk_id} by {delta.x()},{delta.y()}")
                        
                        # CRITICAL SYNC: Update live blk_list to prevent overwriting
                        if live_blks:
                            for live_blk in live_blks:
                                if getattr(live_blk, 'block_id', -1) == blk.block_id:
                                    live_blk.translation = final_text
                                    live_blk.text = final_text
                                    if final_font_size: live_blk.font_size = final_font_size
                                    break
                    except Exception as e:
                        print(f"DEBUG: Error updating live item: {e}")
                else:
                    items_count = len(live_items) if live_items is not None else "None"
                    print(f"DEBUG: Live item NOT found for block {blk_id}. live_items count: {items_count}")
            else:
                print(f"DEBUG: target_blk NOT found for ID {blk_id}. blks count: {len(blks)}")

        # Clean blocks if any were marked for cleaning in the label
        if clean_ids:
            print(f"DEBUG: Cleaning {len(clean_ids)} blocks")
            self.clean_blocks_by_ids(page_num, clean_ids)

        # Save and Refresh
        print("DEBUG: Saving image state and refreshing UI")
        if self.main.webtoon_mode:
            manager = self.main.image_viewer.webtoon_manager
            # Correctly save live updates back to their respective page states
            manager.scene_item_manager.save_loaded_scene_items_to_states()
            
            # Refresh visible area
            manager.scene_item_manager._clear_all_scene_items()
            for p_idx in list(manager.loaded_pages):
                manager.scene_item_manager.load_page_scene_items(p_idx)
        else:
            self.main.image_ctrl.save_current_image_state()
            self.main.image_ctrl.display_image(page_num, switch_page=False)

        print(f"DEBUG: Finished import_current_page_text. updated_count: {updated_count}")

        if updated_count > 0:
            MMessage.success(text=f"Successfully updated {updated_count} blocks on Page {page_num + 1}.", parent=self.main, duration=1)
        else:
            MMessage.warning(text="No blocks were matched for the current page.", parent=self.main)
