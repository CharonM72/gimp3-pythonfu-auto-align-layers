#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-Align Layers Plugin for GIMP 3.x
Automatically aligns layers based on content similarity using template matching
"""

import sys
import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp, GLib, GObject, Gio
import numpy as np
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# ALIGNMENT SETTINGS - Modify these values to customize alignment behavior
# ============================================================================

SEARCH_RADIUS = 50         # Maximum offset to search (+/- pixels) - reduced for your use case
STEP_SIZE = 1             # Pixel step size for search (1 = most accurate)
MIN_OVERLAP = 0.5         # Minimum overlap required between layers (0.0-1.0)
AUTO_FIT_CANVAS = True    # Automatically fit canvas to layers after alignment

class AutoAlignPlugin(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False
    
    def do_query_procedures(self):
        return ["auto-align-layers"]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self,
            name,
            Gimp.PDBProcType.PLUGIN,
            self.run,
            None,
        )
        procedure.set_image_types("*")
        procedure.set_menu_label("Auto-Align Layers")
        procedure.add_menu_path('<Image>/Layer/Align & Distribute/')
        procedure.set_documentation(
            "Auto-align layers based on selection",
            "Automatically aligns layers based on current selection area. Uses top visible layer as template, aligns others to match.",
            name
        )
        procedure.set_attribution("Assistant", "GPL 3", "2025")
        return procedure

    def get_selection_bounds(self, image):
        """Get the bounds of the current selection"""
        try:
            selection = image.get_selection()
            success, x1, y1, x2, y2 = selection.bounds()
            
            if success and (x2 - x1) > 0 and (y2 - y1) > 0:
                return x1, y1, x2 - x1, y2 - y1  # x, y, width, height
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error getting selection bounds: {e}")
            return None

    def extract_layer_data(self, layer, x, y, width, height):
        """Extract pixel data from a layer region"""
        try:
            # Get the drawable data
            success, data = layer.get_buffer().read_pixel_data(x, y, width, height, layer.get_buffer().get_format())
            if not success:
                return None
            
            # Convert to numpy array
            # Assuming RGBA format (4 bytes per pixel)
            pixel_array = np.frombuffer(data, dtype=np.uint8)
            if len(pixel_array) == width * height * 4:  # RGBA
                return pixel_array.reshape(height, width, 4)
            elif len(pixel_array) == width * height * 3:  # RGB
                return pixel_array.reshape(height, width, 3)
            else:
                logger.warning(f"Unexpected pixel data size: {len(pixel_array)}")
                return None
                
        except Exception as e:
            logger.error(f"Error extracting layer data: {e}")
            return None

    def calculate_similarity(self, template, search_region):
        """Calculate similarity between template and search region using normalized cross-correlation"""
        if template is None or search_region is None:
            return 0.0
        
        if template.shape != search_region.shape:
            return 0.0
        
        try:
            # Convert to grayscale for faster comparison
            if len(template.shape) == 3:
                template_gray = np.mean(template[:,:,:3], axis=2)  # Ignore alpha
                search_gray = np.mean(search_region[:,:,:3], axis=2)
            else:
                template_gray = template
                search_gray = search_region
            
            # Normalize
            template_norm = template_gray - np.mean(template_gray)
            search_norm = search_gray - np.mean(search_gray)
            
            # Calculate correlation coefficient
            correlation = np.sum(template_norm * search_norm)
            template_energy = np.sum(template_norm ** 2)
            search_energy = np.sum(search_norm ** 2)
            
            if template_energy == 0 or search_energy == 0:
                return 0.0
            
            return correlation / np.sqrt(template_energy * search_energy)
            
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.0

    def find_best_alignment(self, template_layer, target_layer, template_bounds):
        """Find the best alignment offset for target_layer relative to template_layer using selection"""
        
        template_x, template_y, template_width, template_height = template_bounds
        
        logger.info(f"Using selection as template: ({template_x}, {template_y}) {template_width}x{template_height}")
        
        # Extract template from the selected area on template layer
        template = self.extract_layer_data(template_layer, template_x, template_y, 
                                         template_width, template_height)
        
        if template is None:
            logger.error("Failed to extract template from selection")
            return 0, 0, 0.0
        
        # Get target layer dimensions
        target_width = target_layer.get_width()
        target_height = target_layer.get_height()
        target_offset_x, target_offset_y = target_layer.get_offsets()
        
        # Search for best match in target layer
        best_similarity = -1.0
        best_offset_x = 0
        best_offset_y = 0
        
        # Calculate search bounds on target layer
        # Convert template position to target layer coordinate space
        template_layer_offset_x, template_layer_offset_y = template_layer.get_offsets()
        
        # Template position in image coordinates
        template_image_x = template_x + template_layer_offset_x
        template_image_y = template_y + template_layer_offset_y
        
        # Convert to target layer coordinates
        template_in_target_x = template_image_x - target_offset_x
        template_in_target_y = template_image_y - target_offset_y
        
        search_start_x = max(0, template_in_target_x - SEARCH_RADIUS)
        search_end_x = min(target_width - template_width, template_in_target_x + SEARCH_RADIUS)
        search_start_y = max(0, template_in_target_y - SEARCH_RADIUS)
        search_end_y = min(target_height - template_height, template_in_target_y + SEARCH_RADIUS)
        
        logger.info(f"Searching target layer area: x={search_start_x:.0f}-{search_end_x:.0f}, y={search_start_y:.0f}-{search_end_y:.0f}")
        
        search_count = 0
        for search_x in range(int(search_start_x), int(search_end_x) + 1, STEP_SIZE):
            for search_y in range(int(search_start_y), int(search_end_y) + 1, STEP_SIZE):
                search_region = self.extract_layer_data(target_layer, search_x, search_y,
                                                      template_width, template_height)
                
                if search_region is not None:
                    similarity = self.calculate_similarity(template, search_region)
                    search_count += 1
                    
                    if similarity > best_similarity:
                        best_similarity = similarity
                        # Calculate how much to move target layer
                        best_offset_x = template_in_target_x - search_x
                        best_offset_y = template_in_target_y - search_y
        
        logger.info(f"Searched {search_count} positions, best similarity: {best_similarity:.3f}")
        logger.info(f"Best offset: ({best_offset_x}, {best_offset_y})")
        
        return best_offset_x, best_offset_y, best_similarity

    def fit_canvas_to_layers(self, image):
        """Fit canvas size to accommodate all layers - equivalent to Image > Fit Canvas to Layers"""
        try:
            # Get all layers
            layers = image.get_layers()
            if not layers:
                return
            
            # Find the bounding box of all layers
            min_x = float('inf')
            min_y = float('inf')
            max_x = float('-inf')
            max_y = float('-inf')
            
            for layer in layers:
                layer_x, layer_y = layer.get_offsets()
                layer_width = layer.get_width()
                layer_height = layer.get_height()
                
                layer_right = layer_x + layer_width
                layer_bottom = layer_y + layer_height
                
                min_x = min(min_x, layer_x)
                min_y = min(min_y, layer_y)
                max_x = max(max_x, layer_right)
                max_y = max(max_y, layer_bottom)
            
            # Calculate new canvas size and offset
            new_width = int(max_x - min_x)
            new_height = int(max_y - min_y)
            offset_x = -int(min_x)
            offset_y = -int(min_y)
            
            logger.info(f"Fitting canvas: size=({new_width}, {new_height}), offset=({offset_x}, {offset_y})")
            
            # Resize canvas and adjust layer positions
            if offset_x != 0 or offset_y != 0:
                # First move all layers to account for the offset
                for layer in layers:
                    current_x, current_y = layer.get_offsets()
                    layer.set_offsets(current_x + offset_x, current_y + offset_y)
            
            # Resize the image
            image.resize(new_width, new_height, 0, 0)
            
            logger.info("Canvas fitted to layers")
            
        except Exception as e:
            logger.error(f"Error fitting canvas to layers: {e}")
            Gimp.message(f"Warning: Could not fit canvas to layers: {str(e)}")

    def run(self, procedure, run_mode, image, drawable, parameters, run_data):
        try:
            # Check if there's a selection
            selection_bounds = self.get_selection_bounds(image)
            if selection_bounds is None:
                Gimp.message("Please make a selection first to define the template area")
                return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, None)
            
            # Get all visible layers
            layers = image.get_layers()
            visible_layers = [layer for layer in layers if layer.get_visible()]
            
            if len(visible_layers) < 2:
                Gimp.message("Need at least 2 visible layers to align")
                return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, None)
            
            logger.info(f"Found {len(visible_layers)} visible layers")
            Gimp.message(f"Aligning {len(visible_layers)} visible layers using selection...")
            
            # Use the top-most visible layer as template (first in list)
            template_layer = visible_layers[0]
            logger.info(f"Using '{template_layer.get_name()}' as template layer")
            
            # Start undo group
            image.undo_group_start()
            
            alignments_made = 0
            
            # Align each other layer to the template
            for i, target_layer in enumerate(visible_layers[1:], 1):  # Skip template layer
                logger.info(f"Aligning layer '{target_layer.get_name()}'...")
                Gimp.message(f"Aligning layer {i}/{len(visible_layers)-1}...")
                
                # Find best alignment using selection as template
                offset_x, offset_y, similarity = self.find_best_alignment(
                    template_layer, target_layer, selection_bounds)
                
                if similarity > MIN_OVERLAP:
                    # Apply the offset
                    current_x, current_y = target_layer.get_offsets()
                    new_x = current_x + offset_x
                    new_y = current_y + offset_y
                    
                    target_layer.set_offsets(new_x, new_y)
                    alignments_made += 1
                    
                    logger.info(f"Aligned '{target_layer.get_name()}' with similarity {similarity:.3f}")
                    logger.info(f"Moved from ({current_x}, {current_y}) to ({new_x}, {new_y})")
                else:
                    logger.warning(f"Low similarity ({similarity:.3f}) for '{target_layer.get_name()}', skipping")
            
            # Fit canvas to layers if enabled
            if AUTO_FIT_CANVAS and alignments_made > 0:
                logger.info("Fitting canvas to layers...")
                Gimp.message("Fitting canvas to layers...")
                self.fit_canvas_to_layers(image)
            
            # End undo group
            image.undo_group_end()
            
            # Update display
            Gimp.displays_flush()
            
            if alignments_made > 0:
                canvas_msg = " and fitted canvas" if AUTO_FIT_CANVAS else ""
                Gimp.message(f"Successfully aligned {alignments_made} layer(s){canvas_msg}")
                logger.info(f"Alignment complete: {alignments_made} layers aligned")
            else:
                Gimp.message("No layers could be aligned (similarity too low)")
                logger.warning("No alignments made - check similarity threshold")
            
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
            
        except Exception as e:
            if 'image' in locals():
                image.undo_group_end()
            Gimp.message(f"Auto-align error: {str(e)}")
            logger.error(f"Auto-align error: {str(e)}", exc_info=True)
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)

Gimp.main(AutoAlignPlugin.__gtype__, sys.argv)