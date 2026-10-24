"""One-off pull of the OpenTopography-hosted Bishop lidar into COGs served by /label/api/pilot/topo/.

Run inside the deepgis-xr image (it has GDAL) with /raw on the big HDD and /out = deepgis-xr/data/topo.
Re-running skips finished downloads and finished COGs.
"""
import concurrent.futures as cf
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from osgeo import gdal

gdal.UseExceptions()
BASE = "https://opentopography.s3.sdsc.edu/raster"
# (dataset, product, output metres per pixel or None for native)
JOBS = [("CA14_Delano", "be", None), ("CA12_Lifton", "be", None), ("CA09_Whelley", "be", None),
        ("CA18_Scott", "hh", 0.5), ("CA19_Scott", "hh", 0.5)]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def listing(prefix):
    keys, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        x = urllib.request.urlopen(BASE + "?" + urllib.parse.urlencode(q), timeout=120).read().decode()
        keys += [(k, int(s)) for k, s in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", x, re.S)]
        m = re.search(r"<NextContinuationToken>([^<]+)<", x)
        if not m:
            return keys
        token = m.group(1)


def download(key, size):
    dest = os.path.join("/raw", key)
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return 0
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(f"{BASE}/{urllib.parse.quote(key)}", timeout=300) as r, \
                    open(dest + ".part", "wb") as f:
                while chunk := r.read(1 << 22):
                    f.write(chunk)
            if os.path.getsize(dest + ".part") != size:
                raise IOError("short download")
            os.replace(dest + ".part", dest)
            return size
        except Exception as e:
            log("retry", key, e)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"failed {key}")


def source(ds, prod):
    d = f"/raw/{ds}/{ds}_{prod}"
    tifs = sorted(n for n in os.listdir(d) if n.lower().endswith(".tif"))
    if tifs:
        vrt = f"/raw/{ds}/{ds}_{prod}.local.vrt"
        gdal.BuildVRT(vrt, [os.path.join(d, n) for n in tifs])
        return vrt
    return d  # Esri grid coverage directory


def build(ds, prod, res):
    out = f"/out/{ds}_{prod}.tif"
    if os.path.exists(out):
        done = gdal.Open(out)
        log("have", out, f"{done.RasterXSize}x{done.RasterYSize}", done.GetRasterBand(1).ComputeStatistics(True)[:3])
        return
    src = gdal.Open(source(ds, prod))
    b = src.GetRasterBand(1)
    res = res or abs(src.GetGeoTransform()[1])
    tmp = f"/raw/{ds}/{ds}_{prod}.utm.tif"
    log("warp", ds, prod, f"{src.RasterXSize}x{src.RasterYSize}", "->", res, "m")
    gdal.Warp(tmp, src, format="GTiff", dstSRS="EPSG:26911", xRes=res, yRes=res, targetAlignedPixels=True,
              resampleAlg="average" if res > abs(src.GetGeoTransform()[1]) * 1.01 else "near",
              srcNodata=b.GetNoDataValue(), dstNodata=-9999, outputType=gdal.GDT_Float32,
              multithread=True, warpMemoryLimit=2048, warpOptions=["NUM_THREADS=16"],
              creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=3", "BIGTIFF=IF_SAFER", "NUM_THREADS=16"])
    log("cog", out)
    gdal.Translate(out + ".part.tif", tmp, format="COG",
                   creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=YES", "BLOCKSIZE=512", "OVERVIEW_RESAMPLING=AVERAGE",
                                    "NUM_THREADS=ALL_CPUS", "BIGTIFF=IF_SAFER"])
    os.replace(out + ".part.tif", out)
    os.remove(tmp)
    done = gdal.Open(out)
    st = done.GetRasterBand(1).ComputeStatistics(True)
    log("done", out, f"{done.RasterXSize}x{done.RasterYSize}", f"{os.path.getsize(out) // 1000000} MB",
        "min/max/mean", [round(v, 1) for v in st[:3]])


def main():
    only = set(sys.argv[1:])
    jobs = [j for j in JOBS if not only or j[0] in only]
    for ds, prod, _ in jobs:
        keys = [(k, s) for k, s in listing(f"{ds}/{ds}_{prod}/")]
        total = sum(s for _, s in keys)
        log("download", ds, prod, len(keys), "files", total // 1000000, "MB")
        with cf.ThreadPoolExecutor(8) as ex:
            got = sum(ex.map(lambda ks: download(*ks), keys))
        log("downloaded", ds, prod, got // 1000000, "MB new")
    for job in jobs:
        build(*job)
    log("all done")


if __name__ == "__main__":
    main()
