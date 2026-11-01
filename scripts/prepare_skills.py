"""Prepare a pinned skill snapshot explicitly; installed apps remain offline."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if __package__ in {'',None}:sys.path.insert(0,str(ROOT))
from scripts.skill_snapshot import export_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='Local tebb-skills Git checkout containing the pinned commit')
    parser.add_argument('--output',type=Path,default=ROOT/'skills')
    args=parser.parse_args()
    lock=export_snapshot(args.source,args.output)
    print(json.dumps(dict(repository=lock['repository'],commit=lock['commit'],output=str(args.output),files=len(lock['files']))))


if __name__=='__main__':main()
