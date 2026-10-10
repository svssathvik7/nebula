#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nebula.capture import run_hook
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('--host',required=True,choices=['claude','codex'])
    args=p.parse_args()
    raise SystemExit(run_hook(args.host,sys.stdin.buffer,sys.stdout))
