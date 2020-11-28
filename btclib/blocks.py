#!/usr/bin/env python3

# Copyright (C) 2020 The btclib developers
#
# This file is part of btclib. It is subject to the license terms in the
# LICENSE file found in the top-level directory of this distribution.
#
# No part of btclib including this file, may be copied, modified, propagated,
# or distributed except according to the terms contained in the LICENSE file.

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Type, TypeVar

from dataclasses_json import DataClassJsonMixin, config

from . import varint
from .alias import BinaryData
from .exceptions import BTClibValueError
from .tx import Tx
from .utils import bytesio_from_binarydata, hash256, hex_string

if sys.version_info.minor == 6:  # python 3.6
    import backports.datetime_fromisoformat  # pylint: disable=import-error  # pragma: no cover

    backports.datetime_fromisoformat.MonkeyPatch.patch_fromisoformat()  # pragma: no cover


_BlockHeader = TypeVar("_BlockHeader", bound="BlockHeader")


@dataclass
class BlockHeader(DataClassJsonMixin):
    # 4 bytes, signed little endian int
    version: int = 0
    # 32 bytes, reversed
    previous_block_hash: bytes = field(
        default=b"",
        metadata=config(encoder=lambda v: v.hex(), decoder=bytes.fromhex),
    )
    # 32 bytes, reversed
    merkle_root: bytes = field(
        default=b"",
        metadata=config(encoder=lambda v: v.hex(), decoder=bytes.fromhex),
    )
    # 4 bytes, unsigned little endian int, then converted to datetime
    time: datetime = field(
        default=datetime.fromtimestamp(0),
        metadata=config(
            encoder=datetime.isoformat, decoder=datetime.fromisoformat  # type: ignore
        ),
    )
    # 4 bytes, reversed
    bits: bytes = field(
        default=b"",
        metadata=config(encoder=lambda v: v.hex(), decoder=bytes.fromhex),
    )
    # 4 bytes, little endian int
    nonce: int = 0

    @property
    def bip9(self) -> bool:
        """Return whether the BlockHeader is signaling readiness for BIP9.

        BIP9 ("Version bits with timeout and delay")
        is signalled if the version top 3 bits are 001.
        https://github.com/bitcoin/bips/blob/master/bip-0009.mediawiki
        """
        # version is 4 bytes, 32 bits
        # right shift 29 bits and check if the remaining bits are 001
        return self.version >> 29 == 0b001

    @property
    def bip141(self) -> bool:
        """Return whether the BlockHeader is signaling readiness for BIP141.

        BIP141 ("Segregated Witness")
        is signalled if the 2nd bit from the right is 1

        https://github.com/bitcoin/bips/blob/master/bip-0141.mediawiki
        """
        # version is 4 bytes, 32 bits
        # shift 1 bit to the right and see if the rightmost bit is 1
        return self.bip9 and self.version >> 1 & 1 == 1

    @property
    def bip91(self) -> bool:
        """Return whether the BlockHeader is signaling readiness for BIP91.

        BIP91 ("Reduced threshold Segwit MASF")
        is signalled if the version 5th bit from the right is 1

        https://github.com/bitcoin/bips/blob/master/bip-0091.mediawiki
        """
        # version is 4 bytes, 32 bits
        # shift 4 bits to the right and see if the rightmost bit is 1
        return self.bip141 and self.version >> 4 & 1 == 1

    @property
    def hash(self) -> bytes:
        "Return the reversed 32 bytes hash256 of the BlockHeader."
        s = self.serialize(assert_valid=False)
        hash256_ = hash256(s)
        return hash256_[::-1]

    @property
    def target(self) -> bytes:
        """Return the BlockHeader proof-of-work target.

        The target aabbcc * 256^dd is represented
        in scientific notation by the 4 bytes bits 0xaabbccdd
        """
        # significand (also known as mantissa or coefficient)
        significand = int.from_bytes(self.bits[1:], "big")
        # power term, also called characteristics
        power_term = pow(256, (self.bits[0] - 3))
        return (significand * power_term).to_bytes(32, "big")

    @property
    def difficulty(self) -> float:
        """Return the BlockHeader difficulty.

        Difficulty is the ratio of the genesis block target
        over the BlockHeader target.

        It represents the average number of hash function evaluations
        required to satisfy the BlockHeader target,
        expressed as multiple of the genesis block difficulty used as unit.

        The difficulty of the genesis block is 2^32 (4*2^30),
        i.e. 4 GigaHash function evaluations.
        """
        # genesis block target
        genesis_significand = 0x00FFFF
        genesis_exponent = 0x1D
        # significand ratio
        significand = genesis_significand / int.from_bytes(self.bits[1:], "big")
        # power term ratio
        power_term = pow(256, genesis_exponent - self.bits[0])
        return significand * power_term

    def assert_valid_pow(self) -> None:
        "Assert whether the BlockHeader provides a valid proof-of-work."

        if self.hash >= self.target:
            err_msg = f"invalid proof-of-work: {self.hash.hex()}"
            err_msg += f" >= {self.target.hex()}"
            raise BTClibValueError(err_msg)

    def assert_valid(self) -> None:
        if not 0 < self.version <= 0x7FFFFFFF:
            raise BTClibValueError(f"invalid version: {hex(self.version)}")

        if len(self.previous_block_hash) != 32:
            err_msg = "invalid previous block hash"
            err_msg += f": {self.previous_block_hash.hex()}"
            raise BTClibValueError(err_msg)

        if len(self.merkle_root) != 32:
            err_msg = f"invalid merkle root: {hex_string(self.merkle_root)}"
            raise BTClibValueError(err_msg)

        if self.time.timestamp() < 1231006505:
            err_msg = "invalid timestamp (before genesis)"
            date = datetime.fromtimestamp(self.time.timestamp(), timezone.utc)
            err_msg += f": {date}"
            raise BTClibValueError(err_msg)

        if len(self.bits) != 4:
            raise BTClibValueError(f"invalid bits: {self.bits.hex()}")

        if not 0 < self.nonce <= 0xFFFFFFFF:
            raise BTClibValueError(f"invalid nonce: {hex(self.nonce)}")

        self.assert_valid_pow()

    def serialize(self, assert_valid: bool = True) -> bytes:
        "Return a BlockHeader binary serialization."

        if assert_valid:
            self.assert_valid()

        out = self.version.to_bytes(4, "little", signed=True)
        out += self.previous_block_hash[::-1]
        out += self.merkle_root[::-1]
        out += int(self.time.timestamp()).to_bytes(4, "little")
        out += self.bits[::-1]
        out += self.nonce.to_bytes(4, "little")

        return out

    @classmethod
    def deserialize(
        cls: Type[_BlockHeader], data: BinaryData, assert_valid: bool = True
    ) -> _BlockHeader:
        "Return a BlockHeader by parsing 80 bytes from a byte stream."
        stream = bytesio_from_binarydata(data)

        header = cls()
        header.version = int.from_bytes(stream.read(4), "little", signed=True)
        header.previous_block_hash = stream.read(32)[::-1]
        header.merkle_root = stream.read(32)[::-1]
        t = int.from_bytes(stream.read(4), "little")
        header.time = datetime.fromtimestamp(t, timezone.utc)
        header.bits = stream.read(4)[::-1]
        header.nonce = int.from_bytes(stream.read(4), "little")

        if assert_valid:
            header.assert_valid()
        return header


def merkle_root(transactions: List[Tx]) -> bytes:
    hashes = [transaction.txid[::-1] for transaction in transactions]
    hashes_buffer = []
    while len(hashes) != 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])
        for i in range(len(hashes) // 2):
            hashes_buffer.append(hash256(hashes[2 * i] + hashes[2 * i + 1]))
        hashes = hashes_buffer[:]
        hashes_buffer = []
    return hashes[0][::-1]


_Block = TypeVar("_Block", bound="Block")


@dataclass
class Block(DataClassJsonMixin):
    header: BlockHeader = field(default=BlockHeader())
    transactions: List[Tx] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.serialize(assert_valid=False))

    @property
    def weight(self) -> int:
        return sum(t.weight for t in self.transactions)

    # TODO: implement vsize

    def assert_valid(self) -> None:

        self.header.assert_valid()

        if not self.transactions[0].vin[0].prevout.is_coinbase:
            raise BTClibValueError("first transaction is not a coinbase")
        for transaction in self.transactions[1:]:
            transaction.assert_valid()

        merkle_root_ = merkle_root(self.transactions)
        if merkle_root_ != self.header.merkle_root:
            err_msg = f"invalid merkle root: {self.header.merkle_root.hex()}"
            err_msg += f" instead of: {merkle_root_.hex()}"
            raise BTClibValueError(err_msg)

    def serialize(
        self, include_witness: bool = True, assert_valid: bool = True
    ) -> bytes:
        if assert_valid:
            self.assert_valid()

        out = self.header.serialize()
        out += varint.encode(len(self.transactions))
        return out + b"".join([t.serialize(include_witness) for t in self.transactions])

    @classmethod
    def deserialize(
        cls: Type[_Block], data: BinaryData, assert_valid: bool = True
    ) -> _Block:
        stream = bytesio_from_binarydata(data)

        block = cls()
        block.header = BlockHeader.deserialize(stream)
        n = varint.decode(stream)
        block.transactions = [Tx.deserialize(stream) for _ in range(n)]

        if assert_valid:
            block.assert_valid()
        return block
