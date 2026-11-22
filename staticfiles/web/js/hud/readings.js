/* Recorded field readings (camera keyframe + laser target) for the Earth search page.
   The live picture-in-picture is unchanged. This layer only draws what
   /label/api/field-readings/ returns for the current view. */
(function () {
    var source = null;
    var timer = null;
    var stopped = false;

    function viewer() {
        return (window.AppState && window.AppState.viewer) || window.viewer || null;
    }

    function draw(collection) {
        var v = viewer();
        if (!v || !collection || !collection.features) return;
        if (!source) {
            source = new Cesium.CustomDataSource("field-readings");
            v.dataSources.add(source);
        }
        var keep = {};
        collection.features.forEach(function (feature) {
            var coords = feature.geometry && feature.geometry.coordinates;
            var props = feature.properties || {};
            if (!coords) return;
            var id = "reading-" + props.id;
            keep[id] = true;
            var up = Number.isFinite(props.up_m) ? props.up_m : 0;
            var text = props.vehicle + (props.role === "target" && props.range_m != null
                ? " laser " + props.range_m.toFixed(2) + " m" : " camera");
            var description = text;
            if (props.frame) {
                description += "<br><img src=\"" + props.frame + "\" alt=\"\" style=\"max-width:320px\">";
            }
            var existing = source.entities.getById(id);
            var position = Cesium.Cartesian3.fromDegrees(coords[0], coords[1]);
            if (existing) {
                existing.position = position;
                existing.description = description;
                return;
            }
            source.entities.add({
                id: id,
                position: position,
                description: description,
                point: {
                    pixelSize: props.role === "target" ? 10 : 7,
                    color: props.role === "target"
                        ? Cesium.Color.fromCssColorString("#5eead4")
                        : Cesium.Color.fromCssColorString("#94a3b8"),
                    heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY
                },
                properties: { up: up }
            });
            var entity = source.entities.getById(id);
            if (entity && up) entity.position = Cesium.Cartesian3.fromDegrees(coords[0], coords[1], up);
        });
        source.entities.values.slice().forEach(function (entity) {
            if (!keep[entity.id]) source.entities.remove(entity);
        });
    }

    function load() {
        var v = viewer();
        if (!v || stopped) return;
        var rect = v.camera.computeViewRectangle();
        if (!rect) return;
        var west = Cesium.Math.toDegrees(rect.west);
        var south = Cesium.Math.toDegrees(rect.south);
        var east = Cesium.Math.toDegrees(rect.east);
        var north = Cesium.Math.toDegrees(rect.north);
        if (east - west > 3 || north - south > 3) return;
        var query = "south=" + south + "&west=" + west + "&north=" + north + "&east=" + east;
        fetch("/label/api/field-readings/?" + query, { credentials: "same-origin" })
            .then(function (resp) {
                if (resp.status === 401) { stopped = true; return null; }
                if (!resp.ok) return null;
                return resp.json();
            })
            .then(function (body) { if (body) draw(body); })
            .catch(function () {});
    }

    function schedule() {
        if (stopped) return;
        clearTimeout(timer);
        timer = setTimeout(load, 1500);
    }

    function start() {
        var v = viewer();
        if (!v) { setTimeout(start, 1000); return; }
        v.camera.moveEnd.addEventListener(schedule);
        schedule();
    }

    if (document.readyState === "complete") start();
    else window.addEventListener("load", start);
})();
