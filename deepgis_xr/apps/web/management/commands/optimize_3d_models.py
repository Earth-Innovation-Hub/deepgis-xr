from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Optimize 3D models (GLTF/GLB) for web delivery'

    def add_arguments(self, parser):
        parser.add_argument(
            '--models-dir',
            default='deepgis/static/deepgis/models/gltf',
            help='Directory containing models to optimize (relative to STATIC_ROOT)'
        )
        parser.add_argument(
            '--compress',
            action='store_true',
            help='Apply Draco compression'
        )
        parser.add_argument(
            '--lod',
            action='store_true',
            help='Generate LOD variants'
        )
        parser.add_argument(
            '--textures',
            action='store_true',
            help='Optimize textures'
        )
        parser.add_argument(
            '--quality',
            type=int,
            default=10,
            help='Texture quality (1-100)'
        )
        parser.add_argument(
            '--model',
            help='Process a specific model file only'
        )

    def handle(self, *args, **options):
        # Check for static root
        if not hasattr(settings, 'STATIC_ROOT') or not settings.STATIC_ROOT:
            raise CommandError("STATIC_ROOT must be configured in your settings")

        # Get the absolute path to the models directory
        models_dir = Path(settings.STATIC_ROOT) / options['models_dir']
        
        # Create if not exists
        os.makedirs(models_dir, exist_ok=True)

        # Check if models directory exists
        if not models_dir.exists() or not models_dir.is_dir():
            raise CommandError(f"Models directory not found: {models_dir}")

        # Get path to optimizer script
        script_dir = Path(__file__).resolve().parent.parent.parent / 'scripts'
        optimizer_script = script_dir / 'optimize_gltf.py'

        # Check if optimizer script exists
        if not optimizer_script.exists():
            raise CommandError(f"Optimizer script not found: {optimizer_script}")

        # Make optimizer script executable
        os.chmod(optimizer_script, 0o755)

        self.stdout.write(self.style.SUCCESS(f"Starting model optimization in {models_dir}"))

        # Find models to process
        if options['model']:
            # Process a specific model file
            model_path = models_dir / options['model']
            if not model_path.exists():
                raise CommandError(f"Model file not found: {model_path}")
            models = [model_path]
        else:
            # Find all GLTF files in the models directory
            models = list(models_dir.glob("**/*.gltf"))
            # Also include GLB files if there are any
            models.extend(list(models_dir.glob("**/*.glb")))

        if not models:
            self.stdout.write(self.style.WARNING("No GLTF/GLB models found for optimization"))
            return

        processed = 0
        errors = 0

        # Process each model
        for model in models:
            # Skip already optimized models
            if "_LOD" in model.name or "_optimized" in model.name:
                self.stdout.write(f"Skipping already optimized model: {model.name}")
                continue

            try:
                self.stdout.write(f"Processing: {model.relative_to(settings.STATIC_ROOT)}")

                # Prepare output filename
                if model.suffix.lower() == '.gltf':
                    output_file = model.with_name(f"{model.stem}.glb")
                else:
                    output_file = model.with_name(f"{model.stem}_optimized{model.suffix}")

                # Build command
                cmd = [
                    str(optimizer_script),
                    str(model),
                    '--output', str(output_file),
                    '--quality', str(options['quality']),
                ]

                if options['compress']:
                    cmd.append('--compress')
                if options['lod']:
                    cmd.append('--lod')
                if options['textures']:
                    cmd.append('--optimize-textures')

                # Run the optimizer
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    self.stdout.write(self.style.SUCCESS(f"Optimized: {model.name} → {output_file.name}"))
                    processed += 1
                else:
                    self.stdout.write(self.style.ERROR(f"Error optimizing {model.name}: {result.stderr}"))
                    errors += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {model.name}: {str(e)}"))
                errors += 1

        # Summary
        if processed > 0:
            self.stdout.write(self.style.SUCCESS(f"Successfully optimized {processed} models"))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f"Failed to optimize {errors} models"))

        if options['lod']:
            self.stdout.write(self.style.SUCCESS(
                "LOD variants created. To use them in your templates, update the model path to include _LOD0, _LOD1, etc."
            ))

        # Deploy instructions
        self.stdout.write("\nNext steps:")
        self.stdout.write("1. Run `python manage.py collectstatic` to update your static files")
        self.stdout.write("2. Update your templates to use the optimized .glb files")
        self.stdout.write("3. Configure your web server with compression and caching headers")
        self.stdout.write("   Example for nginx:")
        self.stdout.write("   location ~* \\.glb$ {")
        self.stdout.write("       expires 30d;")
        self.stdout.write("       add_header Cache-Control \"public, max-age=2592000\";")
        self.stdout.write("       gzip_static on;")
        self.stdout.write("   }") 