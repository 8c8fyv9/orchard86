#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Summarize observed restore events; never emit a success receipt."""
import argparse
import json
from pathlib import Path
import re

CHECKPOINT = re.compile(r'Checkpoint completed +id: [^ ]+ [(]([a-zA-Z0-9_]+)[)] result=(-?[0-9]+)')


TRANSFER = re.compile(r'^Transfer: (Received|Wrote|Verified) ([0-9]+) bytes in ([0-9.]+) seconds, ([0-9.]+) MB/s (?:from host|to disk|from disk)(?: [(].*[)])?$')


def scan(host, guest, image_bytes=None):
    report = {'media_format_completed': False, 'asr_connection_observed': False,
              'asr_send_started': False, 'asr_host_send_finished': False,
              'invert_wait_started': False, 'native_success_marker': False, 'snapshot_marker': False, 'psci_marker': False,
              'invert_checkpoint_ok': False, 'cryptex_checkpoint_ok': False,
              'seal_checkpoint_ok': False, 'snapshot_checkpoint_ok': False,
              'host_restore_finished_marker': False,
              'final_status_checkpoint_started': False,
              'receipt_wait_checkpoint_ok': False,
              'checkpoint_errors': {}, 'last_host_checkpoint': None}
    for line in host:
        if (match := CHECKPOINT.search(line)):
            name, result = match.groups()
            result = int(result)
            report['last_host_checkpoint'] = {'name': name, 'result': result}
            if name == 'format_media' and result == 0:
                report['media_format_completed'] = True
            if name in ('seal_system_volume', 'create_system_snapshot'):
                key = 'seal_checkpoint_ok' if name == 'seal_system_volume' else 'snapshot_checkpoint_ok'
                report[key] = result == 0
            if name == 'await_system_image_invert_retry':
                report['invert_checkpoint_ok'] = result == 0
            if name == 'install_splat':
                report['cryptex_checkpoint_ok'] = result == 0
            if name == 'cleanup_wait_status_received':
                report['receipt_wait_checkpoint_ok'] = result == 0
            if result != 0:
                report['checkpoint_errors'][name] = result
        marker = line.strip()
        if marker == 'Connected to ASR':
            report['asr_connection_observed'] = True
        elif marker == 'Sending filesystem now...':
            report['asr_send_started'] = True
        elif 'Checkpoint started' in marker and marker.endswith('(cleanup_send_final_status)'):
            report['final_status_checkpoint_started'] = True
        elif marker == 'Status: Restore Finished':
            report['host_restore_finished_marker'] = True
        elif marker == 'Done sending filesystem' or re.fullmatch(
                r'\[[= ]+\] +[0-9.]+%Done sending filesystem', marker):
            report['asr_host_send_finished'] = True
        elif 'Checkpoint started' in marker and marker.endswith('(await_system_image_invert_retry)'):
            report['invert_wait_started'] = True
    if image_bytes is not None:
        report['image_transfer_samples'] = []
    for line in guest:
        marker = line.strip()
        if image_bytes is not None and (match := TRANSFER.fullmatch(marker)):
            operation, count, seconds, rate = match.groups()
            if int(count) == image_bytes:
                report['image_transfer_samples'].append({
                    'operation': operation, 'bytes': int(count), 'guest_seconds': float(seconds),
                    'reported_mb_per_second': float(rate)})
        if marker == 'restore-outcome = success':
            report['native_success_marker'] = True
        if marker == 'System ARV snapshot successfully created.':
            report['snapshot_marker'] = True
        if marker in ('ApplePSCI - system reset', 'ApplePSCI - system off'):
            report['psci_marker'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host_log', type=Path)
    parser.add_argument('guest_serial', type=Path)
    parser.add_argument('--image-bytes', type=int, help='select native transfer samples of this exact size')
    args = parser.parse_args()
    if args.image_bytes is not None and args.image_bytes <= 0:
        parser.error('image size must be positive')
    with args.host_log.open(errors='replace') as host, args.guest_serial.open(errors='replace') as guest:
        print(json.dumps(scan(host, guest, args.image_bytes), indent=2))


if __name__ == '__main__':
    main()
