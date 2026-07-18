# Publicar una versión de Voxly

Cómo pasar del código a un DMG que cualquiera pueda descargar e instalar.

Casi todo lo automatiza `scripts/release.sh`. Lo que no puede automatizarse es
la configuración inicial de la cuenta de Apple: son **cuatro pasos, una sola vez**.

---

## Preparación (una sola vez)

### 1. Crear el certificado Developer ID Application

Es lo que permite que macOS abra la app en un Mac que no es el tuyo. Requiere el
Apple Developer Program (99 $/año, el mismo que ya usas para las apps de la App
Store).

1. Abre **Xcode → Settings → Accounts**, selecciona tu cuenta y pulsa **Manage
   Certificates…**
2. Pulsa **+** abajo a la izquierda y elige **Developer ID Application**.
3. Xcode lo crea y lo instala en el llavero.

> Alternativa manual: en developer.apple.com → Certificates, IDs & Profiles →
> Certificates → **+** → Developer ID Application. Descarga el `.cer` y haz doble
> clic para instalarlo.

Comprueba que está:

```bash
security find-identity -v -p codesigning | grep "Developer ID Application"
```

Debe aparecer una línea con `Developer ID Application: Eduardo Crovetto (96Y828UCBL)`.

### 2. Crear una contraseña específica de app

La notarización no acepta tu contraseña normal de Apple ID.

1. Entra en [appleid.apple.com](https://appleid.apple.com) → **Sign-In and Security**
   → **App-Specific Passwords**.
2. Genera una nueva (nómbrala "voxly-notarization") y **cópiala**: solo se muestra
   una vez.

### 3. Guardar el perfil de notarización

Esto deja las credenciales en el llavero para que el script no las pida cada vez:

```bash
xcrun notarytool store-credentials voxly \
  --apple-id tu-email@ejemplo.com \
  --team-id 96Y828UCBL \
  --password <la-contraseña-específica-del-paso-2>
```

Verifica:

```bash
xcrun notarytool history --keychain-profile voxly
```

### 4. Crear el repositorio de GitHub para las descargas

Los DMG se sirven desde GitHub Releases (gratis y sin límite de tráfico):

```bash
gh repo create voxly --public --source=. --remote=origin
```

---

## Publicar una versión

### 1. Subir el número de versión

En `Voxly.spec`, ambos campos a la vez:

```python
"CFBundleVersion": "1.0.1",
"CFBundleShortVersionString": "1.0.1",
```

### 2. Ensayo (opcional pero recomendado)

Valida toda la mecánica —build, firma de los 145 binarios internos, DMG— sin
gastar una notarización:

```bash
./scripts/release.sh --dry-run
```

### 3. Release de verdad

```bash
./scripts/release.sh
```

Hace, en orden: compila → copia fuera de iCloud → firma de dentro afuera con
hardened runtime → notariza la app (unos minutos) → staplea → crea el DMG →
firma y notariza el DMG → verifica con `spctl` lo mismo que verá Gatekeeper.

El resultado queda en `~/.dictador/release/Voxly-<versión>.dmg`.

### 4. Subir el DMG a GitHub Releases

```bash
gh release create v1.0.1 ~/.dictador/release/Voxly-1.0.1.dmg \
  --title "Voxly 1.0.1" --notes "Qué ha cambiado…"
```

### 5. Actualizar el appcast y desplegar la web

En `web/appcast.json`, poner la versión nueva y la URL del DMG. Las apps ya
instaladas lo consultan al arrancar y muestran "Update to 1.0.1 →" en el menú.

```bash
cd web && vercel --prod
```

---

## Por qué el proyecto está montado así

**Por qué no el Mac App Store.** Voxly necesita un hotkey global y pegar texto en
apps de terceros; el sandbox obligatorio del App Store prohíbe ambas cosas. Es el
mismo motivo por el que Wispr Flow, superwhisper y MacWhisper se distribuyen
fuera de la tienda.

**Por qué se firma fuera de iCloud.** El repo vive en `~/Desktop`, que iCloud
sincroniza, y iCloud reinyecta atributos extendidos continuamente. Firmar allí
falla con `resource fork, Finder information, or similar detritus not allowed`.
El script copia el bundle a `~/.dictador/release/` antes de tocarlo.

**Por qué se firman los binarios internos uno a uno.** Los `libggml-*` se cargan
por `dlopen` en tiempo de ejecución, así que necesitan firma propia: sin ella la
notarización rechaza el paquete. La firma va de dentro afuera porque firmar el
bundle invalida cualquier firma añadida después dentro de él.

**Por qué solo Apple Silicon.** El `whisper-server` vendorizado en `vendor/` es
arm64. Para dar soporte a Intel habría que compilar un binario universal.

---

## Si algo falla

| Síntoma | Causa y solución |
|---|---|
| `no hay certificado 'Developer ID Application'` | Falta el paso 1 de la preparación |
| `no existe el perfil de notarización 'voxly'` | Falta el paso 3 |
| `resource fork ... detritus not allowed` | Algo se está firmando dentro de iCloud; el script ya lo evita, revisa que no hayas cambiado `WORK` |
| Notarización rechazada | `xcrun notarytool log <submission-id> --keychain-profile voxly` da el motivo exacto, normalmente un binario sin firmar o sin hardened runtime |
| La app abre pero el hotkey no va | Accesibilidad no concedida; el onboarding lo guía. Al reinstalar cambia la firma y macOS revoca el permiso |
