#!/usr/bin/env python3

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "ShopAI"
ACTIVE_JOBS = ROOT / "state" / "vision-jobs"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def atomic_json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def tile_ranges(length, tile_size, overlap):
    if length <= 0:
        raise ValueError("Image dimension must be positive.")

    if tile_size <= 0:
        raise ValueError("Tile size must be positive.")

    if overlap < 0 or overlap >= tile_size:
        raise ValueError(
            "Overlap must be at least zero and smaller than tile size."
        )

    stride = tile_size - overlap
    ranges = []
    start = 0

    while start < length:
        size = min(tile_size, length - start)
        ranges.append((start, size))

        if start + size >= length:
            break

        start += stride

    return ranges


def create_job(
    job_id,
    source,
    image_width,
    image_height,
    tile_size=1024,
    overlap=64,
):
    source = Path(source).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(source)

    job_dir = ACTIVE_JOBS / str(job_id)

    if job_dir.exists():
        raise FileExistsError(job_dir)

    job_dir.mkdir(parents=True)

    master_name = "master" + source.suffix.lower()
    master_path = job_dir / master_name
    shutil.copy2(source, master_path)

    x_ranges = tile_ranges(
        int(image_width),
        int(tile_size),
        int(overlap),
    )

    y_ranges = tile_ranges(
        int(image_height),
        int(tile_size),
        int(overlap),
    )

    tiles = []
    tile_number = 0

    for y, height in y_ranges:
        for x, width in x_ranges:
            tile_number += 1
            tile_id = f"tile-{tile_number:06d}"

            tiles.append({
                "tile_id": tile_id,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "status": "pending",
                "result_file": f"results/{tile_id}.json",
            })

    now = utc_now()

    manifest = {
        "schema_version": 1,
        "job_id": str(job_id),
        "status": "processing",
        "created_at": now,
        "updated_at": now,
        "master_file": master_name,
        "master_sha256": sha256_file(master_path),
        "image_width": int(image_width),
        "image_height": int(image_height),
        "tile_size": int(tile_size),
        "overlap": int(overlap),
        "tile_count": len(tiles),
        "completed_tiles": 0,
        "tiles": tiles,
    }

    atomic_json_write(
        job_dir / "manifest.json",
        manifest,
    )

    return manifest


def load_manifest(job_id):
    path = ACTIVE_JOBS / str(job_id) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def next_pending_tile(job_id):
    manifest = load_manifest(job_id)

    for tile in manifest["tiles"]:
        if tile["status"] == "pending":
            return tile

    return None


def save_tile_result(job_id, tile_id, result):
    job_dir = ACTIVE_JOBS / str(job_id)
    manifest = load_manifest(job_id)

    matches = [
        tile
        for tile in manifest["tiles"]
        if tile["tile_id"] == tile_id
    ]

    if len(matches) != 1:
        raise KeyError(tile_id)

    tile = matches[0]

    record = {
        "schema_version": 1,
        "job_id": str(job_id),
        "tile_id": tile_id,
        "coordinates": {
            "x": tile["x"],
            "y": tile["y"],
            "width": tile["width"],
            "height": tile["height"],
        },
        "saved_at": utc_now(),
        "result": result,
    }

    atomic_json_write(
        job_dir / tile["result_file"],
        record,
    )

    if tile["status"] != "completed":
        tile["status"] = "completed"
        manifest["completed_tiles"] += 1

    if manifest["completed_tiles"] == manifest["tile_count"]:
        manifest["status"] = "completed"

    manifest["updated_at"] = utc_now()

    atomic_json_write(
        job_dir / "manifest.json",
        manifest,
    )

    return record
