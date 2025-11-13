#!/usr/bin/env python3
"""
Print a directory tree for a given path, excluding virtual envs and hidden folders.

Usage:
  python repo_tree.py [path]

Example:
  python repo_tree.py ~/Projects/Prediction-Markets-Trading
"""

import os
import sys

EXCLUDE_DIRS = {".venv", ".git", "__pycache__"}


def print_tree(root: str, prefix: str = ""):
    try:
        entries = sorted(
            e for e in os.listdir(root) if not (e.startswith(".") or e in EXCLUDE_DIRS)
        )
    except PermissionError:
        return  # Skip directories we can't access

    pointers = ["├── "] * (len(entries) - 1) + ["└── "]

    for pointer, name in zip(pointers, entries):
        path = os.path.join(root, name)
        print(prefix + pointer + name)
        if os.path.isdir(path):
            extension = "│   " if pointer == "├── " else "    "
            print_tree(path, prefix + extension)


if __name__ == "__main__":
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    base_name = os.path.basename(os.path.abspath(base_path))
    print(base_name)
    print_tree(base_path)
