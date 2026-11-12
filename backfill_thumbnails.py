"""Generate missing thumbnails for images already stored in uploads/.

Usage:
    python3 backfill_thumbnails.py
"""
import os

from config import UPLOAD_FOLDER
from image_utils import THUMBNAIL_DIR, create_thumbnail, thumbnail_filename


def backfill(upload_folder=UPLOAD_FOLDER):
    created = 0
    skipped = 0
    failed = 0

    os.makedirs(os.path.join(upload_folder, THUMBNAIL_DIR), exist_ok=True)
    for filename in os.listdir(upload_folder):
        source = os.path.join(upload_folder, filename)
        if not os.path.isfile(source):
            continue

        thumb = os.path.join(upload_folder, *thumbnail_filename(filename).split("/"))
        if os.path.exists(thumb):
            skipped += 1
            continue

        try:
            create_thumbnail(source, upload_folder, filename)
            created += 1
        except Exception as exc:
            failed += 1
            print("Failed: {} ({})".format(filename, exc))

    print("Created: {}, skipped: {}, failed: {}".format(created, skipped, failed))
    return created, skipped, failed


if __name__ == "__main__":
    backfill()
