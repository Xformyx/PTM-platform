#!/usr/bin/env python3
"""
Standalone test for markdown_to_html conversion.
Usage: python scripts/test_markdown_to_html.py [path_to_report.md]

Example:
  python scripts/test_markdown_to_html.py
  python scripts/test_markdown_to_html.py ../data/outputs/Universe_AF/Universe_AF_report_260319_0024.md
"""
import sys
import os

# Add workers root to path so "common" can be imported
workers_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, workers_root)

from common.markdown_to_html import convert_report_to_html


def main():
    default_md = os.path.join(
        workers_root, "..", "data", "outputs", "Universe_AF", "Universe_AF_report_260319_0024.md"
    )
    md_path = sys.argv[1] if len(sys.argv) > 1 else default_md
    md_path = os.path.abspath(md_path)

    if not os.path.exists(md_path):
        print(f"Error: File not found: {md_path}")
        sys.exit(1)

    output_dir = os.path.dirname(md_path)
    print(f"Input:  {md_path}")
    print(f"Output: {output_dir}")
    print("Converting...")

    result = convert_report_to_html(
        md_path,
        output_dir=output_dir,
        references=None,  # Will parse from MD; Article modal will fetch from API if needed
        api_base_url="/api",
    )

    if result:
        print(f"OK: {result}")
    else:
        print("Conversion failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
