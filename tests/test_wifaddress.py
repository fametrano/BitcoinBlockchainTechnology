#!/usr/bin/env python3

# Copyright (C) 2017-2020 The btclib developers
#
# This file is part of btclib. It is subject to the license terms in the
# LICENSE file found in the top-level directory of this distribution.
#
# No part of btclib including this file, may be copied, modified, propagated,
# or distributed except according to the terms contained in the LICENSE file.

import unittest

from btclib import base58
from btclib.curve import mult
from btclib.curves import secp256k1 as ec
from btclib.utils import octets_from_int, point_from_octets, octets_from_point, h160
from btclib.wifaddress import wif_from_prvkey, prvkey_from_wif, \
    p2pkh_address, h160_from_p2pkh_address, p2pkh_address_from_wif, \
    p2sh_address, h160_from_p2sh_address
from btclib.script import serialize


class TestKeys(unittest.TestCase):


    def test_wif(self):
        q = b'0C28FCA386C7A227600B2FE50B7CAE11EC86D3BF1FBE471BE89827E19D72AA1D'
        q = 0xC28FCA386C7A227600B2FE50B7CAE11EC86D3BF1FBE471BE89827E19D72AA1D

        # compressed WIF
        wif = b'KwdMAjGmerYanjeui5SHS7JkmpZvVipYvB2LJGU1ZxJwYvP98617'
        self.assertEqual(wif, wif_from_prvkey(q, True))
        prvkey, compressed, network = prvkey_from_wif(wif)
        self.assertEqual(prvkey, q)
        self.assertEqual(compressed, True)

        # compressed WIF (testnet)
        wif = b'cMzLdeGd5vEqxB8B6VFQoRopQ3sLAAvEzDAoQgvX54xwofSWj1fx'
        self.assertEqual(wif, wif_from_prvkey(q, True, 'testnet'))
        prvkey, compressed, network = prvkey_from_wif(wif)
        self.assertEqual(prvkey, q)
        self.assertEqual(compressed, True)

        # uncompressed WIF
        wif = b'5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ'
        self.assertEqual(wif, wif_from_prvkey(q, False))
        prvkey, compressed, network = prvkey_from_wif(wif)
        self.assertEqual(prvkey, q)
        self.assertEqual(compressed, False)

        # uncompressed WIF (testnet)
        wif = b'91gGn1HgSap6CbU12F6z3pJri26xzp7Ay1VW6NHCoEayNXwRpu2'
        self.assertEqual(wif, wif_from_prvkey(q, False, 'testnet'))
        prvkey, compressed, network = prvkey_from_wif(wif)
        self.assertEqual(prvkey, q)
        self.assertEqual(compressed, False)

        # WIF as string with leading spaces
        wif = '  KwdMAjGmerYanjeui5SHS7JkmpZvVipYvB2LJGU1ZxJwYvP98617'
        prvkey, compressed, network = prvkey_from_wif(wif)
        self.assertEqual(prvkey, q)
        self.assertEqual(compressed, True)

        # WIF as string with trailing spaces
        wif = 'KwdMAjGmerYanjeui5SHS7JkmpZvVipYvB2LJGU1ZxJwYvP98617  '
        prvkey, compressed, network = prvkey_from_wif(wif)
        self.assertEqual(prvkey, q)
        self.assertEqual(compressed, True)


    def test_wif_exceptions(self):

        # private key not in (0, n)
        badq = ec.n
        self.assertRaises(ValueError, wif_from_prvkey, badq, True)
        #wif = wif_from_prvkey(badq, True)

        # Not a private key WIF: missing leading 0x80
        payload = b'\x81' + octets_from_int(badq, ec.psize)
        badwif = base58.encode(payload)
        self.assertRaises(ValueError, prvkey_from_wif, badwif)
        # prvkey_from_wif(badwif)

        # Not a compressed WIF: missing trailing 0x01
        payload = b'\x80' + octets_from_int(badq, ec.psize) + b'\x00'
        badwif = base58.encode(payload)
        self.assertRaises(ValueError, prvkey_from_wif, badwif)
        # prvkey_from_wif(badwif)

        # Not a WIF: wrong size (35)
        payload = b'\x80' + octets_from_int(badq, ec.psize) + b'\x01\x00'
        badwif = base58.encode(payload)
        self.assertRaises(ValueError, prvkey_from_wif, badwif)
        # prvkey_from_wif(badwif)

        # Not a WIF: private key not in (0, n)
        payload = b'\x80' + octets_from_int(badq, ec.psize)
        badwif = base58.encode(payload)
        self.assertRaises(ValueError, prvkey_from_wif, badwif)
        # prvkey_from_wif(badwif)


    def test_p2pkh_address_from_pubkey(self):
        # https://en.bitcoin.it/wiki/Technical_background_of_version_1_Bitcoin_addresses
        pub = '0250863ad64a87ae8a2fe83c1af1a8403cb53f53e486d8511dad8a04887e5b2352'
        addr = p2pkh_address(pub)
        self.assertEqual(addr, b'1PMycacnJaSqwwJqjawXBErnLsZ7RkXUAs')

        uncompressed_pub = octets_from_point(ec, point_from_octets(ec, pub), False)
        addr = p2pkh_address(uncompressed_pub)
        self.assertEqual(addr, b'16UwLL9Risc3QfPqBUvKofHmBQ7wMtjvM')

        # trailing/leading spaces in string
        pub = '  0250863ad64a87ae8a2fe83c1af1a8403cb53f53e486d8511dad8a04887e5b2352'
        addr = p2pkh_address(pub)
        self.assertEqual(addr, b'1PMycacnJaSqwwJqjawXBErnLsZ7RkXUAs')

        pub = '0250863ad64a87ae8a2fe83c1af1a8403cb53f53e486d8511dad8a04887e5b2352  '
        addr = p2pkh_address(pub)
        self.assertEqual(addr, b'1PMycacnJaSqwwJqjawXBErnLsZ7RkXUAs')

        self.assertEqual(h160_from_p2pkh_address(addr), h160(pub))
        
        # p2sh address for a network other than 'testnet'
        self.assertRaises(ValueError, h160_from_p2pkh_address, addr, 'testnet')
        # h160_from_p2pkh_address(addr, 'testnet')


    def test_p2sh_address_from_script(self):
        # https://medium.com/@darosior/bitcoin-raw-transactions-part-2-p2sh-94df206fee8d
        script = ['OP_2DUP', 'OP_EQUAL', 'OP_NOT', 'OP_VERIFY', 'OP_SHA1', 'OP_SWAP', 'OP_SHA1', 'OP_EQUAL']
        script_bytes = serialize(script)
        self.assertEqual(script_bytes.hex(), '6e879169a77ca787')

        addr = p2sh_address(script_bytes)
        self.assertEqual(addr, b'37k7toV1Nv4DfmQbmZ8KuZDQCYK9x5KpzP')

        redeem_script_hash = h160_from_p2sh_address(addr)
        self.assertEqual(redeem_script_hash, h160(script_bytes))

        self.assertEqual(redeem_script_hash.hex(), '4266fc6f2c2861d7fe229b279a79803afca7ba34')
        output_script = ['OP_HASH160', redeem_script_hash.hex(), 'OP_EQUAL']
        output_script_bytes = serialize(output_script)

        # address with trailing/leading spaces
        redeem_script_hash2 = h160_from_p2sh_address(' 37k7toV1Nv4DfmQbmZ8KuZDQCYK9x5KpzP ')
        self.assertEqual(redeem_script_hash, redeem_script_hash2)

        # p2sh address for a network other than 'testnet'
        self.assertRaises(ValueError, h160_from_p2sh_address, addr, 'testnet')
        # h160_from_p2sh_address(addr, 'testnet')


    def test_p2pkh_address_from_wif(self):
        wif1 = "5J1geo9kcAUSM6GJJmhYRX1eZEjvos9nFyWwPstVziTVueRJYvW"
        a = p2pkh_address_from_wif(wif1)
        self.assertEqual(a, b'1LPM8SZ4RQDMZymUmVSiSSvrDfj1UZY9ig')

        wif2 = "Kx621phdUCp6sgEXPSHwhDTrmHeUVrMkm6T95ycJyjyxbDXkr162"
        a = p2pkh_address_from_wif(wif2)
        self.assertEqual(a, b'1HJC7kFvXHepkSzdc8RX6khQKkAyntdfkB')

        self.assertEqual(prvkey_from_wif(wif1)[0], prvkey_from_wif(wif2)[0])

        # testnet
        wif1 = "91gGn1HgSap6CbU12F6z3pJri26xzp7Ay1VW6NHCoEayNXwRpu2"
        a = p2pkh_address_from_wif(wif1)
        self.assertEqual(a, b'mvgbzkCSgKbYgaeG38auUzR7otscEGi8U7')

        wif2 = "cMzLdeGd5vEqxB8B6VFQoRopQ3sLAAvEzDAoQgvX54xwofSWj1fx"
        a = p2pkh_address_from_wif(wif2)
        self.assertEqual(a, b'n1KSZGmQgB8iSZqv6UVhGkCGUbEdw8Lm3Q')

        self.assertEqual(prvkey_from_wif(wif1)[0], prvkey_from_wif(wif2)[0])

        # trailing/leading spaces in string
        wif1 = "  5J1geo9kcAUSM6GJJmhYRX1eZEjvos9nFyWwPstVziTVueRJYvW"
        a = p2pkh_address_from_wif(wif1)
        self.assertEqual(a, b'1LPM8SZ4RQDMZymUmVSiSSvrDfj1UZY9ig')

        wif2 = "Kx621phdUCp6sgEXPSHwhDTrmHeUVrMkm6T95ycJyjyxbDXkr162  "
        a = p2pkh_address_from_wif(wif2)
        self.assertEqual(a, b'1HJC7kFvXHepkSzdc8RX6khQKkAyntdfkB')


if __name__ == "__main__":
    # execute only if run as a script
    unittest.main()
