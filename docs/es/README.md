# job-harness: guía rápida en español

Esta es una guía corta. La documentación completa está en inglés: [README](../../README.md), [paso a paso sin terminal](../GETTING-STARTED.md), [glosario](../GLOSSARY.md) y [solución de problemas](../TROUBLESHOOTING.md).

## Qué es
job-harness es una herramienta para **Claude Code** que te ayuda a buscar trabajo en **Australia**. Le das una carpeta con tu CV y tus certificados. Te ayuda a armar un perfil honesto y, todos los días, busca ofertas nuevas en SEEK, LinkedIn y WA Government Jobs, las ordena y prepara un CV y una carta de presentación para las mejores. Tú abres el aviso, haces clic en Aplicar y subes los archivos.

Lo que **nunca** hace:
- No resuelve captchas, no crea cuentas ni escribe contraseñas por ti.
- No envía postulaciones sin tu propia firma en la aprobación **go-live**. Por defecto, tú postulas.
- No inventa experiencia, fechas ni cifras: cada número de un CV o carta sale de tus propios datos.
- No usa servicios ni APIs de pago.
- Tus archivos quedan en una carpeta de tu computador. Lo que Claude lee durante una sesión (tu CV, los avisos) lo procesa Claude bajo tu propio plan.

La herramienta funciona hoy solo para Australia. El soporte de Windows y Linux es nuevo: pasa las pruebas automáticas, pero casi no se ha usado todavía en computadores reales.

## Qué necesitas
**Obligatorio**
- Un computador con macOS, Windows o Linux.
- Una suscripción de pago a Claude (Pro, Max, Team o Enterprise) con Claude Code: la aplicación de escritorio de Claude (pestaña **Code**) o la línea de comandos.
- Python 3.9 o superior y Node.js 20 o superior. Si faltan, Claude te lo dice y te muestra el comando para instalarlos.
- Una carpeta con tus CV, certificados y otros documentos.

**Opcional**
- La extensión **Claude in Chrome**: solo para revisar tus perfiles de SEEK y LinkedIn y crear las alertas.
- Playwright (`job setup --apply-tools`): solo si quieres postulación automática en SEEK Quick Apply.

## Instalación
**A. Aplicación de escritorio (sin terminal).** Instala la aplicación ([descargas](https://code.claude.com/docs/en/desktop-quickstart)), inicia sesión y abre la pestaña **Code**. Crea en tu carpeta personal una carpeta vacía llamada `job-harness-data` y ábrela con **Open folder...**. Escribe:
```
/plugin marketplace add 100FOUNTS/job-harness
/plugin install job-harness@100founts
```
*(La documentación oficial describe el botón **+**, luego **Add plugins**, para instalar plugins en la aplicación de escritorio; no confirma que los comandos `/plugin` funcionen en la pestaña Code. Si no funcionan, ejecuta esos dos comandos una vez en una terminal con `claude plugin marketplace add ...` y `claude plugin install ...`: la terminal y la aplicación comparten la misma configuración de plugins.)*

**B. Terminal, como plugin.**
```bash
claude plugin marketplace add 100FOUNTS/job-harness
claude plugin install job-harness@100founts
```
Abre Claude Code dentro de la carpeta `~/job-harness-data` (tus datos viven ahí, fuera del plugin, así que las actualizaciones no los tocan).

**C. Clonar el repositorio (para desarrolladores).**
```bash
git clone https://github.com/100FOUNTS/job-harness.git
cd job-harness
bin/job setup          # en Windows: bin\job.cmd setup
claude
```

## Primeros pasos
1. Escribe **`/job-harness:job-start`** (si clonaste el repositorio: `/job-start`). Claude revisa tu computador, te explica qué hace la herramienta y te pregunta tu nombre y dónde están tus documentos.
2. Sigue las etapas de la configuración inicial, una por una: 0 lectura de tus documentos, 1 perfil y vacíos, 2 trayectorias objetivo, 3 CV y carta maestros, 4 perfiles de SEEK/LinkedIn, 5 alertas. `job status <nombre>` siempre muestra el siguiente paso.
3. Cuando Claude te pida aprobar algo (tus trayectorias, tus documentos maestros, cambios de perfil), responde "OK" en el chat. Claude firma esa aprobación y deja tus palabras registradas; no tienes que escribir ningún comando. La única aprobación que firmas tú mismo es **go-live**, y solo hace falta si quieres que la herramienta envíe postulaciones por ti.
4. Pide a Claude: "instala la ejecución diaria a las 9" (corre `job schedule install <nombre> --hour 9`). A esa hora tu computador prepara tus ofertas solo, sin usar Claude y sin costo. Solo corre si el computador está encendido. `job schedule run-now <nombre>` hace una prueba ahora.

## Dónde ver los resultados
- **El panel:** `job panel` abre un tablero en tu navegador (normalmente `http://127.0.0.1:8765`; solo tu computador puede verlo). Ahí ves cada oferta, por qué calza o por qué se descartó, y botones para marcar "postulé", "entrevista", etc.
- **La carpeta del día:** `~/job-packages/<nombre>/<fecha>/`, con `SUMMARY.md`, `index.html` y una subcarpeta por oferta con el CV y la carta en PDF.
- Para parar todo: crea un archivo vacío llamado `STOP` en `candidates/<nombre>/`.

## Costos
La ejecución diaria no cuesta nada (son scripts, sin IA). La configuración inicial, `/job-harness:job-tailor` (adapta el CV y la carta de las mejores ofertas) y `/job-harness:job-interview` (preparación de entrevistas) usan tu plan de Claude.

Los documentos de postulación se escriben en inglés australiano (`docs_language`); el idioma de lo que lees (resumen diario) se elige con `ui_language` (`es` para español). Claude te responde en tu idioma.

## Apoya el proyecto
job-harness es gratis, de código abierto y no usa servicios pagos. Si te ayudó en tu búsqueda, un café ayuda a mantenerlo.

<p align="center"><a href="https://donate.stripe.com/4gM28t7b1g0kgHd5YE4wM00"><img src="../assets/buy-me-a-coffee.png" alt="Buy me a coffee: apoya a 100 FOUNTS, que construye job-harness" width="180"></a><br><a href="https://donate.stripe.com/4gM28t7b1g0kgHd5YE4wM00"><b>☕ Buy me a coffee</b></a></p>
