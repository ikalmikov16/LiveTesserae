#!/usr/bin/env python3
"""
Download the public-domain source data the `earth` pattern draws from.

Everything here is public domain (Natural Earth) or NASA-produced and free of
copyright restriction. Roughly 21 MB in total, written to backend/data/, which
is gitignored: it is redistributable but there is no reason to carry 18 MB of
PNG in the repo when one command re-fetches it.

Usage:
    python scripts/fetch_earth_data.py
    python scripts/fetch_earth_data.py --force   # re-download even if present
"""

import argparse
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

NE_BASE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
)
NASA_BASE = "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73934"

# (filename, url, what it is)
SOURCES = [
    (
        "ne_50m_land.geojson",
        f"{NE_BASE}/ne_50m_land.geojson",
        "Natural Earth 1:50m coastlines (public domain)",
    ),
    (
        "ne_50m_lakes.geojson",
        f"{NE_BASE}/ne_50m_lakes.geojson",
        "Natural Earth 1:50m lakes (public domain)",
    ),
    (
        "ne_50m_rivers_lake_centerlines.geojson",
        f"{NE_BASE}/ne_50m_rivers_lake_centerlines.geojson",
        "Natural Earth 1:50m river centrelines (public domain)",
    ),
    (
        "ne_50m_admin_0_countries_lakes.geojson",
        f"{NE_BASE}/ne_50m_admin_0_countries_lakes.geojson",
        "Natural Earth 1:50m countries, lakes as holes (public domain)",
    ),
    (
        "ne_50m_admin_0_boundary_lines_land.geojson",
        f"{NE_BASE}/ne_50m_admin_0_boundary_lines_land.geojson",
        "Natural Earth 1:50m country borders (public domain)",
    ),
    (
        "gebco_08_rev_bath_21600x10800.png",
        "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73963"
        "/gebco_08_rev_bath_21600x10800.png",
        "NASA Blue Marble / GEBCO bathymetry, 1 arcmin (no copyright)",
    ),
    (
        "gebco_08_rev_elev_21600x10800.png",
        f"{NASA_BASE}/gebco_08_rev_elev_21600x10800.png",
        "NASA Blue Marble / GEBCO land elevation, 1 arcmin (no copyright)",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Earth source data")
    parser.add_argument(
        "--force", action="store_true", help="Re-download files that already exist"
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Data directory: {DATA_DIR}")

    failed = []
    for name, url, what in SOURCES:
        dest = DATA_DIR / name
        if dest.exists() and not args.force:
            print(f"  have  {name} ({dest.stat().st_size / 1e6:.1f} MB)")
            continue
        print(f"  get   {name} — {what}")
        try:
            # Written to a temporary name first so an interrupted download cannot
            # leave a truncated file that later looks complete.
            tmp = dest.with_suffix(dest.suffix + ".part")
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(dest)
            print(f"        {dest.stat().st_size / 1e6:.1f} MB")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"        FAILED: {exc}")
            failed.append(name)

    if failed:
        print("\nCould not fetch: " + ", ".join(failed))
        return 1

    print("\nDone. Draw the plate with:")
    print("  python scripts/init_mosaic.py --pattern world --replace")
    print("  python scripts/render_chunks.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
