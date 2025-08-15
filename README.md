# GIMP 3 Python-Fu: Auto-Align Layers

A GIMP 3 plugin that automatically aligns a stack of layers based on a user-defined selection. It uses the top-most visible layer as the "template" and intelligently shifts the other visible layers to match the content within the selection.

This is ideal for tasks like stacking exposures, aligning hand-drawn animation frames, or correcting drift in scanned images.

**DISCLAIMER**: This was almost entirely vibe-coded with the help of Claude and Gemini. But hey, it works.

## Features

-   **Selection-Based Alignment:** Uses a small, user-defined area as the reference point for high precision.
-   **Multi-Layer Support:** Aligns all visible layers below the top-most visible layer.
-   **Robust Matching:** Employs a normalized cross-correlation algorithm to find the best match, even with slight variations in brightness.
-   **Fast Two-Pass Search:** Uses a "coarse-to-fine" search strategy to provide a great balance between speed and accuracy.
-   **Automatic Canvas Resizing:** Optionally fits the canvas to the newly aligned layers after the operation.

## How It Works

The plugin's logic is straightforward:
1.  It identifies the **top-most visible layer** in your layer stack. This layer is considered the "correct" reference.
2.  It takes the pixel data from the area you have **selected** on this top layer.
3.  For every other **visible layer**, it searches for the area that best matches the selection from the reference layer.
4.  Once the best match is found, it calculates the required offset and shifts the layer to align it perfectly.

## Installation

1.  Download the `auto_align_layers.py` script.
2.  Open GIMP and go to `Edit > Preferences > Folders > Plug-ins`.
3.  You will see two folder paths. Choose the one in your user directory (e.g., `C:\Users\YourUser\AppData\Roaming\GIMP\3.0\plug-ins`).
4.  Copy the `auto_align_layers.py` file into that folder.
5.  Restart GIMP.

## How to Use

1.  Load all your layers into a single GIMP image.
2.  Arrange the layers so that the "template" or reference layer is at the very top of the layer stack.
3.  Ensure that the reference layer and all the layers you want to align are visible (the "eye" icon is on). Hide any layers you want to exclude from the process.
4.  Using any selection tool (like the Rectangle Select Tool), **draw a small box** around a distinct, high-contrast feature that is present across all layers.
5.  Go to the menu `Filters > Auto-Align Layers`.
6.  The plugin will process each layer and shift it into position.

## Important Caveats & Best Practices

Understanding these limitations will help you get the best results.

### 1. Selection Size is CRITICAL for Speed
The plugin's speed is directly related to the size of your selection. The alignment algorithm compares every pixel in your selection against thousands of possible locations.

-   **A small selection is exponentially faster than a large one.**
-   For the best performance, **use the smallest selection possible** that still contains a unique feature. A 50x50 pixel box is vastly faster than a 500x500 one.

### 2. Choose a Unique and Complex Area
The algorithm needs a good reference point to work with.

-   **GOOD selections:** High-contrast corners, text, distinct markings, an eye on a portrait, or any area with sharp, unique details.
-   **BAD selections:** Smooth gradients, blurry sky, solid colors, or repeating patterns. The plugin will struggle to find a unique match in these areas.

### 3. The `SEARCH_RADIUS` Limit
The plugin does not search the entire image for a match, as that would be incredibly slow. Instead, it searches in a square area around the initial position of the selection.

-   This area is defined by the `SEARCH_RADIUS` variable at the top of the `.py` script (default is 50 pixels).
-   This means if a layer is offset by **more than 50 pixels** horizontally or vertically, the plugin will not find the match. If your layers are very far apart, you will need to increase this value.

### 4. Alignment Target
The plugin aligns **all other visible layers** to match the **top-most visible layer**. It will not move the top layer. The order of the layers below the top one does not matter.

## Configuration

You can fine-tune the plugin's behavior by editing the settings at the top of the `auto_align_layers.py` file with a text editor.

| Variable        | Description                                                                                                                              |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `SEARCH_RADIUS` | The maximum distance (in pixels) to search for a match. Increase this if your layers have a large initial offset.                        |
| `MIN_OVERLAP`   | The minimum similarity score (0.0 to 1.0) required to consider a match valid. Lowering this may help with noisy images but risks bad matches. |
| `AUTO_FIT_CANVAS` | Set to `True` or `False`. When `True`, the canvas is resized to fit all layers after alignment.                                          |

## License

This plugin is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html).