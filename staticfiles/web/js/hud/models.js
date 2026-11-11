// DeepGIS HUD 3D model loader (glTF/GLB URLs or Cesium Ion assets).
// A model in KNOWN_MODELS stands on the terrain by its own ground point. A #modelLocation
// option with data-model is a site: its model loads with the page, [data-fly-site] buttons
// fly to it, and ?site=<id> opens the page there.
// ========== 3D MODEL LOADING ==========
(function init3DModelSystem() {
    console.log('[3D Models] Initializing 3D model system...');

    // Global state for loaded models
    window.loadedModels = [];

    const getViewer = () => window.AppState?.viewer || window.viewer;

    // What DeepGIS knows about a model file. anchor: the glTF point (x, y up, z) that goes on
    // the ground at the chosen spot. hide: nodes the globe stands in for (a ground slab).
    // radius: metres around the anchor that hold the model, for framing it.
    const KNOWN_MODELS = {
        'lunar_base.glb': { anchor: [11.35, -4.4, 29.28], hide: ['Object_4'], radius: 50 },
    };
    // Share of ambient light a model keeps where there is no sky to fill its shadows
    const AIRLESS_AMBIENT = 0.4;
    // A site's label shows from this far out (m); closer, the model speaks for itself
    const SITE_LABEL_FROM_M = 1500;

    function knownModel(url) {
        const file = url.split(/[?#]/)[0].split('/').pop();
        const known = KNOWN_MODELS[file];
        if (!known) return null;
        // The credit a licence asks for is written once, in the Models panel
        const credit = document.querySelector(`[data-model-credit="${file}"]`)?.innerHTML.trim() || '';
        return { ...known, file, credit };
    }

    // Terrain height (m) at a spot, from the finest tile there
    async function groundHeight(viewer, lon, lat) {
        const spot = Cesium.Cartographic.fromDegrees(lon, lat);
        try {
            await Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, [spot]);
        } catch (e) {
            spot.height = undefined; // a smooth ellipsoid has no tiles to sample
        }
        return Number.isFinite(spot.height) ? spot.height : (viewer.scene.globe.getHeight(spot) ?? 0);
    }

    // Stand a known model on the terrain at lon/lat (degrees); heading turns it clockwise
    // from north. Returns its loadedModels entry.
    async function addKnownModel(viewer, known, url, lon, lat, { heading = 0, scale = 1, name = '' } = {}) {
        const ellipsoid = viewer.scene.globe.ellipsoid;
        const ground = await groundHeight(viewer, lon, lat);
        const origin = Cesium.Cartesian3.fromDegrees(lon, lat, ground, ellipsoid);
        const matrix = Cesium.Transforms.headingPitchRollToFixedFrame(
            origin, new Cesium.HeadingPitchRoll(Cesium.Math.toRadians(heading), 0, 0), ellipsoid);
        // Cesium turns glTF's y-up, z-forward axes to z-up, x-forward before modelMatrix applies
        const axes = Cesium.Matrix4.multiplyTransformation(
            Cesium.Axis.Y_UP_TO_Z_UP, Cesium.Axis.Z_UP_TO_X_UP, new Cesium.Matrix4());
        const anchor = Cesium.Matrix4.multiplyByPoint(
            axes, Cesium.Cartesian3.fromArray(known.anchor), new Cesium.Cartesian3());
        Cesium.Matrix4.multiplyByUniformScale(matrix, scale, matrix);
        Cesium.Matrix4.multiplyByTranslation(matrix, Cesium.Cartesian3.negate(anchor, anchor), matrix);

        const entry = { type: 'model', url, lon, lat, alt: ground, scale, origin, radius: known.radius * scale };
        // Clicking the model selects this entity, whose description carries the credit
        entry.marker = viewer.entities.add({
            name: name || known.file,
            description: known.credit,
            position: Cesium.Cartesian3.fromDegrees(lon, lat, ground + entry.radius, ellipsoid),
        });
        const options = { url, modelMatrix: matrix, id: entry.marker, show: false };
        if (!viewer.scene.skyAtmosphere) {
            options.imageBasedLighting = new Cesium.ImageBasedLighting({
                imageBasedLightingFactor: new Cesium.Cartesian2(AIRLESS_AMBIENT, AIRLESS_AMBIENT),
            });
        }
        try {
            const model = entry.primitive = viewer.scene.primitives.add(await Cesium.Model.fromGltfAsync(options));
            await new Promise((resolve, reject) => {
                model.readyEvent.addEventListener(resolve);
                model.errorEvent.addEventListener(reject);
            });
            for (const node of known.hide || []) {
                const part = model.getNode(node);
                if (part) part.show = false;
            }
            model.show = true;
        } catch (error) {
            removeModel(viewer, entry);
            throw error;
        }
        if (known.credit) {
            entry.credit = new Cesium.Credit(known.credit, true);
            viewer.creditDisplay.addStaticCredit(entry.credit);
        }
        window.loadedModels.push(entry);
        console.log(`[3D Models] ${known.file} stands at (${lon}, ${lat}), ground ${ground.toFixed(1)} m, scale ${scale}`);
        return entry;
    }

    // Look at a known model from heading (degrees, the way the camera faces)
    function frameModel(viewer, entry, { heading = 0, fly = true } = {}) {
        const sphere = new Cesium.BoundingSphere(entry.origin, entry.radius);
        const offset = new Cesium.HeadingPitchRange(
            Cesium.Math.toRadians(heading), Cesium.Math.toRadians(-20), entry.radius * 4);
        if (fly) {
            viewer.camera.flyToBoundingSphere(sphere, { offset, duration: 3 });
        } else {
            viewer.camera.viewBoundingSphere(sphere, offset);
            viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
        }
    }

    function removeModel(viewer, entry) {
        if (entry.primitive) viewer.scene.primitives.remove(entry.primitive);
        if (entry.entity) viewer.entities.remove(entry.entity);
        if (entry.marker) viewer.entities.remove(entry.marker);
        if (entry.credit) viewer.creditDisplay.removeStaticCredit(entry.credit);
    }

    // ---- Sites: models a page opens with ----
    const sites = [...document.querySelectorAll('#modelLocation option[data-model]')].map((o) => ({
        id: o.dataset.site,
        name: o.dataset.siteName || o.textContent.trim(),
        url: o.dataset.model,
        lon: parseFloat(o.dataset.lon),
        lat: parseFloat(o.dataset.lat),
        heading: parseFloat(o.dataset.heading || '0'),
        viewHeading: parseFloat(o.dataset.viewHeading || '0'),
        aliases: (o.dataset.aliases || '').split(',').map((s) => s.trim()).filter(Boolean),
        radius_m: parseFloat(o.dataset.radiusM || '') || undefined,
    }));
    const siteLoads = new Map(); // site id -> promise of its loadedModels entry

    function loadSite(site) {
        if (!siteLoads.has(site.id)) {
            siteLoads.set(site.id, (async () => {
                const viewer = getViewer();
                const known = knownModel(site.url);
                if (!viewer || !known) throw new Error(`No model for site ${site.id}`);
                const entry = await addKnownModel(viewer, known, site.url, site.lon, site.lat,
                    { heading: site.heading, name: site.name });
                entry.site = site.id;
                const far = new Cesium.DistanceDisplayCondition(SITE_LABEL_FROM_M, Number.MAX_VALUE);
                entry.marker.point = {
                    pixelSize: 8, color: Cesium.Color.fromCssColorString('#38bdf8'),
                    outlineColor: Cesium.Color.WHITE, outlineWidth: 1, distanceDisplayCondition: far,
                };
                entry.marker.label = {
                    text: site.name, font: '14px sans-serif', fillColor: Cesium.Color.WHITE,
                    outlineColor: Cesium.Color.BLACK, outlineWidth: 2, style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                    verticalOrigin: Cesium.VerticalOrigin.BOTTOM, pixelOffset: new Cesium.Cartesian2(0, -10),
                    distanceDisplayCondition: far,
                };
                return entry;
            })().catch((error) => {
                siteLoads.delete(site.id);
                throw error;
            }));
        }
        return siteLoads.get(site.id);
    }

    async function flyToSite(id, { fly = true } = {}) {
        const site = sites.find((s) => s.id === id);
        if (!site) return false;
        try {
            const entry = await loadSite(site);
            frameModel(getViewer(), entry, { heading: site.viewHeading, fly });
            return true;
        } catch (error) {
            console.error(`[3D Models] Site ${id} did not load:`, error);
            return false;
        }
    }

    document.querySelectorAll('[data-fly-site]').forEach((btn) => {
        btn.addEventListener('click', () => flyToSite(btn.dataset.flySite));
    });

    // The planet page creates its viewer before its terrain; wait for both
    function whenViewerReady(then, tries = 600) {
        const viewer = getViewer();
        const page = window.DeepGISMoon;
        if (viewer && (!page || page.isInitialized)) then(viewer);
        else if (tries > 0) setTimeout(() => whenViewerReady(then, tries - 1), 300);
    }

    if (sites.length) {
        whenViewerReady(() => {
            const open = new URLSearchParams(window.location.search).get('site');
            sites.forEach((site) => {
                if (site.id === open) flyToSite(site.id, { fly: false });
                else loadSite(site).catch((error) => console.error(`[3D Models] Site ${site.id} did not load:`, error));
            });
        });
    }

    window.DeepGISModels = { sites, loadSite, flyToSite };

    // Setup event listeners for preset buttons
    const presetBtns = document.querySelectorAll('.preset-model-btn');
    presetBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const modelUrl = btn.dataset.url;
            const modelUrlInput = document.getElementById('modelUrl');
            if (modelUrlInput) {
                modelUrlInput.value = modelUrl;
            }
        });
    });

    // Setup model location dropdown
    const modelLocationSelect = document.getElementById('modelLocation');
    const customLocationInputs = document.getElementById('customLocationInputs');
    if (modelLocationSelect && customLocationInputs) {
        modelLocationSelect.addEventListener('change', (e) => {
            customLocationInputs.style.display = e.target.value === 'custom' ? 'block' : 'none';
        });
    }

    // Setup model scale slider
    const modelScaleSlider = document.getElementById('modelScale');
    const scaleValue = document.getElementById('scaleValue');
    if (modelScaleSlider && scaleValue) {
        modelScaleSlider.addEventListener('input', (e) => {
            scaleValue.textContent = `Scale: ${parseFloat(e.target.value).toFixed(1)}x`;
        });
    }

    // Load model at specified location
    async function loadModelAtLocation() {
        const viewer = getViewer();
        if (!viewer) {
            console.error('[3D Models] Viewer not available');
            alert('Viewer not ready yet. Please wait.');
            return;
        }

        const modelUrl = document.getElementById('modelUrl')?.value?.trim();
        if (!modelUrl) {
            alert('Please enter a model URL or Ion Asset ID');
            return;
        }

        const locationOption = document.getElementById('modelLocation')?.value || 'current_view';
        const scale = parseFloat(document.getElementById('modelScale')?.value || '1.0');

        try {
            let modelPosition;
            let modelLon, modelLat, modelAlt = 0;

            const ellipsoid = viewer.scene.globe.ellipsoid;
            const preset = document.getElementById('modelLocation')?.selectedOptions[0]?.dataset;
            switch (preset?.lon !== undefined ? 'preset' : locationOption) {
                case 'preset':
                    modelLon = parseFloat(preset.lon);
                    modelLat = parseFloat(preset.lat);
                    modelAlt = parseFloat(preset.alt || '0');
                    modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, ellipsoid);
                    break;
                case 'custom':
                    modelLon = parseFloat(document.getElementById('customLon')?.value || '0');
                    modelLat = parseFloat(document.getElementById('customLat')?.value || '0');
                    modelAlt = parseFloat(document.getElementById('customAlt')?.value || '0');
                    modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, ellipsoid);
                    break;
                case 'current_view':
                default:
                    const cameraPosition = viewer.camera.positionCartographic;
                    modelLon = Cesium.Math.toDegrees(cameraPosition.longitude);
                    modelLat = Cesium.Math.toDegrees(cameraPosition.latitude);
                    modelAlt = 0; // Ground level
                    modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, ellipsoid);
                    break;
            }

            const known = knownModel(modelUrl);

            // Check if it's an Ion Asset ID
            if (/^\d+$/.test(modelUrl)) {
                const ionAssetId = parseInt(modelUrl);
                const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(ionAssetId);

                const transform = Cesium.Transforms.eastNorthUpToFixedFrame(modelPosition, viewer.scene.globe.ellipsoid);
                const scaleMatrix = Cesium.Matrix4.fromUniformScale(scale);
                tileset.modelMatrix = Cesium.Matrix4.multiply(transform, scaleMatrix, new Cesium.Matrix4());

                viewer.scene.primitives.add(tileset);
                viewer.zoomTo(tileset);

                // Store model info
                window.loadedModels.push({
                    type: 'ion',
                    url: modelUrl,
                    ionAssetId: ionAssetId,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    primitive: tileset
                });

                console.log(`[3D Models] Ion Asset ${ionAssetId} loaded at (${modelLon}, ${modelLat}, ${modelAlt}) with scale ${scale}`);
            } else if (known) {
                frameModel(viewer, await addKnownModel(viewer, known, modelUrl, modelLon, modelLat, { scale }));
            } else {
                // Load as regular GLTF/GLB model
                const entity = viewer.entities.add({
                    name: '3D Model',
                    position: modelPosition,
                    model: {
                        uri: modelUrl,
                        scale: scale,
                        minimumPixelSize: 64,
                        maximumScale: 10000,
                        runAnimations: true,
                        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                        silhouetteColor: Cesium.Color.YELLOW,
                        silhouetteSize: 2.0,
                        show: true
                    }
                });

                await entity.model.readyPromise;
                viewer.zoomTo(entity, new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-30), scale * 100));

                // Store model info
                window.loadedModels.push({
                    type: 'gltf',
                    url: modelUrl,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    entity: entity
                });

                console.log(`[3D Models] GLTF model loaded at (${modelLon}, ${modelLat}, ${modelAlt}) with scale ${scale}`);
            }

        } catch (error) {
            console.error('[3D Models] Error loading model:', error);
            alert(`Failed to load model: ${error.message}`);
        }
    }

    // Quick load at current location with 1:1 scale
    async function quickLoadModelAtCurrentLocation() {
        const viewer = getViewer();
        if (!viewer) {
            console.error('[3D Models] Viewer not available');
            alert('Viewer not ready yet. Please wait.');
            return;
        }

        const modelUrl = document.getElementById('modelUrl')?.value?.trim();
        if (!modelUrl) {
            alert('Please enter a model URL or Ion Asset ID');
            return;
        }

        try {
            const cameraPosition = viewer.camera.positionCartographic;
            const modelLon = Cesium.Math.toDegrees(cameraPosition.longitude);
            const modelLat = Cesium.Math.toDegrees(cameraPosition.latitude);
            const modelAlt = 0; // Ground level
            const modelPosition = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelAlt, viewer.scene.globe.ellipsoid);
            const scale = 1.0;
            const known = knownModel(modelUrl);

            // Check if it's an Ion Asset ID
            if (/^\d+$/.test(modelUrl)) {
                const ionAssetId = parseInt(modelUrl);
                const tileset = await Cesium.Cesium3DTileset.fromIonAssetId(ionAssetId);

                const transform = Cesium.Transforms.eastNorthUpToFixedFrame(modelPosition, viewer.scene.globe.ellipsoid);
                tileset.modelMatrix = transform;

                viewer.scene.primitives.add(tileset);
                viewer.zoomTo(tileset);

                // Store model info
                window.loadedModels.push({
                    type: 'ion',
                    url: modelUrl,
                    ionAssetId: ionAssetId,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    primitive: tileset
                });

                console.log(`[3D Models] Quick loaded Ion Asset ${ionAssetId}`);
            } else if (known) {
                frameModel(viewer, await addKnownModel(viewer, known, modelUrl, modelLon, modelLat));
            } else {
                const entity = viewer.entities.add({
                    name: '3D Model',
                    position: modelPosition,
                    model: {
                        uri: modelUrl,
                        scale: scale,
                        minimumPixelSize: 64,
                        maximumScale: 10000,
                        runAnimations: true,
                        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                        show: true
                    }
                });

                await entity.model.readyPromise;
                viewer.zoomTo(entity, new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-30), 100));

                // Store model info
                window.loadedModels.push({
                    type: 'gltf',
                    url: modelUrl,
                    lon: modelLon,
                    lat: modelLat,
                    alt: modelAlt,
                    scale: scale,
                    entity: entity
                });

                console.log(`[3D Models] Quick loaded GLTF model`);
            }

            console.log('[3D Models] Model quick-loaded at current location (1:1 scale)');
        } catch (error) {
            console.error('[3D Models] Error quick-loading model:', error);
            alert(`Failed to load model: ${error.message}`);
        }
    }

    // Remove all models
    function removeAllModels() {
        const viewer = getViewer();
        if (!viewer) {
            console.error('[3D Models] Viewer not available');
            return;
        }

        window.loadedModels.forEach((entry) => removeModel(viewer, entry));

        // Clear the array; a site's model comes back when its button asks for it
        window.loadedModels = [];
        siteLoads.clear();

        console.log('[3D Models] All models removed');
    }

    // Setup button event listeners
    const loadModelBtn = document.getElementById('loadModel');
    if (loadModelBtn) {
        loadModelBtn.addEventListener('click', loadModelAtLocation);
    }

    const quickLoadBtn = document.getElementById('quickLoadModel');
    if (quickLoadBtn) {
        quickLoadBtn.addEventListener('click', quickLoadModelAtCurrentLocation);
    }

    const removeModelBtn = document.getElementById('removeModel');
    if (removeModelBtn) {
        removeModelBtn.addEventListener('click', removeAllModels);
    }

    console.log('[3D Models] 3D model system initialized');
})();
