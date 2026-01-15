import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DEFAULT_QUALITY = 80


@dataclass
class ConversionStats:
    scanned: int = 0
    eligible: int = 0
    converted: int = 0
    skipped_existing: int = 0
    deleted_originals: int = 0
    failed: int = 0
    total_input_bytes: int = 0
    total_output_bytes: int = 0
    total_deleted_bytes: int = 0


def iter_images(directory: Path, recursive: bool) -> Iterable[Path]:
    if recursive:
        iterator = directory.rglob("*")
    else:
        iterator = directory.glob("*")

    for path in iterator:
        if not path.is_file():
            continue
        yield path


def to_webp_path(src_path: Path) -> Path:
    return src_path.with_suffix(".webp")


def should_convert(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def ensure_webp_compatible_mode(img: Image.Image) -> Image.Image:
    # WEBP supports RGB/RGBA; converting avoids palette/CMYK surprises.
    if img.mode in ("RGB", "RGBA"):
        return img
    if "A" in img.getbands():
        return img.convert("RGBA")
    return img.convert("RGB")


def format_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def convert_one(
    src_path: Path,
    *,
    quality: int,
    overwrite: bool,
    replace: bool,
    stats: ConversionStats,
) -> None:
    stats.scanned += 1
    if not should_convert(src_path):
        return

    stats.eligible += 1
    dst_path = to_webp_path(src_path)

    if dst_path.exists() and not overwrite:
        stats.skipped_existing += 1
        if replace:
            try:
                dst_size = dst_path.stat().st_size
                if dst_size > 0:
                    src_size = src_path.stat().st_size
                    src_path.unlink()
                    stats.deleted_originals += 1
                    stats.total_deleted_bytes += src_size
                    print(
                        f"Deleted original (webp exists): {src_path.as_posix()} -> {dst_path.as_posix()}"
                    )
            except Exception as exc:
                stats.failed += 1
                print(f"Failed to delete original: {src_path.as_posix()} ({exc})")
        return

    try:
        src_size = src_path.stat().st_size
        with Image.open(src_path) as img:
            img = ensure_webp_compatible_mode(img)
            img.save(dst_path, "WEBP", quality=quality, method=6)

        dst_size = dst_path.stat().st_size
        stats.total_input_bytes += src_size
        stats.total_output_bytes += dst_size
        stats.converted += 1
        print(f"Converted: {src_path.as_posix()} -> {dst_path.as_posix()}")

        if replace:
            try:
                src_path.unlink()
                stats.deleted_originals += 1
                stats.total_deleted_bytes += src_size
                print(f"Deleted original: {src_path.as_posix()}")
            except Exception as exc:
                stats.failed += 1
                print(f"Failed to delete original: {src_path.as_posix()} ({exc})")
    except Exception as exc:
        stats.failed += 1
        print(f"Failed: {src_path.as_posix()} ({exc})")


def convert_to_webp(
    directory: Path,
    *,
    quality: int,
    recursive: bool,
    overwrite: bool,
    replace: bool,
) -> ConversionStats:
    stats = ConversionStats()
    for path in iter_images(directory, recursive):
        convert_one(
            path,
            quality=quality,
            overwrite=overwrite,
            replace=replace,
            stats=stats,
        )
    return stats


def print_summary(stats: ConversionStats) -> None:
    print("")
    print("Summary:")
    print(f"  Scanned files: {stats.scanned}")
    print(f"  Eligible images: {stats.eligible}")
    print(f"  Converted: {stats.converted}")
    print(f"  Skipped (existing webp): {stats.skipped_existing}")
    print(f"  Deleted originals: {stats.deleted_originals}")
    print(f"  Failed: {stats.failed}")

    if stats.converted <= 0:
        if stats.deleted_originals > 0:
            print(f"  Deleted bytes (originals): {format_bytes(stats.total_deleted_bytes)}")
        return

    before_b = stats.total_input_bytes
    after_b = stats.total_output_bytes
    delta_b = before_b - after_b

    if before_b > 0:
        saved_pct = (delta_b / before_b) * 100.0
    else:
        saved_pct = 0.0

    print(f"  Total size before (converted files only): {format_bytes(before_b)}")
    print(f"  Total size after  (webp outputs only):     {format_bytes(after_b)}")
    print(f"  Saved: {format_bytes(delta_b)} ({saved_pct:.2f}%)")
    if stats.deleted_originals > 0:
        print(f"  Deleted bytes (originals): {format_bytes(stats.total_deleted_bytes)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch convert .jpg/.jpeg/.png to .webp with same basename.",
    )
    parser.add_argument(
        "--dir",
        default=".",
        help="Target directory to scan (default: current directory).",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help=f"WebP quality 0-100 (default: {DEFAULT_QUALITY}).",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the top-level directory (no subfolders).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .webp files.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="After a successful conversion (or if .webp already exists), delete the original image file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    directory = Path(args.dir).resolve()
    quality = int(args.quality)
    if quality < 0 or quality > 100:
        raise SystemExit("--quality must be within 0..100")

    stats = convert_to_webp(
        directory,
        quality=quality,
        recursive=not args.no_recursive,
        overwrite=bool(args.overwrite),
        replace=bool(args.replace),
    )
    print_summary(stats)


if __name__ == "__main__":
    main()



