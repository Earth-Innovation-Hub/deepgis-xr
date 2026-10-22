#!/usr/bin/env python3
"""
Build the planetary gazetteers the AI pilot uses to resolve place names off Earth.

Downloads the IAU Gazetteer of Planetary Nomenclature centre points that USGS
publishes per body, keeps adopted names, and writes
staticfiles/web/geo/nomenclature/<body>.json as
{"source": ..., "features": [[name, lat, lon, diameter_km, type], ...]},
largest first, with planetocentric latitude and east longitude in -180..180.

    python3 scripts/build_planet_nomenclature.py [moon mars ...]
"""

import io
import json
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

BODIES = ("moon", "mars", "mercury", "venus", "io", "europa", "ganymede",
          "callisto", "titan", "pluto", "charon")
URL = "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/{}_nomenclature_center_pts.zip"
SOURCE = ("IAU/USGS Gazetteer of Planetary Nomenclature, "
          "https://planetarynames.wr.usgs.gov/")
OUT = Path(__file__).resolve().parent.parent / "staticfiles" / "web" / "geo" / "nomenclature"


def read_dbf(data):
    """Records of a dBase III table as dicts of stripped strings."""
    count = struct.unpack("<I", data[4:8])[0]
    header_len, record_len = struct.unpack("<HH", data[8:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0")[0].decode()
        fields.append((name, data[pos + 16]))
        pos += 32
    rows = []
    for i in range(count):
        rec = data[header_len + i * record_len: header_len + (i + 1) * record_len]
        if rec[:1] == b"*":  # deleted
            continue
        row, off = {}, 1
        for name, size in fields:
            row[name] = rec[off:off + size].decode("utf-8", "replace").strip()
            off += size
        rows.append(row)
    return rows


def number(s):
    try:
        return float(s)
    except ValueError:
        return None


def build(body):
    with urllib.request.urlopen(URL.format(body.upper()), timeout=120) as resp:
        archive = zipfile.ZipFile(io.BytesIO(resp.read()))
    dbf = next(n for n in archive.namelist() if n.lower().endswith(".dbf"))
    features = []
    for r in read_dbf(archive.read(dbf)):
        lat, lon = number(r.get("center_lat", "")), number(r.get("center_lon", ""))
        name = r.get("clean_name") or r.get("name")
        if not name or lat is None or lon is None or "adopted" not in r.get("approval", "").lower():
            continue
        lon = (lon + 180) % 360 - 180
        diameter = number(r.get("diameter", "")) or 0.0
        features.append([name, round(lat, 4), round(lon, 4), round(diameter, 2), r.get("type", "")])
    features.sort(key=lambda f: -f[3])
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{body}.json"
    path.write_text(json.dumps({"source": SOURCE, "features": features},
                               ensure_ascii=False, separators=(",", ":")))
    return path, len(features)


if __name__ == "__main__":
    for body in sys.argv[1:] or BODIES:
        path, n = build(body)
        print(f"{body}: {n} names -> {path.name} ({path.stat().st_size // 1024} KB)")
