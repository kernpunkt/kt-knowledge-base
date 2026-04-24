#!/usr/bin/env python3
"""
Enrich documents with Bedrock-compatible metadata sidecar files.

For each .md file found in the repo, this script:
  1. Parses YAML frontmatter (Obsidian-compatible)
  2. Reads git history for last_updated and last_editor
  3. Writes a <file>.metadata.json sidecar in the format AWS Bedrock expects

Usage:
    python enrich-metadata.py --repo-name <name> --root-dir <path> [--output-dir <path>]
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Bedrock metadata constraints
MAX_METADATA_VALUE_LENGTH = 256
MAX_METADATA_ATTRIBUTES = 10
# S3 Vectors limit: filterable metadata JSON must be <= 2048 bytes per vector.
# We target 1800 to leave headroom for Bedrock's own internal framing.
MAX_METADATA_BYTES = 1800

# Supported document extensions (images excluded — Bedrock cannot index them)
DOCUMENT_EXTENSIONS = {'.md'}
ALL_SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS

# Directories to skip
SKIP_DIRS = {
    'node_modules', '.git', 'dist', 'build', '.next', '__pycache__',
    'vendor', '.venv', 'venv', 'cdk.out', '.cache',
}


def get_git_metadata(file_path: Path, root_dir: Path) -> tuple[str, str]:
    """Return (iso_timestamp, author_email) from the last git commit touching this file."""
    rel_path = file_path.relative_to(root_dir)
    try:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%aI\t%ae', '--', str(rel_path)],
            capture_output=True,
            text=True,
            cwd=str(root_dir),
            timeout=10,
        )
        output = result.stdout.strip()
        if output and '\t' in output:
            parts = output.split('\t', 1)
            return parts[0].strip(), parts[1].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Fallback: file not tracked or git not available
    return datetime.now(timezone.utc).isoformat(), 'unknown'


def parse_frontmatter(content: str) -> dict[str, Any]:
    """
    Extract YAML frontmatter from Markdown content.
    Returns an empty dict if no frontmatter is present or parsing fails.
    """
    if not content.startswith('---'):
        return {}

    # Match the closing --- on its own line
    match = re.match(r'^---\r?\n(.*?)\r?\n---\r?\n', content, re.DOTALL)
    if not match:
        return {}

    frontmatter_str = match.group(1)

    if HAS_YAML:
        try:
            data = yaml.safe_load(frontmatter_str)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError:
            return {}
    else:
        # Minimal fallback parser for simple key: value pairs (no nested objects)
        result: dict[str, Any] = {}
        for line in frontmatter_str.splitlines():
            if ':' in line:
                key, _, value = line.partition(':')
                key = key.strip()
                value = value.strip()
                if key and not key.startswith('#'):
                    result[key] = value
        return result


def normalize_value(value: Any) -> str | int | float | bool | None:
    """
    Convert a frontmatter value to a Bedrock-compatible primitive.
    Lists are serialized as comma-separated strings.
    Nested dicts are skipped (returns None).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        v = value.strip()
        return v[:MAX_METADATA_VALUE_LENGTH] if len(v) > MAX_METADATA_VALUE_LENGTH else v
    if isinstance(value, list):
        # Convert list to comma-separated string; flatten nested items
        parts = []
        for item in value:
            if isinstance(item, (str, int, float, bool)):
                parts.append(str(item))
        joined = ','.join(parts)
        if len(joined) > MAX_METADATA_VALUE_LENGTH:
            print(
                f'  Warning: serialized list value truncated to {MAX_METADATA_VALUE_LENGTH} chars',
                file=sys.stderr,
            )
            return joined[:MAX_METADATA_VALUE_LENGTH]
        return joined
    if isinstance(value, dict):
        # Nested objects cannot be stored as metadata; skip
        return None
    # None or other types
    return None


def build_metadata(
    file_path: Path,
    root_dir: Path,
    repo_name: str,
    is_document: bool,
) -> dict[str, Any]:
    """Build the metadataAttributes dict for a single file."""
    last_updated, last_editor = get_git_metadata(file_path, root_dir)
    rel_path = str(file_path.relative_to(root_dir))

    attributes: dict[str, Any] = {
        'source_repo': repo_name,
        'last_updated': last_updated,
        'last_editor': last_editor,
        'file_path': rel_path,
    }

    if is_document:
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
        except OSError as e:
            print(f'  Warning: could not read {file_path}: {e}', file=sys.stderr)
            content = ''

        frontmatter = parse_frontmatter(content)

        for key, raw_value in frontmatter.items():
            # Skip if we'd exceed the attribute limit
            if len(attributes) >= MAX_METADATA_ATTRIBUTES:
                print(
                    f'  Warning: {file_path.name} has more than {MAX_METADATA_ATTRIBUTES} '
                    f'metadata attributes; extra frontmatter fields skipped.',
                    file=sys.stderr,
                )
                break

            normalized = normalize_value(raw_value)
            if normalized is None:
                continue

            # Sanitize key: only alphanumeric, underscores, hyphens
            clean_key = re.sub(r'[^\w\-]', '_', str(key)).strip('_')
            if not clean_key:
                continue

            attributes[clean_key] = normalized

    # Enforce S3 Vectors 2048-byte filterable metadata limit.
    # Drop extra frontmatter fields (never the four standard ones) until it fits.
    standard_keys = {'source_repo', 'last_updated', 'last_editor', 'file_path'}
    while len(json.dumps(attributes, ensure_ascii=False).encode()) > MAX_METADATA_BYTES:
        extra_keys = [k for k in reversed(list(attributes)) if k not in standard_keys]
        if not extra_keys:
            break
        dropped = extra_keys[0]
        del attributes[dropped]
        print(f'  Warning: dropped metadata field "{dropped}" to stay under S3 Vectors byte limit', file=sys.stderr)

    return attributes


def write_sidecar(file_path: Path, attributes: dict[str, Any]) -> None:
    """Write the .metadata.json sidecar next to the source file."""
    sidecar_path = file_path.with_suffix(file_path.suffix + '.metadata.json')
    payload = {'metadataAttributes': attributes}
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def enrich_directory(root_dir: Path, repo_name: str, output_dir: Path) -> int:
    """Walk the directory, enrich all supported files. Returns count of processed files."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            file_path = Path(dirpath) / filename
            suffix = file_path.suffix.lower()

            if suffix not in ALL_SUPPORTED_EXTENSIONS:
                continue

            # Skip existing sidecar files
            if filename.endswith('.metadata.json'):
                continue

            is_document = suffix in DOCUMENT_EXTENSIONS

            # Compute output path: mirror structure under output_dir
            try:
                rel = file_path.relative_to(root_dir)
            except ValueError:
                continue

            output_file = output_dir / rel

            print(f'  Processing: {rel}')

            attributes = build_metadata(file_path, root_dir, repo_name, is_document)

            # Write sidecar alongside the output file location
            sidecar_path = output_file.with_suffix(output_file.suffix + '.metadata.json')
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {'metadataAttributes': attributes}
            sidecar_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )

            count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Generate Bedrock metadata sidecar files for documents in a git repo.',
    )
    parser.add_argument(
        '--repo-name',
        required=True,
        help='Name of the GitHub repository (used as source_repo metadata value)',
    )
    parser.add_argument(
        '--root-dir',
        required=True,
        type=Path,
        help='Root directory of the checked-out repository',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=None,
        help='Directory to write sidecar files (default: alongside source files in root-dir)',
    )

    args = parser.parse_args()

    root_dir = args.root_dir.resolve()
    output_dir = (args.output_dir or root_dir).resolve()

    if not root_dir.is_dir():
        print(f'Error: root-dir does not exist: {root_dir}', file=sys.stderr)
        sys.exit(1)

    if not HAS_YAML:
        print(
            'Warning: PyYAML not available; using minimal frontmatter parser. '
            'Install PyYAML for full frontmatter support.',
            file=sys.stderr,
        )

    print(f'Enriching documents in: {root_dir}')
    print(f'Repo name: {args.repo_name}')
    print(f'Output dir: {output_dir}')
    print()

    count = enrich_directory(root_dir, args.repo_name, output_dir)
    print(f'\nDone. Processed {count} file(s).')


if __name__ == '__main__':
    main()
