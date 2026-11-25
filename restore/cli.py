#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""mac27 恢复阶段统一入口：IPSW 预检与受控恢复编排。"""
import argparse
import json
from pathlib import Path
import sys

from ipsw import summarize_ipsw
import run_restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)

    inspect_p = sub.add_parser('inspect-ipsw', help='只读解析 IPSW BuildManifest.plist 与组件路径')
    inspect_p.add_argument('--ipsw', type=Path, required=True)

    run_p = sub.add_parser('run', help='调用恢复控制器（默认内置 controller.py）并校验恢复产物')
    run_p.add_argument('--controller', type=Path, default=Path(__file__).resolve().with_name('controller.py'))
    for name in ('ipsw', 'qemu', 'firmware', 'output'):
        run_p.add_argument('--' + name, type=Path, required=True)
    run_p.add_argument('--execute', action='store_true', help='显式允许执行恢复控制器')

    args = parser.parse_args()
    if args.cmd == 'inspect-ipsw':
        try:
            print(json.dumps(summarize_ipsw(args.ipsw), indent=2, ensure_ascii=False))
        except Exception as exc:
            parser.exit(1, f'restore inspect-ipsw: {exc}\n')
        return 0

    if not args.execute:
        parser.error('执行恢复必须显式传入 --execute')
    try:
        print(json.dumps(run_restore.run(args), ensure_ascii=False))
    except Exception as exc:
        parser.exit(1, f'restore run: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
