#!/usr/bin/env python3
"""Use public-key OAEP encryption and TPM private-key decryption, as OpenBao does."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

os.environ['INFRABOX_TPM_PIN'] = sys.stdin.read().strip()
lib, token, label, bits = sys.argv[1:]
base = ['pkcs11-tool', '--module', lib, '--token-label', token, '--login',
        '--pin', 'env:INFRABOX_TPM_PIN', '--label', label]
def run(args):
    p = subprocess.run(args, capture_output=True)
    if p.returncode:
        raise RuntimeError('PKCS11 cryptographic verification failed: ' + args[0])
    return p.stdout
with tempfile.TemporaryDirectory(prefix='infrabox-pkcs11-') as d:
    d = Path(d)
    public, plain, encrypted, decrypted = [str(d / n) for n in ['public.der', 'plain', 'encrypted', 'decrypted']]
    run(base + ['--read-object', '--type', 'pubkey', '--output-file', public])
    description = run(['openssl', 'pkey', '-pubin', '-inform', 'DER', '-in', public, '-text', '-noout'])
    if (bits + ' bit').encode() not in description:
        raise RuntimeError('Seal key size differs from configured size')
    Path(plain).write_bytes(os.urandom(32))
    run(['openssl', 'pkeyutl', '-encrypt', '-pubin', '-keyform', 'DER', '-inkey', public,
         '-in', plain, '-out', encrypted, '-pkeyopt', 'rsa_padding_mode:oaep',
         '-pkeyopt', 'rsa_oaep_md:sha256', '-pkeyopt', 'rsa_mgf1_md:sha256'])
    run(base + ['--decrypt', '--mechanism', 'RSA-PKCS-OAEP', '--hash-algorithm', 'SHA256',
                '--mgf', 'MGF1-SHA256', '--input-file', encrypted, '--output-file', decrypted])
    if Path(plain).read_bytes() != Path(decrypted).read_bytes():
        raise RuntimeError('TPM round trip mismatch')
print('TPM RSA-OAEP SHA256 round trip verified')
