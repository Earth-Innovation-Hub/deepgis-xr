# DeepGIS Label App Setup

This document provides instructions for setting up and using the DeepGIS Label App with database integration for image management.

## Overview

The DeepGIS Label App allows users to annotate images with various shapes (circles, ellipses, bezier curves) and categorize them. The app can now load images directly from a database, providing a more organized and scalable approach to image management.

## Setup Steps

### 1. Directory Structure

The app expects images to be organized in a specific directory structure:

```
static/
  images/
    label-set/
      navagunjara-ortho-set/  # Default image directory
        image_1.jpg
        image_2.jpg
        ...
```

### 2. Download Sample Images

We've provided a setup script to create the directory structure and download sample images:

```bash
# Make sure you're in the project root directory
cd deepgis-xr

# Create the script directory if it doesn't exist
mkdir -p scripts

# Run the setup script
python scripts/setup_label_images.py
```

### 3. Import Images to Database

After downloading the images, you need to import them into the database:

```bash
# Run the import command
python manage.py import_images --directory static/images/label-set/navagunjara-ortho-set/ --source "Sample Images" --path-prefix "https://deepgis.org/static/images/label-set/navagunjara-ortho-set/"
```

Options:
- `--directory`: The directory containing the images to import
- `--source`: A description of the image source (default: "import")
- `--path-prefix`: A URL or path prefix to add to the image paths in the database
- `--clean`: Remove database entries for images not found in the directory
- `--categories`: List of categories to assign to the imported images (default: Buildings, Roads, Vegetation, Water Bodies)

### 4. Start the Application

```bash
# Start the Django development server
python manage.py runserver 0.0.0.0:8090
```

### 5. Access the Label App

Open your browser and navigate to:
```
https://deepgis.org/label/
```

## Using the Label App

1. The app will load a random image from the database
2. Use the tools in the sidebar to annotate the image:
   - Circle: Click and drag to create a circle
   - Ellipse: Click and drag to create an ellipse
   - Bezier: Click to add points, click the first point to close the shape
3. Select a category for your annotation from the sidebar
4. Click "Submit Labels" when done
5. The app will load another image for labeling

## Managing Images

### Adding New Images

To add new images to the system:

1. Place the images in a directory
2. Run the import command:
   ```bash
   python manage.py import_images --directory /path/to/your/images/ --source "Your Source"
   ```

### Syncing with a Directory

To keep the database in sync with a directory (adding new images and removing deleted ones):

```bash
python manage.py import_images --directory /path/to/your/images/ --source "Your Source" --clean
```

### Admin Interface

You can also manage images through the Django admin interface:

1. Go to https://deepgis.org/admin/
2. Log in with an admin account
3. Navigate to "Images" under the "Core" section
4. Here you can add, edit, or delete images manually

## Troubleshooting

If images aren't loading properly:
1. Check that the image paths in the database are correct
2. Ensure the images are accessible from the web server
3. Check the browser console for any errors
4. Check the server logs for exceptions 