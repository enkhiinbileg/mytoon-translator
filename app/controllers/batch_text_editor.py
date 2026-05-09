import os
import re
import numpy as np
import imkit as imk
from typing import TYPE_CHECKING
from PySide6 import QtCore, QtGui
from app.ui.dayu_widgets.message import MMessage
from modules.rendering.render import pyside_word_wrap

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
            
        # 1. Try matching by Stable block_id if available (User-preferred)
        target_id = getattr(blk, 'block_id', -1)
        if target_id >= 0:
            for item in live_items:
                if getattr(item, 'block_id', -1) == target_id:
                    return item

        # 2. Try matching by UUID if available
        target_uuid = getattr(blk, 'uuid', None)
        if target_uuid:
            for item in live_items:
                if getattr(item, 'uuid', None) == target_uuid:
                    return item

        # 3. Fallback to index-based matching stored in UserRole
        if blk_idx is not None:
            for item in live_items:
                if item.data(QtCore.Qt.UserRole) == blk_idx:
                    # Additional check for Webtoon mode: ensure item is on the correct page
                    if getattr(self.main, "webtoon_mode", False) and page_num is not None:
                        # Find which page this item belongs to
                        layout = self.main.image_viewer.webtoon_manager.layout_manager
                        item_page = layout.get_page_at_position(item.pos().y())
                        if item_page != page_num:
                            continue
                    return item

        # 2. Fallback to position matching
        # Base coordinates from block
        bx, by = blk.xyxy[0], blk.xyxy[1]
        
        # Apply offsets if in Webtoon mode
        if getattr(self.main, "webtoon_mode", False) and page_num is not None:
            try:
                # Use LazyWebtoonManager structure
                webtoon_manager = getattr(self.main.image_viewer, "webtoon_manager", None)
                if webtoon_manager and hasattr(webtoon_manager, "layout_manager"):
                    layout = webtoon_manager.layout_manager
                    loader = webtoon_manager.image_loader
                    
                    if page_num < len(layout.image_positions):
                        # Y offset (page vertical position)
                        by += layout.image_positions[page_num]
                        
                        # X offset (horizontal centering)
                        if page_num in loader.image_items:
                            bx += loader.image_items[page_num].pos().x()
            except Exception as e:
                print(f"Error calculating webtoon offset for page {page_num}: {e}")

        for item in live_items:
            # Match by position and rotation (with some tolerance)
            if self._is_close(item.pos().x(), bx, 5) and \
               self._is_close(item.pos().y(), by, 5) and \
               self._is_close(item.rotation(), blk.angle, 1):
                return item
        return None

    def clean_blocks_by_ids(self, page_idx: int, blk_ids: list[int]):
        """Runs segmentation and inpainting for specific blocks on a page."""
        if not (0 <= page_idx < len(self.main.image_files)):
            return

        file_path = self.main.image_files[page_idx]
        state = self.main.image_states.get(file_path, {})
        blks = state.get("blk_list", [])
        
        # If current page is active, use live blocks
        if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_idx:
            blks = self.main.blk_list or []

        targets = [b for b in blks if getattr(b, 'block_id', -1) in blk_ids]
        if not targets:
            return

        # 1. Load image
        image = self.main.image_data.get(file_path)
        if image is None:
            image = self.main.image_ctrl.load_image(file_path)
            if image is not None:
                self.main.image_data[file_path] = image
        
        if image is None:
            return

        # 2. Compute segmentation bboxes
        from modules.detection.utils.content import get_inpaint_bboxes
        for blk in targets:
            # Ensure coordinates are integers for slice operations
            if blk.xyxy is not None:
                blk.xyxy = [int(v) for v in blk.xyxy]
            blk.inpaint_bboxes = get_inpaint_bboxes(blk.xyxy, image)

        # 3. Create brush strokes (for inpainter)
        strokes = self.main.manual_workflow_ctrl._serialize_segmentation_strokes(targets)
        
        # 4. Run Inpainting
        # We use the pipeline's inpaint_page_from_saved_strokes
        patches = self.main.pipeline.inpainting.inpaint_page_from_saved_strokes(image, strokes)
        
        if patches:
            # If webtoon mode, map coordinates
            if getattr(self.main, "webtoon_mode", False):
                manager = self.main.image_viewer.webtoon_manager
                for patch in patches:
                    x, y, _w, _h = patch['bbox']
                    scene_pos = manager.coordinate_converter.page_local_to_scene_position(QtCore.QPointF(x, y), page_idx)
                    if scene_pos:
                        patch['scene_pos'] = [scene_pos.x(), scene_pos.y()]
                        patch['page_index'] = page_idx
            
            # Apply patches via signal for thread-safety
            self.main.patches_processed.emit(patches, file_path)
            self.main.mark_project_dirty()

    def _fast_solid_clean(self, page_idx: int, blk_ids: list[int]):
        """Fast cleaning by filling blocks with their dominant background color."""
        print(f"DEBUG: Starting _fast_solid_clean for page {page_idx}, blocks: {blk_ids}")
        file_path = self.main.image_files[page_idx]
        
        # Accessing main object from thread - let's be careful
        image = self.main.image_data.get(file_path)
        if image is None:
            print(f"DEBUG: Image not in cache, loading: {file_path}")
            # Use cv2 directly if possible to avoid UI-thread issues in image_ctrl
            import cv2
            image = cv2.imread(file_path)
            if image is not None:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                self.main.image_data[file_path] = image
        
        if image is None:
            print(f"DEBUG: Failed to load image for page {page_idx}")
            return

        print(f"DEBUG: Image loaded successfully for page {page_idx}. Shape: {image.shape}")
        
        state = self.main.image_states.get(file_path, {})
        blks = state.get("blk_list", [])
        if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_idx:
            blks = self.main.blk_list or []
        
        targets = [b for b in blks if getattr(b, 'block_id', -1) in blk_ids]
        print(f"DEBUG: Found {len(targets)} target blocks to clean.")
        
        patches = []
        h, w = image.shape[:2]

        for blk in targets:
            try:
                # In webtoon mode, coordinates might be scene-relative, need to clip to page
                if getattr(self.main, "webtoon_mode", False):
                    manager = self.main.image_viewer.webtoon_manager
                    local_xyxy = manager.coordinate_converter.clip_textblock_to_page(blk, page_idx)
                    if local_xyxy is None:
                        continue
                    x1, y1, x2, y2 = [int(v) for v in local_xyxy]
                else:
                    # Ensure coordinates are integers
                    x1, y1, x2, y2 = [int(v) for v in blk.xyxy]
                
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                
                if x2 <= x1 or y2 <= y1:
                    continue

                sample_pts = [
                    (y1, x1), (y1, x2-1), (y2-1, x1), (y2-1, x2-1),
                    (y1, (x1+x2)//2), (y2-1, (x1+x2)//2),
                    ((y1+y2)//2, x1), ((y1+y2)//2, x2-1)
                ]
                
                colors = []
                for py, px in sample_pts:
                    if 0 <= py < h and 0 <= px < w:
                        colors.append(image[py, px])
                
                if colors:
                    avg_color = np.median(colors, axis=0).astype(np.uint8)
                else:
                    avg_color = np.array([255, 255, 255], dtype=np.uint8)
                print(f"DEBUG: Block {getattr(blk, 'block_id', '?')} avg_color: {avg_color}")

                filled_patch = np.full((y2 - y1, x2 - x1, 3), avg_color, dtype=np.uint8)
                
                patches.append({
                    'x': x1, 'y': y1, 'w': x2 - x1, 'h': y2 - y1,
                    'bbox': [x1, y1, x2 - x1, y2 - y1],
                    'image': filled_patch,
                    'page_index': page_idx
                })
            except Exception as e:
                print(f"DEBUG Error cleaning block: {e}")
                continue

        if patches:
            print(f"DEBUG: Emitting {len(patches)} patches for page {page_idx}")
            if getattr(self.main, "webtoon_mode", False):
                # Map coordinates to scene positions in webtoon mode
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
        def inpaint_worker():
            # AI part runs in background with pre-captured image
            return self.main.pipeline.inpainting.get_patches_for_mask(page_idx, mask, image=rendered_image)
            
        def on_finished(result):
            # Applying patches runs in main thread
            if result:
                patches, f_path = result
                if patches and f_path:
                    # Enrich on main thread to avoid freezes
                    self.main.pipeline.inpainting.enrich_patches_with_scene_pos(patches, page_idx)
                    self.main.image_ctrl.on_inpaint_patches_processed(patches, f_path)
            self.main.mark_project_dirty()
            
        # Execute threaded
        self.main.run_threaded(
            inpaint_worker, 
            on_finished, 
            self.main.default_error_handler, 
            self.main.on_manual_finished
        )

    def tap_to_clean(self, item):
        """Cleans a single text block item."""
        if not item:
            return
            
        # 1. Determine page index
        page_idx = -1
        if getattr(self.main, "webtoon_mode", False):
            layout = self.main.image_viewer.webtoon_manager.layout_manager
            page_idx = layout.get_page_at_position(item.pos().y())
        else:
            page_idx = self.main.curr_img_idx
            
        if page_idx < 0:
            return
            
        # 2. Get block ID
        blk_id = getattr(item, 'block_id', -1)
        if blk_id < 0:
            # Try to find the block in the state to get its index/ID
            file_path = self.main.image_files[page_idx]
            state = self.main.image_states.get(file_path, {})
            blks = state.get("blk_list", [])
            # In regular mode, use live list
            if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_idx:
                blks = self.main.blk_list or []
                
            for idx, blk in enumerate(blks):
                # This is a bit loose but should work for finding the ID
                if self._is_close(blk.xyxy[0], item.pos().x(), 5) and self._is_close(blk.xyxy[1], item.pos().y(), 5):
                    blk_id = getattr(blk, 'block_id', idx + 1)
                    break
        
        if blk_id >= 0:
            print(f"Magic Wand: Cleaning block {blk_id} on page {page_idx}")
            self.clean_blocks_by_ids(page_idx, [blk_id])

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
                MMessage.success(text=f"Magic Wand: Successfully cleaned {count} blocks.", parent=self.main)
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
            for page_idx, file_path in enumerate(self.main.image_files):
                state = self.main.image_states.get(file_path, {})
                blks = state.get("blk_list", [])
                
                # If current page is active and not in webtoon mode, use live blocks
                if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_idx:
                    blks = self.main.blk_list or []
                
                if not blks:
                    continue

                # Ensure stable IDs and collect them
                blk_ids = []
                for idx, blk in enumerate(blks):
                    if getattr(blk, 'block_id', -1) < 0:
                        blk.block_id = idx + 1
                    blk_ids.append(blk.block_id)
                
                if blk_ids:
                    # Use fast solid clean as requested for speed
                    self._fast_solid_clean(page_idx, blk_ids)
                    count += len(blk_ids)
            return count

        def on_clean_finished(count):
            self.main.loading.setVisible(False)
            self.main.enable_hbutton_group()
            if count > 0:
                MMessage.success(text=f"Magic Wand All: Successfully cleaned {count} blocks across all pages.", parent=self.main)
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

        output = []
        for page_idx, file_path in enumerate(self.main.image_files):
            basename = os.path.basename(file_path)
            output.append(f"### PAGE {page_idx + 1}: {basename} ###")
            
            state = self.main.image_states.get(file_path) or {}
            blks = state.get("blk_list") or []
            
            # Use current live blk_list if it's the active page and not in webtoon mode
            if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_idx:
                blks = self.main.blk_list or []

            # Assign stable IDs to blocks if they don't have them
            for idx, blk in enumerate(blks):
                if getattr(blk, 'block_id', -1) < 0:
                    blk.block_id = idx + 1
            
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
                blk_uuid = getattr(blk, "uuid", "")
                stable_id = getattr(blk, "block_id", idx + 1)
                
                output.append(f"[#{stable_id} {label}]")
                # Split translation into lines and prefix each with //
                for line in translation.splitlines():
                    output.append(f"// {line}")
                output.append("") # Extra newline for spacing
            output.append("\n")
            
        text_content = "\n".join(output)
        QtGui.QGuiApplication.clipboard().setText(text_content)
        MMessage.success(text="All text copied to clipboard in batch format!", parent=self.main)

    def export_current_page_text(self):
        if self.main.curr_img_idx < 0:
            MMessage.warning(text="No page selected", parent=self.main)
            return

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
            for line in translation.splitlines():
                output.append(f"// {line}")
            output.append("")
            
        text_content = "\n".join(output)
        QtGui.QGuiApplication.clipboard().setText(text_content)
        MMessage.success(text=f"Text from Page {page_idx + 1} copied to clipboard!", parent=self.main)

    def import_all_text(self):
        text_content = QtGui.QGuiApplication.clipboard().text()
        if not text_content:
            MMessage.warning(text="Clipboard is empty", parent=self.main)
            return

        # Flexible Regex to parse the format
        # Matches "### PAGE 1: filename.jpg ###" or just "PAGE 1: filename.jpg"
        page_splits = re.split(r"(?:###\s*)?PAGE \d+: .*?(?:\s*###)?", text_content)
        page_headers = re.findall(r"(?:###\s*)?PAGE (\d+): (.*?)(?:\s*###)?", text_content)
        
        # Regex for block header: [#1 Dialogue UUID:uuid-string]
        # Group 1: Index, Group 2: Class/Label, Group 3: Optional UUID
        block_header_re = r"\[#(\d+) (.*?)(?: UUID:([a-fA-F0-9-]+))?\]"
        
        if not page_headers:
            MMessage.error(text="Invalid format. Could not find any page headers (e.g. PAGE 1: ...)", parent=self.main)
            return

        # The split will have an empty string or garbage at index 0
        content_parts = page_splits[1:]
        
        updated_count = 0
        missing_reports = [] # To track unmatched IDs
        
        # 1. Pre-assign stable IDs to ALL blocks in ALL pages if they don't have them
        # This ensures matching works correctly for all pages
        for page_idx, file_path in enumerate(self.main.image_files):
            blks = self.main.image_states.get(file_path, {}).get('blk_list', [])
            if not getattr(self.main, "webtoon_mode", False) and self.main.curr_img_idx == page_idx:
                blks = self.main.blk_list or []
            
            for idx, blk in enumerate(blks):
                if getattr(blk, 'block_id', -1) < 0:
                    blk.block_id = idx + 1

        # 2. Process the content page by page
        for header, content in zip(page_headers, content_parts):
            page_num = int(header[0]) - 1
            if page_num < 0 or page_num >= len(self.main.image_files):
                continue
                
            file_path = self.main.image_files[page_num]
            if file_path not in self.main.image_states:
                self.main.image_states[file_path] = {'blk_list': [], 'viewer_state': {'text_items_state': []}}
            
            state = self.main.image_states[file_path]
            blks = state.setdefault("blk_list", [])
            viewer_state = state.setdefault('viewer_state', {})
            text_items_state = viewer_state.setdefault('text_items_state', [])
            
            # More robust block matching:
            # 1. Matches [#1 Label]
            # 2. Captures all lines starting with //
            # 3. If no // lines, captures everything until next block or next page
            
            # This regex captures the ID and then looks for content
            block_pattern = r"\[#(\d+) .*?\]\s*\n(.*?)(?=\n\s*\n|\n\[#|$)"
            matches = re.finditer(block_pattern, content, re.DOTALL)
            
            block_matches = []
            for match in matches:
                b_id = match.group(1)
                b_content = match.group(2).strip()
                
                # Extract text from lines starting with //
                lines = b_content.splitlines()
                extracted_lines = []
                for line in lines:
                    if line.strip().startswith("//"):
                        extracted_lines.append(line.strip()[2:].strip())
                    else:
                        extracted_lines.append(line.strip())
                
                final_text = "\n".join(extracted_lines).strip()
                block_matches.append((b_id, "", "", final_text)) # Simplified for compatibility with loop below
            
            # If current page is active, update the live blocks and live items too
            is_active_page = (page_num == self.main.curr_img_idx and not getattr(self.main, "webtoon_mode", False))
            live_blks = self.main.blk_list if is_active_page else None
            live_items = self.main.image_viewer.text_items if is_active_page else None

            # Get settings from UI for typesetting
            try:
                render_settings = self.main.text_ctrl.render_settings()
                max_font_size = self.main.settings_page.get_max_font_size()
                min_font_size = self.main.settings_page.get_min_font_size()
                alignment = self.main.button_to_alignment[render_settings.alignment_id]
                font_family = render_settings.font_family
                line_spacing = float(render_settings.line_spacing)
                outline_width = float(render_settings.outline_width)
            except Exception as e:
                print(f"Batch typeset setup error: {e}")
                render_settings = None
            # Group by blocks using the block header regex
            # We look ahead for the next block header or page break
            block_matches = re.findall(block_header_re + r"\s*\n(?:\/\/\s*.*?\n)?(.*?)(?=\n\n|\n\[#|$)", content, re.DOTALL)
            
            # Identify blocks that need cleaning
            clean_ids = []
            for b_match in block_matches:
                blk_idx_str, blk_label, blk_uuid, blk_text = b_match
                if "CLEAN" in blk_label.upper() or "WAND" in blk_label.upper():
                    clean_ids.append(int(blk_idx_str))

            for b_match in block_matches:
                blk_id_str, _unused_label, _unused_uuid, blk_text = b_match
                blk_id = int(blk_id_str)
                final_text = blk_text.strip()
                
                # Try to find block by ID first, then UUID, then index
                target_blk = None
                if blk_id >= 0:
                    target_blk = next((b for b in blks if getattr(b, 'block_id', -1) == blk_id), None)
                
                if not target_blk and blk_uuid:
                    target_blk = next((b for b in blks if getattr(b, 'uuid', None) == blk_uuid), None)
                
                # Final fallback by index if we have a valid index-like string
                if not target_blk and 0 <= (blk_id - 1) < len(blks):
                    target_blk = blks[blk_id - 1]
                
                if target_blk:
                    blk = target_blk
                    blk_idx = blks.index(blk)
                    updated_count += 1
                    # Update State
                    # Apply typesetting if possible
                    final_font_size = None
                    
                    if render_settings:
                        try:
                            # Use blk's dimensions for wrapping
                            # blk.xywh provides [x, y, w, h]
                            w, h = blk.xywh[2], blk.xywh[3]
                            
                            wrapped_text, font_size = pyside_word_wrap(
                                final_text,
                                font_family,
                                w, h,
                                line_spacing,
                                outline_width,
                                render_settings.bold,
                                render_settings.italic,
                                render_settings.underline,
                                alignment,
                                render_settings.direction,
                                max_font_size,
                                min_font_size
                            )
                            final_text = wrapped_text
                            final_font_size = font_size
                        except Exception as e:
                            print(f"Error typeseting block {blk_idx}: {e}")

                    # Update state
                    blk.translation = final_text
                    blk.text = final_text # Update source as well for manual mode consistency
                    blk.target_lang = self.main.t_combo.currentText()
                    blk.source_lang = self.main.s_combo.currentText()
                    if final_font_size:
                        blk.font_size = final_font_size
                    
                    if 0 <= blk_idx < len(text_items_state):
                        props = text_items_state[blk_idx]
                        props['text'] = final_text
                        props['block_id'] = blk.block_id # Save stable ID to state
                        props['uuid'] = blk.uuid # Save UUID to state
                        props['target_lang'] = self.main.t_combo.currentText()
                        props['source_lang'] = self.main.s_combo.currentText()
                        if final_font_size:
                            props['font_size'] = final_font_size
                        
                        # Apply current UI styles to the state
                        if render_settings:
                            props['alignment'] = int(alignment)
                            props['font_family'] = font_family
                            props['bold'] = render_settings.bold
                            props['italic'] = render_settings.italic
                            props['underline'] = render_settings.underline
                            props['line_spacing'] = line_spacing
                            props['text_color'] = render_settings.color
                            if render_settings.outline:
                                props['outline'] = True
                                props['outline_color'] = render_settings.outline_color
                                props['outline_width'] = outline_width
                            else:
                                props['outline'] = False
                    
                    # Update live blocks (for sidebars)
                    if live_blks and 0 <= blk_idx < len(live_blks):
                        lblk = live_blks[blk_idx]
                        lblk.translation = final_text
                        lblk.text = final_text
                        if final_font_size:
                            lblk.font_size = final_font_size
                    
                    # Update live items (for immediate visual feedback on image)
                    item = self._find_item_for_blk(blk, live_items, page_num, blk_idx)
                    if item:
                        try:
                            # Apply all styles to the live item
                            if render_settings:
                                item.font_family = font_family
                                item.font_size = final_font_size or item.font_size
                                item.text_color = QtGui.QColor(render_settings.color)
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
                                    item.outline_color = None

                            # set_text will call apply_all_attributes which uses the values we just set
                            item.set_text(final_text, item.boundingRect().width())
                        except Exception as e:
                            print(f"Error updating live item {blk_idx}: {e}")
                        except:
                            pass
                else:
                    missing_reports.append(f"Page {page_num + 1}: [#{blk_id}]")
            
            if clean_ids:
                self.clean_blocks_by_ids(page_num, clean_ids)

        # Save current image state if needed
        self.main.image_ctrl.save_current_image_state()
        # Full UI refresh
        if self.main.webtoon_mode:
            # In webtoon mode, refresh loaded pages
            manager = self.main.image_viewer.webtoon_manager
            loaded_pages = list(manager.loaded_pages)
            # Clear current items first to avoid duplicates
            manager.scene_item_manager._clear_all_scene_items()
            # Reload each loaded page from its updated state
            for page_idx in loaded_pages:
                manager.scene_item_manager.load_page_scene_items(page_idx)
        elif self.main.curr_img_idx >= 0:
            # Regular mode refresh
            self.main.image_ctrl.display_image(self.main.curr_img_idx, switch_page=False)
        
        if updated_count > 0:
            msg = f"Successfully updated {updated_count} blocks across {len(page_headers)} pages."
            if missing_reports:
                msg += "\n\nThe following IDs could not be matched:\n" + "\n".join(missing_reports)
            MMessage.success(text=msg, duration=10, parent=self.main)
        elif missing_reports:
            msg = "Could not match any IDs from the text.\n\nMissing IDs:\n" + "\n".join(missing_reports)
            MMessage.warning(text=msg, duration=10, parent=self.main)
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
        
        # Ensure state exists
        if file_path not in self.main.image_states:
            self.main.image_states[file_path] = {'blk_list': [], 'viewer_state': {'text_items_state': []}}
        
        state = self.main.image_states[file_path]
        blks = state.setdefault("blk_list", [])
        viewer_state = state.setdefault('viewer_state', {})
        text_items_state = viewer_state.setdefault('text_items_state', [])
        
        # Pre-assign stable IDs
        for idx, blk in enumerate(blks):
            if getattr(blk, 'block_id', -1) < 0:
                blk.block_id = idx + 1

        # Regex to find blocks. Support both the [ID Label] and // Text format
        block_pattern = r"\[#(\d+) .*?\]\s*\n(.*?)(?=\n\s*\n|\n\[#|$)"
        matches = re.finditer(block_pattern, text_content, re.DOTALL)
        
        updated_count = 0
        
        is_active_page = (not getattr(self.main, "webtoon_mode", False))
        live_blks = self.main.blk_list if is_active_page else None
        live_items = self.main.image_viewer.text_items if is_active_page else None

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

        for match in matches:
            blk_id = int(match.group(1))
            b_content = match.group(2).strip()
            
            # Extract text from lines starting with //
            lines = b_content.splitlines()
            extracted_lines = []
            for line in lines:
                if line.strip().startswith("//"):
                    extracted_lines.append(line.strip()[2:].strip())
                else:
                    extracted_lines.append(line.strip())
            
            final_text = "\n".join(extracted_lines).strip()
            
            # Find block
            target_blk = next((b for b in blks if getattr(b, 'block_id', -1) == blk_id), None)
            if not target_blk and 0 <= (blk_id - 1) < len(blks):
                target_blk = blks[blk_id - 1]

            if target_blk:
                blk = target_blk
                blk_idx = blks.index(blk)
                updated_count += 1
                
                final_font_size = None
                if render_settings:
                    try:
                        w, h = blk.xywh[2], blk.xywh[3]
                        wrapped_text, font_size = pyside_word_wrap(
                            final_text, font_family, w, h, line_spacing, outline_width,
                            render_settings.bold, render_settings.italic, render_settings.underline,
                            alignment, render_settings.direction, max_font_size, min_font_size
                        )
                        final_text = wrapped_text
                        final_font_size = font_size
                    except: pass

                blk.translation = final_text
                blk.text = final_text
                if final_font_size: blk.font_size = final_font_size
                
                if 0 <= blk_idx < len(text_items_state):
                    props = text_items_state[blk_idx]
                    props['text'] = final_text
                    if final_font_size: props['font_size'] = final_font_size
                    if render_settings:
                        props['alignment'] = int(alignment)
                        props['font_family'] = font_family
                        props['text_color'] = render_settings.color

                if live_blks and 0 <= blk_idx < len(live_blks):
                    lblk = live_blks[blk_idx]
                    lblk.translation = final_text
                    lblk.text = final_text

                item = self._find_item_for_blk(blk, live_items, page_num, blk_idx)
                if item:
                    try:
                        if render_settings:
                            item.font_family = font_family
                            item.font_size = final_font_size or item.font_size
                        item.set_text(final_text, item.boundingRect().width())
                    except: pass

        self.main.image_ctrl.save_current_image_state()
        if self.main.webtoon_mode:
            manager = self.main.image_viewer.webtoon_manager
            manager.scene_item_manager._clear_all_scene_items()
            for p_idx in list(manager.loaded_pages):
                manager.scene_item_manager.load_page_scene_items(p_idx)
        else:
            self.main.image_ctrl.display_image(page_num, switch_page=False)

        if updated_count > 0:
            MMessage.success(text=f"Successfully updated {updated_count} blocks on the current page.", parent=self.main)
        else:
            MMessage.warning(text="No blocks were matched for the current page.", parent=self.main)
