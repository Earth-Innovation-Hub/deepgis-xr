# DeepGIS XR

A Django-based geospatial platform for extended reality (XR) applications with integrated GIS capabilities, machine learning support, and real-time data processing.

## Features

- **Geospatial Processing**: Built on GDAL/OGR with support for various spatial data formats
- **Tile Server Integration**: Built-in MapTiler tile server for high-performance map serving
- **Machine Learning Ready**: Includes PyTorch and scikit-image for ML/AI processing
- **Real-time Processing**: Celery integration for asynchronous task processing
- **REST API**: Full REST API support through Django REST framework
- **Cross-Origin Support**: Configured CORS headers for web and mobile clients
- **Spatial Database**: SQLite with SpatiaLite extension for spatial data storage

## Architecture

The application consists of two main services:

1. **Web Service**
   - Django application (Port 8090)
   - Handles API requests, data processing, and ML tasks
   - Serves static and media files
   - Manages user authentication and data access

2. **Tile Server**
   - MapTiler TileServer-GL (Port 8091)
   - Serves vector and raster tiles
   - Supports multiple tile formats (MVT, PNG, JPEG, WebP)
   - CORS-enabled for cross-origin requests

## Prerequisites

- Docker and Docker Compose
- GDAL 3.0+ (installed automatically in container)
- Python 3.9+
- 4GB+ RAM recommended
- SSD storage recommended for tile serving

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/deepgis-xr.git
   cd deepgis-xr
   ```

2. Build and start the services:
   ```bash
   docker-compose up --build
   ```

3. Access the services:
   - Web Application: http://localhost:8060
   - Tile Server: http://localhost:8091

## Project Structure

```
deepgis-xr/
├── data/               # Tile server data directory
├── deepgis_xr/        # Django project directory
├── media/             # User uploaded files
├── static/            # Static files
├── staticfiles/       # Collected static files
├── Dockerfile         # Web service container definition
├── docker-compose.yml # Service orchestration
├── requirements.txt   # Python dependencies
└── config.json        # Tile server configuration
```

## Configuration

### Django Settings
- Set in `deepgis_xr/settings.py`
- Override using environment variables
- Debug mode controlled via `DEBUG` environment variable

### Tile Server
- Configuration in `config.json`
- Supports custom styles and data sources
- CORS enabled by default for development

## Development

1. Start services in development mode:
   ```bash
   docker-compose up
   ```

2. Run migrations:
   ```bash
   docker-compose exec web python manage.py migrate
   ```

3. Create superuser:
   ```bash
   docker-compose exec web python manage.py createsuperuser
   ```

## API Endpoints

The REST API provides endpoints for:
- Spatial data upload and processing
- Tile generation and serving
- Machine learning model inference
- User management and authentication

Detailed API documentation available at `/api/docs/` when running the server.

## Dependencies

### Core
- Django 3.2.24
- Django REST Framework 3.12.4
- GDAL/OGR (via system packages)
- Celery 5.2+ with Redis

### Geospatial
- Rasterio 1.3.0
- Shapely 1.8.0
- Fiona 1.9.1
- GeoPandas 0.12.0
- PyProj 3.5.0

### Machine Learning
- PyTorch
- TorchVision
- scikit-image

## Production Deployment

For production deployment:

1. Update `config.json` with production domains
2. Set appropriate environment variables:
   ```bash
   DEBUG=False
   DJANGO_SETTINGS_MODULE=deepgis_xr.settings
   ```
3. Use proper SSL/TLS certificates
4. Configure proper authentication
5. Set up monitoring and logging

## 3D tools 
![image](https://github.com/user-attachments/assets/bd1944b8-da80-4713-9f70-b471a2bc69e2)


## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
1. Open an issue in the repository
2. Contact the maintainers
3. Check the documentation in the `/docs` directory 
