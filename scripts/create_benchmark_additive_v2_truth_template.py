#!/usr/bin/env python3
from __future__ import annotations

import argparse

from benchmarking.v2_truth_template import create_blank_additive_v2_template


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(create_blank_additive_v2_template(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
