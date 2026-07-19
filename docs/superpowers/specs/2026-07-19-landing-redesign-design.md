# Landing redesign — evolución "nivel Wispr" de usevoxly.vercel.app

**Fecha**: 2026-07-19 · **Aprobado por**: Eduardo · **Enfoque**: evolución in-place de `web/index.html` (fichero único, vanilla, sin build)

## Objetivo

Subir la ejecución visual de la landing actual al nivel de referencia del sector
(wisprflow.ai) sin cambiar de identidad: misma paleta papel/tinta con acentos
ámbar/teal, mismas secciones base, demo simulada (no capturas reales).

## Decisiones cerradas

| Decisión | Elección |
|---|---|
| Dirección visual | Evolucionar la actual (claro, papel/tinta/ámbar/teal) |
| Demo del hero | Simulada pulida — sin assets nuevos ni capturas |
| Secciones nuevas | FAQ + comparativa vs cloud + banner free/open source |
| Ejecución | `web/index.html` único, vanilla CSS/JS, deploy `vercel --prod` |

## Dirección visual

- **Tipografía**: escala fluida `clamp()`; hero headline 72–96px desktop /
  40-48px móvil, tracking apretado (−0.03em), jerarquía más contrastada.
  Fuentes del sistema (sin webfonts).
- **Fondo hero**: gradiente radial muy desaturado (melocotón→menta) + grano
  sutil (SVG noise inline). El resto de secciones alternan `--paper` /
  `--bg-raised` como ahora.
- **Motion**: reveals al scroll (IntersectionObserver, una sola clase
  `.visible`), demo con easing pulido, hover con elevación en cards, CTA con
  micro-interacción. Todo bajo `@media (prefers-reduced-motion: no-preference)`.
- **Ritmo**: secciones ~160px de separación desktop / ~96px móvil.

## Estructura (orden final)

1. **Nav** — brand + enlaces GitHub y FAQ
2. **Hero** — headline grande, subhead, CTA descarga; bajo el CTA:
   "Free · Signed & notarized by Apple · Apple Silicon · macOS 13+".
   Demo simulada a la derecha (columna en desktop, apilada en móvil).
3. **Banner free/open source** — franja fina: "Free. No account. No
   subscription. Open source." + enlace al repo.
4. **Privacy** — sección actual "Dictation that doesn't phone home", pulida.
5. **Three steps** — Hold / Speak / Let go, pulida.
6. **Modos** — "Same voice, different output", pulida.
7. **Comparativa** — tabla Voxly vs dictado cloud (Wispr Flow como referencia
   sin nombrarla agresivamente): privacidad del audio, precio (gratis vs
   ~$12/mes), offline, límites de uso, código abierto. En móvil la tabla
   scrollea horizontal dentro de su contenedor.
8. **FAQ** — acordeón `<details>/<summary>` nativo, 7 preguntas: ¿gratis?,
   ¿qué Macs?, ¿dónde va mi voz?, ¿necesito Ollama u otra IA?, ¿funciona
   offline?, ¿qué idiomas?, ¿cómo se actualiza?
9. **CTA final** — "Stop typing what you could just say" + botón descarga.
10. **Footer** — GitHub, issues, copyright.

## Restricciones

- Peso total del HTML < 45 KB (hoy 20 KB).
- Cero dependencias externas: sin webfonts, sin CDN, sin JS de terceros.
- Contraste AA en todos los pares texto/fondo (la paleta actual ya cumple).
- Responsive: sin scroll horizontal del body en ningún viewport ≥320px.
- Los enlaces de descarga siguen apuntando a
  `github.com/crovettopro/voxly/releases/latest/download/Voxly-1.0.0.dmg`.

## Fuera de alcance

- Capturas o vídeo real de la app.
- Dominio propio, analytics, SEO técnico más allá de meta tags existentes.
- Versión en español (la landing es EN-only por ahora).

## Verificación

- Visual: abrir en viewport 1440/768/375, light y dark del sistema (la página
  es claro-fijo: verificar que no rompe con dark mode del navegador).
- `prefers-reduced-motion`: sin animaciones.
- Lighthouse: accesibilidad ≥95, performance ≥95.
- Deploy a producción y verificación en https://usevoxly.vercel.app.
