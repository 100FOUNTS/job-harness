# job-harness: guía rápida en español

Esta es una guía corta. La documentación completa está en inglés: [README](../../README.md), [paso a paso sin terminal](../GETTING-STARTED.md), [glosario](../GLOSSARY.md) y [solución de problemas](../TROUBLESHOOTING.md).

## Qué es
job-harness es una herramienta para **Claude Code** que te ayuda a buscar trabajo en **Australia**. Le das una carpeta con tu CV y tus certificados. Te ayuda a armar un perfil honesto y, todos los días, busca ofertas nuevas en SEEK, LinkedIn y WA Government Jobs, las ordena y prepara un CV y una carta de presentación para las mejores. Tú abres el aviso, haces clic en Aplicar y subes los archivos.

<p align="center"><img src="../assets/demo.gif" alt="Recorrido de 20 segundos por el panel con datos de ejemplo: detalle del aviso, descartar con Deshacer, qué lleva a entrevistas y lo descartado." width="900"><br><sub>20 segundos en el panel, con datos de ejemplo (la interfaz está en inglés).</sub></p>

Además:
- **Más fuentes, sin scraping.** Puedes seguir a empresas puntuales por sus feeds públicos de empleo en Greenhouse, Lever, Ashby, Workable o SmartRecruiters, y sumar Adzuna con una clave gratuita. `job doctor` muestra las fuentes disponibles. Para agregar un portal o un país: [docs/ADDING-A-SOURCE.md](../ADDING-A-SOURCE.md) (en inglés).
- **Pega un link.** ¿Encontraste un aviso por tu cuenta? Pega el link (o el texto, si la página no se puede leer) en el panel. Lo puntúa, le prepara CV y carta y lo deja en *To apply*.
- **Alertas rojas.** Marca sueldo bajo tu mínimo o bajo el mínimo legal, pruebas sin pago, trabajo solo a comisión, cobros por adelantado y otras señales de estafa, empleador oculto y avisos que se republican sin parar. Solo avisan: no descartan nada.
- **Seguimientos.** A las postulaciones sin noticias en 10 días les prepara un borrador de email de seguimiento en su carpeta. Nunca lo envía por ti.
- **Qué lleva a entrevistas.** Con 10 postulaciones con respuesta, la vista *Funnel* muestra la tasa de entrevistas por rango de puntaje, línea y fuente.
- **En el celular.** `job panel --lan` abre el tablero en tu wifi con un link con token. Quien tenga el link en esa red puede verlo, así que úsalo en casa y no lo compartas.

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
- Una suscripción de pago a Claude (Pro, Max, Ultra, Team o Enterprise) con Claude Code: la aplicación de escritorio de Claude (pestaña **Code**) o la línea de comandos.
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
4. Pide a Claude: "instala la ejecución diaria a las 9" (corre `job schedule install <nombre> --hour 9`). A esa hora tu computador prepara tus ofertas solo, sin usar Claude y sin costo. Funciona en macOS (LaunchAgent), Windows (Programador de tareas) y Linux (temporizador de systemd, o una línea de crontab si no hay systemd). Solo corre si el computador está encendido. `job schedule run-now <nombre>` hace una prueba ahora.

## Dónde ver los resultados
- **El panel:** `job panel` abre un tablero en tu navegador (normalmente `http://127.0.0.1:8765`; solo tu computador puede verlo). Ahí ves cada oferta, por qué calza o por qué se descartó, y botones para marcar "postulé", "entrevista", etc.
- **La carpeta del día:** `~/job-packages/<nombre>/<fecha>/`, con `SUMMARY.md`, `index.html` y una subcarpeta por oferta con el CV y la carta en PDF.
- Para parar todo: crea un archivo vacío llamado `STOP` en `candidates/<nombre>/`.

## Costos
La ejecución diaria no cuesta nada (son scripts, sin IA). La configuración inicial, `/job-harness:job-tailor` (adapta el CV y la carta de las mejores ofertas) y `/job-harness:job-interview` (preparación de entrevistas) usan tu plan de Claude.

Los documentos de postulación se escriben en inglés australiano (`docs_language`); el idioma de lo que lees (resumen diario) se elige con `ui_language` (`es` para español). Claude te responde en tu idioma.

## Versión lite (Cowork y claude.ai)
¿No quieres instalar Claude Code? La carpeta [`lite/`](../../lite/README.md) trae tres habilidades (skills) independientes que subes a claude.ai o a Cowork: revisar un aviso contra tu CV, adaptar tu CV y escribir la carta, y prepararte para una entrevista. No incluyen la búsqueda diaria, el panel ni las verificaciones automáticas de cifras: lee siempre el resultado antes de enviarlo. Las instrucciones para subirlas están en [lite/README.md](../../lite/README.md) (en inglés).

## Contribuir
Los reportes de errores, los sitios que dejaron de funcionar, las nuevas fuentes de avisos y los nuevos países son bienvenidos. Empieza por [CONTRIBUTING.md](../../CONTRIBUTING.md) (en inglés) y el [Código de Conducta](../../CODE_OF_CONDUCT.md). Para problemas de seguridad: [SECURITY.md](../../SECURITY.md). Los cambios de cada versión están en el [CHANGELOG](../../CHANGELOG.md).

## Página de presentación
Una página corta con lo esencial: [100founts.github.io/job-harness](https://100founts.github.io/job-harness/).

## Apoya el proyecto
job-harness es gratis, de código abierto y no usa servicios pagos. Si te ayudó en tu búsqueda, un café ayuda a mantenerlo.

<p align="center"><a href="https://donate.stripe.com/4gM28t7b1g0kgHd5YE4wM00"><img src="../assets/buy-me-a-coffee.png" alt="Buy me a coffee: apoya a 100 FOUNTS, que construye job-harness" width="180"></a><br><a href="https://donate.stripe.com/4gM28t7b1g0kgHd5YE4wM00"><b>☕ Buy me a coffee</b></a><br>¿Prefieres un aporte mensual? <a href="https://github.com/sponsors/100FOUNTS">Patrocina a 100FOUNTS en GitHub</a>.</p>
