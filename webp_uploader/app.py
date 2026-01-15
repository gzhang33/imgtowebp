import argparse
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request
from PIL import Image
from werkzeug.utils import secure_filename


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DEFAULT_QUALITY = 80


@dataclass
class UploadItemResult:
    original_name: str
    status: str
    message: str
    output_relpath: str | None = None
    input_bytes: int = 0
    output_bytes: int = 0


def ensure_webp_compatible_mode(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "RGBA"):
        return img
    if "A" in img.getbands():
        return img.convert("RGBA")
    return img.convert("RGB")


def safe_subdir(subdir: str) -> Path:
    subdir = (subdir or "").strip()
    if not subdir:
        return Path(".")

    # Prevent absolute paths and traversal; keep only relative parts.
    candidate = Path(subdir)
    if candidate.is_absolute():
        return Path(".")

    cleaned_parts: list[str] = []
    for part in candidate.parts:
        if part in ("", ".", ".."):
            continue
        cleaned_parts.append(part)

    if not cleaned_parts:
        return Path(".")
    return Path(*cleaned_parts)


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


def create_app(output_dir: Path) -> Flask:
    app = Flask(__name__)
    output_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def index() -> str:
        return render_template("index.html", results=None, summary=None, output_dir=str(output_dir))

    @app.post("/upload")
    def upload() -> str:
        files = request.files.getlist("files")
        quality_raw = request.form.get("quality", str(DEFAULT_QUALITY))
        overwrite = request.form.get("overwrite") == "on"
        subdir = safe_subdir(request.form.get("subdir", ""))

        try:
            quality = int(quality_raw)
        except ValueError:
            quality = DEFAULT_QUALITY

        if quality < 0:
            quality = 0
        if quality > 100:
            quality = 100

        results: list[UploadItemResult] = []
        total_in = 0
        total_out = 0
        converted = 0
        skipped = 0
        failed = 0

        target_dir = (output_dir / subdir).resolve()
        if output_dir.resolve() not in target_dir.parents and target_dir != output_dir.resolve():
            target_dir = output_dir.resolve()

        target_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            if not f or not f.filename:
                continue

            original_name = f.filename
            safe_name = secure_filename(original_name)
            ext = Path(safe_name).suffix.lower()

            if ext not in SUPPORTED_EXTENSIONS:
                skipped += 1
                results.append(
                    UploadItemResult(
                        original_name=original_name,
                        status="skipped",
                        message="Unsupported file type (only .jpg/.jpeg/.png).",
                    )
                )
                continue

            stem = Path(safe_name).stem
            out_path = target_dir / f"{stem}.webp"

            if out_path.exists() and not overwrite:
                skipped += 1
                results.append(
                    UploadItemResult(
                        original_name=original_name,
                        status="skipped",
                        message="Output exists and overwrite is disabled.",
                        output_relpath=str(out_path.relative_to(output_dir)),
                    )
                )
                continue

            try:
                data = f.read()
                if not data:
                    skipped += 1
                    results.append(
                        UploadItemResult(
                            original_name=original_name,
                            status="skipped",
                            message="Empty file.",
                        )
                    )
                    continue

                total_in += len(data)
                with Image.open(io.BytesIO(data)) as img:
                    img = ensure_webp_compatible_mode(img)
                    img.save(out_path, "WEBP", quality=quality, method=6)

                out_size = out_path.stat().st_size
                total_out += out_size
                converted += 1
                results.append(
                    UploadItemResult(
                        original_name=original_name,
                        status="converted",
                        message="Saved.",
                        output_relpath=str(out_path.relative_to(output_dir)),
                        input_bytes=len(data),
                        output_bytes=out_size,
                    )
                )
            except Exception as exc:
                failed += 1
                results.append(
                    UploadItemResult(
                        original_name=original_name,
                        status="failed",
                        message=str(exc),
                    )
                )

        saved_bytes = total_in - total_out
        saved_pct = (saved_bytes / total_in * 100.0) if total_in > 0 else 0.0

        summary: dict[str, Any] = {
            "files_received": len(files),
            "converted": converted,
            "skipped": skipped,
            "failed": failed,
            "total_input": format_bytes(total_in),
            "total_output": format_bytes(total_out),
            "saved": format_bytes(saved_bytes),
            "saved_pct": f"{saved_pct:.2f}%",
            "output_dir": str(output_dir),
            "subdir": str(subdir),
            "overwrite": overwrite,
            "quality": quality,
        }

        return render_template(
            "index.html",
            results=results,
            summary=summary,
            output_dir=str(output_dir),
        )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Web UI for converting uploaded images to WebP.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--output-dir",
        default="webp_output",
        help="Directory to store generated .webp files (default: webp_output).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app(Path(args.output_dir).resolve())
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()


