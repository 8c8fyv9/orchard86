# SPDX-License-Identifier: GPL-3.0-or-later
"""Bound outstanding mux data independently of application read size."""
def allowance(sent, acknowledged):
    if not 0 <= acknowledged <= sent: raise ValueError("invalid credit")
    return min(16384,max(0,1048576-(sent-acknowledged)))
