# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate supplied restore evidence; never infer success from logs or exit alone."""
def evaluate(*, final_message, client_result, receipt_drained, guest_finished, writers_stopped):
    reasons = []
    if type(final_message) is not dict or final_message.get('MsgType') != 'StatusMsg':
        reasons.append('missing-final-status-message')
    else:
        status = final_message.get('Status')
        if type(status) is not int or not 0 <= status <= 2**64-1:
            reasons.append('invalid-final-status-type')
        elif status != 0:
            reasons.append('nonzero-final-status')
        for key in ('AMRError', 'ErrorCode'):
            if key in final_message:
                value = final_message[key]
                if type(value) is not int or value != 0:
                    reasons.append('error-field-'+key)
    if type(client_result) is not dict:
        reasons.append('missing-client-result')
    else:
        if type(client_result.get('returncode')) is not int or client_result['returncode'] != 0:
            reasons.append('client-not-successful')
        if client_result.get('timed_out') is not False:
            reasons.append('client-timeout-unproven')
        if client_result.get('cancelled') is not False:
            reasons.append('client-cancellation-unproven')
    for name, value in (('receipt-drained', receipt_drained), ('guest-finished', guest_finished),
                         ('writers-stopped', writers_stopped)):
        if value is not True:
            reasons.append(name+'-unproven')
    return {'handoff_ready': not reasons, 'reasons': reasons,
            'independent_boot_proven': False}
