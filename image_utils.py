import os
import tempfile
import uuid

from PIL import Image, ImageOps

try:
    from PIL import UnidentifiedImageError
except ImportError:  # Pillow < 7, including the Python 3.6 production package
    UnidentifiedImageError = OSError

from config import ALLOWED_EXTENSIONS


ORIGINAL_MAX_SIZE = (2000, 2000)
THUMBNAIL_MAX_SIZE = (320, 320)
THUMBNAIL_DIR = "thumbnails"
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


def _allowed_filename(filename):
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def thumbnail_filename(filename):
    """Return the upload-relative thumbnail path for a stored image."""
    if not filename:
        return ""
    stem = os.path.splitext(os.path.basename(filename))[0]
    return THUMBNAIL_DIR + "/" + stem + ".jpg"


def _flatten_to_rgb(image):
    """Convert any Pillow mode to RGB, using white behind transparency."""
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _exif_transpose(image):
    """Apply EXIF orientation, including on the older Pillow in production."""
    if hasattr(ImageOps, "exif_transpose"):
        return ImageOps.exif_transpose(image)
    try:
        exif = image._getexif() or {}
        orientation = exif.get(274)
    except (AttributeError, KeyError, TypeError, ValueError):
        return image
    operations = {
        2: (Image.FLIP_LEFT_RIGHT,),
        3: (Image.ROTATE_180,),
        4: (Image.FLIP_TOP_BOTTOM,),
        5: (Image.FLIP_LEFT_RIGHT, Image.ROTATE_90),
        6: (Image.ROTATE_270,),
        7: (Image.FLIP_LEFT_RIGHT, Image.ROTATE_270),
        8: (Image.ROTATE_90,),
    }
    for operation in operations.get(orientation, ()):
        image = image.transpose(operation)
    return image


def _save_jpeg(image, destination, max_size, quality):
    image = _exif_transpose(image)
    image.thumbnail(max_size, LANCZOS)
    image = _flatten_to_rgb(image)
    image.save(
        destination,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
    )


def create_thumbnail(source_path, upload_folder, filename=None):
    """Create a thumbnail for an existing image and return its relative path."""
    filename = filename or os.path.basename(source_path)
    thumb_name = thumbnail_filename(filename)
    thumb_path = os.path.join(upload_folder, *thumb_name.split("/"))
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

    with Image.open(source_path) as image:
        _save_jpeg(image, thumb_path, THUMBNAIL_MAX_SIZE, quality=76)
    return thumb_name


def compress_existing_image(source_path, max_size=ORIGINAL_MAX_SIZE):
    """Compress an existing image in place, preserving its file extension.

    The replacement is written atomically and is only kept when it is smaller
    than the source.  Preserving the format keeps existing database filenames
    and Nginx content types valid.
    """
    extension = os.path.splitext(source_path)[1].lower()
    supported = {".jpg", ".jpeg", ".png", ".webp"}
    if extension not in supported:
        return 0

    original_size = os.path.getsize(source_path)
    directory = os.path.dirname(source_path)
    fd, temporary_path = tempfile.mkstemp(prefix=".compress-", dir=directory)
    os.close(fd)

    try:
        with Image.open(source_path) as image:
            image.load()
            image = _exif_transpose(image)
            image.thumbnail(max_size, LANCZOS)

            if extension in (".jpg", ".jpeg"):
                image = _flatten_to_rgb(image)
                image.save(
                    temporary_path,
                    format="JPEG",
                    quality=84,
                    optimize=True,
                    progressive=True,
                )
            elif extension == ".png":
                # Keep PNG lossless so screenshots and transparent product
                # images retain their text and alpha channel.
                if image.mode not in (
                    "1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"
                ):
                    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                image.save(
                    temporary_path,
                    format="PNG",
                    optimize=True,
                    compress_level=9,
                )
            else:
                image.save(
                    temporary_path,
                    format="WEBP",
                    quality=84,
                    method=6,
                )

        compressed_size = os.path.getsize(temporary_path)
        if compressed_size >= original_size:
            return 0
        os.replace(temporary_path, source_path)
        # mkstemp creates mode 0600.  Nginx runs as a separate user and must
        # retain read access after the atomic replacement.
        os.chmod(source_path, 0o644)
        temporary_path = None
        return original_size - compressed_size
    finally:
        if temporary_path:
            try:
                os.remove(temporary_path)
            except OSError:
                pass


def save_upload(file, upload_folder):
    """Validate, normalize and compress an upload, then create its thumbnail.

    The stored original is a high-quality JPEG with a bounded resolution.  The
    return value remains a single filename so existing database columns do not
    need a migration.
    """
    if not file or not _allowed_filename(file.filename):
        return ""

    filename = uuid.uuid4().hex + ".jpg"
    destination = os.path.join(upload_folder, filename)
    os.makedirs(upload_folder, exist_ok=True)

    try:
        file.stream.seek(0)
        with Image.open(file.stream) as image:
            image.load()
            _save_jpeg(image, destination, ORIGINAL_MAX_SIZE, quality=84)
        create_thumbnail(destination, upload_folder, filename)
        return filename
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        for path in (
            destination,
            os.path.join(upload_folder, *thumbnail_filename(filename).split("/")),
        ):
            try:
                os.remove(path)
            except OSError:
                pass
        return ""
