# SPDX-License-Identifier: GPL-3.0-or-later
"""Map 32-bit mux stream counters to bounded absolute counters."""
MODULUS = 1 << 32

def wire_sequence(absolute):
    if type(absolute) is not int or absolute < 0:
        raise ValueError("invalid absolute sequence")
    return absolute % MODULUS

def unwrap_ack(wire, previous, sent):
    if (type(wire) is not int or not 0 <= wire < MODULUS
            or not 0 <= previous <= sent or sent - previous >= MODULUS):
        raise ValueError("invalid acknowledgement interval")
    absolute = previous + (wire - previous) % MODULUS
    if absolute > sent:
        raise ValueError("ACK outside outstanding interval")
    return absolute
