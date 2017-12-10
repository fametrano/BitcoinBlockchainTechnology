# -*- coding: utf-8 -*-
"""
Created on Sun Dec 10 16:53:56 2017

@author: dfornaro
"""

from electrum_seed import from_mnemonic_to_seed_eletrcum, verify_mnemonic_electrum, from_entropy_to_mnemonic_int_electrum, from_mnemonic_int_to_mnemonic_electrum
from change_receive_path import path
from bip32_functions import bip32_master_key, bip32_xprvtoxpub

def generate_wallet_electrum(entropy, number_words = 24, passphrase='', version = "standard"):
  verify = False
  while verify==False:
    mnemonic_int = from_entropy_to_mnemonic_int_electrum(entropy, number_words)
    mnemonic = from_mnemonic_int_to_mnemonic_electrum(mnemonic_int, 'Dictionary.txt')
    verify = verify_mnemonic_electrum(mnemonic, version)
    if verify==False:
      entropy = entropy + 1
  seed = from_mnemonic_to_seed_eletrcum(mnemonic, passphrase)
  seed = int(seed, 16)
  seed_bytes = 64
  xprv = bip32_master_key(seed, seed_bytes)
  xpub = bip32_xprvtoxpub(xprv)
  return mnemonic, entropy, xpub

def generate_receive(xpub, number):
  index_child = [0, number]
  return path(xpub, index_child)

def generate_change(xpub, number):
  index_child = [1, number]
  return path(xpub, index_child)

entropy = 0x545454545454545454545454545454545454545454545454545454545454666666
number_words = 24

entropy_lenght = int(11*number_words/4)

print('Your entropy should have', entropy_lenght, 'hexadecimal digits')
mnemonic, entropy, xpub = generate_wallet_electrum(entropy)

print('\nmnemonic: ', mnemonic)
print('\nxpub: ', xpub)

receive0 = generate_receive(xpub, 0)
receive1 = generate_receive(xpub, 1)
receive2 = generate_receive(xpub, 2)
receive3 = generate_receive(xpub, 3)

change0 = generate_change(xpub, 0)
change1 = generate_change(xpub, 1)
change2 = generate_change(xpub, 2)
change3 = generate_change(xpub, 3)


print('\nfirst receive address: ', receive0)
print('second receive address: ', receive1)
print('third receive address: ', receive2)
print('fourth receive address: ', receive3)

print('\nfirst change address: ', change0)
print('second change address: ', change1)
print('third change address: ', change2)
print('fourth change address: ', change3)
