import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from nebula.capture import run_hook
p=argparse.ArgumentParser(); p.add_argument('--host',required=True,choices=('claude','codex'))
if __name__=='__main__': raise SystemExit(run_hook(p.parse_args().host,sys.stdin.buffer,sys.stdout))
