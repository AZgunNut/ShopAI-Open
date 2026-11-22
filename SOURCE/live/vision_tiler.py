#!/usr/bin/env python3

from pathlib import Path

from PIL import Image

import memory_guard
import vision_tile_store


def save_png_atomic(image, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".png.tmp")

    image.save(
        temporary,
        format="PNG",
        optimize=False,
    )

    temporary.replace(destination)


def materialize_tiles(job_id):
    job_dir = (
        vision_tile_store.ACTIVE_JOBS
        / str(job_id)
    )

    manifest = vision_tile_store.load_manifest(job_id)
    master = job_dir / manifest["master_file"]

    if not master.is_file():
        raise FileNotFoundError(master)

    manifest["status"] = "tiling"
    manifest["tile_images_ready"] = 0

    vision_tile_store.atomic_json_write(
        job_dir / "manifest.json",
        manifest,
    )

    with Image.open(master) as image:
        image.load()

        actual_size = image.size
        expected_size = (
            manifest["image_width"],
            manifest["image_height"],
        )

        if actual_size != expected_size:
            raise RuntimeError(
                "Master-image dimensions changed: "
                f"expected {expected_size}, got {actual_size}"
            )

        ready = 0

        for tile in manifest["tiles"]:
            memory_guard.wait_for_safe_start()

            relative = (
                Path("tiles")
                / f"{tile['tile_id']}.png"
            )

            destination = job_dir / relative

            if not destination.is_file():
                left = tile["x"]
                top = tile["y"]
                right = left + tile["width"]
                bottom = top + tile["height"]

                cropped = image.crop(
                    (left, top, right, bottom)
                )

                try:
                    save_png_atomic(
                        cropped,
                        destination,
                    )
                finally:
                    cropped.close()

            tile["image_file"] = str(relative)
            ready += 1
            manifest["tile_images_ready"] = ready
            manifest["updated_at"] = (
                vision_tile_store.utc_now()
            )

            vision_tile_store.atomic_json_write(
                job_dir / "manifest.json",
                manifest,
            )

    manifest["status"] = "ready_for_analysis"
    manifest["updated_at"] = vision_tile_store.utc_now()

    vision_tile_store.atomic_json_write(
        job_dir / "manifest.json",
        manifest,
    )

    return manifest


def create_tiled_job(
    job_id,
    source,
    tile_size=1024,
    overlap=64,
):
    source = Path(source).expanduser().resolve()

    with Image.open(source) as image:
        width, height = image.size

    vision_tile_store.create_job(
        job_id=job_id,
        source=source,
        image_width=width,
        image_height=height,
        tile_size=tile_size,
        overlap=overlap,
    )

    return materialize_tiles(job_id)
