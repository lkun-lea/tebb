"""Read-only deployment check; no login email, local data import or cloud writes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk_companion.accounts.personalization_cloud import CloudError, preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connect', action='store_true', help='explicit read-only network check')
    args = parser.parse_args()
    try:
        report = preflight(connect=args.connect)
    except CloudError as exc:
        print(json.dumps({'status':exc.code, 'error':str(exc)}, ensure_ascii=False))
        return 2 if exc.code in {'needs_configuration','invalid_config'} else 1
    print(json.dumps(report, ensure_ascii=False))
    return 3 if report['status'] == 'needs_login' else 0


if __name__ == '__main__':
    raise SystemExit(main())
