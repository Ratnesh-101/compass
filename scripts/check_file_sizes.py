#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compass — Codebase File Size & Modularity Enforcement Script.

Classifies all repository files into standard audit categories:
  - IN_SCOPE: Human-maintained application code, services, routes, agent logic, tests, scripts, CLI
  - GENERATED: Machine-generated code and lockfiles
  - VENDORED: External vendored libraries
  - BUILD_OUTPUT: Build output bundles, compilation artifacts, source maps
  - DEPENDENCY: External package dependencies (node_modules, venvs, cache)
  - BINARY: Non-text binary assets (executables, images, fonts, media)
  - DOCUMENTATION: Documentation files (markdown, text, rst)
  - DATA_CONFIGURATION: Pure data and declarative configuration files
  - GIT_METADATA: Git version control internals

Enforces strict source code limits for IN_SCOPE files:
  - Preferred limit: <= 500 lines
  - Absolute limit:  <= 700 lines (Build FAILS if any in-scope file exceeds 700 lines)

Usage:
  python scripts/check_file_sizes.py
  python scripts/check_file_sizes.py --strict    # Fails if any in-scope file exceeds 500 lines
  python scripts/check_file_sizes.py --verbose   # Lists files per category
"""

import os
import sys
import argparse
from pathlib import Path

# Dependency and environment directories
DEPENDENCY_DIRS = {
    'node_modules',
    'venv',
    '.venv',
    'env',
    '__pycache__',
    '.pytest_cache',
    '.ruff_cache',
    '.mypy_cache',
    '.gemini',
    '.agents',
}

# Build and compilation output directories
BUILD_OUTPUT_DIRS = {
    'dist',
    'build',
    'out',
    '.next',
    '.nuxt',
    '.cache',
    'coverage',
    'htmlcov',
}

# Tooling and IDE metadata directories
IDE_METADATA_DIRS = {
    '.vscode',
    '.idea',
}

# Vendor directories
VENDOR_DIRS = {
    'vendor',
    'third_party',
}

# Machine-generated lockfiles
LOCKFILES = {
    'package-lock.json',
    'yarn.lock',
    'pnpm-lock.yaml',
    'bun.lock',
    'poetry.lock',
    'pipfile.lock',
    'uv.lock',
    'cargo.lock',
    'gemfile.lock',
}

# Binary asset extensions (Section 8: non-text, executable, media)
BINARY_EXTENSIONS = {
    '.exe', '.bin', '.dll', '.so', '.dylib',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
    '.mp3', '.mp4', '.webm', '.ogg', '.wav',
    '.pdf', '.zip', '.tar', '.gz', '.db', '.sqlite', '.pyc',
}

# Documentation extensions (Section 9)
DOC_EXTENSIONS = {
    '.md', '.mdx', '.txt', '.rst',
}

# Data & declarative configuration extensions (Section 10)
DATA_CONFIG_EXTENSIONS = {
    '.json', '.yaml', '.yml', '.toml', '.ini', '.env', '.csv', '.sql',
}


def classify_file(path: Path, root: Path) -> str:
    """
    Classify a file into one of the standard Compass audit categories.
    Follows strict no-loophole policy: defaults to IN_SCOPE for any ambiguous code.
    """
    rel_parts = [part.lower() for part in path.relative_to(root).parts]
    name_lower = path.name.lower()
    suffix_lower = path.suffix.lower()

    # 1. Git metadata
    if any(p == '.git' for p in rel_parts):
        return 'GIT_METADATA'

    # 2. Dependency / Environment directories
    if any(p in DEPENDENCY_DIRS for p in rel_parts):
        return 'DEPENDENCY'

    # 3. Tooling / IDE metadata
    if any(p in IDE_METADATA_DIRS for p in rel_parts) or name_lower == '.ds_store':
        return 'GIT_METADATA'

    # 4. Build / Compilation output
    if any(p in BUILD_OUTPUT_DIRS for p in rel_parts):
        return 'BUILD_OUTPUT'
    if name_lower.endswith('.min.js') or name_lower.endswith('.min.css') or name_lower.endswith('.map'):
        return 'BUILD_OUTPUT'
    if name_lower.endswith('.bundle.js') or name_lower.endswith('.bundle.css'):
        return 'BUILD_OUTPUT'

    # 5. Vendored code
    if any(p in VENDOR_DIRS for p in rel_parts):
        return 'VENDORED'

    # 6. Lockfiles and machine-generated files
    if name_lower in LOCKFILES:
        return 'GENERATED'
    if '_generated' in name_lower or '.generated.' in name_lower or '.gen.' in name_lower:
        return 'GENERATED'

    # 7. Binary files (executables, images, media, compiled assets)
    if suffix_lower in BINARY_EXTENSIONS or name_lower.endswith('.exe'):
        return 'BINARY'

    # 8. Documentation
    if suffix_lower in DOC_EXTENSIONS:
        return 'DOCUMENTATION'

    # 9. Data & configuration (unless executable source code)
    if suffix_lower in DATA_CONFIG_EXTENSIONS:
        return 'DATA_CONFIGURATION'

    # 10. In-scope application source code (components, routes, services, agents, tests, scripts, CLI)
    return 'IN_SCOPE'


def count_lines(path: Path) -> int:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except Exception:
        return 0


def audit_repository(root: Path, max_lines: int = 700, warn_lines: int = 500):
    categories = {
        'IN_SCOPE': [],
        'GENERATED': [],
        'VENDORED': [],
        'BUILD_OUTPUT': [],
        'DEPENDENCY': [],
        'BINARY': [],
        'DOCUMENTATION': [],
        'DATA_CONFIGURATION': [],
        'GIT_METADATA': [],
    }

    # Fast directory walk with pruning of massive dependencies while counting them
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dir_parts = [p.lower() for p in rel_dir.parts]

        # Check if entire directory is Git metadata
        if any(p == '.git' for p in dir_parts):
            categories['GIT_METADATA'].extend(filenames)
            continue

        # Check if entire directory is dependencies/environment
        if any(p in DEPENDENCY_DIRS for p in dir_parts):
            categories['DEPENDENCY'].extend(filenames)
            continue

        # Check if entire directory is IDE metadata
        if any(p in IDE_METADATA_DIRS for p in dir_parts):
            categories['GIT_METADATA'].extend(filenames)
            continue

        # Check if entire directory is build output
        if any(p in BUILD_OUTPUT_DIRS for p in dir_parts):
            categories['BUILD_OUTPUT'].extend(filenames)
            continue

        # Check if entire directory is vendored
        if any(p in VENDOR_DIRS for p in dir_parts):
            categories['VENDORED'].extend(filenames)
            continue

        for filename in filenames:
            path = Path(dirpath) / filename
            cat = classify_file(path, root)
            if cat == 'IN_SCOPE':
                lines = count_lines(path)
                categories['IN_SCOPE'].append((lines, path))
            else:
                categories[cat].append(path)

    # Sort in-scope files by line count descending
    categories['IN_SCOPE'].sort(key=lambda x: x[0], reverse=True)

    in_scope = categories['IN_SCOPE']
    passed = [x for x in in_scope if x[0] <= warn_lines]
    warned = [x for x in in_scope if warn_lines < x[0] <= max_lines]
    failed = [x for x in in_scope if x[0] > max_lines]

    return {
        'passed': passed,
        'warned': warned,
        'failed': failed,
        'categories': categories,
    }


def main():
    parser = argparse.ArgumentParser(description="Compass Source File Size Audit & Classification")
    parser.add_argument("--max-lines", type=int, default=700, help="Absolute maximum lines (default: 700)")
    parser.add_argument("--warn-lines", type=int, default=500, help="Preferred limit (default: 500)")
    parser.add_argument("--strict", action="store_true", help="Fail build if any file exceeds preferred limit (>500 lines)")
    parser.add_argument("--verbose", action="store_true", help="Print details for all categories")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    result = audit_repository(root, max_lines=args.max_lines, warn_lines=args.warn_lines)

    passed = result['passed']
    warned = result['warned']
    failed = result['failed']
    cats = result['categories']
    total_in_scope = len(passed) + len(warned) + len(failed)

    print("=" * 70)
    print("COMPASS FILE SIZE & SOURCE CODE AUDIT")
    print("=" * 70)
    print()
    print("IN SCOPE")
    print("-" * 35)
    print(f"Files checked:     {total_in_scope}")
    print(f"<= {args.warn_lines} lines (PASS): {len(passed)}")
    print(f"{args.warn_lines + 1}-{args.max_lines} lines (WARN): {len(warned)}")
    print(f"> {args.max_lines} lines (FAIL):  {len(failed)}")
    print()

    print("EXCLUDED")
    print("-" * 35)
    print(f"Generated:          {len(cats['GENERATED'])}")
    print(f"Vendored:           {len(cats['VENDORED'])}")
    print(f"Build output:       {len(cats['BUILD_OUTPUT'])}")
    print(f"Dependencies:       {len(cats['DEPENDENCY'])}")
    print(f"Documentation:      {len(cats['DOCUMENTATION'])}")
    print(f"Binary/assets:      {len(cats['BINARY'])}")
    print(f"Configuration/data: {len(cats['DATA_CONFIGURATION'])}")
    print(f"Git metadata:       {len(cats['GIT_METADATA'])}")
    print()

    if failed:
        print("FAILED FILES (> 700 lines):")
        print("-" * 35)
        for count, p in failed:
            print(f"  [FAIL] {count:4d} lines: {p.relative_to(root)}")
        print()

    if warned:
        print(f"WARNING FILES ({args.warn_lines + 1}-{args.max_lines} lines):")
        print("-" * 35)
        for count, p in warned:
            print(f"  [WARN] {count:4d} lines: {p.relative_to(root)}")
        print()

    print("=" * 70)
    if failed:
        print(f"STATUS: FAIL ({len(failed)} file(s) exceed {args.max_lines} lines)")
        sys.exit(1)
    elif args.strict and warned:
        print(f"STATUS: STRICT FAIL ({len(warned)} file(s) exceed {args.warn_lines} lines)")
        sys.exit(1)
    else:
        print("STATUS: PASS")
        sys.exit(0)


if __name__ == '__main__':
    main()
