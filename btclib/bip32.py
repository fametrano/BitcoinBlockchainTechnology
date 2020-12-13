#!/usr/bin/env python3

# Copyright (C) 2017-2020 The btclib developers
#
# This file is part of btclib. It is subject to the license terms in the
# LICENSE file found in the top-level directory of this distribution.
#
# No part of btclib including this file, may be copied, modified, propagated,
# or distributed except according to the terms contained in the LICENSE file.

"""BIP32 Hierarchical Deterministic Wallet functions.

A deterministic wallet is a hash-chain of private/public key pairs that
derives from a single root, which is the only element requiring backup.
Moreover, there are schemes where public keys can be calculated without
accessing private keys.

A hierarchical deterministic wallet is a tree of multiple hash-chains,
derived from a single root, allowing for selective sharing of keypair
chains.

Here, the HD wallet is implemented according to BIP32 bitcoin standard
https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki.

A BIP32 extended key is 78 bytes:

- [  : 4] version
- [ 4: 5] depth in the derivation path
- [ 5: 9] parent fingerprint
- [ 9:13] index
- [13:45] chain code
- [45:78] compressed pub_key or [0x00][prv_key]
"""

import copy
import hmac
from dataclasses import InitVar, dataclass, field
from typing import Optional, Type, TypeVar, Union

from dataclasses_json import DataClassJsonMixin, config

from . import base58, bip39, electrum
from .alias import INF, BinaryData, Octets, Point, String
from .bip32_path import (
    BIP32DerPath,
    _int_from_index_str,
    _str_from_index_int,
    indexes_from_bip32_path,
)
from .curve import mult, secp256k1
from .exceptions import BTClibTypeError, BTClibValueError
from .mnemonic import Mnemonic
from .network import (
    _NETWORKS,
    _P2WPKH_PRV_PREFIXES,
    _XPRV_PREFIXES,
    _XPRV_VERSIONS_ALL,
    _XPUB_VERSIONS_ALL,
    NETWORKS,
)
from .sec_point import bytes_from_point, point_from_octets
from .utils import (
    bytes_from_octets,
    bytesio_from_binarydata,
    hash160,
    hex_string,
)

ec = secp256k1


_BIP32KeyData = TypeVar("_BIP32KeyData", bound="BIP32KeyData")
_EXPECTED_DECODED_LENGHT = 78


@dataclass
class BIP32KeyData(DataClassJsonMixin):
    version: bytes = field(
        default=b"", metadata=config(encoder=lambda v: v.hex(), decoder=bytes.fromhex)
    )
    depth: int = -1
    parent_fingerprint: bytes = field(
        default=b"", metadata=config(encoder=lambda v: v.hex(), decoder=bytes.fromhex)
    )
    # index is an int, not bytes, to avoid any byteorder ambiguity
    index: int = field(
        default=-1,
        metadata=config(encoder=_str_from_index_int, decoder=_int_from_index_str),
    )
    chain_code: bytes = field(
        default=b"", metadata=config(encoder=lambda v: v.hex(), decoder=bytes.fromhex)
    )
    key: bytes = field(
        default=b"", metadata=config(encoder=lambda v: v.hex(), decoder=bytes.fromhex)
    )
    check_validity: InitVar[bool] = True

    def __post_init__(self, check_validity: bool) -> None:
        if check_validity:
            self.assert_valid()

    def is_hardened(self) -> bool:
        return self.index >= 0x80000000

    def assert_valid(self) -> None:

        if not isinstance(self.version, bytes):
            raise BTClibTypeError("version is not an instance of bytes")
        if len(self.version) != 4:
            err_msg = "invalid version length: "
            err_msg += f"{len(self.version)} bytes"
            err_msg += " instead of 4"
            raise BTClibValueError(err_msg)

        if not isinstance(self.depth, int):
            raise BTClibTypeError("depth is not an instance of int")
        if self.depth < 0 or self.depth > 255:
            raise BTClibValueError(f"invalid depth: {self.depth}")

        if not isinstance(self.parent_fingerprint, bytes):
            raise BTClibTypeError("parent fingerprint is not an instance of bytes")
        if len(self.parent_fingerprint) != 4:
            err_msg = "invalid parent fingerprint length: "
            err_msg += f"{len(self.parent_fingerprint)} bytes"
            err_msg += " instead of 4"
            raise BTClibValueError(err_msg)

        if not isinstance(self.index, int):
            raise BTClibTypeError("index is not an instance of bytes")
        if not 0 <= self.index <= 0xFFFFFFFF:
            raise BTClibValueError(f"invalid index: {self.index}")

        if not isinstance(self.chain_code, bytes):
            raise BTClibTypeError("chain code is not an instance of bytes")
        if len(self.chain_code) != 32:
            err_msg = "invalid chain code length: "
            err_msg += f"{len(self.chain_code)} bytes"
            err_msg += " instead of 32"
            raise BTClibValueError(err_msg)

        if not isinstance(self.key, bytes):
            raise BTClibTypeError("key is not an instance of bytes")
        if len(self.key) != 33:
            err_msg = "invalid key length: "
            err_msg += f"{len(self.key)} bytes"
            err_msg += " instead of 33"
            raise BTClibValueError(err_msg)

        if self.version in _XPRV_VERSIONS_ALL:
            if self.key[0] != 0:
                raise BTClibValueError(
                    f"invalid private key prefix: 0x{self.key[:1].hex()}"
                )
            q = int.from_bytes(self.key[1:], byteorder="big", signed=False)
            if not 0 < q < ec.n:
                raise BTClibValueError(f"invalid private key not in 1..n-1: {hex(q)}")
        elif self.version in _XPUB_VERSIONS_ALL:
            if self.key[0] not in (2, 3):
                err_msg = f"invalid public key prefix not in (0x02, 0x03): 0x{self.key[:1].hex()}"
                raise BTClibValueError(err_msg)
            try:
                ec.y(int.from_bytes(self.key[1:], byteorder="big", signed=False))
            except BTClibValueError as e:
                err_msg = f"invalid public key: 0x{self.key.hex()}"
                raise BTClibValueError(err_msg) from e
        else:
            raise BTClibValueError(
                f"unknown extended key version: 0x{self.version.hex()}"
            )

        if self.depth == 0:
            if self.parent_fingerprint != bytes.fromhex("00000000"):
                err_msg = f"zero depth with non-zero parent fingerprint: 0x{self.parent_fingerprint.hex()}"
                raise BTClibValueError(err_msg)
            if self.index != 0:
                raise BTClibValueError(f"zero depth with non-zero index: {self.index}")

    def serialize(self, assert_valid: bool = True) -> bytes:

        if assert_valid:
            self.assert_valid()

        xkey_bin = self.version
        xkey_bin += self.depth.to_bytes(1, byteorder="big", signed=False)
        xkey_bin += self.parent_fingerprint
        xkey_bin += self.index.to_bytes(4, byteorder="big", signed=False)
        xkey_bin += self.chain_code
        xkey_bin += self.key
        return xkey_bin

    @classmethod
    def deserialize(
        cls: Type[_BIP32KeyData], xkey_bin: BinaryData, assert_valid: bool = True
    ) -> _BIP32KeyData:
        "Return a BIP32KeyData by parsing 73 bytes from binary data."

        stream = bytesio_from_binarydata(xkey_bin)
        xkey = cls(check_validity=False)

        xkey.version = stream.read(4)
        xkey.depth = int.from_bytes(stream.read(1), byteorder="big", signed=False)
        xkey.parent_fingerprint = stream.read(4)
        xkey.index = int.from_bytes(stream.read(4), byteorder="big", signed=False)
        xkey.chain_code = stream.read(32)
        xkey.key = stream.read(33)

        if assert_valid:
            xkey.assert_valid()
        return xkey

    def b58encode(self, assert_valid: bool = True) -> bytes:
        data_binary = self.serialize(assert_valid)
        return base58.b58encode(data_binary)

    @classmethod
    def b58decode(
        cls: Type[_BIP32KeyData], data_str: String, assert_valid: bool = True
    ) -> _BIP32KeyData:
        if isinstance(data_str, str):
            data_str = data_str.strip()
        data_decoded = base58.b58decode(data_str)
        if assert_valid and len(data_decoded) != _EXPECTED_DECODED_LENGHT:
            err_msg = f"invalid decoded length: {len(data_decoded)}"
            err_msg += f" instead of {_EXPECTED_DECODED_LENGHT}"
            raise BTClibValueError(err_msg)
        return cls.deserialize(data_decoded, assert_valid)


def _rootxprv_from_seed(
    seed: Octets, version: Octets = NETWORKS["mainnet"].bip32_prv
) -> BIP32KeyData:
    """Return BIP32 root master extended private key from seed."""

    seed = bytes_from_octets(seed)
    bitlenght = len(seed) * 8
    if bitlenght < 128:
        raise BTClibValueError(
            f"too few bits for seed: {bitlenght} in '{hex_string(seed)}'"
        )
    if bitlenght > 512:
        raise BTClibValueError(
            f"too many bits for seed: {bitlenght} in '{hex_string(seed)}'"
        )
    hmac_ = hmac.new(b"Bitcoin seed", seed, "sha512").digest()
    k = b"\x00" + hmac_[:32]
    v = bytes_from_octets(version, 4)
    if v not in _XPRV_VERSIONS_ALL:
        raise BTClibValueError(f"unknown private key version: {v.hex()}")

    return BIP32KeyData(
        version=v,
        depth=0,
        parent_fingerprint=bytes.fromhex("00000000"),
        index=0,
        chain_code=hmac_[32:],
        key=k,
    )


def rootxprv_from_seed(
    seed: Octets, version: Octets = NETWORKS["mainnet"].bip32_prv
) -> str:
    """Return BIP32 root master extended private key from seed."""
    xkey = _rootxprv_from_seed(seed, version)
    return xkey.b58encode().decode("ascii")


def _mxprv_from_bip39_mnemonic(
    mnemonic: Mnemonic, passphrase: Optional[str] = None, network: str = "mainnet"
) -> BIP32KeyData:
    """Return BIP32 root master extended private key from BIP39 mnemonic."""

    seed = bip39.seed_from_mnemonic(mnemonic, passphrase or "")
    version = NETWORKS[network].bip32_prv
    return _rootxprv_from_seed(seed, version)


def mxprv_from_bip39_mnemonic(
    mnemonic: Mnemonic, passphrase: Optional[str] = None, network: str = "mainnet"
) -> str:
    """Return BIP32 root master extended private key from BIP39 mnemonic."""
    xkey = _mxprv_from_bip39_mnemonic(mnemonic, passphrase, network)
    return xkey.b58encode().decode("ascii")


def _mxprv_from_electrum_mnemonic(
    mnemonic: Mnemonic, passphrase: Optional[str] = None, network: str = "mainnet"
) -> BIP32KeyData:
    """Return BIP32 master extended private key from Electrum mnemonic.

    Note that for a "standard" mnemonic the derivation path is "m",
    for a "segwit" mnemonic it is "m/0h" instead.
    """

    version, seed = electrum._seed_from_mnemonic(mnemonic, passphrase or "")
    network_index = _NETWORKS.index(network)

    if version == "standard":
        xversion = _XPRV_PREFIXES[network_index]
        return _rootxprv_from_seed(seed, xversion)
    if version == "segwit":
        xversion = _P2WPKH_PRV_PREFIXES[network_index]
        rootxprv = rootxprv_from_seed(seed, xversion)
        return _derive(rootxprv, 0x80000000)  # "m/0h"
    raise BTClibValueError(f"unmanaged electrum mnemonic version: {version}")


def mxprv_from_electrum_mnemonic(
    mnemonic: Mnemonic, passphrase: Optional[str] = None, network: str = "mainnet"
) -> str:
    """Return BIP32 master extended private key from Electrum mnemonic.

    Note that for a "standard" mnemonic the derivation path is "m",
    for a "segwit" mnemonic it is "m/0h" instead.
    """
    xkey = _mxprv_from_electrum_mnemonic(mnemonic, passphrase, network)
    return xkey.b58encode().decode("ascii")


BIP32Key = Union[BIP32KeyData, String]


def _xpub_from_xprv(xprv: BIP32Key) -> BIP32KeyData:
    """Neutered Derivation (ND).

    Derivation of the extended public key corresponding to an extended
    private key (“neutered” as it removes the ability to sign transactions).
    """

    if isinstance(xprv, BIP32KeyData):
        xkey = copy.copy(xprv)
    else:
        xkey = BIP32KeyData.b58decode(xprv)

    if xkey.key[0] != 0:
        err_msg = f"not a private key: {xkey.b58encode().decode('ascii')}"
        raise BTClibValueError(err_msg)

    i = _XPRV_VERSIONS_ALL.index(xkey.version)
    xkey.version = _XPUB_VERSIONS_ALL[i]

    q = int.from_bytes(xkey.key[1:], byteorder="big", signed=False)
    Q = mult(q)
    xkey.key = bytes_from_point(Q)

    return xkey


def xpub_from_xprv(xprv: BIP32Key) -> str:
    """Neutered Derivation (ND).

    Derivation of the extended public key corresponding to an extended
    private key (“neutered” as it removes the ability to sign transactions).
    """
    xkey = _xpub_from_xprv(xprv)
    return xkey.b58encode().decode("ascii")


@dataclass
class _ExtendedBIP32KeyData(BIP32KeyData):
    # extensions used to cache intermediate results
    # in multi-level derivation: do not rely on them elsewhere
    q: int = 0  # non-zero for private key only
    Q: Point = INF  # non-Infinity for public key only


def __ckd(xkey: _ExtendedBIP32KeyData, index: int) -> None:

    xkey.depth += 1
    xkey.index = index
    if xkey.key[0] == 0:  # private key
        Q_bytes = bytes_from_point(mult(xkey.q))
        xkey.parent_fingerprint = hash160(Q_bytes)[:4]
        if xkey.is_hardened():  # hardened derivation
            hmac_ = hmac.new(
                xkey.chain_code,
                xkey.key + index.to_bytes(4, byteorder="big", signed=False),
                "sha512",
            ).digest()
        else:  # normal derivation
            hmac_ = hmac.new(
                xkey.chain_code,
                Q_bytes + index.to_bytes(4, byteorder="big", signed=False),
                "sha512",
            ).digest()
        xkey.chain_code = hmac_[32:]
        offset = int.from_bytes(hmac_[:32], byteorder="big", signed=False)
        xkey.q = (xkey.q + offset) % ec.n
        xkey.key = b"\x00" + xkey.q.to_bytes(32, byteorder="big", signed=False)
        xkey.Q = INF
    else:  # public key
        xkey.parent_fingerprint = hash160(xkey.key)[:4]
        if xkey.is_hardened():
            raise BTClibValueError("invalid hardened derivation from public key")
        hmac_ = hmac.new(
            xkey.chain_code,
            xkey.key + index.to_bytes(4, byteorder="big", signed=False),
            "sha512",
        ).digest()
        xkey.chain_code = hmac_[32:]
        offset = int.from_bytes(hmac_[:32], byteorder="big", signed=False)
        xkey.Q = ec.add(xkey.Q, mult(offset))
        xkey.key = bytes_from_point(xkey.Q)
        xkey.q = 0


def _derive(
    xkey: BIP32Key, der_path: BIP32DerPath, forced_version: Optional[Octets] = None
) -> BIP32KeyData:

    if not isinstance(xkey, BIP32KeyData):
        xkey = BIP32KeyData.b58decode(xkey)

    indexes = indexes_from_bip32_path(der_path)

    final_depth = xkey.depth + len(indexes)
    if final_depth > 255:
        err_msg = f"final depth greater than 255: {final_depth}"
        raise BTClibValueError(err_msg)

    is_prv = xkey.key[0] == 0
    q = int.from_bytes(xkey.key[1:], byteorder="big", signed=False) if is_prv else 0
    Q = INF if is_prv else point_from_octets(xkey.key, ec)
    xkey = _ExtendedBIP32KeyData(
        version=xkey.version,
        depth=xkey.depth,
        parent_fingerprint=xkey.parent_fingerprint,
        index=xkey.index,
        chain_code=xkey.chain_code,
        key=xkey.key,
        q=q,
        Q=Q,
    )
    for index in indexes:
        __ckd(xkey, index)

    if forced_version:
        if xkey.version in _XPRV_VERSIONS_ALL:
            allowed_versions = _XPRV_VERSIONS_ALL
        else:
            allowed_versions = _XPUB_VERSIONS_ALL
        fversion = bytes_from_octets(forced_version, 4)
        if fversion not in allowed_versions:
            err_msg = "invalid version forced on the extended key"
            err_msg += f"{hex_string(fversion)}"
            raise BTClibValueError(err_msg)
        xkey.version = fversion

    return xkey


def derive(
    xkey: BIP32Key, der_path: BIP32DerPath, forced_version: Optional[Octets] = None
) -> str:
    """Derive a BIP32 key across a path spanning multiple depth levels.

    Valid BIP32DerPath examples:

    - string like "m/44h/0'/1H/0/10"
    - iterable integer indexes
    - one single integer index
    - bytes in multiples of the 4-bytes index

    BIP32DerPath is case/blank/extra-slash insensitive
    (e.g. "M /44h / 0' /1H // 0/ 10 / ").
    """
    xkey = _derive(xkey, der_path, forced_version)
    return xkey.b58encode().decode("ascii")


def _derive_from_account(
    xkey: BIP32Key, branch: int, address_index: int, branches_0_1_only: bool = True
) -> BIP32KeyData:

    if not isinstance(xkey, BIP32KeyData):
        xkey = BIP32KeyData.b58decode(xkey)

    if not xkey.is_hardened():
        raise UserWarning("invalid public derivation at account level")
    if branch >= 0x80000000:
        raise BTClibValueError("invalid private derivation at branch level")
    if branches_0_1_only and branch not in (0, 1):
        raise BTClibValueError(f"invalid branch: {branch} not in (0, 1)")
    if address_index >= 0x80000000:
        raise BTClibValueError("invalid private derivation at address index level")

    return _derive(xkey, f"m/{branch}/{address_index}")


def derive_from_account(
    xkey: BIP32Key, branch: int, address_index: int, branches_0_1_only: bool = True
) -> str:

    xkey = _derive_from_account(xkey, branch, address_index, branches_0_1_only)
    return xkey.b58encode().decode("ascii")


def crack_prv_key(parent_xpub: BIP32Key, child_xprv: BIP32Key) -> str:

    if isinstance(parent_xpub, BIP32KeyData):
        p = copy.copy(parent_xpub)
    else:
        p = BIP32KeyData.b58decode(parent_xpub)

    if p.key[0] not in (2, 3):
        err_msg = "extended parent key is not a public key: "
        err_msg += f"{p.b58encode().decode('ascii')}"
        raise BTClibValueError(err_msg)

    if isinstance(child_xprv, BIP32KeyData):
        c = child_xprv
    else:
        c = BIP32KeyData.b58decode(child_xprv)

    if c.key[0] != 0:
        err_msg = "extended child key is not a private key: "
        err_msg += f"{c.b58encode().decode('ascii')}"
        raise BTClibValueError(err_msg)

    # check depth
    if c.depth != p.depth + 1:
        raise BTClibValueError("not a parent's child: wrong depths")

    # check fingerprint
    if c.parent_fingerprint != hash160(p.key)[:4]:
        raise BTClibValueError("not a parent's child: wrong parent fingerprint")

    if c.is_hardened():
        raise BTClibValueError("hardened child derivation")

    p.version = c.version

    hmac_ = hmac.new(
        p.chain_code,
        p.key + c.index.to_bytes(4, byteorder="big", signed=False),
        "sha512",
    ).digest()
    child_q = int.from_bytes(c.key[1:], byteorder="big", signed=False)
    offset = int.from_bytes(hmac_[:32], byteorder="big", signed=False)
    parent_q = (child_q - offset) % ec.n
    p.key = b"\x00" + parent_q.to_bytes(32, byteorder="big", signed=False)

    return p.b58encode().decode("ascii")
