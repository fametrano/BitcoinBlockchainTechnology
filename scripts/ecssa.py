# -*- coding: utf-8 -*-
"""
Created on Sat Oct 28 01:03:03 2017

@author: Leonardo, fametrano
"""

# import - check - decode - from/to ec_point - from/to int
# ecdsa - ecssa - sign-to-contract - test


# %% import

from hashlib import sha256
from base58 import b58decode_check, __chars as b58digits
from ECsecp256k1 import pointAdd, pointMultiply, \
                        order as ec_order, prime as ec_prime, G as ec_G, \
                        a as ec_a, b as ec_b
from FiniteFields import modInv, modular_sqrt
from string import hexdigits
from rfc6979 import rfc6979
from ecutils import default_hasher, check_hash_digest, decode_prv, hash_to_int, decode_pub, ec_x_to_y, int_to_bytes


# %% ecssa sign
# source:
# https://github.com/sipa/secp256k1/blob/968e2f415a5e764d159ee03e95815ea11460854e/src/modules/schnorr/schnorr.md

# different structure, cannot compute e (int) before ecssa_sign_raw

def ecssa_sign(m, prv, eph_prv=None, hasher=default_hasher):
  check_hash_digest(m)
  prv = decode_prv(prv)
  eph_prv = rfc6979(prv, m, hasher) if eph_prv is None else decode_prv(eph_prv)
  return ecssa_sign_raw(m, prv, eph_prv, hasher)

def ecssa_sign_raw(m, prv, eph_prv, hasher=default_hasher):
  R = pointMultiply(eph_prv, ec_G)
  if R[1] % 2 == 1:
      eph_prv = ec_order - eph_prv  # <=> R_y = ec_prime - R_y
  R_x = int_to_bytes(R[0], 32)
  e = hash_to_int(hasher(R_x + m).digest())
  assert e != 0 and e < ec_order, "sign fail"
  s = (eph_prv - e * prv) % ec_order
  return R[0], s

def ecssa_verify(m, ssasig, pub, hasher=default_hasher):
  check_hash_digest(m)
  check_ssasig(ssasig)
  pub = decode_pub(pub)
  return ecssa_verify_raw(m, ssasig, pub, hasher)

def ecssa_verify_raw(m, ssasig, pub, hasher):
  R_x, s = int_to_bytes(ssasig[0], 32), ssasig[1]
  e = hash_to_int(hasher(R_x + m).digest())
  if e == 0 or e >= ec_order:  # invalid e value
    return False
  # by choice at this level do not manage point at infinity (h = 0, R = 0G)
  R = pointAdd(pointMultiply(e, pub), pointMultiply(s, ec_G))
  if R[1] % 2 == 1:  # R.y odd
    return False
  return R[0] == ssasig[0]

def ecssa_recover(m, ssasig, hasher=default_hasher):
  check_hash_digest(m)
  check_ssasig(ssasig)
  return ecssa_recover_raw(m, ssasig, hasher)

def ecssa_recover_raw(m, ssasig, hasher=default_hasher):
  R_x, s = ssasig
  R = (R_x, ec_x_to_y(R_x, 0))
  R_x = int_to_bytes(R_x, 32)
  e = hash_to_int(hasher(R_x + m).digest())
  assert e != 0 and e < ec_order, "invalid e value"
  e1 = modInv(e, ec_order)
  # by choice at this level do not manage point at infinity (h = 0, R = 0G)
  return pointAdd(pointMultiply(e1, R), pointMultiply(-e1 * s % ec_order, ec_G))

def check_ssasig(ssasig):
  """check sig has correct ssa format
  """
  assert type(ssasig) == tuple and len(ssasig) == 2 and \
         type(ssasig[0]) == int and type(ssasig[1]) == int, \
         "ssasig must be a tuple of 2 int"
  assert 0 < ssasig[0] and ssasig[0] < ec_prime, "R.x must be in [1..prime]"
  assert 0 < ssasig[1] and ssasig[1] < ec_order, "s must be in [1..order]"
