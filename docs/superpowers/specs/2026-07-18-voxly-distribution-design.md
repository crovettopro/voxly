# Voxly: distribución pública para macOS

**Fecha:** 2026-07-18
**Estado:** aprobado, pendiente de implementar
**Objetivo:** que cualquier persona con un Mac pueda descargar Voxly desde una web,
instalarla con doble clic y estar dictando en menos de cinco minutos, sin tocar la
terminal.

## Contexto

Voxly funciona hoy como app personal: menu bar (rumps), whisper.cpp vendorizado
dentro del bundle, hotkey global (pynput) y pegado automático vía Accesibilidad.
El bundle pesa 52 MB sin el modelo de voz; el modelo (547 MB) se descarga solo al
primer arranque. La firma actual es un certificado autofirmado local ("Dictador
Dev") que solo sirve en esta máquina: en el Mac de otra persona Gatekeeper
bloquearía la app.

Los tres huecos entre "funciona en mi Mac" y "funciona en el de un desconocido":

1. **Confianza**: sin Developer ID + notarización, macOS no deja abrir la app.
2. **Primer arranque**: la app necesita micrófono, Accesibilidad y 547 MB de
   modelo. Hoy nada de eso se explica; el usuario ve un icono que no responde.
3. **Descubrimiento y actualizaciones**: no hay dónde descargarla ni forma de
   avisar de versiones nuevas.

## Decisiones tomadas

| Decisión | Elección | Por qué |
|---|---|---|
| Canal | Web + DMG notarizado | La app usa hotkey global y pegado en apps de terceros; el sandbox del Mac App Store lo prohíbe. Es lo que hacen Wispr Flow, superwhisper y MacWhisper. |
| Monetización v1 | Gratis, el usuario pone su IA | Sin backend ni pagos que construir. El tramo de pago (modelos propios) llega cuando haya usuarios. |
| Alcance v1 | Solo gratis | Validar interés antes de invertir en infraestructura de cobro. |
| Hosting de binarios | GitHub Releases | Gratis, sin límite de ancho de banda para descargas de releases. |
| Landing | Vercel, `voxly.vercel.app` | Sin coste ni compra de dominio para validar. Dominio propio cuando haya tracción. |
| Versión de lanzamiento | 1.0.0 | La app es funcionalmente completa; 0.3.0 infravalora lo que hay. |

## Alcance

**Dentro:** firma Developer ID, notarización, DMG, onboarding de primer arranque,
aviso de actualizaciones, landing de descarga, textos en inglés.

**Fuera (explícitamente):** Mac App Store, auto-instalación de updates (Sparkle),
soporte Intel, backend de pago, cuentas de usuario, versión Windows/Linux.

## Arquitectura

Cuatro piezas nuevas, todas aisladas del código existente:

```
scripts/release.sh          → build + firma + notarización + DMG   (nuevo)
src/dictador/onboarding.py  → asistente de primer arranque         (nuevo)
src/dictador/updates.py     → comprobación de versión              (nuevo)
web/                        → landing estática + appcast.json      (nuevo)
```

Los enganches en el código actual son mínimos: `app.py` llama al onboarding y al
comprobador de updates durante el arranque; `Voxly.spec` sube de versión.

### 1. Firma y notarización — `scripts/release.sh`

Sustituye a `deploy.sh` (que se queda para desarrollo local). Pasos:

1. Compila con PyInstaller.
2. Firma **de dentro afuera** todos los Mach-O: las dylibs de Python, el
   `whisper-server` vendorizado y todos los `libggml-*` (que se cargan por
   `dlopen`, así que necesitan firma propia), y por último el bundle. Certificado
   **Developer ID Application**, `--options runtime` (hardened runtime) y
   `--entitlements voxly.entitlements` (ya existe en el repo con los tres
   permisos que PyInstaller necesita).
3. Comprime en ZIP y envía a notarizar con `xcrun notarytool submit --wait`.
4. `xcrun stapler staple` sobre el `.app`.
5. Construye el DMG (`create-dmg` o `hdiutil`) con fondo, icono y enlace a
   `/Applications`.
6. Firma y notariza también el DMG, y lo staplea.
7. **Verificación final**: `spctl -a -vvv -t install` sobre el DMG — es
   literalmente lo que ejecuta Gatekeeper en el Mac del usuario. Si falla, el
   script sale con error.

El script es idempotente y aborta en cualquier fallo (`set -euo pipefail`). Las
credenciales de notarización van en un perfil de llavero (`notarytool
store-credentials`), nunca en el repo.

**Requisito manual (necesita la cuenta de Apple del usuario):** crear el
certificado Developer ID Application en developer.apple.com y guardar el perfil
de notarización. Se documenta paso a paso en `docs/RELEASING.md`.

### 2. Onboarding de primer arranque — `onboarding.py`

Ventana PyObjC (`NSWindow`) construida **en el hilo principal** — restricción
conocida: instanciar ventanas fuera de él aborta el proceso con SIGABRT, ya nos
pasó con `NSPanel`. Se sigue el patrón de `overlay.py`.

Se muestra cuando falta algún requisito, comprobado en tiempo real (no por un
flag guardado, que se desincroniza si el usuario revoca un permiso):

| Paso | Detección | Acción |
|---|---|---|
| Micrófono | `AVCaptureDevice.authorizationStatusForMediaType_` | `requestAccessForMediaType_` dispara el prompt del sistema |
| Accesibilidad | `AXIsProcessTrusted()` | Botón que abre el panel exacto de Ajustes; sondeo cada segundo para detectar la concesión y avanzar solo |
| Modelo de voz | `stt.find_model()` | `stt.ensure_model(progress_cb)` en hilo secundario, barra de progreso actualizada en el principal |
| Motor de IA | `refine.health()` | Detecta Ollama; si no hay, explica las tres salidas: instalar Ollama, poner una API key, o seguir sin IA |

El paso de IA es **informativo, nunca bloqueante**: sin IA el modo Verbatim
transcribe igual, y así se le dice. Al terminar, una pantalla final invita a
probar el dictado ("mantén pulsada la tecla Cmd derecha y habla").

La ventana es un componente autónomo: recibe callbacks de comprobación y no
conoce a `DictadorApp`. Se puede lanzar sola (`python -m dictador --onboarding`)
para probarla sin reinstalar permisos.

### 3. Aviso de actualizaciones — `updates.py`

Al arrancar (y cada 24 h) se pide un `appcast.json` publicado en la landing:

```json
{"version": "1.0.1", "url": "https://github.com/.../Voxly-1.0.1.dmg", "notes": "..."}
```

Si la versión remota es mayor que la del bundle (comparación por tuplas de
enteros, no alfabética), aparece un ítem destacado en el menú que abre la URL de
descarga. Sin auto-instalación: Sparkle sobre una app PyInstaller es una fuente
de problemas desproporcionada para el valor que aporta en v1.

Todo fallo (sin red, JSON inválido, campo ausente) es silencioso salvo en el log:
un comprobador de updates roto jamás debe estorbar a la app.

### 4. Landing y distribución — `web/`

Página estática en Vercel:

- Demo en GIF: dictar y ver el texto aparecer en otra app.
- Tres bullets de valor: **local** (tu voz no sale del Mac), **rápido** (~1 s),
  **gratis**.
- Requisitos visibles antes de descargar: **Mac con Apple Silicon** (el
  `whisper-server` vendorizado es arm64) y **macOS 13 o superior**.
- Botón de descarga apuntando al DMG en GitHub Releases.
- `appcast.json` servido desde la misma web.

### 5. Ajustes para usuarios desconocidos

- `config.yaml` debe funcionar tal cual sin ningún `.env`: sin API keys, backend
  LLM en `auto`, degradando a "sin IA" si no hay nada.
- Textos de usuario en inglés (la UI ya lo está; faltan los del onboarding).
- Bundle a 1.0.0 en `Voxly.spec`.

## Verificación

La prueba real es una **cuenta de usuario nueva en el Mac**, que tiene la base de
datos TCC virgen y ninguna herramienta de desarrollo: descargar el DMG desde la
web, arrastrar a Aplicaciones, abrir, pasar el onboarding completo y dictar una
frase — sin abrir la terminal ni una sola vez. Eso valida Gatekeeper, permisos y
descarga del modelo de una pasada.

Antes de eso, verificaciones por pieza:

- **Firma**: `codesign -vvv --deep --strict` y `spctl -a -vvv -t install` sobre el
  DMG final.
- **Onboarding**: lanzable aislado con `--onboarding`; cada paso se prueba
  revocando el permiso correspondiente en Ajustes.
- **Updates**: `appcast.json` local con versión superior e inferior; se comprueba
  que solo avisa en el primer caso y que no rompe nada sin red.
- **Regresión**: la app sigue dictando igual tras los cambios (dictado real, no
  solo tests).

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Notarización rechazada por firma incompleta de las dylibs de ggml | El script firma de dentro afuera y verifica con `spctl` antes de publicar |
| El usuario concede Accesibilidad pero macOS no lo refleja hasta reiniciar la app | El onboarding detecta el cambio por sondeo y, si hace falta, ofrece relanzar |
| 547 MB de descarga percibidos como "la app no hace nada" | Barra de progreso explícita en el onboarding, con tamaño y motivo |
| Solo Apple Silicon deja fuera a Macs Intel | Requisito visible en la landing; soporte Intel es trabajo futuro (compilar whisper universal) |
