// Run: docker run --rm -v "$PWD":/w -w /w node:22-alpine node --test 'tests/js/*.test.js'
const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../../staticfiles/web/js/planet-bodies.js');

/** Just enough Cesium to record what the registry builds. */
const record = (kind) => function (...args) { this.kind = kind; this.args = args; };
const StubCesium = {
    Ellipsoid: function (x, y, z) { this.radii = { x, y, z }; },
    GeographicTilingScheme: record('tiling'),
    Credit: record('credit'),
    WebMapServiceImageryProvider: record('wms'),
    UrlTemplateImageryProvider: record('xyz'),
};

test('every body has a unique id, sane radii and at least one imagery source', () => {
    const ids = P.BODIES.map((b) => b.id);
    assert.equal(new Set(ids).size, ids.length);
    for (const b of P.BODIES) {
        const [a, bb, c] = b.radiiM;
        assert.ok(a > 0 && bb === a && c > 0 && c <= a, `${b.id} radii`);
        assert.ok(b.imagery.length >= 1, `${b.id} imagery`);
        assert.ok(b.gazetteer && b.stacTarget, `${b.id} names`);
        const sourceIds = b.imagery.map((s) => s.id);
        assert.equal(new Set(sourceIds).size, sourceIds.length, `${b.id} source ids`);
    }
});

test('the USGS Astrogeology layer list is complete', () => {
    const wms = P.BODIES.flatMap((b) => b.imagery.filter((s) => s.type === 'wms').map((s) => `${b.id}:${s.layer}`));
    for (const want of [
        'mercury:MESSENGER_Color', 'mercury:MESSENGER', 'venus:MAGELLAN', 'venus:MAGELLAN_color',
        'io:SSI_color', 'europa:GALILEO_VOYAGER', 'ganymede:GALILEO_VOYAGER', 'callisto:GALILEO_VOYAGER',
        'titan:Titan_ISS_Controlled_Mosaic', 'titan:Titan_HiSAR_Mosaic', 'pluto:NEWHORIZONS_PLUTO_MOSAIC',
        'pluto:NEWHORIZONS_PLUTO_ClrSHADE', 'charon:NEWHORIZONS_CHARON_MOSAIC',
        'moon:LROC_WAC', 'mars:MDIM21_color', 'mars:MOLA_color',
    ]) assert.ok(wms.includes(want), want);
});

test('sources are https, with the fields their type needs', () => {
    for (const b of P.BODIES) for (const s of b.imagery) {
        assert.match(s.url, /^https:\/\//, s.id);
        assert.ok(s.credit && s.link && s.maxLevel > 0, s.id);
        if (s.type === 'wms') {
            assert.match(s.map, new RegExp(`^/maps/\\w+/${b.id}_simp_cyl\\.map$`), s.id);
            assert.ok(s.layer, s.id);
        } else {
            assert.equal(s.type, 'xyz', s.id);
            assert.match(s.url, /\{x\}.*\{y\}|\{y\}.*\{x\}/, s.id);
            assert.equal(s.url.includes('{lz}'), Boolean(s.levelOffset), `${s.id}: {lz} goes with levelOffset`);
        }
    }
});

test('get is case-insensitive and rejects unknown bodies', () => {
    assert.equal(P.get('Mars').name, 'Mars');
    assert.equal(P.get('earth'), undefined);
    assert.equal(P.get(undefined), undefined);
});

test('meanRadius and homeView', () => {
    assert.equal(P.meanRadius(P.get('moon')), 1737400);
    assert.equal(Math.round(P.meanRadius(P.get('mars'))), 3389527);
    assert.deepEqual(P.homeView(P.get('moon')), { lon: 23.47297, lat: 0.67408, heightM: 3005702 });
    assert.deepEqual(P.homeView(P.get('europa')), { lon: 0, lat: 0, heightM: 2700184 });
});

test('probeUrl asks for the level-0 western tile', () => {
    const moon = P.get('moon');
    assert.equal(P.probeUrl(moon.imagery[0]),
        'https://lroc-tiles.quickmap.io/tiles/wac_nac_nacroi/lunar-fulleqc/1/0/0.jpg');
    assert.equal(P.probeUrl(moon.imagery[1]),
        'https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/0/0/0.jpg');
    const wms = new URL(P.probeUrl(P.get('titan').imagery[0]));
    assert.equal(wms.searchParams.get('map'), '/maps/saturn/titan_simp_cyl.map');
    assert.equal(wms.searchParams.get('LAYERS'), 'Titan_ISS_Controlled_Mosaic');
    assert.equal(wms.searchParams.get('BBOX'), '-180,-90,0,90');
});

test('cesiumEllipsoid and imageryProvider build on the body ellipsoid', () => {
    const mars = P.get('mars');
    const ellipsoid = P.cesiumEllipsoid(mars, StubCesium);
    assert.deepEqual(ellipsoid.radii, { x: 3396190, y: 3396190, z: 3376200 });

    const wms = P.imageryProvider(mars.imagery.find((s) => s.type === 'wms'), ellipsoid, StubCesium);
    assert.equal(wms.kind, 'wms');
    const opts = wms.args[0];
    assert.equal(opts.url, 'https://planetarymaps.usgs.gov/cgi-bin/mapserv');
    assert.equal(opts.layers, 'MDIM21_color');
    assert.equal(opts.parameters.map, '/maps/mars/mars_simp_cyl.map');
    assert.equal(opts.tilingScheme.args[0].ellipsoid, ellipsoid);

    const lroc = P.imageryProvider(P.get('moon').imagery[0], ellipsoid, StubCesium);
    assert.equal(lroc.kind, 'xyz');
    assert.equal(lroc.args[0].tileWidth, 512);
    assert.equal(lroc.args[0].customTags.lz(null, 0, 0, 3), 4);
});

test('stacCollectionsFor matches targets whatever their case', () => {
    const collections = [
        { id: 'lola', summaries: { 'ssys:targets': ['moon'] } },
        { id: 'kaguya', summaries: { 'ssys:targets': ['Moon'] } },
        { id: 'hirise', summaries: { 'ssys:targets': ['Mars'] } },
        { id: 'untagged' },
    ];
    assert.deepEqual(P.stacCollectionsFor(P.get('moon'), collections).map((c) => c.id), ['lola', 'kaguya']);
    assert.deepEqual(P.stacCollectionsFor(P.get('mars'), collections).map((c) => c.id), ['hirise']);
});
