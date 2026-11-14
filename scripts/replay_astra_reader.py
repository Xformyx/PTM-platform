"""Replay saved readers with archive code; full science remains package/replay.py."""
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ptm_shared.astra_reader_replay import PROGRAM, main

if __name__=='__main__':raise SystemExit(main())
