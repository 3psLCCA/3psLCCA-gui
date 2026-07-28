#!/usr/bin/env python3

import argparse
import json
from pathlib import Path


def trim_json(input_file: Path):
    with input_file.open("r", encoding="utf-8") as f:
        sheets = json.load(f)

    trimmed = []

    for sheet in sheets:
        trimmed.append({
            "sheetName": sheet.get("sheetName"),
            "data": [
                {
                    "src_id": item.get("src_id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                }
                for item in sheet.get("data", [])
            ],
        })

    output_file = input_file.with_name(
        f"{input_file.stem}.trimmed{input_file.suffix}"
    )

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2, ensure_ascii=False)

    print(f"✓ Wrote {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Trim SOR JSON to keep only src_id, name, and description."
    )
    parser.add_argument("input", type=Path, help="Input JSON file")

    args = parser.parse_args()
    trim_json(args.input)


if __name__ == "__main__":
    main()