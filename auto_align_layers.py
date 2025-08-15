#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-Align Layers Plugin for GIMP 3.x
(Final Production Version)
"""

import sys
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject, Gegl
import math

# ============================================================================
# ALIGNMENT SETTINGS
# ============================================================================
SEARCH_RADIUS = 50
STEP_SIZE = 1
MIN_OVERLAP = 0.5
AUTO_FIT_CANVAS = True

class AutoAlignPlugin(Gimp.PlugIn):
    def do_set_i18n(self, procname):
        return False
    
    def do_query_procedures(self):
        return ["auto-align-layers"]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("*")
        procedure.set_menu_label("Auto-Align Layers")
        procedure.add_menu_path('<Image>/Filters/')
        procedure.set_documentation(
            "Auto-align layers based on selection",
            "Automatically aligns layers based on current selection area.",
            name)
        procedure.set_attribution("Charon", "GPL 3", "2025")
        return procedure

    def get_selection_bounds(self, image):
        pdb = Gimp.get_pdb()
        procedure = pdb.lookup_procedure('gimp-selection-bounds')
        config = procedure.create_config()
        config.set_property('image', image)
        result = procedure.run(config)
        
        if result.index(0) == Gimp.PDBStatusType.SUCCESS:
            x1, y1 = result.index(2), result.index(3)
            x2, y2 = result.index(4), result.index(5)
            
            if (x2 - x1) > 0 and (y2 - y1) > 0:
                return x1, y1, x2 - x1, y2 - y1
        return None

    def extract_layer_data(self, layer, x, y, width, height):
        buffer = layer.get_buffer()
        rect = Gegl.Rectangle.new(x, y, width, height)
        pixel_format = "RGBA u8"
        bpp = 4
        data_bytes = buffer.get(rect, 1.0, pixel_format, Gegl.AbyssPolicy.NONE)

        if not data_bytes: return None
        
        pixels = []
        for i in range(0, len(data_bytes), bpp):
            r, g, b = data_bytes[i], data_bytes[i+1], data_bytes[i+2]
            gray = int(0.299 * r + 0.587 * g + 0.114 * b)
            pixels.append(gray)
        return pixels, width, height

    def calculate_similarity(self, template_data, search_data):
        if not template_data or not search_data: return 0.0
        template_pixels, t_width, t_height = template_data
        search_pixels, s_width, s_height = search_data
        if t_width != s_width or t_height != s_height: return 0.0
        
        template_mean = sum(template_pixels) / len(template_pixels)
        search_mean = sum(search_pixels) / len(search_pixels)
        correlation, template_sq_sum, search_sq_sum = 0.0, 0.0, 0.0
        
        for t_val, s_val in zip(template_pixels, search_pixels):
            t_norm = t_val - template_mean
            s_norm = s_val - search_mean
            correlation += t_norm * s_norm
            template_sq_sum += t_norm * t_norm
            search_sq_sum += s_norm * s_norm
        
        if template_sq_sum == 0 or search_sq_sum == 0: return 0.0
        return correlation / math.sqrt(template_sq_sum * search_sq_sum)

    def find_best_alignment(self, template_layer, target_layer, template_bounds):
        template_x, template_y, template_width, template_height = template_bounds
        template_data = self.extract_layer_data(template_layer, template_x, template_y, template_width, template_height)
        if template_data is None: return 0, 0, 0.0
        
        target_width, target_height = target_layer.get_width(), target_layer.get_height()
        _, target_offset_x, target_offset_y = target_layer.get_offsets()
        _, template_layer_offset_x, template_layer_offset_y = template_layer.get_offsets()
        
        template_image_x = template_x + template_layer_offset_x
        template_image_y = template_y + template_layer_offset_y
        template_in_target_x = template_image_x - target_offset_x
        template_in_target_y = template_image_y - target_offset_y

        best_similarity = -1.0
        coarse_best_x, coarse_best_y = 0, 0

        # --- PASS 1: Coarse Search with large steps ---
        Gimp.message("Performing quick coarse search...")
        COARSE_STEP = 8
        search_start_x = max(0, int(template_in_target_x - SEARCH_RADIUS))
        search_end_x = min(target_width - template_width, int(template_in_target_x + SEARCH_RADIUS))
        search_start_y = max(0, int(template_in_target_y - SEARCH_RADIUS))
        search_end_y = min(target_height - template_height, int(template_in_target_y + SEARCH_RADIUS))

        for search_x in range(search_start_x, search_end_x + 1, COARSE_STEP):
            for search_y in range(search_start_y, search_end_y + 1, COARSE_STEP):
                search_data = self.extract_layer_data(target_layer, search_x, search_y, template_width, template_height)
                if search_data is not None:
                    similarity = self.calculate_similarity(template_data, search_data)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        coarse_best_x = search_x
                        coarse_best_y = search_y
        
        # --- PASS 2: Fine Search around the best coarse point ---
        Gimp.message("Performing precise fine search...")
        best_offset_x, best_offset_y = 0, 0
        FINE_RADIUS = COARSE_STEP // 2 # Search in a small box around the coarse result
        
        search_start_x = max(0, int(coarse_best_x - FINE_RADIUS))
        search_end_x = min(target_width - template_width, int(coarse_best_x + FINE_RADIUS))
        search_start_y = max(0, int(coarse_best_y - FINE_RADIUS))
        search_end_y = min(target_height - template_height, int(coarse_best_y + FINE_RADIUS))

        for search_x in range(search_start_x, search_end_x + 1, 1): # Step size is now 1
            for search_y in range(search_start_y, search_end_y + 1, 1):
                search_data = self.extract_layer_data(target_layer, search_x, search_y, template_width, template_height)
                if search_data is not None:
                    similarity = self.calculate_similarity(template_data, search_data)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_offset_x = int(template_in_target_x - search_x)
                        best_offset_y = int(template_in_target_y - search_y)

        return best_offset_x, best_offset_y, best_similarity

    def fit_canvas_to_layers(self, image):
        image.resize_to_layers()

    def run(self, procedure, run_mode, image, n_drawables, drawables, config):
        undo_group_started = False
        try:
            if n_drawables == 0:
                raise ValueError("Plugin requires an active layer.")

            selection_bounds = self.get_selection_bounds(image)
            if selection_bounds is None:
                raise ValueError("Please make a selection first to define the template area.")
            
            visible_layers = [layer for layer in image.get_layers() if layer.get_visible()]
            
            if len(visible_layers) < 2:
                raise ValueError("Need at least 2 visible layers to align.")
            
            Gimp.message(f"Aligning {len(visible_layers)} visible layers...")
            template_layer = visible_layers[0]
            
            image.undo_group_start()
            undo_group_started = True
            
            alignments_made = 0
            for target_layer in visible_layers[1:]:
                offset_x, offset_y, similarity = self.find_best_alignment(template_layer, target_layer, selection_bounds)
                if similarity > MIN_OVERLAP:
                    # DEFINITIVE FIX: Unpack the 3-value tuple here as well before setting new offsets
                    _, current_x, current_y = target_layer.get_offsets()
                    target_layer.set_offsets(current_x + offset_x, current_y + offset_y)
                    alignments_made += 1
                else:
                    Gimp.message(f"Low similarity ({similarity:.3f}) for layer '{target_layer.get_name()}', skipping.")
            
            if AUTO_FIT_CANVAS and alignments_made > 0:
                Gimp.message("Fitting canvas to layers...")
                self.fit_canvas_to_layers(image)
            
            image.undo_group_end()
            Gimp.displays_flush()
            
            if alignments_made > 0:
                Gimp.message(f"Successfully aligned {alignments_made} layer(s).")
            else:
                Gimp.message("No layers could be aligned (similarity too low).")
            
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

        except Exception as e:
            if undo_group_started:
                try:
                    image.undo_group_end()
                except:
                    pass

            Gimp.message(f"Auto-Align Layers error: {str(e)}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)
        
GObject.type_register(AutoAlignPlugin)

Gimp.main(AutoAlignPlugin.__gtype__, sys.argv)