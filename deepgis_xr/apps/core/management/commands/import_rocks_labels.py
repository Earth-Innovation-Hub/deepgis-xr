import csv
import json
from datetime import datetime
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from deepgis_xr.apps.core.models import TiledGISLabel, CategoryType, Labeler, RasterImage


class Command(BaseCommand):
    help = 'Import TiledGISLabel data from CSV file (rocks dataset)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-file',
            type=str,
            required=True,
            help='Path to CSV file containing TiledGISLabel data'
        )
        parser.add_argument(
            '--category-name',
            type=str,
            default='Rock',
            help='Category name for the labels (default: Rock)'
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip labels that already exist (by id)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of labels to import in each batch (default: 1000)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually importing'
        )

    def handle(self, *args, **options):
        csv_file = Path(options['csv_file'])
        category_name = options['category_name']
        skip_existing = options['skip_existing']
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        if not csv_file.exists():
            raise CommandError(f'CSV file not found: {csv_file}')

        self.stdout.write(self.style.SUCCESS(f'Reading CSV file: {csv_file}'))

        # Get or create category
        category, created = CategoryType.objects.get_or_create(category_name=category_name)
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created category: {category_name}'))
        else:
            self.stdout.write(f'Using existing category: {category_name}')

        # Get or create a default labeler
        # Labeler requires a user, so we need to get/create a system user
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Try to get an existing user, or create a system user for imports
        try:
            system_user = User.objects.filter(is_superuser=True).first()
            if not system_user:
                system_user = User.objects.first()
        except:
            system_user = None
            
        if system_user:
            labeler, _ = Labeler.objects.get_or_create(user=system_user)
        else:
            self.stdout.write(self.style.WARNING(
                'No user found. Labels will be created without a labeler.'
            ))
            labeler = None

        # Read CSV and import labels
        imported_count = 0
        skipped_count = 0
        error_count = 0

        with open(csv_file, 'r', encoding='utf-8') as f:
            # Try to detect delimiter
            sample = f.read(1024)
            f.seek(0)
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(sample).delimiter

            reader = csv.DictReader(f, delimiter=delimiter)
            
            # Validate required columns
            required_columns = ['northeast_Lat', 'northeast_Lng', 'southwest_Lat', 'southwest_Lng', 
                              'label_json', 'geometry']
            missing_columns = [col for col in required_columns if col not in reader.fieldnames]
            if missing_columns:
                raise CommandError(f'Missing required columns: {missing_columns}')

            batch = []
            total_rows = 0

            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                total_rows += 1
                
                try:
                    # Parse label ID (if present)
                    label_id = None
                    if 'id' in row and row['id']:
                        try:
                            label_id = int(row['id'])
                        except ValueError:
                            pass

                    # Skip if exists and skip_existing is True
                    if skip_existing and label_id and TiledGISLabel.objects.filter(id=label_id).exists():
                        skipped_count += 1
                        continue

                    # Parse coordinates
                    try:
                        northeast_lat = float(row['northeast_Lat'])
                        northeast_lng = float(row['northeast_Lng'])
                        southwest_lat = float(row['southwest_Lat'])
                        southwest_lng = float(row['southwest_Lng'])
                    except (ValueError, KeyError) as e:
                        self.stdout.write(self.style.WARNING(
                            f'Row {row_num}: Invalid coordinates - {e}'
                        ))
                        error_count += 1
                        continue

                    # Parse label_json
                    try:
                        if row['label_json'].startswith('"') and row['label_json'].endswith('"'):
                            # Remove outer quotes if present
                            label_json_str = row['label_json'][1:-1].replace('""', '"')
                        else:
                            label_json_str = row['label_json']
                        label_json = json.loads(label_json_str)
                    except (json.JSONDecodeError, KeyError) as e:
                        self.stdout.write(self.style.WARNING(
                            f'Row {row_num}: Invalid label_json - {e}'
                        ))
                        error_count += 1
                        continue

                    # Parse zoom_level
                    zoom_level = int(row.get('zoom_level', 23))

                    # Parse label_type
                    label_type = row.get('label_type', 'P')  # Default to Polygon

                    # Parse geometry (WKT or GeoJSON)
                    geometry = row.get('geometry', '')

                    # Parse category_id (if different from default)
                    category_id = row.get('category_id')
                    if category_id:
                        try:
                            cat_id = int(category_id)
                            if cat_id != category.id:
                                # Try to find category by ID
                                try:
                                    category = CategoryType.objects.get(id=cat_id)
                                except CategoryType.DoesNotExist:
                                    pass  # Use default category
                        except ValueError:
                            pass

                    # Parse parent_raster_id (optional)
                    parent_raster = None
                    parent_raster_id = row.get('parent_raster_id')
                    if parent_raster_id:
                        try:
                            parent_raster = RasterImage.objects.get(id=int(parent_raster_id))
                        except (RasterImage.DoesNotExist, ValueError):
                            pass

                    # Parse pub_date
                    pub_date = datetime.now()
                    if row.get('pub_date'):
                        try:
                            pub_date = datetime.fromisoformat(row['pub_date'].replace('Z', '+00:00'))
                        except (ValueError, AttributeError):
                            pass

                    # Create TiledGISLabel object
                    label_data = {
                        'northeast_lat': northeast_lat,
                        'northeast_lng': northeast_lng,
                        'southwest_lat': southwest_lat,
                        'southwest_lng': southwest_lng,
                        'zoom_level': zoom_level,
                        'label_json': label_json,
                        'label_type': label_type,
                        'geometry': geometry,
                        'category': category,
                        'parent_raster': parent_raster,
                        'pub_date': pub_date,
                    }
                    
                    # Only add labeler if we have one
                    if labeler:
                        label_data['labeler'] = labeler

                    if dry_run:
                        self.stdout.write(f'Would import label ID {label_id or "new"} at ({northeast_lat}, {northeast_lng})')
                        imported_count += 1
                    else:
                        batch.append(TiledGISLabel(**label_data))

                        # Import in batches
                        if len(batch) >= batch_size:
                            TiledGISLabel.objects.bulk_create(batch, ignore_conflicts=True)
                            imported_count += len(batch)
                            self.stdout.write(f'Imported batch: {len(batch)} labels (total: {imported_count})')
                            batch = []

                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'Row {row_num}: Error processing - {str(e)}'
                    ))
                    error_count += 1
                    continue

            # Import remaining batch
            if not dry_run and batch:
                TiledGISLabel.objects.bulk_create(batch, ignore_conflicts=True)
                imported_count += len(batch)
                self.stdout.write(f'Imported final batch: {len(batch)} labels')

        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('Import Summary:'))
        self.stdout.write(f'  Total rows processed: {total_rows}')
        if dry_run:
            self.stdout.write(self.style.WARNING(f'  Would import: {imported_count} labels (DRY RUN)'))
        else:
            self.stdout.write(self.style.SUCCESS(f'  Imported: {imported_count} labels'))
        self.stdout.write(f'  Skipped: {skipped_count} labels')
        self.stdout.write(f'  Errors: {error_count} rows')
        self.stdout.write(self.style.SUCCESS('='*60))

