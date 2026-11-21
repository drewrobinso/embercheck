#!/bin/bash
# LOCAL TEST SIGNING ONLY - never ship these files. Releases are signed by SignPath in CI.
# Creates a throw-away self-signed code-signing cert in ./signing/ (gitignored) and signs copies of the
# built exes into dist/test-signed/ so the signing + timestamp pipeline can be checked with osslsigncode.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
VERSION=$(sed -n "s/^VERSION = '\(.*\)'/\1/p" src/bambu_optimizer.py)
S=signing; mkdir -p "$S"; chmod 700 "$S"
if [ ! -f "$S/test-codesign.key" ]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -days 365 -nodes -keyout "$S/test-codesign.key" -out "$S/test-codesign.crt" \
    -subj "/CN=Bambu Print Optimizer TEST (self-signed, do not trust)" \
    -addext "keyUsage=critical,digitalSignature" -addext "extendedKeyUsage=codeSigning" 2>/dev/null
  chmod 600 "$S/test-codesign.key"
fi
OUT=dist/test-signed; rm -rf "$OUT"; mkdir -p "$OUT"
for f in "dist/PrintOptimizer/PrintOptimizer.exe" "dist/PrintOptimizer-Setup-$VERSION.exe"; do
  b=$(basename "$f" .exe)
  ok=0
  for tsa in ${TSA:-http://timestamp.digicert.com https://timestamp.sectigo.com https://freetsa.org/tsr}; do
    rm -f "$OUT/$b-TESTSIGNED.exe"
    if osslsigncode sign -certs "$S/test-codesign.crt" -key "$S/test-codesign.key" -h sha256 \
        -n "Bambu Print Optimizer" -i "https://github.com/drewrobinso/bambu-print-optimizer" \
        -ts "$tsa" -in "$f" -out "$OUT/$b-TESTSIGNED.exe" >/dev/null 2>&1; then ok=1; echo "timestamped by $tsa"; break; fi
  done
  [ $ok = 1 ] || { echo "signing/timestamp failed for $f"; exit 1; }
  echo "== $OUT/$b-TESTSIGNED.exe"
  osslsigncode verify -CAfile "$S/test-codesign.crt" -TSA-CAfile /etc/ssl/certs/ca-certificates.crt -in "$OUT/$b-TESTSIGNED.exe" 2>&1 \
    | grep -E "Message digest|Signer's certificate|Subject:|Timestamp|Signature verification|Succeeded|Failed" | head -12
done
