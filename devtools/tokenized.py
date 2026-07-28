#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

WORD_RE = re.compile(r"[a-z0-9]+")

STOP_WORDS = {
    "a", "an", "the",
    "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being",
    "am", "do", "does", "did", "done",
    "to", "of", "in", "on", "at", "for", "from", "with",
    "by", "as", "into", "onto", "over", "under", "through",
    "up", "down", "out", "off", "about", "against",
    "between", "among", "during", "before", "after",
    "above", "below", "within", "without",
    "this", "that", "these", "those",
    "it", "its", "their", "them", "they",
    "he", "him", "his", "she", "her", "hers",
    "we", "our", "ours", "you", "your", "yours",
    "i", "me", "my", "mine",
    "can", "could", "should", "would", "may", "might",
    "must", "shall", "will",
    "if", "then", "than", "such", "so", "not", "no",
    "all", "any", "each", "every", "other", "same",
    "there", "here", "also",
    "including", "include", "includes", "included",
    "etc", "per", "via", "using", "use"
}


def extract_tokens(sheets: list[dict]) -> set[str]:
    """Extract lowercase, stop-word-filtered tokens from every name/description
    field across all sheets' data rows (already-parsed JSON, not a file)."""
    tokens = set()

    for sheet in sheets:
        for item in sheet.get("data", []):
            for field in ("name", "description"):
                # Always lowercase before searching
                text = (item.get(field) or "").lower()

                # Replace separators
                for ch in "-_/\\|,.:;()[]{}<>\"'":
                    text = text.replace(ch, " ")

                for token in WORD_RE.findall(text):

                    # Remove stop words
                    if token in STOP_WORDS:
                        continue

                    # Remove pure numbers
                    if token.isdigit():
                        continue

                    # Remove single letters (a, b, c, x, etc.)
                    if len(token) == 1 and token.isalpha():
                        continue

                    # Ensure saved tokens are lowercase
                    tokens.add(token.lower())

    return tokens


def write_tokens_file(sheets: list[dict], dest_json: Path) -> Path:
    """Write a `.tokens` sidecar next to dest_json, containing every
    unique token extracted from sheets. Used both by the CLI below and by
    the Excel->JSON generators so the tokens file is produced alongside the
    database JSON rather than as a separate manual step."""
    tokens = extract_tokens(sheets)

    output_file = dest_json.with_name(f"{dest_json.stem}.tokens")
    with output_file.open("w", encoding="utf-8") as f:
        f.write(",".join(sorted(tokens)))

    return output_file


def tokenize_json(input_file: Path):
    with input_file.open("r", encoding="utf-8") as f:
        sheets = json.load(f)

    tokens = extract_tokens(sheets)
    output_file = input_file.with_name(f"{input_file.stem}.tokens")
    with output_file.open("w", encoding="utf-8") as f:
        f.write(",".join(sorted(tokens)))

    print(f"✓ Extracted {len(tokens)} unique lowercase tokens")
    print(f"✓ Output: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Create lowercase unique tokens from JSON name and description fields."
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Input JSON file"
    )

    args = parser.parse_args()
    tokenize_json(args.input)


if __name__ == "__main__":
    main()