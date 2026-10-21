/**
 * Planetary bodies the viewer can open: shape, imagery, terrain and the names
 * other services know them by.
 *
 * Plain data plus helpers that take `Cesium` as an argument, so the registry
 * loads under `node --test` (tests/js/planet-bodies.test.js) with a stub.
 *
 * Imagery sources are tried in order; the first that answers its probe is
 * used. All of them send `Access-Control-Allow-Origin: *` and serve
 * equirectangular (simple cylindrical) tiles, which Cesium draws directly on
 * a GeographicTilingScheme over the body's ellipsoid: no reprojection proxy.
 *
 *   xyz  Pre-tiled 2x1-at-level-0 pyramids (NASA Trek, LROC QuickMap).
 *        `{lz}` in the URL is the level plus `levelOffset`, for pyramids whose
 *        level 0 is a single tile.
 *   wms  USGS Astrogeology MapServer: one GetMap per tile, rendered on request
 *        (~0.4 s a tile), so it follows the pre-tiled sources.
 *
 * Radii are IAU (Mars: IAU 2000 biaxial; the rest spheres, as the USGS
 * simple-cylindrical products treat them).
 */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.PlanetBodies = factory();
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    const USGS_WMS = 'https://planetarymaps.usgs.gov/cgi-bin/mapserv';
    const USGS_LINK = 'https://astrogeology.usgs.gov/';

    const trek = (id, name, path, maxLevel, credit, ext = 'jpg') => ({
        id, name, type: 'xyz', maxLevel, credit,
        url: `https://trek.nasa.gov/tiles/${path}/1.0.0/default/default028mm/{z}/{y}/{x}.${ext}`,
        link: `https://trek.nasa.gov/${path.split('/')[0].toLowerCase()}/`,
    });

    const usgs = (id, name, map, layer, credit, maxLevel = 7) => ({
        id, name, type: 'wms', url: USGS_WMS, map, layer, maxLevel,
        credit: `${credit} · USGS Astrogeology`, link: USGS_LINK,
    });

    const BODIES = [
        {
            id: 'moon', name: 'Moon', radiiM: [1737400, 1737400, 1737400],
            gazetteer: 'Moon', stacTarget: 'moon',
            home: { lon: 23.47297, lat: 0.67408 },
            imagery: [
                // QuickMap's level 0 is one 512 px tile holding the whole Moon in its top
                // half; from level 1 on, level z is a 2^z x 2^(z-1) grid, Y=0 at the north.
                // That is Cesium's 2x1 geographic scheme one level down, hence levelOffset 1.
                // Real NAC detail ends at QuickMap level 16 (~0.5 m/px); Cesium upsamples beyond.
                {
                    id: 'lroc-wac-nac', name: 'LROC QuickMap (WAC + NAC)', type: 'xyz',
                    url: 'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/{lz}/{x}/{y}.jpg',
                    levelOffset: 1, tileSize: 512, maxLevel: 15,
                    credit: 'NASA/GSFC/Arizona State University - LROC QuickMap',
                    link: 'https://quickmap.lroc.asu.edu',
                },
                trek('trek-lro-wac', 'NASA Moon Trek (LRO WAC mosaic)',
                    'Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02', 8,
                    'NASA/GSFC/Arizona State University - LRO WAC via NASA Moon Trek'),
                usgs('usgs-lroc-wac', 'LROC WAC mosaic', '/maps/earth/moon_simp_cyl.map', 'LROC_WAC',
                    'NASA/GSFC/Arizona State University', 8),
            ],
            // Quantized mesh whose layer.json sits above /mesh and declares scheme
            // "slippyMap" (Y=0 north), levels 0-15 and vertex normals; without it Cesium
            // guesses TMS rows and flips the terrain.
            terrain: {
                name: 'LOLA DEM (LROC QuickMap)',
                url: 'https://dem-tiles.b-cdn.net/lunar/qts_demstack/lunar-fulleqc',
                link: 'https://quickmap.lroc.asu.edu',
            },
        },
        {
            id: 'mars', name: 'Mars', radiiM: [3396190, 3396190, 3376200],
            gazetteer: 'Mars', stacTarget: 'mars',
            imagery: [
                trek('trek-viking-mdim21-color', 'Viking MDIM 2.1 colour (NASA Mars Trek)',
                    'Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m', 7, 'NASA/JPL/USGS - Viking via NASA Mars Trek'),
                trek('trek-mola-color-shade', 'MOLA colour shaded relief (NASA Mars Trek)',
                    'Mars/EQ/Mars_MGS_MOLA_ClrShade_merge_global_463m', 7, 'NASA/JPL/GSFC - MOLA via NASA Mars Trek'),
                usgs('usgs-mdim21-color', 'Viking MDIM 2.1 colour', '/maps/mars/mars_simp_cyl.map', 'MDIM21_color', 'NASA/JPL'),
                usgs('usgs-mola-color', 'MOLA colour elevation', '/maps/mars/mars_simp_cyl.map', 'MOLA_color', 'NASA/GSFC'),
                usgs('usgs-themis', 'THEMIS day IR', '/maps/mars/mars_simp_cyl.map', 'THEMIS', 'NASA/JPL/ASU'),
            ],
        },
        {
            id: 'mercury', name: 'Mercury', radiiM: [2439400, 2439400, 2439400],
            gazetteer: 'Mercury', stacTarget: 'mercury',
            imagery: [
                trek('trek-messenger-color', 'MESSENGER enhanced colour (NASA Mercury Trek)',
                    'Mercury/EQ/Mercury_MESSENGER_MDIS_Basemap_EnhancedColor_Mosaic_Global_665m', 7,
                    'NASA/JHU APL/CIW - MESSENGER via NASA Mercury Trek'),
                trek('trek-messenger-bdr', 'MESSENGER basemap 166 m (NASA Mercury Trek)',
                    'Mercury/EQ/Mercury_MESSENGER_MDIS_Basemap_BDR_Mosaic_Global_166m', 7,
                    'NASA/JHU APL/CIW - MESSENGER via NASA Mercury Trek'),
                usgs('usgs-messenger-color', 'MESSENGER colour mosaic', '/maps/mercury/mercury_simp_cyl.map', 'MESSENGER_Color', 'NASA/JHU APL/CIW'),
                usgs('usgs-messenger', 'MESSENGER basemap', '/maps/mercury/mercury_simp_cyl.map', 'MESSENGER', 'NASA/JHU APL'),
            ],
        },
        {
            id: 'venus', name: 'Venus', radiiM: [6051800, 6051800, 6051800],
            gazetteer: 'Venus', stacTarget: 'venus',
            imagery: [
                usgs('usgs-magellan-color', 'Magellan C3-MDIR colour', '/maps/venus/venus_simp_cyl.map', 'MAGELLAN_color', 'NASA/JPL'),
                usgs('usgs-magellan', 'Magellan FMAP', '/maps/venus/venus_simp_cyl.map', 'MAGELLAN', 'NASA/JPL'),
            ],
        },
        {
            id: 'io', name: 'Io', radiiM: [1821600, 1821600, 1821600],
            gazetteer: 'Io', stacTarget: 'io',
            imagery: [usgs('usgs-ssi-color', 'Galileo SSI colour', '/maps/jupiter/io_simp_cyl.map', 'SSI_color', 'NASA/JPL')],
        },
        {
            id: 'europa', name: 'Europa', radiiM: [1560800, 1560800, 1560800],
            gazetteer: 'Europa', stacTarget: 'europa',
            imagery: [usgs('usgs-galileo-voyager', 'Galileo / Voyager', '/maps/jupiter/europa_simp_cyl.map', 'GALILEO_VOYAGER', 'NASA/JPL')],
        },
        {
            id: 'ganymede', name: 'Ganymede', radiiM: [2631200, 2631200, 2631200],
            gazetteer: 'Ganymede', stacTarget: 'ganymede',
            imagery: [usgs('usgs-galileo-voyager', 'Galileo / Voyager', '/maps/jupiter/ganymede_simp_cyl.map', 'GALILEO_VOYAGER', 'NASA/JPL')],
        },
        {
            id: 'callisto', name: 'Callisto', radiiM: [2410300, 2410300, 2410300],
            gazetteer: 'Callisto', stacTarget: 'callisto',
            imagery: [usgs('usgs-galileo-voyager', 'Galileo / Voyager', '/maps/jupiter/callisto_simp_cyl.map', 'GALILEO_VOYAGER', 'NASA/JPL')],
        },
        {
            id: 'titan', name: 'Titan', radiiM: [2574730, 2574730, 2574730],
            gazetteer: 'Titan', stacTarget: 'titan',
            imagery: [
                usgs('usgs-iss', 'Cassini ISS mosaic', '/maps/saturn/titan_simp_cyl.map', 'Titan_ISS_Controlled_Mosaic', 'NASA/JPL/SSI'),
                usgs('usgs-hisar', 'Cassini HiSAR mosaic', '/maps/saturn/titan_simp_cyl.map', 'Titan_HiSAR_Mosaic', 'NASA/JPL'),
            ],
        },
        {
            id: 'pluto', name: 'Pluto', radiiM: [1188300, 1188300, 1188300],
            gazetteer: 'Pluto', stacTarget: 'pluto',
            imagery: [
                usgs('usgs-nh-mosaic', 'New Horizons mosaic', '/maps/pluto/pluto_simp_cyl.map', 'NEWHORIZONS_PLUTO_MOSAIC', 'NASA/JHU APL/SwRI'),
                usgs('usgs-nh-color', 'New Horizons colour shaded relief', '/maps/pluto/pluto_simp_cyl.map', 'NEWHORIZONS_PLUTO_ClrSHADE', 'NASA/JHU APL/SwRI'),
            ],
        },
        {
            id: 'charon', name: 'Charon', radiiM: [606000, 606000, 606000],
            gazetteer: 'Charon', stacTarget: 'charon',
            imagery: [usgs('usgs-nh-mosaic', 'New Horizons mosaic', '/maps/pluto/charon_simp_cyl.map', 'NEWHORIZONS_CHARON_MOSAIC', 'NASA/JHU APL/SwRI')],
        },
    ];

    const byId = new Map(BODIES.map((b) => [b.id, b]));

    /** The body with this id, or undefined. */
    const get = (id) => byId.get(String(id || '').toLowerCase());

    /** Mean radius (2a + c) / 3 in metres, for spherical distance maths. */
    const meanRadius = (body) => (2 * body.radiiM[0] + body.radiiM[2]) / 3;

    /** Opening camera target: the body's `home`, else 0°/0°, from ~1.7 radii up (whole disc in view). */
    function homeView(body) {
        const home = body.home || { lon: 0, lat: 0 };
        return { lon: home.lon, lat: home.lat, heightM: Math.round(1.73 * body.radiiM[0]) };
    }

    function cesiumEllipsoid(body, Cesium) {
        const [a, b, c] = body.radiiM;
        return new Cesium.Ellipsoid(a, b, c);
    }

    /** A URL that answers 200 when the source is up: its level-0 western tile. */
    function probeUrl(source) {
        if (source.type === 'wms') {
            const q = new URLSearchParams({
                map: source.map, SERVICE: 'WMS', VERSION: '1.1.1', REQUEST: 'GetMap', STYLES: '',
                LAYERS: source.layer, SRS: 'EPSG:4326', FORMAT: 'image/png', WIDTH: '64', HEIGHT: '64',
                BBOX: '-180,-90,0,90',
            });
            return `${source.url}?${q}`;
        }
        return source.url
            .replace('{lz}', String(source.levelOffset || 0))
            .replace('{z}', '0').replace('{x}', '0').replace('{y}', '0');
    }

    function imageryProvider(source, ellipsoid, Cesium) {
        const tilingScheme = new Cesium.GeographicTilingScheme({ ellipsoid });
        const credit = new Cesium.Credit(source.credit, true);
        const size = source.tileSize || 256;
        if (source.type === 'wms') {
            return new Cesium.WebMapServiceImageryProvider({
                url: source.url,
                layers: source.layer,
                parameters: { map: source.map, format: 'image/png', transparent: false, styles: '' },
                tilingScheme, tileWidth: size, tileHeight: size, maximumLevel: source.maxLevel, credit,
            });
        }
        const offset = source.levelOffset || 0;
        return new Cesium.UrlTemplateImageryProvider({
            url: source.url,
            customTags: { lz: (provider, x, y, level) => level + offset },
            tilingScheme, tileWidth: size, tileHeight: size, maximumLevel: source.maxLevel, credit,
        });
    }

    /** STAC collections about this body (targets are matched case-insensitively). */
    function stacCollectionsFor(body, collections) {
        const target = body.stacTarget.toLowerCase();
        return collections.filter((c) => {
            const targets = c.summaries?.['ssys:targets'] || c['ssys:targets'] || [];
            return targets.some((t) => String(t).toLowerCase() === target);
        });
    }

    return {
        BODIES,
        get,
        meanRadius,
        homeView,
        cesiumEllipsoid,
        probeUrl,
        imageryProvider,
        stacCollectionsFor,
    };
});
