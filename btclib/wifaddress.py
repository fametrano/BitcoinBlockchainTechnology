#!/usr/bin/env python3

# Copyright (C) 2017-2020 The btclib developers
#
# This file is part of btclib. It is subject to the license terms in the
# LICENSE file found in the top-level directory of this distribution.
#
# No part of btclib including this file, may be copied, modified, propagated,
# or distributed except according to the terms contained in the LICENSE file.

"""Wallet Import Format (WIF) and Address functions.

Implementation of Base58 encoding of private keys (WIFs)
and public keys (addresses).
"""

from typing import Tuple, Union

from . import base58
from .curve import mult
from .curves import secp256k1
from .utils import Octets, int_from_octets, octets_from_int, \
    octets_from_point, h160

_NETWORKS = ['mainnet', 'testnet', 'regtest']
_CURVES = [secp256k1, secp256k1, secp256k1]
_WIF_PREFIXES = [
    b'\x80',  # WIF starts with {K,L} (if compressed) or 5 (if uncompressed)
    b'\xef',  # WIF starts with c (if compressed) or 9 (if uncompressed)
    b'\xef',  # WIF starts with c (if compressed) or 9 (if uncompressed)
]
_P2PKH_PREFIXES = [
    b'\x00',  # address starts with 1
    b'\x6f',  # address starts with {m, n}
    b'\x6f'   # address starts with {m, n}
]
_P2SH_PREFIXES = [
    b'\x05',  # address starts with 3
    b'\xc4',  # address starts with 2
    b'\xc4',  # address starts with 2
]


def wif_from_prvkey(prvkey: Union[int, Octets],
                    compressed: bool = True,
                    network: str = 'mainnet') -> bytes:
    """Return the Wallet Import Format from a private key."""

    network_index = _NETWORKS.index(network)
    payload = _WIF_PREFIXES[network_index]

    ec = _CURVES[network_index]
    if isinstance(prvkey, int):
        payload += octets_from_int(prvkey, ec.nsize)
    elif isinstance(prvkey, str):
        prvkey = prvkey.strip()
        t = bytes.fromhex(prvkey)
        payload += t
        prvkey = int.from_bytes(t, 'big')
    else:
        payload += prvkey
        prvkey = int.from_bytes(prvkey, 'big')
    if not 0 < prvkey < ec.n:
        raise ValueError(f"private key {hex(prvkey)} not in (0, ec.n)")

    payload += b'\x01' if compressed else b''
    return base58.encode(payload)


def prvkey_from_wif(wif: Union[str, bytes]) -> Tuple[int, bool, str]:
    """Return the (private key, compressed, network) tuple from a WIF."""

    if isinstance(wif, str):
        wif = wif.strip()

    payload = base58.decode(wif)
    wif_index = _WIF_PREFIXES.index(payload[0:1])
    ec = _CURVES[wif_index]

    if len(payload) == ec.nsize + 2:       # compressed WIF
        compressed = True
        if payload[-1] != 0x01:            # must have a trailing 0x01
            raise ValueError("Not a compressed WIF: missing trailing 0x01")
        prv = int_from_octets(payload[1:-1])
    elif len(payload) == ec.nsize + 1:     # uncompressed WIF
        compressed = False
        prv = int_from_octets(payload[1:])
    else:
        raise ValueError(f"Not a WIF: wrong size ({len(payload)})")

    if not 0 < prv < ec.n:
        msg = f"Not a WIF: private key {hex(prv)} not in [1, n-1]"
        raise ValueError(msg)

    network = _NETWORKS[wif_index]
    return prv, compressed, network


def p2pkh_address_from_wif(wif: Union[str, bytes]) -> bytes:
    """Return the address corresponding to a WIF.

    WIF encodes the information about the pubkey to be used for the
    address computation being the compressed or uncompressed one.
    """

    if isinstance(wif, str):
        wif = wif.strip()

    prv, compressed, network = prvkey_from_wif(wif)
    network_index = _NETWORKS.index(network)
    ec = _CURVES[network_index]
    Pub = mult(ec, prv)
    o = octets_from_point(ec, Pub, compressed)
    return p2pkh_address(o, network)


def p2pkh_address(pubkey: Octets, network: str = 'mainnet') -> bytes:
    """Return the p2pkh address corresponding to a public key."""

    payload = _P2PKH_PREFIXES[_NETWORKS.index(network)]
    payload += h160(pubkey)
    return base58.encode(payload)


def h160_from_p2pkh_address(address = Union[str, bytes],
                            network: str = 'mainnet') -> bytes:
    if isinstance(address, str):
        address = address.strip()

    payload = base58.decode(address, 21)
    # check that it is a p2pkh address
    i = _P2PKH_PREFIXES.index(payload[0:1])
    # check that it is a p2pkh address for the given network
    if _NETWORKS[i] != network:
        msg = f"{address} is a p2pkh address for "
        msg += f"a network other than '{network}'"
        raise ValueError(msg)
    return payload[1:]


def p2sh_address(redeem_script: Octets, network: str = 'mainnet') -> bytes:
    """Return p2sh address."""

    payload = _P2SH_PREFIXES[_NETWORKS.index(network)]
    payload += h160(redeem_script)
    return base58.encode(payload)


def h160_from_p2sh_address(address = Union[str, bytes],
                           network: str = 'mainnet') -> bytes:
    if isinstance(address, str):
        address = address.strip()

    payload = base58.decode(address, 21)
    # check that it is a p2sh address
    i = _P2SH_PREFIXES.index(payload[0:1])
    # check that it is a p2sh address for the given network
    if _NETWORKS[i] != network:
        msg = f"{address} is a p2sh address for "
        msg += f"a network other than '{network}'"
        raise ValueError(msg)
    return payload[1:]
