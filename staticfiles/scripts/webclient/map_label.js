// Global state management
window.globals = {
    rasters: [],
    layers: {},
    active_layer: "",
    drawnItems: new L.FeatureGroup(),
    categoryColor: {},
    histogram_chart: null,
    chart: null,
    lastLayer: null,
    drawControl: null  // Global drawControl reference
};

// Helper function to parse hash URL
function parseHashUrl() {
    const hash = window.location.hash;
    if (!hash) return null;
    
    const [zoom, lat, lng] = hash.substring(1).split('/').map(Number);
    return { zoom, lat, lng };
}

// Helper function to generate hash URL
function generateHashUrl(layer, zoom, lat, lng) {
    return `https://mbtiles.deepgis.org/data/${layer}/#${zoom}/${lat}/${lng}`;
}

// Initialize map (check if already initialized and DOM is ready)
var map;
function initializeMap() {
    // Check if map element exists
    const mapElement = document.getElementById('map');
    if (!mapElement) {
        console.warn('Map element not found, deferring initialization');
        return;
    }
    
    if (window.globals && window.globals.map && window.globals.map._container) {
        // Use existing map
        map = window.globals.map;
        console.log('Using existing map instance');
    } else {
        // Check if container is already initialized by Leaflet
        if (mapElement._leaflet_id) {
            console.warn('Map container already has Leaflet instance, skipping initialization');
            return;
        }
        
        // Initialize new map
        map = L.map('map', {
            minZoom: 12,
            maxZoom: 24,
            updateWhenZooming: false,
            updateWhenIdle: true,
            preferCanvas: true
        });
        
        // Set initial view based on URL hash or default coordinates
        const hashCoords = parseHashUrl();
        if (hashCoords) {
            map.setView([hashCoords.lat, hashCoords.lng], hashCoords.zoom);
        } else {
            map.setView([33.78210534131368, -111.26527270115186], 20);
        }
        
        // Store in globals
        if (window.globals) {
            window.globals.map = map;
        }
        
        // Set up map event handlers
        setupMapHandlers(map);
        
        // Trigger map ready event after a short delay to ensure map is fully initialized
        setTimeout(() => {
            if (typeof window.onMapReady === 'function') {
                window.onMapReady(map);
            }
            // Dispatch custom event for other listeners
            window.dispatchEvent(new CustomEvent('mapready', { detail: { map: map } }));
        }, 100);
    }
}

// Set up map event handlers
function setupMapHandlers(mapInstance) {
    if (!mapInstance) return;
    
    // Update URL hash when map moves
    mapInstance.on('moveend', function() {
        const center = mapInstance.getCenter();
        const zoom = mapInstance.getZoom();
        const hash = `#${zoom}/${center.lat.toFixed(5)}/${center.lng.toFixed(5)}`;
        
        // Only update hash if we're viewing an MBTiles layer
        if (window.globals.active_layer && window.globals.active_layer.startsWith('bf_')) {
            window.history.replaceState(null, null, hash);
        }
    });
    
    // Add feature group to map first
    mapInstance.addLayer(window.globals.drawnItems);

    // Initialize draw control with the properly initialized feature group
    // Store in globals for global access
    window.globals.drawControl = new L.Control.Draw({
        edit: {
            featureGroup: window.globals.drawnItems
        },
        draw: {
            polyline: false,
            circle: false,
            circlemarker: false,
            marker: false,
            polygon: {
                allowIntersection: false,
                showArea: true
            },
            rectangle: true
        }
    });
    
    // Create local reference for convenience
    const drawControl = window.globals.drawControl;

    // Initialize raster layers with the feature group (check if function exists)
    if (typeof window.initRasterLayers === 'function') {
        const { baseLayers: rasterBaseLayers, overlayLayers, layerControl: rasterLayerControl } = window.initRasterLayers(mapInstance, window.globals.drawnItems);
    } else {
        console.warn('window.initRasterLayers not available, make sure raster_layers.js is loaded');
    }

    // Handle base layer changes
    mapInstance.on('baselayerchange', function(e) {
        window.globals.active_layer = e.name;
        
        // If switching to an MBTiles layer, update URL hash
        if (e.name && e.name.startsWith('bf_')) {
            const center = mapInstance.getCenter();
            const zoom = mapInstance.getZoom();
            const hash = `#${zoom}/${center.lat.toFixed(5)}/${center.lng.toFixed(5)}`;
            window.history.replaceState(null, null, hash);
        }
    });

    // Add the draw control after organizing other controls
    mapInstance.addControl(drawControl);

    // Add our additional layers to the globals without redeclaring baseLayers
    window.globals.layers["OpenStreetMap"] = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '© OpenStreetMap contributors'
    });

window.globals.layers["Google Satellite"] = L.tileLayer('http://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
    maxZoom: 19,
    subdomains: ['mt0', 'mt1', 'mt2', 'mt3'],
    attribution: '© Google'
});

    // Add default layer
    window.globals.layers["OpenStreetMap"].addTo(mapInstance);

    // Create additional layers object without conflicting with rasterBaseLayers
    var additionalLayers = {
        "OpenStreetMap": window.globals.layers["OpenStreetMap"],
        "Google Satellite": window.globals.layers["Google Satellite"]
    };

    // Create empty overlays object for additional layers
    var overlays = {};

    // Add layer control for additional layers
    var additionalLayerControl = L.control.layers(additionalLayers, overlays, {
        position: 'topleft',
        collapsed: true
    }).addTo(mapInstance);

    // Draw event handlers
    mapInstance.on(L.Draw.Event.CREATED, function(e) {
    var layer = e.layer;
    window.globals.drawnItems.addLayer(layer);
});

    mapInstance.on(L.Draw.Event.EDITED, function(e) {
        var layers = e.layers;
        layers.eachLayer(function(layer) {
            // Handle edited layers
        });
    });

    mapInstance.on(L.Draw.Event.DELETED, function(e) {
        var layers = e.layers;
        layers.eachLayer(function(layer) {
            // Handle deleted layers
        });
    });
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeMap);
} else {
    // DOM is already ready
    initializeMap();
}

// Rest of the code that uses the global map variable (will be set after initialization)

function updateCategoryProperties() {
    $.ajax({
        url: "/webclient/getCategoryInfo",
        type: "GET",
        dataType: "json",
        success: function(response) {
            $('#categories_coll')[0].html = '';
            var output = [];
            window.globals.categoryColor = {};
            for (category in response) {
                cat_list_item = '<li class="grid">' +
                    '<input type="radio" name="category_select" data-color="' + response[category]['color'] + '" value="' + category + '" id="' + category + '">' +
                    '<label for="' + category + '">' + category + '</label>' +
                    '<span class="circle" style="color:' + response[category]['color'] + '; background-color:' + response[category]['color'] +
                    ';"></span></li>';
                output.push(cat_list_item);
                window.globals.categoryColor[response[category]['color']] = category;
            }
            $('#categories_coll').html(output.join(''));

            set_label_draw_color = function() {
                if ($('#freeHandButton').hasClass('btn-warning')) {
                    freeHand();
                    var drawer = window.globals.drawnItems.getLayer(window.globals.lastLayer);
                    if (drawer) {
                        drawer.setMode('view');
                    }
                } else {
                    var color = rgbToHex($(this).attr('data-color'));
                    if (window.globals.drawControl) {
                        window.globals.drawControl.setDrawingOptions({
                        rectangle: {
                            shapeOptions: {
                                color: color
                            }
                        },
                        polygon: {
                            icon: new L.DivIcon({
                                iconSize: new L.Point(4, 4),
                                className: 'leaflet-div-icon leaflet-editing-icon'
                            }),
                            shapeOptions: {
                                color: color,
                                smoothFactor: 0.1
                            }
                        }
                    });
                    } else {
                        console.warn('drawControl not initialized yet');
                    }
                }
            };
            $("input:radio[name=category_select]").on('change load', set_label_draw_color);
            $("input:radio[name=category_select]:first").attr('checked', true).trigger('change');
        },
        error: function(xhr, errmsg, err) {
            alert(xhr.status + ": " + xhr.responseText);
        }
    });
}

function change_draw_color () {
    if ($('#DrawOrHist').hasClass('btn-danger')) {
        $('#DrawOrHist').removeClass('btn-danger');
        $('#DrawOrHist').addClass('btn-success');
        $('#DrawOrHist').html('<i class="fa fa-check"></i> Plot Histograms');
    } else {
        $('#DrawOrHist').removeClass('btn-success');
        $('#DrawOrHist').addClass('btn-danger');
        $('#DrawOrHist').html('<i class="fa fa-check"></i> Draw objects');
        $("input:radio[name=category_select]:first").attr('checked', true).trigger('change');
    }
};

$('#DrawOrHist').click(change_draw_color);

$('#imagemodal').on('hide.bs.modal', function (e) {
    $('#modal_body').html("");
});

$('#ShowAllHist').click(function () {
    var histogram_count = 1;
    var all_active_layers = window.globals.drawnItems ? window.globals.drawnItems.getLayers() : [];
    var histograms = {};
    for ( layer in all_active_layers) {
        $('#modal_body').append('<canvas id="histogram' + String(layer) + '" width="600" height="300"></canvas>');
        var chart = $("#histogram" + String(layer)).get(0).getContext("2d");

        current_layer = all_active_layers[layer];
        if (current_layer._layers) {
            current_layer = all_active_layers[layer].getLayers()[0];
        }

        var histogram_data = {
            labels: [0, 1, 2, 3, 4, 5, 6, 7],
            datasets: [
                {
                    label: "Count per rock area for " + current_layer._popup._content,
                    borderColor: "#ff0000",
                    pointBorderColor: "#ff0000",
                    pointBackgroundColor: "#ff0000",
                    pointHoverBackgroundColor: "#ff0000",
                    pointHoverBorderColor: "#ff0000",
                    pointBorderWidth: 1,
                    pointHoverRadius: 1,
                    pointHoverBorderWidth: 1,
                    pointRadius: 3,
                    fill: true,
                    borderWidth: 1,
                    data: [0, 0, 0, 0, 0, 0, 0],
                }
            ]
        };
        var histogram_chart = new Chart(chart, {
            type: 'bar',
            data: histogram_data,
            options: {
                showLines: true,
                scales: {
                    x: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Rock area (sq. m)'
                        }
                    },
                    y: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Count'
                        }
                    }
                }
            }
        });
        bins = getBinsValue();
        var bounds = current_layer.getBounds();
        var ne_lat = bounds._northEast.lat;
        var ne_lng = bounds._northEast.lng;
        var sw_lat = bounds._southWest.lat;
        var sw_lng = bounds._southWest.lng;
        histograms[String(sw_lng) + String(ne_lng) + String(sw_lat) + String(ne_lat)] = histogram_chart;
        $.ajax({
            url: "getHistogramWindow/?northeast_lat=" + ne_lat + "&northeast_lng=" + ne_lng + "&southwest_lat=" + sw_lat + "&southwest_lng=" + sw_lng + "&number_of_bins=" + bins,
            type: "GET",
            success: function(data) {
                histograms[data.unique].data.labels = data.x;
                histograms[data.unique].data.datasets[0].data = data.y;
                histograms[data.unique].update();
            }
        });
        $('#imagemodal').modal('show');
    }
});

function showSnackBar(text) {
    var snackBar = document.getElementById("snackbar");
    snackBar.innerHTML = text;
    // Add the "show" class to DIV
    snackBar.className = "show";
    // After 3 seconds, remove the show class from DIV
    setTimeout(function() {
        snackBar.className = snackBar.className.replace("show", "");
    }, 6000);
}

updateCategoryProperties();

// Create a custom control for the DeepGIS home link
var HomeControl = L.Control.extend({
    options: {
        position: 'topleft'
    },
    onAdd: function(map) {
        var container = L.DomUtil.create('div', 'leaflet-control leaflet-control-home');
        container.style.backgroundColor = 'white';
        container.style.padding = '5px 10px';
        container.style.borderRadius = '4px';
        container.style.boxShadow = '0 1px 5px rgba(0,0,0,0.65)';
        container.style.cursor = 'pointer';
        container.style.marginBottom = '10px';

        container.innerHTML = `
            <a href="/" style="text-decoration: none; color: #333; font-weight: bold;">
                <i class="fa fa-home"></i> DeepGIS
            </a>
        `;

        return container;
    }
});

// Add controls to map
new HomeControl().addTo(map);

// Add scale control
L.control.scale({
    position: 'bottomleft',
    imperial: false
}).addTo(map);

// Initialize histogram chart
window.globals.chart = $("#histogram").get(0).getContext("2d");

var histogram_data = {
    labels: [0, 1, 2, 3, 4, 5, 6, 7],
    datasets: [
        {
            label: "Rock area count",
            borderColor: "#ff0000",
            pointBorderColor: "#ff0000",
            pointBackgroundColor: "#ff0000",
            pointHoverBackgroundColor: "#ff0000",
            pointHoverBorderColor: "#ff0000",
            pointBorderWidth: 1,
            pointHoverRadius: 1,
            pointHoverBorderWidth: 1,
            pointRadius: 2,
            fill: true,
            borderWidth: 1,
            data: [0, 0, 0, 0, 0, 0, 0],
        }
    ]
};

window.globals.histogram_chart = new Chart(window.globals.chart, {
    type: 'bar',
    data: histogram_data,
    options: {
        showLines: true,
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false
            }
        },
        scales: {
            x: {
                display: true,
                title: {
                    display: true,
                    text: 'Area (m²)',
                    font: {
                        size: 10
                    }
                },
                ticks: {
                    font: {
                        size: 9
                    }
                }
            },
            y: {
                display: true,
                title: {
                    display: true,
                    text: 'Count',
                    font: {
                        size: 10
                    }
                },
                ticks: {
                    font: {
                        size: 9
                    }
                }
            }
        }
    }
});

// Create a custom control for the histogram controls
var HistogramControl = L.Control.extend({
    options: {
        position: 'bottomright'
    },
    onAdd: function(map) {
        var container = L.DomUtil.create('div', 'leaflet-control leaflet-control-histogram');
        container.style.backgroundColor = 'rgba(255, 255, 255, 0.85)';
        container.style.padding = '5px';
        container.style.borderRadius = '4px';
        container.style.boxShadow = '0 1px 5px rgba(0,0,0,0.4)';
        container.style.marginRight = '10px';
        container.style.maxWidth = '250px';
        container.style.backdropFilter = 'blur(2px)';
        container.style.transition = 'all 0.3s ease';

        // Add toggle button
        var toggleBtn = L.DomUtil.create('button', 'histogram-toggle', container);
        toggleBtn.innerHTML = '<i class="fa fa-chart-bar"></i>';
        toggleBtn.style.position = 'absolute';
        toggleBtn.style.right = '5px';
        toggleBtn.style.top = '5px';
        toggleBtn.style.padding = '2px 5px';
        toggleBtn.style.fontSize = '0.8em';
        toggleBtn.style.backgroundColor = 'transparent';
        toggleBtn.style.border = 'none';
        toggleBtn.style.cursor = 'pointer';

        // Create content container
        var content = L.DomUtil.create('div', 'histogram-content', container);
        content.style.display = 'none';  // Start collapsed
        
        content.innerHTML = `
            <div id="histogram-controls" style="margin-bottom: 5px;">
                <div style="margin-bottom: 3px; display: flex; align-items: center; gap: 5px;">
                    <label id="customRange2label" style="font-size: 0.8em; margin: 0;">Bins: 10</label>
                    <input type="range" class="custom-range" id="customRange2" min="5" max="50" value="10" style="width: 100px;">
                </div>
                <div style="display: flex; gap: 3px;">
                    <button id="DrawOrHist" class="btn btn-danger btn-sm" style="flex: 1; padding: 2px 5px; font-size: 0.8em;">
                        <i class="fa fa-check"></i> Draw
                    </button>
                    <button id="freeHandButton" class="btn btn-success btn-sm" style="flex: 1; padding: 2px 5px; font-size: 0.8em;">
                        <i class="fa fa-check"></i> Free Hand
                    </button>
                </div>
            </div>
            <canvas id="histogram" width="220" height="120" style="margin-top: 3px;"></canvas>
        `;

        // Toggle functionality
        L.DomEvent.on(toggleBtn, 'click', function() {
            if (content.style.display === 'none') {
                content.style.display = 'block';
            } else {
                content.style.display = 'none';
            }
        });

        // Prevent map interactions when using the controls
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);

        return container;
    }
});

// Function to update histogram visibility based on data
function updateHistogramVisibility(data) {
    const content = document.querySelector('.histogram-content');
    const hasData = data && data.y && data.y.some(value => value > 0);
    
    if (content) {
        content.style.display = hasData ? 'block' : 'none';
    }
}

// Update the AJAX success handlers to check for data
// This should be set up after map is initialized
function setupHistogramHandlers() {
    if (!window.globals.map) {
        setTimeout(setupHistogramHandlers, 100);
        return;
    }
    
    const map = window.globals.map;
    map.on('moveend', function(e) {
        bins = getBinsValue();
        $.ajax({
            url: "getHistogramWindow/?northeast_lat=" + map.getBounds()._northEast.lat.toString() + 
                 "&northeast_lng=" + map.getBounds()._northEast.lng.toString() + 
                 "&southwest_lat=" + map.getBounds()._southWest.lat.toString() + 
                 "&southwest_lng=" + map.getBounds()._southWest.lng.toString() + 
                 "&number_of_bins=" + bins,
            type: "GET",
            success: function(data) {
                if (window.globals.histogram_chart) {
                    window.globals.histogram_chart.data.labels = data.x;
                    window.globals.histogram_chart.data.datasets[0].data = data.y;
                    window.globals.histogram_chart.data.datasets[0].borderColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointBorderColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointBackgroundColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointHoverBackgroundColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointHoverBorderColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].label = "Rock area count";
                    window.globals.histogram_chart.update();
                    if (typeof updateHistogramVisibility === 'function') {
                        updateHistogramVisibility(data);
                    }
                }
            }
        });
    });
}

// Set up histogram handlers when map is ready
window.addEventListener('mapready', function(e) {
    setTimeout(setupHistogramHandlers, 300);
});

// Fallback
setTimeout(setupHistogramHandlers, 1500);

// Legacy code - these should be handled in setupMapHandlers
// Wrap in a function that runs after map is initialized
function initializeLegacyControls() {
    if (!window.globals.map) {
        console.warn('Map not initialized, deferring legacy controls');
        setTimeout(initializeLegacyControls, 100);
        return;
    }
    
    const map = window.globals.map;
    
    // Check if map is fully initialized (has controlCorners property)
    if (!map._controlCorners) {
        console.warn('Map not fully initialized yet, deferring controls');
        setTimeout(initializeLegacyControls, 100);
        return;
    }
    
    // Add histogram control if HistogramControl is defined
    if (typeof HistogramControl !== 'undefined') {
        try {
            // Check if histogram control is already added
            if (!document.querySelector('.leaflet-control-histogram')) {
                new HistogramControl().addTo(map);
                console.log('HistogramControl added successfully');
            }
        } catch (e) {
            console.warn('HistogramControl error:', e);
        }
    }
    
    // drawControl is now managed in setupMapHandlers function
    // This is just a safety check
    if (window.globals.drawControl) {
        try {
            // Check if already added
            const controlContainer = map._controlContainer;
            if (controlContainer && !controlContainer.querySelector('.leaflet-draw')) {
                window.globals.drawControl.addTo(map);
            }
        } catch (e) {
            console.warn('drawControl error:', e);
        }
    }
    
    // drawnItems is already in window.globals.drawnItems
    // This is just a safety check
    if (window.globals.drawnItems && !map.hasLayer(window.globals.drawnItems)) {
        window.globals.drawnItems.addTo(map);
    }
}

// Initialize legacy controls when map is ready
// Listen for mapready event for more reliable initialization
window.addEventListener('mapready', function(e) {
    console.log('Map ready event received');
    setTimeout(initializeLegacyControls, 200);
});

// Fallback: also try with setTimeout in case event is missed
setTimeout(initializeLegacyControls, 1000);

draw_shapes = function(geoJson, label_type) {
    geoJson.properties.options.weight = 0.5;
    if (label_type == "circle" || label_type == "Circle") {
        draw_shapes_layer = L.circle([geoJson.geometry.coordinates[1], geoJson.geometry.coordinates[0]], geoJson.properties.options);
    } else if (label_type.toLowerCase() == "rectangle") {
        var draw_shapes_layer = L.rectangle([
            [geoJson.geometry.coordinates[0][0].slice().reverse(), geoJson.geometry.coordinates[0][1].slice().reverse(),
                geoJson.geometry.coordinates[0][2].slice().reverse(), geoJson.geometry.coordinates[0][3].slice().reverse()
            ]
        ], geoJson.properties.options);
    } else if (label_type.toLowerCase() == "polygon") {
        coords = [];
        for (j = 0; j < geoJson.geometry.coordinates.length; j++) {
            coords.push([]);
            for (k = 0; k < geoJson.geometry.coordinates[j].length; k++) {
                coords[j].push(geoJson.geometry.coordinates[j][k].slice().reverse());
            }
        }
        var draw_shapes_layer = L.polygon(coords, geoJson.properties.options);
    } else {
        draw_shapes_layer = L.geoJSON(geoJson, geoJson.properties.options);
    }
    if ($('#DrawOrHist').hasClass('btn-success')) {
        draw_shapes_layer.bindPopup("Histogram #" + histogram_polygons).openPopup();
        histogram_polygons += 1;
    }
    if (window.globals.drawnItems) {
        window.globals.drawnItems.addLayer(draw_shapes_layer);
    }

    if ($('#DrawOrHist').hasClass('btn-success') && window.globals.drawnItems) {
        window.globals.drawnItems.on('click', function(e) {
            bins = getBinsValue();
            var bounds = e.layer.getBounds();
            var ne_lat = bounds._northEast.lat;
            var ne_lng = bounds._northEast.lng;
            var sw_lat = bounds._southWest.lat;
            var sw_lng = bounds._southWest.lng;
            $.ajax({
                url: "getHistogramWindow/?northeast_lat=" + ne_lat + "&northeast_lng=" + ne_lng + "&southwest_lat=" + sw_lat + "&southwest_lng=" + sw_lng + "&number_of_bins=" + bins,
                type: "GET",
                success: function(data) {
                    window.globals.histogram_chart.data.labels = data.x;
                    window.globals.histogram_chart.data.datasets[0].data = data.y;
                    window.globals.histogram_chart.data.datasets[0].borderColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointBorderColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointBackgroundColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointHoverBackgroundColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].pointHoverBorderColor = "#ff0000";
                    window.globals.histogram_chart.data.datasets[0].label = "Count per rock area for " + e.layer._popup._content;
                    window.globals.histogram_chart.update();
                }
            });
        });
    }
    return draw_shapes_layer;
};

function project(lat, lng, zoom) {
    var d = Math.PI / 180,
        max = 1 - 1E-15,
        sin = Math.max(Math.min(Math.sin(lat * d), max), -max),
        scale = 256 * Math.pow(2, zoom);
    var point = {
        x: 1 * lng * d,
        y: 1 * Math.log((1 + sin) / (1 - sin)) / 2
    };
    return point;
}

$('#freeHandButton').click(freeHand);

function freeHand() {
    if ($('#freeHandButton').hasClass('btn-success')) {
        $('#freeHandButton').html('<i class="fa fa-exclamation-triangle"</i>  Disable Free Hand');
        $('#freeHandButton').removeClass('btn-success');
        $('#freeHandButton').addClass('btn-warning');

        var color = rgbToHex($("input:radio[name=category_select]:checked").attr('data-color'));
        var drawer = new L.FreeHandShapes();
        drawer.options = {
            polygon: {
                smoothFactor: 0.000000000001,
                fillOpacity : 0.25,
                noClip : false,
                color: color,
            },
            polyline : {
                color: color,
                opacity: 0.25,
                smoothFactor: 0.000000000001,
                noClip : false,
                clickable : false,
                weight: 1
            },
            simplify_tolerance: 0.000000000001,
            merge_polygons: false,
            concave_polygons: true
        };

        drawer.setMode('add');

        drawer.on('layeradd', function(data) {
            drawer.setMode('view');
            var layer = data.layer;
            var geoJson = layer.toGeoJSON(20);
            var label_type = "polygon";
            var bounds = layer.getBounds();
            var ne_lat = bounds._northEast.lat;
            var ne_lng = bounds._northEast.lng;
            var sw_lat = bounds._southWest.lat;
            var sw_lng = bounds._southWest.lng;
            geoJson.properties.options = layer.options;
            var radio_label_class = $("input:radio[name=category_select]:checked").val();
            requestObj = {
                northeast_lat: ne_lat,
                northeast_lng: ne_lng,
                southwest_lat: sw_lat,
                southwest_lng: sw_lng,
                zoom_level: map.getZoom(),
                label_type: label_type,
                raster: window.globals.active_layer,
                category_name: radio_label_class,
                geoJSON: geoJson
            };

            if ($('#DrawOrHist').hasClass('btn-success')) {
                layer.bindPopup("Histogram #" + histogram_polygons).openPopup();
                histogram_polygons += 1;
                // Case to display histogram
                bins = getBinsValue();
                $.ajax({
                    url: "getHistogramWindow/?northeast_lat=" + ne_lat + "&northeast_lng=" + ne_lng + "&southwest_lat=" + sw_lat + "&southwest_lng=" + sw_lng + "&number_of_bins=" + bins,
                    type: "GET",
                    success: function(data) {
                        window.globals.histogram_chart.data.labels = data.x;
                        window.globals.histogram_chart.data.datasets[0].data = data.y;
                        window.globals.histogram_chart.data.datasets[0].borderColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointBorderColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointBackgroundColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointHoverBackgroundColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointHoverBorderColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].label = "Count per rock area for Histogram #" + (histogram_polygons - 1);
                        window.globals.histogram_chart.update();
                        layer.openPopup();
                    }
                });
            } else {
                showSnackBar("Adding objects to database is currently disabled.");
//                $.ajax({
//                    url: "/webclient/addTiledLabel",
//                    type: "POST",
//                    dataType: "text",
//                    data: JSON.stringify(requestObj),
//                    success: function(data) {
//                        showSnackBar(JSON.parse(data).message);
//                    },
//                    error: function(data) {
//                        showSnackBar(JSON.parse(data).message);
//                    }
//                });
            }
            $('#freeHandButton').html('<i class="fa fa-check"></i>Enable Free Hand');
            $('#freeHandButton').removeClass('btn-warning');
            $('#freeHandButton').addClass('btn-success');

            layer.on('click', function(e) {
                bins = getBinsValue();
                var bounds = e.sourceTarget._bounds;
                var ne_lat = bounds._northEast.lat;
                var ne_lng = bounds._northEast.lng;
                var sw_lat = bounds._southWest.lat;
                var sw_lng = bounds._southWest.lng;
                $.ajax({
                    url: "getHistogramWindow/?northeast_lat=" + ne_lat + "&northeast_lng=" + ne_lng + "&southwest_lat=" + sw_lat + "&southwest_lng=" + sw_lng + "&number_of_bins=" + bins,
                    type: "GET",
                    success: function(data) {
                        window.globals.histogram_chart.data.labels = data.x;
                        window.globals.histogram_chart.data.datasets[0].data = data.y;
                        window.globals.histogram_chart.data.datasets[0].borderColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointBorderColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointBackgroundColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointHoverBackgroundColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].pointHoverBorderColor = "#ff0000";
                        window.globals.histogram_chart.data.datasets[0].label = "Count per rock area for " + e.sourceTarget._popup._content;
                        window.globals.histogram_chart.update();
                    }
                });
            });
        });
        if (window.globals.drawnItems) {
            window.globals.drawnItems.addLayer(drawer);
            window.globals.lastLayer = window.globals.drawnItems.getLayerId(drawer);
        }
    } else {
        $('#freeHandButton').html('<i class="fa fa-check"></i>Enable Free Hand');
        $('#freeHandButton').removeClass('btn-warning');
        $('#freeHandButton').addClass('btn-success');
    }
}

// Set up draw event handlers after map is initialized
function setupDrawEventHandlers() {
    if (!window.globals.map) {
        setTimeout(setupDrawEventHandlers, 100);
        return;
    }
    
    const map = window.globals.map;
    map.on(L.Draw.Event.CREATED, function(event) {
    var layer = event.layer;
    var geoJson = layer.toGeoJSON(20);
    geoJson.properties.options = layer.options;
    var ne_lat;
    var ne_lng;
    var sw_lat;
    var sw_lng;
    if (window.globals.active_layer == "") {
        showSnackBar("No active raster layer present.");
        return;
    }
    var bounds = layer.getBounds();
    ne_lat = bounds._northEast.lat;
    ne_lng = bounds._northEast.lng;
    sw_lat = bounds._southWest.lat;
    sw_lng = bounds._southWest.lng;
    var radio_label_class = $("input:radio[name=category_select]:checked").val();
    requestObj = {
        northeast_lat: ne_lat,
        northeast_lng: ne_lng,
        southwest_lat: sw_lat,
        southwest_lng: sw_lng,
        zoom_level: map.getZoom(),
        label_type: event.layerType,
        category_name: radio_label_class,
        raster: window.globals.active_layer,
        geoJSON: geoJson
    };
    var _layer = draw_shapes(geoJson, event.layerType);

    if ($('#DrawOrHist').hasClass('btn-success')) {
        // Case to display histogram
        bins = getBinsValue();
        $.ajax({
            url: "getHistogramWindow/?northeast_lat=" + ne_lat + "&northeast_lng=" + ne_lng + "&southwest_lat=" + sw_lat + "&southwest_lng=" + sw_lng + "&number_of_bins=" + bins,
            type: "GET",
            success: function(data) {
                window.globals.histogram_chart.data.labels = data.x;
                window.globals.histogram_chart.data.datasets[0].data = data.y;
                window.globals.histogram_chart.data.datasets[0].borderColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointBorderColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointBackgroundColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointHoverBackgroundColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointHoverBorderColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].label = "Count per rock area for Histogram #" + (histogram_polygons - 1);
                window.globals.histogram_chart.update();
                _layer.openPopup();
            }
        });
    } else {
        showSnackBar("Adding objects to database is currently disabled.");
        // Case to draw objects
        // $.ajax({
        //     url: "/webclient/addTiledLabel",
        //     type: "POST",
        //     dataType: "text",
        //     data: JSON.stringify(requestObj),
        //     success: function(data) {
        //         showSnackBar(JSON.parse(data).message);
        //     },
        //     error: function(data) {
        //         showSnackBar(JSON.parse(data).message);
        //     }
        // });
    }
});

    map.on('draw:deleted', function(e) {
        var request_obj = [];
        var json = e.layers.toGeoJSON(20);

        e.layers.eachLayer(function(layer) {
            if (window.globals.drawnItems) {
                window.globals.drawnItems.removeLayer(layer);
            }
            if (layer instanceof L.Rectangle) {
            var label_type = "rectangle";
        } else if (layer instanceof L.Circle) {
            //Workaround from https://github.com/Leaflet/Leaflet.draw/issues/701
            layer._map = layer._map || map;
                var label_type = "circle";
            } else if (layer instanceof L.Polygon) {
                var label_type = "polygon";
            } else {
                return; //Not one of the possible label types
            }

            var bounds = layer.getBounds();
            var jsonMessage = JSON.stringify(layer.toGeoJSON(20));
            var northeast = bounds.getNorthEast();
            var southwest = bounds.getSouthWest();
            delete_layer_dict = {
                northeast_lat: northeast.lat,
                northeast_lng: northeast.lng,
                southwest_lat: southwest.lat,
                southwest_lng: southwest.lng,
                label_type: label_type,
                geoJSON: jsonMessage,
                category_name: window.globals.categoryColor[hexToRgb(layer.options.color)]
            };

            request_obj.push(delete_layer_dict);

            if (layer._map != null) {
                layer._map.removeLayer(layer);
            }
        });

    // $.ajax({
    //     url: "/webclient/deleteTileLabels",
    //     type: "POST",
    //     dataType: "text",
    //     data: JSON.stringify(request_obj),
    //     success: function(data) {
    //         showSnackBar(JSON.parse(data).message);
    //     },
    //     error: function(data) {
    //         showSnackBar(JSON.parse(data).message);
    //     }
    // });
    });
    
    // Close the setupDrawEventHandlers function
}

// Set up draw event handlers when map is ready
window.addEventListener('mapready', function(e) {
    setTimeout(setupDrawEventHandlers, 300);
});

// Fallback
setTimeout(setupDrawEventHandlers, 1500);

function getBinsValue() {
    const rangeElement = $("#customRange2")[0];
    return rangeElement ? rangeElement.valueAsNumber : 10; // default to 10 bins if element not found
}

$("#customRange2").on("click", function() {
    const bins = getBinsValue();
    const rangeElement = $("#customRange2")[0];
    if (rangeElement) {
        $("#customRange2label").text("Histogram Bins: " + rangeElement.value);
    }
    
    if (!window.globals.map) {
        console.warn('Map not initialized for histogram');
        return;
    }
    
    const map = window.globals.map;
    $.ajax({
        url: "getHistogramWindow/?northeast_lat=" + map.getBounds()._northEast.lat.toString() + 
             "&northeast_lng=" + map.getBounds()._northEast.lng.toString() + 
             "&southwest_lat=" + map.getBounds()._southWest.lat.toString() + 
             "&southwest_lng=" + map.getBounds()._southWest.lng.toString() + 
             "&number_of_bins=" + bins,
        type: "GET",
        success: function(data) {
            if (window.globals.histogram_chart) {
                window.globals.histogram_chart.data.labels = data.x;
                window.globals.histogram_chart.data.datasets[0].data = data.y;
                window.globals.histogram_chart.data.datasets[0].borderColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointBorderColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointBackgroundColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointHoverBackgroundColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].pointHoverBorderColor = "#ff0000";
                window.globals.histogram_chart.data.datasets[0].label = "Count per rock area in the current view window";
                window.globals.histogram_chart.update();
            }
        }
    });
});

$("#category_submit").click(function() {
    $("#category_submit").attr("disabled", true);
    if ($("#add_new_category").val()) {
        $.post("/webclient/addCategory", {
            data: $("#add_new_category").val()
        }).done(function(data) {
            if (data.result == "failure") {
                showSnackBar(data.reason);
            };
            if (data.result == "success") {
                cat_list_item = '<li class="grid">' +
                    '<input type="radio" name="category_select" value="' + data.data + '" id="' + data.data + '">' +
                    '<label for="' + data.data + '">' + data.data + '</label>' +
                    '<span class="circle" style="color:' + data.color + '; background-color:' +
                    data.color + ';"></span></li>';

                $('#categories_coll').append($(cat_list_item));
                showSnackBar("Successfully added " + data.data + " to Categories");

                updateCategoryProperties();
                var inputField = document.getElementById("add_new_category");

                inputField.value = "";
            };
        });
    } else {
        alert("Missing category name.");
    }
    $("#category_submit").attr("disabled", false);
});

function hexToRgb(hex) {
    var result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result ? "rgb(" + parseInt(result[1], 16) + ", " + parseInt(result[2], 16) + ", " + parseInt(result[3], 16) + ")" : null;
}

function componentToHex(i) {
    var c = parseInt(i);
    var hex = c.toString(16);
    return hex.length == 1 ? "0" + hex : hex;
}

function rgbToHex(i) {
    var regex = /\d+/g;
    var result = i.match(regex);
    return "#" + componentToHex(result[0]) + componentToHex(result[1]) + componentToHex(result[2]);
}

change_draw_color();
change_draw_color();

// Add category button click handler
$('#add-category').click(function() {
    var categoryName = $('#category-input').val().trim();
    if (categoryName) {
        $.ajax({
            url: '/webclient/createCategory',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ name: categoryName }),
            success: function(response) {
                if (response.status === 'success') {
                    // Clear the input
                    $('#category-input').val('');
                    // Refresh the categories list
                    updateCategoryProperties();
                    showSnackBar('Category "' + categoryName + '" created successfully');
                } else {
                    showSnackBar('Error creating category: ' + response.message);
                }
            },
            error: function(xhr, status, error) {
                showSnackBar('Error creating category: ' + error);
            }
        });
    } else {
        showSnackBar('Please enter a category name');
    }
});
