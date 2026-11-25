#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apple TSS request construction, submission, and ApImg4Ticket parsing."""
import copy
import hashlib
import plistlib
import ssl
from urllib.parse import parse_qs
import urllib.request

TSS_URL = 'https://gs.apple.com/TSS/controller?action=2'


def select_identity(manifest, device_class='vma2macosap', *, variant=None, restore_behavior=None):
    identities = [
        i for i in manifest.get('BuildIdentities', [])
        if i.get('Info', {}).get('DeviceClass') == device_class
        and (variant is None or i['Info'].get('Variant') == variant)
        and (restore_behavior is None or i['Info'].get('RestoreBehavior') == restore_behavior)
    ]
    if len(identities) != 1:
        raise ValueError(f'expected 1 BuildIdentity, got {len(identities)}')
    return identities[0]


def build_request(identity, ecid, nonce):
    if not 0 < ecid < 2**64 or len(nonce) not in (20, 32, 48):
        raise ValueError('invalid ECID or nonce length')
    request = {
        '@ApImg4Ticket': True,
        '@BBTicket': False,
        '@HostPlatformInfo': 'linux',
        '@VersionInfo': 'orchard86/1',
        'ApECID': ecid,
        'ApNonce': nonce,
        'ApProductionMode': True,
        'ApSecurityMode': True,
    }
    for k in ('ApChipID', 'ApBoardID', 'ApSecurityDomain'):
        v = identity[k]
        request[k] = int(v, 0) if isinstance(v, str) else int(v)
    for k in ('UniqueBuildID', 'Ap,OSLongVersion'):
        if k in identity:
            request[k] = identity[k]
    parameters = {
        'ApRawProductionMode': True,
        'ApCurrentProductionMode': True,
        'ApRawSecurityMode': True,
        'ApRequiresImage4': True,
        'ApInRomDFU': False,
    }
    excluded = {'BasebandFirmware', 'SE,UpdatePayload', 'BaseSystem', 'Diags', 'Ap,ExclaveOS'}
    for key, entry in identity['Manifest'].items():
        info = entry.get('Info', {})
        rules = info.get('RestoreRequestRules', [])
        if key in excluded or info.get('IsFTAB') or not (rules or entry.get('Trusted')):
            continue
        e = {k: copy.deepcopy(v) for k, v in entry.items() if k != 'Info'}
        if rules:
            for rule in rules:
                conditions = rule.get('Conditions', {})
                if all(k in parameters and parameters[k] == v for k, v in conditions.items()):
                    e.update(rule.get('Actions', {}))
        else:
            e.update(EPRO=True, ESEC=True)
        if e.get('Trusted'):
            e.setdefault('Digest', b'')
        request[key] = e
    return request


def parse_response(body):
    if len(body) > 2 * 1024**2:
        raise ValueError('oversized TSS response')
    prefix = body.split(b'<?xml', 1)[0].decode('utf-8', errors='strict')
    fields = parse_qs(prefix)
    status = fields.get('STATUS', [None])[0]
    if status is None:
        raise ValueError('TSS response lacks STATUS')
    ticket = None
    if b'<?xml' in body:
        p = plistlib.loads(body[body.index(b'<?xml'):])
        ticket = p.get('ApImg4Ticket')
        if not isinstance(ticket, bytes):
            ticket = None
    if status != '0' or ticket is None:
        msg = fields.get('MESSAGE', [''])[0]
        raise RuntimeError(f'TSS signing failed: STATUS={status} MESSAGE={msg}')
    return ticket


def fetch_ticket(identity, ecid, nonce, *, ca_file=None, timeout=30):
    payload = plistlib.dumps(build_request(identity, ecid, nonce))
    req = urllib.request.Request(
        TSS_URL,
        data=payload,
        headers={'Content-Type': 'text/xml; charset="utf-8"', 'User-Agent': 'InetURL/1.0'},
    )
    ctx = ssl.create_default_context(cafile=str(ca_file)) if ca_file else ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return parse_response(resp.read())


def build_policy_request(identity, ecid, nonce, policy_im4p, next_ticket):
    """Build a LocalBoot=false RestorePolicy (lpol) TSS request."""
    if not 0 < ecid < 2**64 or len(nonce) not in (20, 32, 48):
        raise ValueError('invalid ECID or nonce length')
    req = {
        '@ApImg4Ticket': True,
        '@BBTicket': False,
        '@HostPlatformInfo': 'linux',
        '@VersionInfo': 'orchard86/1',
        'ApECID': ecid,
        'ApNonce': nonce,
        'Ap,LocalBoot': False,
        'Ap,LocalPolicy': {'Digest': hashlib.sha384(policy_im4p).digest(), 'Trusted': True},
        'Ap,NextStageIM4MHash': hashlib.sha384(next_ticket).digest(),
        'ApProductionMode': True,
        'ApSecurityMode': True,
    }
    for k in ('ApChipID', 'ApBoardID', 'ApSecurityDomain'):
        v = identity[k]
        req[k] = int(v, 0) if isinstance(v, str) else int(v)
    return req


def fetch_policy_ticket(identity, ecid, nonce, policy_im4p, next_ticket, *, ca_file=None, timeout=30):
    payload = plistlib.dumps(build_policy_request(identity, ecid, nonce, policy_im4p, next_ticket))
    req = urllib.request.Request(
        TSS_URL,
        data=payload,
        headers={'Content-Type': 'text/xml; charset="utf-8"', 'User-Agent': 'InetURL/1.0'},
    )
    ctx = ssl.create_default_context(cafile=str(ca_file)) if ca_file else ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return parse_response(resp.read())
