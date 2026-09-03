#!/usr/bin/env python3
"""Run synthetic human decisions against real Git and public RunStore Gates."""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

COGITO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(COGITO / 'tests'))
from test_stage_delivery_acceptance import StageDeliveryAcceptanceTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('simulation.json'))
    args = parser.parse_args()
    scenarios = []
    for kind in ('feature', 'maintenance'):
        case = StageDeliveryAcceptanceTests()
        try:
            case.setUp()
            scenarios.append(case.run_scenario(kind))
        finally:
            case.doCleanups()
        print(f'{kind}: PASS — rejection, correction, fresh review, explicit acceptance, finalization')
    report = {
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'method': 'Real temporary Git repositories, public RunStore Gates, actual controlled Python checks; synthetic human and reviewer inputs.',
        'passed': len(scenarios), 'scenarios': scenarios,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Actual results: {args.output}')


if __name__ == '__main__':
    main()
