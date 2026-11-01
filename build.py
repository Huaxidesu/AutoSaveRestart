#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地打包 AutoSaveRestart 为 .mcdr（和 .github/workflows/build-mcdr.yml 等价）。

用法：
    python build.py            # 输出 dist/AutoSaveRestart-v<版本>.mcdr
    python build.py --check    # 只校验现有 dist 里的包，不重新打包

.mcdr 就是 zip：根目录放 mcdreforged.plugin.json，其余文件按包名目录放。
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE_DIR = ROOT / "autosave"
METADATA_PATH = ROOT / "mcdreforged.plugin.json"
DIST_DIR = ROOT / "dist"

SKIP_PARTS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def read_metadata() -> dict:
    with METADATA_PATH.open("r", encoding="utf-8") as file:
        metadata = json.load(file)
    for key in ("id", "version", "name"):
        if not metadata.get(key):
            raise SystemExit(f"mcdreforged.plugin.json 缺少字段: {key}")
    return metadata


def package_files() -> list[Path]:
    files = []
    for path in sorted(PACKAGE_DIR.rglob("*")):
        if not path.is_file():
            continue
        if SKIP_PARTS & set(path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        files.append(path)
    return files


def build() -> Path:
    metadata = read_metadata()
    name = metadata["name"]
    version = metadata["version"]

    DIST_DIR.mkdir(exist_ok=True)
    output_path = DIST_DIR / f"{name}-v{version}.mcdr"

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(METADATA_PATH, arcname="mcdreforged.plugin.json")
        for path in package_files():
            archive.write(path, arcname=path.relative_to(ROOT).as_posix())

    verify(output_path)
    print(f"built: {output_path} ({output_path.stat().st_size} bytes)")
    return output_path


def verify(output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "r") as archive:
        names = set(archive.namelist())
        broken = archive.testzip()
    if broken is not None:
        raise SystemExit(f"包内文件损坏: {broken}")
    if "mcdreforged.plugin.json" not in names:
        raise SystemExit("包内缺少 mcdreforged.plugin.json")
    if not any(name.startswith("autosave/") for name in names):
        raise SystemExit("包内缺少 autosave/ 目录")


def main(argv: list[str]) -> int:
    if "--check" in argv:
        packages = sorted(DIST_DIR.glob("*.mcdr"))
        if not packages:
            print("dist/ 里还没有 .mcdr")
            return 1
        for package in packages:
            verify(package)
            print(f"ok: {package} ({package.stat().st_size} bytes)")
        return 0

    build()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
