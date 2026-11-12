"""Safely compress historical originals and create their thumbnails.

Run only after backing up the uploads directory:
    python3 compress_historical_images.py
"""
import os
import sys

from config import UPLOAD_FOLDER
from image_utils import compress_existing_image, create_thumbnail, thumbnail_filename


def compress_all(upload_folder=UPLOAD_FOLDER, shard=0, shards=1):
    processed = 0
    reduced = 0
    saved_bytes = 0
    failed = 0

    all_filenames = [
        name
        for name in os.listdir(upload_folder)
        if os.path.isfile(os.path.join(upload_folder, name))
    ]
    filenames = [
        name for index, name in enumerate(all_filenames) if index % shards == shard
    ]
    total = len(filenames)

    for index, filename in enumerate(filenames, 1):
        source = os.path.join(upload_folder, filename)
        thumb_path = os.path.join(
            upload_folder, *thumbnail_filename(filename).split("/")
        )
        # A thumbnail is written only after its original has been processed,
        # so it also acts as a safe resume marker after an interrupted run.
        if os.path.exists(thumb_path):
            continue
        try:
            saved = compress_existing_image(source)
            processed += 1
            if saved:
                reduced += 1
                saved_bytes += saved

            create_thumbnail(source, upload_folder, filename)
        except Exception as exc:
            failed += 1
            print("Failed: {} ({})".format(filename, exc), flush=True)

        if index % 250 == 0 or index == total:
            print(
                "Progress: {}/{}; reduced: {}; saved: {:.1f} MB; failed: {}".format(
                    index, total, reduced, saved_bytes / 1048576.0, failed
                ),
                flush=True,
            )

    print(
        "Finished: processed={}, reduced={}, saved={:.1f} MB, failed={}".format(
            processed, reduced, saved_bytes / 1048576.0, failed
        ),
        flush=True,
    )
    return processed, reduced, saved_bytes, failed


if __name__ == "__main__":
    shard_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    shards_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    if shard_arg < 0 or shards_arg < 1 or shard_arg >= shards_arg:
        raise SystemExit("Usage: compress_historical_images.py [shard] [shards]")
    compress_all(shard=shard_arg, shards=shards_arg)
