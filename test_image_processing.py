import io
import os
from pathlib import Path

from PIL import Image
from werkzeug.datastructures import FileStorage

from image_utils import compress_existing_image, save_upload, thumbnail_filename


def _image_upload(size=(3000, 1800), image_format="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", size, (180, 80, 40)).save(stream, format=image_format)
    stream.seek(0)
    return FileStorage(stream=stream, filename="proof.png", content_type="image/png")


def test_upload_is_compressed_and_thumbnail_is_created(tmp_path):
    filename = save_upload(_image_upload(), str(tmp_path))

    assert filename.endswith(".jpg")
    original = tmp_path / filename
    thumbnail = tmp_path / thumbnail_filename(filename)
    assert original.exists()
    assert thumbnail.exists()

    with Image.open(original) as image:
        assert image.format == "JPEG"
        assert image.width <= 2000
        assert image.height <= 2000
    with Image.open(thumbnail) as image:
        assert image.format == "JPEG"
        assert image.width <= 320
        assert image.height <= 320
    assert os.path.getsize(thumbnail) < os.path.getsize(original)


def test_invalid_image_is_rejected_without_files(tmp_path):
    upload = FileStorage(
        stream=io.BytesIO(b"not an image"),
        filename="fake.jpg",
        content_type="image/jpeg",
    )

    assert save_upload(upload, str(tmp_path)) == ""
    assert list(tmp_path.rglob("*")) == []


def test_historical_png_is_resized_in_place_without_format_change(tmp_path):
    source = tmp_path / "historical.png"
    Image.effect_noise((3000, 1800), 80).convert("RGB").save(source, format="PNG")
    before = source.stat().st_size

    saved = compress_existing_image(str(source))

    assert saved > 0
    assert source.stat().st_size < before
    if os.name != "nt":
        assert source.stat().st_mode & 0o777 == 0o644
    with Image.open(source) as image:
        assert image.format == "PNG"
        assert image.width <= 2000
        assert image.height <= 2000


def test_admin_templates_load_thumbnail_and_link_original():
    template_dir = Path(__file__).parent / "templates"
    for template_name in ("admin_products.html", "product_form.html", "order_detail.html"):
        source = (template_dir / template_name).read_text(encoding="utf-8")
        assert "|thumbnail" in source
        assert "target=\"_blank\"" in source
