#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-Align Layers Plugin for GIMP 3.x

This plugin automatically aligns visible layers in a GIMP image based on a
user-defined selection. It uses the top-most visible layer as the "template"
and shifts the other visible layers to match the content within that selection.

The alignment is performed using a normalized cross-correlation algorithm to find
the best match, and it employs a two-pass (coarse-to-fine) search strategy
for a balance of speed and accuracy.
"""

import sys
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GLib, GObject, Gegl
import math

# ============================================================================
# ALIGNMENT SETTINGS - Modify these values to customize alignment behavior
# ============================================================================

# The maximum distance (in pixels) to search for a match from the initial position.
# A larger radius can find matches that are farther apart but will be slower.
SEARCH_RADIUS = 50

# The minimum similarity score (from 0.0 to 1.0) required to consider a match valid.
# Lowering this may help align layers with very different lighting or content,
# but increases the risk of a false positive (incorrect alignment).
MIN_OVERLAP = 0.5

# If True, the image canvas will be automatically resized to fit all layers
# after the alignment process is complete.
AUTO_FIT_CANVAS = True


class AutoAlignPlugin(Gimp.PlugIn):
    """
    The main GIMP PlugIn class that GIMP interacts with.
    """
    
    # ============================================================================
    # GIMP PlugIn Boilerplate and Registration
    # ============================================================================
    
    def do_set_i18n(self, procname):
        """Internationalization setup (not used in this simple plugin)."""
        return False
    
    def do_query_procedures(self):
        """Tells GIMP the names of the procedures this plugin provides."""
        # PDB procedure names must use hyphens (kebab-case), not underscores.
        return ["auto-align-layers"]

    def do_create_procedure(self, name):
        """Creates and configures the GIMP procedure for the plugin."""
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        
        # Set plugin properties
        procedure.set_image_types("*")  # Works on all image types
        procedure.set_menu_label("Auto-Align Layers From Selection")
        procedure.add_menu_path('<Image>/Filters/')
        
        # Set documentation for the GIMP Procedure Browser
        procedure.set_documentation(
            "Auto-align layers based on selection",
            "Automatically aligns layers based on current selection area.",
            name)
        procedure.set_attribution("Charon", "GPL 3", "2025")
        return procedure

    # ============================================================================
    # Core Logic Functions
    # ============================================================================

    def get_selection_bounds(self, image):
        """
        Gets the bounds of the current selection using a stable PDB call.
        The direct API for this has proven unreliable, so this is the safest method.
        """
        pdb = Gimp.get_pdb()
        procedure = pdb.lookup_procedure('gimp-selection-bounds')
        
        # Create a configuration object to pass arguments to the procedure
        config = procedure.create_config()
        config.set_property('image', image)
        
        # Run the procedure and get the results
        result = procedure.run(config)
        
        if result.index(0) == Gimp.PDBStatusType.SUCCESS:
            # The 'is_empty' flag (result.index(1)) is buggy and cannot be trusted.
            # We determine if a selection exists solely by its dimensions.
            x1, y1 = result.index(2), result.index(3)
            x2, y2 = result.index(4), result.index(5)
            
            # If the width and height are positive, we have a valid selection.
            if (x2 - x1) > 0 and (y2 - y1) > 0:
                # Return the bounds as (x, y, width, height)
                return x1, y1, x2 - x1, y2 - y1
        return None

    def extract_layer_data(self, layer, x, y, width, height):
        """
        Extracts pixel data from a specified region of a layer and converts
        it to a list of grayscale values for similarity comparison.
        """
        try:
            buffer = layer.get_buffer()
            rect = Gegl.Rectangle.new(x, y, width, height)
            
            # The GIMP 3 API for getting pixel data requires 5 arguments:
            # rect, scale, format, abyss_policy.
            pixel_format = "RGBA u8"
            bpp = 4  # Bytes per pixel for RGBA (Red, Green, Blue, Alpha)
            data_bytes = buffer.get(rect, 1.0, pixel_format, Gegl.AbyssPolicy.NONE)

            if not data_bytes: return None
            
            pixels = []
            # Iterate through the raw byte data, stepping by the bytes per pixel
            for i in range(0, len(data_bytes), bpp):
                r, g, b = data_bytes[i], data_bytes[i+1], data_bytes[i+2]
                # Convert RGB to a single grayscale value using the standard formula
                gray = int(0.299 * r + 0.587 * g + 0.114 * b)
                pixels.append(gray)
            return pixels, width, height
        except Exception as e:
            # If anything goes wrong, log it and return None
            Gimp.message(f"Error extracting layer data: {e}")
            return None

    def calculate_similarity(self, template_data, search_data):
        """
        Calculates the similarity between two sets of pixel data using
        Normalized Cross-Correlation. Returns a score from -1.0 to 1.0.
        """
        if not template_data or not search_data: return 0.0
        
        template_pixels, t_width, t_height = template_data
        search_pixels, s_width, s_height = search_data
        
        if t_width != s_width or t_height != s_height: return 0.0
        
        # Calculate the average pixel value (mean) for both datasets
        template_mean = sum(template_pixels) / len(template_pixels)
        search_mean = sum(search_pixels) / len(search_pixels)
        
        correlation, template_sq_sum, search_sq_sum = 0.0, 0.0, 0.0
        
        # This loop calculates the three main components of the NCC formula
        for t_val, s_val in zip(template_pixels, search_pixels):
            t_norm = t_val - template_mean
            s_norm = s_val - search_mean
            
            correlation += t_norm * s_norm
            template_sq_sum += t_norm * t_norm
            search_sq_sum += s_norm * s_norm
        
        # Avoid division by zero if an image is solid black or white
        if template_sq_sum == 0 or search_sq_sum == 0: return 0.0
        
        # The final NCC score
        return correlation / math.sqrt(template_sq_sum * search_sq_sum)

    def find_best_alignment(self, template_layer, target_layer, template_bounds):
        """
        Finds the best offset for the target_layer using a two-pass
        (coarse-to-fine) search strategy to maximize speed and accuracy.
        """
        template_x, template_y, template_width, template_height = template_bounds
        template_data = self.extract_layer_data(template_layer, template_x, template_y, template_width, template_height)
        if template_data is None: return 0, 0, 0.0
        
        # Get dimensions and offsets for coordinate calculations
        target_width, target_height = target_layer.get_width(), target_layer.get_height()
        # The get_offsets() method in GIMP 3 returns a 3-value tuple (success, x, y).
        # We use an underscore (_) to ignore the unneeded boolean value.
        _, target_offset_x, target_offset_y = target_layer.get_offsets()
        _, template_layer_offset_x, template_layer_offset_y = template_layer.get_offsets()
        
        # Convert the selection's top-left corner from image coordinates
        # to the target layer's local coordinate system.
        template_image_x = template_x + template_layer_offset_x
        template_image_y = template_y + template_layer_offset_y
        template_in_target_x = template_image_x - target_offset_x
        template_in_target_y = template_image_y - target_offset_y

        best_similarity = -1.0
        coarse_best_x, coarse_best_y = 0, 0

        # --- PASS 1: Coarse Search ---
        # Quickly scan the search area with large steps to find the approximate best location.
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
        
        # --- PASS 2: Fine Search ---
        # Perform a slow, precise search in a tiny area around the best coarse result.
        Gimp.message("Performing precise fine search...")
        best_offset_x, best_offset_y = 0, 0
        FINE_RADIUS = COARSE_STEP // 2
        
        search_start_x = max(0, int(coarse_best_x - FINE_RADIUS))
        search_end_x = min(target_width - template_width, int(coarse_best_x + FINE_RADIUS))
        search_start_y = max(0, int(coarse_best_y - FINE_RADIUS))
        search_end_y = min(target_height - template_height, int(coarse_best_y + FINE_RADIUS))

        for search_x in range(search_start_x, search_end_x + 1, 1): # Step size is 1 for full precision
            for search_y in range(search_start_y, search_end_y + 1, 1):
                search_data = self.extract_layer_data(target_layer, search_x, search_y, template_width, template_height)
                if search_data is not None:
                    similarity = self.calculate_similarity(template_data, search_data)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        # Calculate the final offset needed to move the target layer
                        best_offset_x = int(template_in_target_x - search_x)
                        best_offset_y = int(template_in_target_y - search_y)

        return best_offset_x, best_offset_y, best_similarity

    def fit_canvas_to_layers(self, image):
        """Resizes the canvas to fit the bounding box of all layers."""
        # GIMP 3 provides a simple, direct method for this.
        image.resize_to_layers()

    # ============================================================================
    # Main Plugin Execution
    # ============================================================================
    
    def run(self, procedure, run_mode, image, n_drawables, drawables, config):
        """
        The main entry point of the plugin, called by GIMP when the user
        runs the filter.
        """
        undo_group_started = False
        try:
            # --- Pre-condition Checks ---
            # Raise exceptions for user errors, which are caught by the except block.
            if n_drawables == 0:
                raise ValueError("Plugin requires an active layer.")

            selection_bounds = self.get_selection_bounds(image)
            if selection_bounds is None:
                raise ValueError("Please make a selection first to define the template area.")
            
            visible_layers = [layer for layer in image.get_layers() if layer.get_visible()]
            
            if len(visible_layers) < 2:
                raise ValueError("Need at least 2 visible layers to align.")
            
            # --- Main Logic ---
            Gimp.message(f"Aligning {len(visible_layers)} visible layers...")
            template_layer = visible_layers[0] # Topmost visible layer is the reference
            
            # Group all actions into a single "Undo" step in GIMP
            image.undo_group_start()
            undo_group_started = True # Flag that the group has started for safe cleanup
            
            alignments_made = 0
            # Iterate through all visible layers except the top one
            for target_layer in visible_layers[1:]:
                offset_x, offset_y, similarity = self.find_best_alignment(template_layer, target_layer, selection_bounds)
                
                if similarity > MIN_OVERLAP:
                    # Get the layer's current position
                    _, current_x, current_y = target_layer.get_offsets()
                    # Apply the calculated offset to move the layer
                    target_layer.set_offsets(current_x + offset_x, current_y + offset_y)
                    alignments_made += 1
                else:
                    Gimp.message(f"Low similarity ({similarity:.3f}) for layer '{target_layer.get_name()}', skipping.")
            
            # Resize canvas if enabled and if any layers were moved
            if AUTO_FIT_CANVAS and alignments_made > 0:
                Gimp.message("Fitting canvas to layers...")
                self.fit_canvas_to_layers(image)
            
            image.undo_group_end()
            Gimp.displays_flush() # Update the GIMP display to show the changes
            
            if alignments_made > 0:
                Gimp.message(f"Successfully aligned {alignments_made} layer(s).")
            else:
                Gimp.message("No layers could be aligned (similarity too low).")
            
            # Return a success status to GIMP
            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

        except Exception as e:
            # This is the central error handler for ANY failure in the script.
            # It ensures the plugin exits gracefully and informs the user.
            
            # If an error occurred after the undo group started, safely end it.
            if undo_group_started:
                try:
                    image.undo_group_end()
                except:
                    pass # Ignore cleanup errors, the primary error is more important

            # Display the error message in the GIMP Error Console
            Gimp.message(f"Auto-Align Layers error: {str(e)}")
            
            # Return a failure status to GIMP
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)

# ============================================================================
# Plugin Initialization
# ============================================================================

# This line is crucial for GIMP 3. It registers the Python class with the
# GObject type system so that GIMP can "see" and interact with it.
GObject.type_register(AutoAlignPlugin)

# This line starts the main GIMP plugin process, passing it the registered
# plugin type and command-line arguments.
Gimp.main(AutoAlignPlugin.__gtype__, sys.argv)