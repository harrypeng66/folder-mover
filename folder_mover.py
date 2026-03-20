from __future__ import annotations

import csv
import shutil
import sys
from io import StringIO
from pathlib import Path


BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
SOURCE_ROOT = BASE_DIR
MAPPING_FILE = BASE_DIR / "映射关系模板.csv"
DEST_ROOT = BASE_DIR / "迁移结果"

SOURCE_HEADER_CANDIDATES = ("产品文件夹", "源文件夹", "source", "source_folder")
TARGET_HEADER_CANDIDATES = ("材质文件夹", "目标文件夹", "target", "target_folder")


def main() -> int:
    if not SOURCE_ROOT.exists():
        print(f"Source folder not found: {SOURCE_ROOT}")
        return 1
    if not MAPPING_FILE.exists():
        print(f"Mapping file not found: {MAPPING_FILE}")
        return 1

    mapping = load_mapping(MAPPING_FILE)
    if not mapping:
        print("Mapping file is empty or invalid.")
        return 1

    DEST_ROOT.mkdir(parents=True, exist_ok=True)

    moved = 0
    skipped = 0
    source_folders = [
        item
        for item in SOURCE_ROOT.iterdir()
        if item.is_dir() and item.name != DEST_ROOT.name
    ]

    for folder in sorted(source_folders, key=lambda item: item.name.lower()):
        target_group = mapping.get(folder.name.casefold())
        if not target_group:
            skipped += 1
            continue

        destination = DEST_ROOT / target_group / folder.name
        move_folder(folder, destination)
        moved += 1

    print(
        f"Done. moved={moved}, skipped={skipped}, source={SOURCE_ROOT}, dest={DEST_ROOT}"
    )
    return 0


def load_mapping(path: Path) -> dict[str, str]:
    text = read_text_with_fallback(path)
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        return {}

    headers = [normalize_header(item) for item in reader.fieldnames]
    source_col = pick_column(headers, SOURCE_HEADER_CANDIDATES)
    target_col = pick_column(headers, TARGET_HEADER_CANDIDATES)

    if not source_col or not target_col:
        if len(headers) >= 2:
            source_col = source_col or headers[0]
            target_col = target_col or headers[1]
        else:
            return {}

    mapping: dict[str, str] = {}
    for row in reader:
        source_name = (row.get(source_col, "") or "").strip()
        target_name = (row.get(target_col, "") or "").strip()
        if not source_name or not target_name:
            continue
        mapping[source_name.casefold()] = target_name

    return mapping


def read_text_with_fallback(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def normalize_header(value: str) -> str:
    return value.strip().lstrip("\ufeff")


def pick_column(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {header.lower(): header for header in headers}
    for candidate in candidates:
        if candidate in headers:
            return candidate
        match = normalized.get(candidate.lower())
        if match:
            return match
    return None


def move_folder(source_folder: Path, destination_folder: Path) -> None:
    destination_folder.parent.mkdir(parents=True, exist_ok=True)

    if not destination_folder.exists():
        shutil.move(str(source_folder), str(destination_folder))
        return

    if destination_folder.is_file():
        destination_folder = unique_path(destination_folder)
        shutil.move(str(source_folder), str(destination_folder))
        return

    merge_directories(source_folder, destination_folder)
    remove_empty_tree(source_folder)


def merge_directories(source_dir: Path, destination_dir: Path) -> None:
    for entry in sorted(source_dir.iterdir(), key=lambda item: item.name.lower()):
        target_entry = destination_dir / entry.name
        if entry.is_dir():
            if target_entry.exists():
                if target_entry.is_dir():
                    merge_directories(entry, target_entry)
                    remove_empty_tree(entry)
                else:
                    shutil.move(str(entry), str(unique_path(target_entry)))
            else:
                shutil.move(str(entry), str(target_entry))
            continue

        if target_entry.exists():
            target_entry = unique_path(target_entry)
        shutil.move(str(entry), str(target_entry))


def remove_empty_tree(path: Path) -> None:
    current = path
    while current.exists() and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    for index in range(1, 10000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Unable to resolve unique path for {path}")


if __name__ == "__main__":
    raise SystemExit(main())
