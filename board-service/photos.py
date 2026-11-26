"""Board photo attachments. Uploads are decoded and re-encoded so no source metadata survives."""
import io
import math
import warnings

from PIL import Image, ImageCms, ImageMath
from pillow_heif import register_heif_opener

# Phones may send HEIC originals; libheif applies the stored rotation and reports orientation 1.
register_heif_opener()

MAX_FILES = 3
MAX_UPLOAD = 5 * 1024 * 1024
MAX_EDGE = 2000
QUALITY = 82
# The JPEG opener also returns multi-picture files as format "MPO".
FORMATS = ("JPEG", "PNG", "WEBP", "HEIF")
# JPEG decodes at a reduced scale (draft). HEIC decodes at full size but phones keep it under
# 50MP; other formats decode at full size and are mostly screenshots.
PIXEL_LIMITS = {"JPEG": 50_000_000, "MPO": 50_000_000, "HEIF": 50_000_000}
DEFAULT_PIXEL_LIMIT = 16_000_000
# A request may carry three full-size photos and the text fields with multipart overhead.
REQUEST_LIMIT = 24 * 1024 * 1024
# Werkzeug also applies the form memory limit to its multipart read buffer.
FORM_MEMORY = 512 * 1024
# Pillow's own guard only backs up the explicit per-format check below.
Image.MAX_IMAGE_PIXELS = max(PIXEL_LIMITS.values())
ORIENTATION = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
               4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
               6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
UNSUPPORTED = "JPG·PNG·WebP·HEIC 사진만 올릴 수 있습니다."
TOO_LARGE = "사진 해상도가 너무 큽니다. 크기를 줄여 다시 올려 주세요."


class Rejected(ValueError):
    pass


def chosen(files):
    """Browsers send one empty part when no file is selected."""
    return [item for item in files if item and item.filename]


def _normalize(image):
    """Bring every decoded mode to L, LA, RGB, RGBA or CMYK, keeping color information and transparency."""
    key = image.info.get("transparency")
    if image.mode.startswith("I") or image.mode == "F":
        wide = image.convert("I") if image.mode != "F" else image
        # 16-bit grayscale: scale to 8 bits instead of clipping everything to white. A transparent
        # key names an original 16-bit value, so the mask comes from the unscaled pixels.
        gray = wide.point(lambda value: value / 256).convert("L") if image.mode != "F" else wide.convert("L")
        gray.info = {name: value for name, value in image.info.items() if name != "transparency"}
        if isinstance(key, int) and image.mode != "F":
            mask = ImageMath.lambda_eval(lambda args: (args["pixels"] != key) * 255, pixels=wide).convert("L")
            merged = Image.merge("LA", (gray, mask))
            merged.info = gray.info
            return merged
        return gray
    if key is not None:
        return image.convert("LA" if image.mode == "L" else "RGBA")
    if image.mode in ("La", "PA", "RGBa"):
        return image.convert("RGBA")
    if image.mode in ("P", "1"):
        return image.convert("RGB")
    return image


def _srgb_encode(linear):
    return 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055


def _srgb(image):
    """Convert colors to sRGB from an ICC profile or a PNG gamma; alpha is carried over unchanged."""
    alpha = image.getchannel("A") if "A" in image.getbands() else None
    profile = image.info.get("icc_profile")
    gamma = image.info.get("gamma")
    converted = None
    if profile:
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
            # Match the pixels to the profile's own color space (a gray profile on a gray+alpha PNG, etc.).
            mode = {"GRAY": "L", "RGB": "RGB", "CMYK": "CMYK"}[source.profile.xcolor_space.strip()]
            color = image if image.mode == mode else image.convert(mode)
            converted = ImageCms.profileToProfile(color, source, ImageCms.createProfile("sRGB"), outputMode="RGB")
        except (KeyError, ImageCms.PyCMSError, OSError, ValueError):
            converted = None
    elif gamma and "srgb" not in image.info and abs(gamma - 0.45455) > 0.01:
        # PNG gAMA without ICC: samples are linear light raised to `gamma`; re-encode with the sRGB curve.
        table = [round(255 * _srgb_encode((level / 255) ** (1 / gamma))) for level in range(256)]
        converted = image.convert("RGB").point(table * 3)
    if converted is None:
        return image
    if alpha is not None:
        converted.putalpha(alpha)
    return converted


def convert(stream):
    """Return (jpeg bytes, width, height) or raise Rejected with a user-facing reason."""
    raw = stream.read(MAX_UPLOAD + 1)
    if not raw:
        raise Rejected("빈 파일은 올릴 수 없습니다.")
    if len(raw) > MAX_UPLOAD:
        raise Rejected("사진은 한 장에 5MB까지 올릴 수 있습니다.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(io.BytesIO(raw), formats=FORMATS)
            width, height = source.size
            if width * height > PIXEL_LIMITS.get(source.format, DEFAULT_PIXEL_LIMIT):
                raise Rejected(TOO_LARGE)
            orientation = source.getexif().get(0x0112)
            if source.format in ("JPEG", "MPO"):
                # Ask for the long edge only, so wide panoramas also decode at a reduced scale.
                scale = MAX_EDGE / max(width, height)
                if scale < 1:
                    source.draft("RGB", (math.ceil(width * scale), math.ceil(height * scale)))
            if source.format != "HEIF":
                # First frame of animations and multi-picture JPEG. A HEIC already opens on its
                # primary image, which need not be the first one stored.
                source.seek(0)
            source.load()
            image = _normalize(source)
            image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            image = _srgb(image)
            if orientation in ORIENTATION:
                image = image.transpose(ORIENTATION[orientation])
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            # A new canvas carries no EXIF, XMP, ICC, comments or text chunks from the upload.
            clean = Image.new("RGB", image.size, "white")
            clean.paste(image, mask=image.getchannel("A") if image.mode == "RGBA" else None)
            out = io.BytesIO()
            clean.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    except Rejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected(TOO_LARGE)
    except (Image.UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise Rejected(UNSUPPORTED)
    return out.getvalue(), clean.width, clean.height
