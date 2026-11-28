/* Recorded field readings (camera keyframe + laser target) for the Earth search page.
   The live picture-in-picture is unchanged. This layer only draws what
   /label/api/field-readings/ returns for the current view: each dot is coloured by
   the view the rover had of the map object, and its popup shows the keyframe label
   under the spectrometer's patch and whether the reading counted as evidence. */
(function () {
    var source = null;
    var timer = null;
    var stopped = false;

    function viewer() {
        return (window.AppState && window.AppState.viewer) || window.viewer || null;
    }

    /* Dot colour = which view the rover had of the map object under the laser; a white
       ring = the reading counted as evidence. */
    var VIEW_COLOURS = {
        top: "#4ade80",
        side: "#fbbf24",
        unknown: "#5eead4",
        face: "#a78bfa",
        under: "#f87171",
        conflict: "#f87171",
        none: "#f87171"
    };
    var VIEW_WORDS = {
        top: "its top, as the overhead image sees it",
        side: "its side",
        unknown: "not known (no hit height)",
        face: "a fence or wall face (no vote)",
        under: "below a canopy or roof (no vote)",
        conflict: "label and hit height disagree (no vote)",
        none: "sky (no vote)"
    };

    function esc(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c];
        });
    }

    function colourOf(props) {
        if (props.role !== "target") return "#94a3b8";
        if (props.link) return VIEW_COLOURS[props.link.view] || VIEW_COLOURS.unknown;
        return "#64748b";
    }

    function frameHtml(props) {
        var s = props.surface;
        var patch = s && s.patch;
        var html = "<div style=\"position:relative;display:inline-block;max-width:320px\">" +
            "<img src=\"" + esc(props.frame) + "\" alt=\"\" style=\"display:block;max-width:320px;width:100%\">";
        if (patch && patch.length === 3) {
            var d = patch[2];
            html += "<div style=\"position:absolute;border:2px solid #fde047;border-radius:50%;" +
                "box-sizing:border-box;left:" + ((patch[0] - d / 2) * 100) + "%;top:calc(" +
                (patch[1] * 100) + "% - " + (d / 2 / 0.75 * 100) + "%);width:" + (d * 100) +
                "%;height:" + (d / 0.75 * 100) + "%\"></div>" +
                "<div style=\"position:absolute;width:6px;height:6px;margin:-3px 0 0 -3px;border-radius:50%;" +
                "background:#ef4444;left:" + (patch[0] * 100) + "%;top:" + (patch[1] * 100) + "%\"></div>";
        }
        return html + "</div>";
    }

    function describe(props) {
        var lines = ["<b>" + esc(props.vehicle) + "</b> " + esc((props.captured || "").replace("T", " ").slice(0, 19)) +
            " UTC" + (props.role === "target" && props.range_m != null
                ? ", laser " + props.range_m.toFixed(2) + " m" : ", camera position (no laser target)")];
        var s = props.surface;
        if (s) {
            var shares = Object.keys(s.shares || {}).map(function (k) {
                return esc(k) + " " + Math.round(100 * s.shares[k]) + "%";
            }).join(", ");
            lines.push("Patch: <b>" + esc(s.label) + "</b>" + (shares ? " (" + shares + ")" : "") +
                (s.centre ? "; laser on <b>" + esc(s.centre) + "</b>" : "") +
                (s.from ? "; label copied from reading " + esc(s.from) : ""));
        } else if (props.frame) {
            lines.push("Patch: not labelled yet");
        }
        var k = props.link;
        if (k) {
            lines.push("Map object " + esc(k.entity) + ", now " + esc(k.entity_category) +
                (k.entity_score != null ? " " + k.entity_score.toFixed(2) : "") +
                (k.share_on_entity != null ? " (" + Math.round(100 * k.share_on_entity) + "% of the target on it)" : ""));
            lines.push("View: " + esc(VIEW_WORDS[k.view] || k.view) + (k.view_by ? ", from the " + esc(k.view_by) : ""));
            lines.push(k.usable ? "<b style=\"color:#16a34a\">Counted as evidence</b>"
                : "Not counted: " + k.why_not.map(esc).join("; "));
        } else if (props.unlinked) {
            lines.push("Not counted: " + esc(props.unlinked));
        }
        var html = lines.join("<br>");
        if (props.frame) {
            html += "<br>" + frameHtml(props) +
                "<br><small>Yellow circle: the spectrometer's patch. Red dot: the laser.</small>";
        }
        return html;
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
            var description = describe(props);
            var colour = Cesium.Color.fromCssColorString(colourOf(props));
            var counted = !!(props.link && props.link.usable);
            var existing = source.entities.getById(id);
            var position = Cesium.Cartesian3.fromDegrees(coords[0], coords[1]);
            if (existing) {
                existing.position = position;
                existing.description = description;
                existing.point.color = colour;
                existing.point.outlineWidth = counted ? 2 : 0;
                return;
            }
            source.entities.add({
                id: id,
                name: "Field reading " + props.id,
                position: position,
                description: description,
                point: {
                    pixelSize: props.role === "target" ? 10 : 7,
                    color: colour,
                    outlineColor: Cesium.Color.WHITE,
                    outlineWidth: counted ? 2 : 0,
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
