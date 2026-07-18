#!/bin/bash
# Crea un certificado de firma de código autofirmado "Dictador Dev" y lo instala
# confiado en el llavero. Con él, la firma del app es estable entre rebuilds y
# macOS NO revoca los permisos TCC (Accesibilidad/Micrófono/etc.) en cada build.
#
# Requiere interacción: macOS muestra un diálogo pidiendo la contraseña del
# usuario al confiar el certificado (una sola vez).
set -euo pipefail

NAME="Dictador Dev"
DIR="$HOME/.dictador/cert"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

# ¿ya existe la identidad? entonces no hay nada que hacer
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$NAME"; then
  echo "OK: la identidad '$NAME' ya existe en el llavero."
  exit 0
fi

mkdir -p "$DIR"
cd "$DIR"

cat > openssl.cnf <<'EOF'
[req]
distinguished_name = dn
x509_extensions = codesign_ext
prompt = no
[dn]
CN = Dictador Dev
[codesign_ext]
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
basicConstraints = critical,CA:FALSE
EOF

echo "→ Generando clave y certificado (10 años)…"
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 3650 -nodes -config openssl.cnf

# Importamos clave y cert como PEM por separado: el p12 falla según qué
# openssl lo genere ("MAC verification failed" — cifrados que el llavero
# no entiende). Con PEMs el llavero forma la identidad casándolos solo.
echo "→ Importando clave privada al llavero (autorizada para codesign)…"
security import key.pem -k "$KEYCHAIN" -T /usr/bin/codesign

echo "→ Importando certificado…"
security import cert.pem -k "$KEYCHAIN"

echo "→ Confiando el certificado para firma de código (saldrá un diálogo de contraseña)…"
security add-trusted-cert -p codeSign -k "$KEYCHAIN" cert.pem

chmod 600 key.pem
echo "→ Verificando identidad…"
security find-identity -v -p codesigning | grep "$NAME" && echo "LISTO: firma con: codesign -s '$NAME' …"
