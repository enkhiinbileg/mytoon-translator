import numpy as np
import time
import logging
import imkit as imk

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QBrush

from modules.utils.device import resolve_device
from modules.utils.pipeline_config import inpaint_map, get_config, get_inpainter_backend

logger = logging.getLogger(__name__)


class InpaintingHandler:
    """Handles image inpainting functionality."""
    
    def __init__(self, main_page):
        self.main_page = main_page
        self.inpainter_cache = None
        self.cached_inpainter_key = None

    def _ensure_inpainter(self, inpainter_key=None):
        settings_page = self.main_page.settings_page
        if inpainter_key is None:
            inpainter_key = settings_page.get_tool_selection('inpainter')
        if inpainter_key == "None":
            return None
        if self.inpainter_cache is None or self.cached_inpainter_key != inpainter_key:
            backend = get_inpainter_backend(inpainter_key)
            device = resolve_device(settings_page.is_gpu_enabled(), backend)
            InpainterClass = inpaint_map[inpainter_key]
            logger.info("pre-inpaint: initializing inpainter '%s' on device %s", inpainter_key, device)
            t0 = time.time()
            self.inpainter_cache = InpainterClass(device, backend=backend)
            self.cached_inpainter_key = inpainter_key
            logger.info("pre-inpaint: inpainter initialized in %.2fs", time.time() - t0)
        return self.inpainter_cache

    def manual_inpaint(self):
        image_viewer = self.main_page.image_viewer
        settings_page = self.main_page.settings_page
        mask = image_viewer.get_mask_for_inpainting()
        
        # Handle webtoon mode vs regular mode differently
        if self.main_page.webtoon_mode:
            # In webtoon mode, use visible area image for inpainting
            image, mappings = image_viewer.get_visible_area_image()
        else:
            # Regular mode - get the full image
            image = image_viewer.get_image_array()

        if image is None or mask is None:
            return None

        inpainter_key = settings_page.get_tool_selection('inpainter')
        if inpainter_key == "None":
            inpainter_key = "LaMa"
            logger.info("Manual inpaint requested but inpainter is None. Falling back to LaMa.")

        self._ensure_inpainter(inpainter_key)
        config = get_config(settings_page)
        # Force high quality Crop strategy for manual tools
        from modules.inpainting.schema import HDStrategy
        config.hd_strategy = HDStrategy.CROP
        config.hd_strategy_crop_margin = 128
        
        inpaint_input_img = self.inpainter_cache(image, mask, config)
        inpaint_input_img = imk.convert_scale_abs(inpaint_input_img) 

        return inpaint_input_img

    def _qimage_to_np(self, qimg: QImage):
        if qimg.width() <= 0 or qimg.height() <= 0:
            return np.zeros((max(1, qimg.height()), max(1, qimg.width())), dtype=np.uint8)
        ptr = qimg.constBits()
        arr = np.array(ptr).reshape(qimg.height(), qimg.bytesPerLine())
        return arr[:, :qimg.width()]

    def _generate_mask_from_saved_strokes(self, strokes: list[dict], image: np.ndarray):
        if image is None or not strokes:
            return None
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            return None

        human_qimg = QImage(width, height, QImage.Format_Grayscale8)
        gen_qimg = QImage(width, height, QImage.Format_Grayscale8)
        human_qimg.fill(0)
        gen_qimg.fill(0)

        human_painter = QPainter(human_qimg)
        gen_painter = QPainter(gen_qimg)

        human_painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        gen_painter.setPen(QPen(QColor(255, 255, 255), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        human_painter.setBrush(QBrush(QColor(255, 255, 255)))
        gen_painter.setBrush(QBrush(QColor(255, 255, 255)))

        has_any = False
        for stroke in strokes:
            path = stroke.get('path')
            if path is None:
                continue
            brush_hex = QColor(stroke.get('brush', '#00000000')).name(QColor.HexArgb)
            if brush_hex == "#80ff0000":
                gen_painter.drawPath(path)
                has_any = True
                continue

            width_px = max(1, int(stroke.get('width', 25)))
            human_pen = QPen(QColor(255, 255, 255), width_px, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            human_painter.setPen(human_pen)
            human_painter.drawPath(path)
            has_any = True

        human_painter.end()
        gen_painter.end()

        if not has_any:
            return None

        human_mask = self._qimage_to_np(human_qimg)
        gen_mask = self._qimage_to_np(gen_qimg)
        kernel = np.ones((5, 5), np.uint8)
        human_mask = imk.dilate(human_mask, kernel, iterations=2)
        gen_mask = imk.dilate(gen_mask, kernel, iterations=3)
        mask = np.where((human_mask > 0) | (gen_mask > 0), 255, 0).astype(np.uint8)
        if np.count_nonzero(mask) == 0:
            return None
        return mask

    def _get_regular_patches(self, mask: np.ndarray, inpainted_image: np.ndarray, original_image: np.ndarray = None):
        contours, _ = imk.find_contours(mask)
        patches = []
        for c in contours:
            x, y, w, h = imk.bounding_rect(c)
            
            # Extract mask and image for this patch
            patch_mask = mask[y:y + h, x:x + w]
            patch_image = inpainted_image[y:y + h, x:x + w].copy()
            
            if original_image is not None:
                # No blending requested
                pass

            patches.append({'bbox': [x, y, w, h], 'image': patch_image})
        return patches

    def _get_page_image_for_inpainting(self, page_idx: int):
        """Returns the page image with existing patches applied."""
        if self.main_page.webtoon_mode:
            # Use webtoon manager to render the specific page with patches
            loader = self.main_page.image_viewer.webtoon_manager.image_loader
            base_image = loader.get_image_data(page_idx)
            if base_image is None:
                file_path = self.main_page.image_files[page_idx]
                return self.main_page.image_data.get(file_path)
                
            h = base_image.shape[0]
            # Use the internal renderer to get the full page with patches
            return loader._render_page_with_scene_items(
                page_idx, base_image, paint_all=False, include_patches=True, 
                crop_top=0, crop_bottom=h
            )
        else:
            # Regular mode
            # If it's the current page, we can use get_image_array which includes patches
            if page_idx == self.main_page.curr_img_idx:
                img = self.main_page.image_viewer.get_image_array(include_patches=True)
                if img is not None:
                    return img
            
            # Fallback to raw if not current page or get_image_array failed
            file_path = self.main_page.image_files[page_idx]
            return self.main_page.image_data.get(file_path)

    def inpaint_page_from_saved_strokes(self, image: np.ndarray, strokes: list[dict]):
        mask = self._generate_mask_from_saved_strokes(strokes, image)
        if mask is None:
            return []
            
        inpainter_key = self.main_page.settings_page.get_tool_selection('inpainter')
        if inpainter_key == "None":
            inpainter_key = "LaMa"
            logger.info("Manual stroke inpaint requested but inpainter is None. Falling back to LaMa.")

        self._ensure_inpainter(inpainter_key)
        config = get_config(self.main_page.settings_page)
        # Force high quality Crop strategy for manual tools
        from modules.inpainting.schema import HDStrategy
        config.hd_strategy = HDStrategy.CROP
        config.hd_strategy_crop_margin = 128
        
        inpainted = self.inpainter_cache(image, mask, config)
        inpainted = imk.convert_scale_abs(inpainted)
        return self._get_regular_patches(mask, inpainted, original_image=image)

    def get_patches_for_mask(self, page_idx: int, mask: np.ndarray, image: np.ndarray = None):
        """AI part of inpainting - returns patches without applying them.
        
        Args:
            page_idx: Index of the page
            mask: Inpainting mask
            image: Pre-rendered image with patches. If None, it will be rendered (not thread-safe).
        """
        if page_idx < 0 or page_idx >= len(self.main_page.image_files):
            return None, None
            
        file_path = self.main_page.image_files[page_idx]
        
        if image is None:
            # Use rendered image with patches for seamless blending (MAIN THREAD ONLY)
            image = self._get_page_image_for_inpainting(page_idx)
            if image is None:
                image = self.main_page.image_data.get(file_path)
            
        if image is None or mask is None:
            return None, None

        inpainter_key = self.main_page.settings_page.get_tool_selection('inpainter')
        if inpainter_key == "None":
            # Fallback to LaMa for manual tools if None is selected globally
            inpainter_key = "LaMa"
            logger.info("Inpainting was bypassed (None), but manual tool requested it. Falling back to LaMa.")

        self._ensure_inpainter(inpainter_key)
        if self.inpainter_cache is None:
            return

        config = get_config(self.main_page.settings_page)
        # Force high quality Crop strategy for manual tools (PS-level)
        from modules.inpainting.schema import HDStrategy
        config.hd_strategy = HDStrategy.CROP
        config.hd_strategy_crop_margin = 128

        inpainted = self.inpainter_cache(image, mask, config)
        inpainted = imk.convert_scale_abs(inpainted)
        
        # Get patches from the inpainted result with seamless blending
        patches = self._get_regular_patches(mask, inpainted, original_image=image)
        
        for patch in patches:
            patch['page_index'] = page_idx
                
        return patches, file_path

    def enrich_patches_with_scene_pos(self, patches: list, page_idx: int):
        """Adds scene_pos to patches. MUST BE CALLED ON MAIN THREAD."""
        if not self.main_page.webtoon_mode:
            return
            
        manager = self.main_page.image_viewer.webtoon_manager
        for patch in patches:
            lx, ly = patch['bbox'][0], patch['bbox'][1]
            scene_pos = manager.coordinate_converter.page_local_to_scene_position(QPointF(lx, ly), page_idx)
            patch['scene_pos'] = [scene_pos.x(), scene_pos.y()]

    def inpaint_page_from_mask(self, page_idx: int, mask: np.ndarray):
        """Performs inpainting and applies it (main thread)."""
        patches, file_path = self.get_patches_for_mask(page_idx, mask)
        if patches and file_path:
            self.enrich_patches_with_scene_pos(patches, page_idx)
            self.main_page.image_ctrl.on_inpaint_patches_processed(patches, file_path)

    def inpaint_complete(self, patch_list):
        # Handle webtoon mode vs regular mode
        if self.main_page.webtoon_mode:
            # In webtoon mode, group patches by page and apply them
            patches_by_page = {}
            for patch in patch_list:
                if 'page_index' in patch and 'file_path' in patch:
                    file_path = patch['file_path']
                    
                    if file_path not in patches_by_page:
                        patches_by_page[file_path] = []
                    
                    # Remove page-specific keys for the patch command but keep scene_pos for webtoon mode
                    clean_patch = {
                        'bbox': patch['bbox'],
                        'image': patch['image']
                    }
                    # Add scene position info for webtoon mode positioning
                    if 'scene_pos' in patch:
                        clean_patch['scene_pos'] = patch['scene_pos']
                        clean_patch['page_index'] = patch['page_index']
                    patches_by_page[file_path].append(clean_patch)
            
            # Apply patches to each page
            for file_path, patches in patches_by_page.items():
                self.main_page.image_ctrl.on_inpaint_patches_processed(patches, file_path)
        else:
            # Regular mode - original behavior
            self.main_page.apply_inpaint_patches(patch_list)
        
        self.main_page.image_viewer.clear_brush_strokes() 
        self.main_page.undo_group.activeStack().endMacro()  
        # get_best_render_area(self.main_page.blk_list, original_image, inpainted)    

    def get_inpainted_patches(self, mask: np.ndarray, inpainted_image: np.ndarray, original_image: np.ndarray = None):
        # slice mask into bounding boxes
        contours, _ = imk.find_contours(mask)
        patches = []
        # Handle webtoon mode vs regular mode
        if self.main_page.webtoon_mode:
            # In webtoon mode, we need to map patches back to their respective pages
            visible_image, mappings = self.main_page.image_viewer.get_visible_area_image()
            if visible_image is None or not mappings:
                return patches
                
            for i, c in enumerate(contours):
                x, y, w, h = imk.bounding_rect(c)
                patch_bottom = y + h
                
                # Extract the raw patch
                patch_img = inpainted_image[y:y+h, x:x+w].copy()

                # Find all pages that this patch overlaps with
                overlapping_mappings = []
                for mapping in mappings:
                    if (y < mapping['combined_y_end'] and patch_bottom > mapping['combined_y_start']):
                        overlapping_mappings.append(mapping)
                
                if not overlapping_mappings:
                    continue
                    
                # If patch spans multiple pages, clip and redistribute
                for mapping in overlapping_mappings:
                    # Calculate the intersection with this page
                    clip_top = max(y, mapping['combined_y_start'])
                    clip_bottom = min(patch_bottom, mapping['combined_y_end'])
                    
                    if clip_bottom <= clip_top:
                        continue
                        
                    # Extract the portion of the patch for this page
                    clipped_patch = inpainted_image[clip_top:clip_bottom, x:x+w]
                    # Convert coordinates back to page-local coordinates
                    page_local_y = clip_top - mapping['combined_y_start'] + mapping['page_crop_top']
                    clipped_height = clip_bottom - clip_top
                    
                    # Extract the portion of the blended patch for this page
                    page_patch = patch_img[clip_top-y : clip_bottom-y, :]

                    # Calculate the correct scene position
                    scene_y = mapping['scene_y_start'] + (clip_top - mapping['combined_y_start'])
                    
                    patches.append({
                        'bbox': [x, int(page_local_y), w, clipped_height],
                        'image': page_patch.copy(),
                        'page_index': mapping['page_index'],
                        'file_path': self.main_page.image_files[mapping['page_index']],
                        'scene_pos': [x, scene_y]
                    })
        else:
            # Regular mode - original behavior with blending
            for c in contours:
                x, y, w, h = imk.bounding_rect(c)
                patch_img = inpainted_image[y:y+h, x:x+w].copy()
                
                patches.append({
                    'bbox': [x, y, w, h],
                    'image': patch_img.copy(),
                })
                
        return patches
    
    def inpaint(self):
        mask = self.main_page.image_viewer.get_mask_for_inpainting()
        if self.main_page.webtoon_mode:
            image, _ = self.main_page.image_viewer.get_visible_area_image()
        else:
            image = self.main_page.image_viewer.get_image_array()
            
        painted = self.manual_inpaint()              
        patches = self.get_inpainted_patches(mask, painted, original_image=image)
        return patches
