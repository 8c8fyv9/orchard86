#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Parse Apple IPSW BuildManifest.plist for VMApple (vma2macosap) restore."""
import plistlib
import zipfile


def read_manifest(ipsw_path):
    """Read and parse BuildManifest.plist from an IPSW archive."""
    with zipfile.ZipFile(ipsw_path) as archive:
        entries = [x for x in archive.infolist() if x.filename == 'BuildManifest.plist']
        if len(entries) != 1 or entries[0].file_size == 0:
            raise ValueError('IPSW 必须包含恰好一个非空的 BuildManifest.plist')
        with archive.open(entries[0]) as fh:
            return plistlib.loads(fh.read())


def select_vmapple_erase_identity(manifest):
    """Select the unique VMApple Customer Erase Install identity."""
    candidates = [
        item for item in manifest.get('BuildIdentities', [])
        if item.get('Info', {}).get('DeviceClass') == 'vma2macosap'
        and item.get('Info', {}).get('Variant') == 'Customer Erase Install (IPSW)'
        and item.get('Info', {}).get('RestoreBehavior') == 'Erase'
    ]
    if len(candidates) != 1:
        raise ValueError(f'预期唯一的 vma2macosap Erase 身份，实际匹配 {len(candidates)} 个')
    return candidates[0]


def summarize_ipsw(ipsw_path):
    """Return a concise summary of product version, build, and key restore components."""
    manifest = read_manifest(ipsw_path)
    identity = select_vmapple_erase_identity(manifest)
    info = identity.get('Info', {})
    comp_map = identity.get('Manifest', {})
    components = {
        key: comp_map[key].get('Info', {}).get('Path')
        for key in ('iBSS', 'iBEC', 'DeviceTree', 'RestoreKernelCache',
                    'RestoreRamDisk', 'RestoreTrustCache', 'OS')
        if key in comp_map
    }
    return {
        'product_version': manifest.get('ProductVersion'),
        'product_build_version': manifest.get('ProductBuildVersion'),
        'device_class': info.get('DeviceClass'),
        'variant': info.get('Variant'),
        'board_id': info.get('BoardID'),
        'chip_id': info.get('ChipID'),
        'components': components,
    }
