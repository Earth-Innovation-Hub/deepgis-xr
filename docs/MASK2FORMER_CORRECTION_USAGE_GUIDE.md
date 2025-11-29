# Mask2Former Correction Interface - Usage Guide

## Overview

The correction interface allows you to edit Mask2Former predictions and add them to training datasets for model retraining.

## Getting Started

1. **Open a Mask2Former Analysis Report**
   - Navigate to an AI analysis report for a Mask2Former prediction
   - Click the **"Correct Predictions & Add to Training Dataset"** button

2. **Correction Panel Opens**
   - A sidebar panel appears on the right side
   - Predictions are displayed as colored polygons on the Cesium viewer
   - A list of predictions appears in the panel

---

## Edit Tools

### 0. **Draw New Polygon (Add Missing Objects)**

**To activate draw mode:**
1. **Select a category** from the "Categories" list first (required)
2. Click the **"Draw Polygon"** button
3. The button will turn green (active state)
4. Status message: "Draw mode ON"

**How to draw:**
1. **Click on the map** to add the first point
   - A yellow point marker appears
   - Status message updates
   
2. **Click again** to add more points
   - Each click adds a new point
   - A preview polygon shows the shape being drawn
   
3. **Right-click** to finish the polygon
   - Polygon must have at least 3 points
   - The new polygon is added as a new annotation
   - It appears in the predictions list
   
4. **To cancel:**
   - Click "Draw Polygon" again to deactivate
   - Or start drawing a new polygon (cancels the previous one)

**Tips:**
- You can add new polygons for objects that Mask2Former missed
- Each new polygon uses the currently selected category
- New polygons are saved along with corrected predictions
- Use this to add manual annotations to your training dataset

---

### 1. **Select a Prediction**

**Method 1: Click in the list**
- Click on any prediction in the "Predictions" list
- The selected prediction will be highlighted in **cyan** on the map
- The viewer will automatically fly to the selected prediction

**Method 2: Click on the map** (when in edit mode)
- Click directly on a polygon on the map
- The polygon will be highlighted

---

### 2. **Edit Mask (Polygon Vertices)**

**To activate edit mode:**
1. Click the **"Edit Mask"** button in the tool buttons section
2. The button will turn blue (active state)
3. Status message: "Edit mode ON"

**How to edit:**
1. **Click on a polygon** to start editing it
   - Yellow edit points (vertices) will appear
   - The polygon outline turns yellow
   
2. **Drag vertices** to reshape the polygon
   - Click and drag any yellow vertex point
   - The polygon updates in real-time
   
3. **Add a vertex:**
   - **Double-click** on an edge where you want to add a new vertex
   - A new yellow vertex point appears
   
4. **Delete a vertex:**
   - **Right-click** on a yellow vertex point
   - The vertex is removed (minimum 3 vertices required)
   
5. **Stop editing:**
   - Click the **"Edit Mask"** button again to deactivate
   - Or click on a different polygon
   - Or click on empty space

**Tips:**
- Changes are automatically saved to the undo stack
- You can undo/redo edits using the Undo/Redo buttons
- The polygon must have at least 3 vertices

---

### 3. **Change Category**

**Steps:**
1. **Select a prediction** (click it in the list or on the map)
2. **Select a category** from the "Categories" list
   - Click on any category in the categories section
   - Selected category will be highlighted
3. **Click "Change Category"** button
   - The prediction's category is updated
   - The polygon color changes to match the new category
   - Success message appears

**Note:** You must select both a prediction AND a category before clicking "Change Category"

---

### 4. **Delete Prediction**

**Steps:**
1. **Select a prediction** (click it in the list)
2. **Click "Delete"** button
3. **Confirm deletion** in the popup dialog
4. The prediction is removed from the map and list

**Warning:** This action cannot be undone (unless you use the Undo button immediately)

---

### 5. **Undo / Redo**

**Undo:**
- Click the **"Undo"** button to reverse the last action
- Works for: edits, category changes, deletions

**Redo:**
- Click the **"Redo"** button to reapply an undone action
- Only available after undoing something

**Limitations:**
- Undo/redo only works within the current session
- Closing the panel clears the undo/redo history

---

### 6. **Clear All Corrections**

**Steps:**
1. Click the **"Clear All"** button at the bottom
2. Confirm in the popup dialog
3. All predictions reset to their original state
4. All undo/redo history is cleared

**Use case:** Start over if you made too many mistakes

---

## Training Dataset Management

### Select or Create Dataset

1. **Select existing dataset:**
   - Use the dropdown at the top of the panel
   - Shows: "Dataset Name (X annotations)"

2. **Create new dataset:**
   - Click **"New Dataset"** button
   - Enter dataset name
   - Optionally enter description
   - New dataset is automatically selected

---

## Saving Corrections

**Steps:**
1. Make your corrections (edit masks, change categories, delete false positives)
2. **Select a training dataset** from the dropdown
3. Click **"Save Corrections"** button
4. Wait for success message
5. Panel closes automatically after 2 seconds

**What gets saved:**
- All corrected predictions as GeoJSON
- Link to the training dataset
- Source prediction session ID
- List of corrections made

**After saving:**
- Corrections are stored in the database
- Can be used for model training
- View in Django admin under "Training Labels"

---

## Visual Indicators

### Colors:
- **White outline**: Normal prediction
- **Cyan outline**: Selected prediction
- **Yellow outline**: Currently being edited
- **Yellow points**: Editable vertices (in edit mode)

### Status Messages:
- **Blue (info)**: Instructions and tips
- **Green (success)**: Actions completed successfully
- **Red (error)**: Something went wrong
- **Yellow (loading)**: Operation in progress

---

## Keyboard Shortcuts

Currently, keyboard shortcuts are not implemented. All actions use mouse clicks.

---

## Tips & Best Practices

1. **Work systematically:**
   - Select one prediction at a time
   - Make all corrections to it before moving to the next

2. **Use categories wisely:**
   - Select category BEFORE clicking "Change Category"
   - Categories are loaded from your database

3. **Edit mode:**
   - Only one polygon can be edited at a time
   - Click "Edit Mask" again to exit edit mode
   - Changes are saved to undo stack automatically

4. **Save frequently:**
   - Save after making corrections to a batch of predictions
   - You can reopen the panel and continue editing

5. **Check your work:**
   - Review predictions in the list
   - Verify categories are correct
   - Ensure polygon shapes match the objects

---

## Troubleshooting

### "Please select a prediction first"
- Click on a prediction in the list or on the map
- The selected prediction should have a cyan outline

### "Please select a category first"
- Click on a category in the "Categories" section
- Selected category will be highlighted

### Edit points not appearing
- Make sure "Edit Mask" button is active (blue)
- Click directly on the polygon, not just near it

### Can't delete vertex
- Polygon must have at least 3 vertices
- Right-click directly on the yellow vertex point

### Changes not saving
- Make sure a training dataset is selected
- Check for error messages in the status area
- Verify you're logged in (required for saving)

---

## Technical Details

- **Edit points**: Yellow spheres that appear on polygon vertices
- **Vertex manipulation**: Drag to move, double-click edge to add, right-click to delete
- **Undo system**: Stores entity state before each modification
- **GeoJSON conversion**: Automatically converts Cesium entities to GeoJSON format
- **API endpoint**: Uses `/label/semi-supervised/api/save-labels/` with training dataset parameters

---

## Next Steps After Saving

1. **View in Admin:**
   - Go to Django admin
   - Navigate to "Training Labels"
   - See your saved corrections

2. **Prepare for Training:**
   - Collect multiple corrected predictions
   - Ensure dataset has enough annotations
   - Use training dataset management interface

3. **Train Model:**
   - Use the training API endpoints
   - Fine-tune Mask2Former with your corrections
   - Deploy new model version

