# Corrección de la evaluación oficial — Flask

Fecha de ejecución: 11/11/2026. Repositorio de referencia: **Cs2-Manager/backend1**,
rama oficial **main**. Alcance de cambios: **solo `back/`**.

**Resultado parcial, no aprobación oficial:** se refactorizaron 35 funciones
complejas de producción sin modificar los contratos HTTP. El conteo local
conservador completo baja **188 → 154**; en los 44 archivos del anexo baja
**52 → 17**. Estos valores **no son una reevaluación de los 143 oficiales**:
hay diferencias de estado, alcance y extracción. No se declara alcanzado el
objetivo oficial ≤ 90 ni el índice ≥ 50.

## 1. Referencia oficial y diagnóstico inicial

El `EVALUACION.md` original de Flask no estaba localmente. Se usa la transcripción
de resultados y el anexo completo de 44 archivos suministrados por el usuario,
preservados en `official-evaluation-reference.json`. **No se usa ni modifica**
`front/docs/EVALUACION.md`, que pertenece a otro repositorio.

| Señal oficial del 11/11/2026 | Valor |
|---|---:|
| Índice / mínimo informado | 14 / 50 |
| Criterios aprobados | 13/15 |
| LOC | 19.048 |
| Complejidad | 143 |
| Duplicación | 8,6 % |
| SEC / SQL / DBG | 0 / 0 / 0 |
| Tamaño / acoplamiento | 131 / 33 |
| Cobertura / endpoints | 81 % / 127 |

Se consultaron la guía del 28/10/2026 (§4.2–4.7), los informes Flask anteriores,
los scripts existentes, fixtures de pruebas y pruebas de integración disponibles.
Los contadores históricos de duplicación sumaban incidencias superpuestas y
tenían limitaciones de normalización; **no se modificaron esos scripts**.

Había **15 archivos de aplicación Flask ya modificados sin commit** al comenzar,
además de `.coverage` y cambios de React/NestJS. Muchos servicios del anexo
ya tenían extracciones que los dejaban bajo el umbral local. Esos 15 archivos
se conservaron **idénticos byte a byte**, comprobando SHA256 inicial/final;
no se atribuye ese trabajo previo a esta ejecución.

La medición inicial y Pytest/cobertura completos se terminaron antes del primer
cambio productivo. SQLite en memoria fue forzado con `TEST_DATABASE_URL=sqlite://`
y se quitó `TEST_POSTGRES_URL` **solo del entorno de cada proceso de pruebas**.
No se inspeccionó manualmente ni modificó `.env`; la aplicación carga su
configuración habitual al importarse, sin registrar valores. No se rotaron
secretos y no se usó PostgreSQL.

## 2. Método local reproducible y límites

Se agregó `scripts/estimate_flask_quality.py` como **estimador nuevo**, no como
reemplazo del evaluador ni modificación de sus reglas. Se congeló antes del
refactor: sus hashes inicial/final coinciden. **El propio estimador cuenta**
en ambos inventarios: aporta seis funciones complejas. No se excluyen tests,
scripts ni migraciones; no se cambian extensiones ni umbrales.

- Se recorren los Python del repositorio, sin dependencias/cachés/compilados y
  sin archivos de más de 1 MB. Se guardan hashes por archivo y rangos de funciones.
- Complejidad: base 1 más nodos AST `if`, `for`, `while`, `except`, `with`,
  `assert`, ternarios, operadores booleanos y filtros de comprensiones, como
  describe la guía. **Se incluyen ramas de funciones anidadas** al recorrer
  una función exterior: estimación conservadora, por ejemplo en `register_cli`.
- Umbral alto **≥ 6**; tamaño ≥ 30 líneas no vacías o > 4 parámetros. Se incluyen
  parámetros keyword-only y firma; `self`/`cls` se descuentan en métodos.
- Duplicación: tokenización para quitar comentarios, AST para docstrings/imports,
  espacios normalizados, ventanas de cinco líneas **por archivo** y unión de
  `archivo:línea`; una línea superpuesta se cuenta una sola vez.
- CBO es un proxy de identificadores AST con mayúscula y clases declaradas;
  **no reproduce necesariamente el regex oficial**. Cohesión es un proxy de
  pares de métodos que comparten atributos `self`.
- SEC/SQL/DBG se publican crudos con ubicaciones y se revisan por separado;
  el detector local no es exhaustivo ni una auditoría profesional de seguridad.

Evidencias inicial/final: `quality-evaluation-session-initial.json` y
`quality-evaluation-session-final.json`. Incluyen **todas las funciones**, no
solo las refactorizadas. El inventario anotado
`complexity-evaluation-inventory.json` agrega responsabilidades/propuestas,
ramas iniciales, los 44 archivos y todos los hallazgos pendientes.

Las 28.136 LOC iniciales locales **no equivalen a las 19.048 oficiales**. Tampoco
se puede inferir que la diferencia 143 → 52 sea mérito de esta ejecución: el
working tree tenía trabajo previo y el evaluador no está disponible. La comparación
válida de esta sesión es **el mismo estimador sobre sus dos snapshots**.

## 3. Inventario de los 44 archivos oficiales

Cantidad de funciones locales con complejidad ≥ 6, incluyendo todas las funciones
de cada archivo. `0 → 0` indica ausencia local **antes** de nuestras correcciones,
no una corrección atribuible a esta sesión. Los scripts operativos se cuentan.

| Archivo | Inicial → final | Decisión |
|---|---:|---|
| `app/cli.py` | 1 → 1 | Registro con callbacks anidados; conservar, revisar separación por comandos |
| `app/config.py` | 1 → 1 | Resolución de claves; preservar seguridad/configuración existente |
| `app/db_bootstrap.py` | 2 → 2 | Compatibilidad de esquemas; sin tocar bootstrap/migraciones |
| `app/notifications/catalog.py` | 1 → 1 | Catálogo cohesivo de variantes; pendiente dispatch por tipo |
| `app/notifications/outbox.py` | 2 → 0 | Tiempo/destinatarios y transiciones de entrega separados |
| `app/permissions/policies.py` | 1 → 1 | Matriz explícita de privacidad conservada |
| `app/realtime/client.py` | 1 → 0 | Transporte/fallos sanitizados separados del sobre firmado |
| `app/realtime/events.py` | 2 → 1 | Contexto/audiencia de propuestas reutilizados; actividad pendiente |
| `app/realtime/identity.py` | 1 → 0 | Headers/HMAC/replay, JSON y usuario separados |
| `app/routes/faceit.py` | 1 → 0 | Conversión de query reutilizada sin cambiar defaults |
| `app/serializers/faceit.py` | 0 → 0 | Extracciones previas preservadas |
| `app/serializers/lineups.py` | 1 → 0 | Normalización uniforme de campos y relaciones opcionales |
| `app/serializers/matchmaking.py` | 0 → 0 | Extracciones previas preservadas |
| `app/serializers/profiles.py` | 1 → 0 | Whitelist de contadores y ratios reales |
| `app/serializers/steam.py` | 2 → 1 | Política de procedencia común; cuenta/privacidad conservada |
| `app/serializers/team_lineups.py` | 1 → 1 | Proyección cohesiva de roster; no fragmentar solo por umbral |
| `app/serializers/teams.py` | 1 → 1 | Proyección y permisos de equipo conservados |
| `app/services/faceit_api.py` | 0 → 0 | Trabajo previo, máximo local 5 |
| `app/services/faceit_service.py` | 0 → 0 | Trabajo previo, máximo local 5 |
| `app/services/grenade_lineup_service.py` | 0 → 0 | Trabajo previo, máximo local 5 |
| `app/services/lineup_service.py` | 0 → 0 | Trabajo previo, máximo local 5 |
| `app/services/map_service.py` | 0 → 0 | Trabajo previo, máximo local 5 |
| `app/services/match_service.py` | 3 → 0 | Validaciones, resolución de mapa y agregación comunes |
| `app/services/matchmaking/demo_parser.py` | 5 → 1 | I/O nativo separado de normalización de rondas/eventos |
| `app/services/matchmaking/discovery.py` | 2 → 0 | Transporte, errores, esquema y validación de códigos |
| `app/services/matchmaking/sharecode.py` | 1 → 1 | Codificador binario cohesivo; no alterar protocolo |
| `app/services/matchmaking/stats.py` | 0 → 0 | Extracciones previas preservadas |
| `app/services/matchmaking/storage.py` | 4 → 0 | Streaming acotado, escaneo, archivo y limpieza separados |
| `app/services/matchmaking_service.py` | 5 → 0 | Autorización, merge/creación, elegibilidad e ingesta separados |
| `app/services/media_validation.py` | 1 → 0 | Políticas HTTPS/puerto/IP separadas, mismo orden de errores |
| `app/services/profile_service.py` | 0 → 0 | Extracciones previas preservadas |
| `app/services/steam_api.py` | 3 → 0 | Taxonomía HTTP, identidad verificada y juegos normalizados |
| `app/services/steam_openid.py` | 1 → 0 | Aserción del proveedor, callback/identidad y verificación remota |
| `app/services/steam_service.py` | 0 → 0 | Extracciones previas preservadas |
| `app/services/tactical_service.py` | 0 → 0 | Extracciones previas preservadas |
| `app/services/tactical_validation.py` | 0 → 0 | Extracciones previas, máximo local 4 |
| `app/services/team_lineup_service.py` | 0 → 0 | Extracciones previas preservadas |
| `app/services/team_service.py` | 0 → 0 | Extracciones previas preservadas |
| `app/services/workshop_service.py` | 1 → 0 | Selección de campos parciales y reglas de categoría/texto |
| `app/validators.py` | 2 → 0 | Limpieza/parseo/seguridad URL y conversión de contadores |
| `app/worker/matchmaking.py` | 1 → 1 | Refactor previo preservado, orquestación de job pendiente |
| `scripts/faceit_browser_fixture.py` | 1 → 1 | Fixture con assertion/context manager/ciclos; sin ejecución real |
| `scripts/phase8_browser_fixture.py` | 1 → 1 | Fixture con assertion/context manager/ciclo; sin alterar |
| `scripts/verify_faceit_oauth_runtime.py` | 2 → 2 | Diagnóstico operativo/configuración; sin usar credenciales reales |

## 4. Funciones refactorizadas y responsabilidad

Complejidad inicial → final del **mismo cuerpo identificado**, no ahorro oficial
garantizado. Los helpers nuevos también se miden: ninguno nuevo de aplicación
llega a 6. Todas las ramas iniciales (`If`, `BoolOp`, `With`, etc.) y sus cantidades
quedan en el inventario JSON, junto con los rangos originales.

| Archivo (bajo `app/`) | Función | CC antes → después | Responsabilidad / solución |
|---|---|---:|---|
| `notifications/outbox.py` | `persist_notification` | 11 → 4 | Persistir una notificación: extraer fecha defensiva y destinatarios positivos/únicos |
| igual | `dispatch_event` | 8 → 4 | Entregar: aislar transición DELIVERED/FAILED/PENDING y commit tolerante |
| `realtime/client.py` | `publish_event` | 7 → 3 | Firmar/publicar: separar transporte y errores sanitizados |
| `realtime/events.py` | `_build_proposal_decision` | 9 → 4 | Construir decisión: reutilizar lookup de contexto y regla de audiencia |
| `realtime/identity.py` | `identity` | 14 → 4 | Endpoint interno: separar autenticación antes de JSON y lookup de usuario |
| `routes/faceit.py` | `faceit_matches` | 7 → 1 | Historial JWT: conversión entera/default y texto opcional reutilizables |
| `serializers/lineups.py` | `_base` | 12 → 3 | Proyección de granada: whitelist de textos normalizados y relaciones opcionales |
| `serializers/profiles.py` | `serialize_stats` | 12 → 3 | Contadores: una regla de ausencia, ratios reales y mismas claves |
| `serializers/steam.py` | `build_provenance` | 12 → 4 | Una política fuente/disponibilidad para cada sección explícita |
| `services/match_service.py` | `_apply_result` | 7 → 3 | Incrementar resultado mediante whitelist de columnas |
| igual | `_apply_counters` | 7 → 3 | Mapeo único de contadores agregados, incluido daño |
| igual | `record_match` | 10 → 1 | Separar validación/clasificación/mapa de persistencia transaccional |
| `services/matchmaking/demo_parser.py` | `_sid` | 9 → 5 | Separar reglas de identidad decimal/float sin aceptar booleanos/fracciones |
| igual | `_parse_event` | 6 → 5 | Retry compatible sin kwargs con traducción de error propia |
| igual | `_round_teams` | 6 → 3 | Separar snapshot del parser de normalización por tick |
| igual | `parse_demo` | 19 → 4 | Separar dependencia/header, rondas, muerte/daño/MVP y fallback |
| `services/matchmaking/discovery.py` | `_request` | 14 → 3 | Transporte, tabla de errores y decodificación defensiva separados |
| igual | `get_next_share_code` | 7 → 5 | Reutilizar validación canónica manteniendo mensajes/categorías distintos |
| `services/matchmaking/storage.py` | `save_upload` | 10 → 5 | Separar streaming con límite, publicación atómica y limpieza compartida |
| igual | `_iter_inbox_files` | 8 → 3 | Distinguir directorios de usuarios de archivos completos |
| igual | `scan_inbox` | 10 → 3 | Índice de archivos, operación por demo y reintento OSError |
| igual | `prepared_demo` | 6 → 4 | Context manager de descompresión y limpieza en éxito/error |
| `services/matchmaking_service.py` | `authorize` | 9 → 4 | Parsear código y resolver autorización renovable antes de actualizar |
| igual | `_register_share_code` | 9 → 5 | Merge/creación separados, una política de commit/flush |
| igual | `build_section` | 6 → 2 | Predicado de elegibilidad, sin cambiar privacidad de propietario |
| igual | `request_sync` | 8 → 4 | Preconditions separadas de intervalo/encolado de corrida |
| igual | `enqueue_ingested_demo` | 6 → 4 | Resolver partida y compartir construcción de job; no reencolar resultados OK |
| `services/media_validation.py` | `public_https_url` | 11 → 3 | Puerto/esquema/host e IP pública, sin descargar contenido |
| `services/steam_api.py` | `_get_json` | 7 → 5 | Tabla HTTP con mensajes/códigos originales |
| igual | `fetch_player_summaries` | 9 → 1 | Shape/identidad separados de presentación verificada |
| igual | `fetch_owned_games` | 9 → 4 | Distinguir privado/vacío y normalizar cada juego válido |
| `services/steam_openid.py` | `verify_response` | 11 → 3 | Validar proveedor y binding callback/identity antes de check_authentication |
| `services/workshop_service.py` | `_validate_payload` | 11 → 5 | Categoría/textos y campos presentes en PATCH; sin resetear ausentes |
| `validators.py` | `parse_url` | 9 → 5 | Texto/límite, parseo, esquema/credenciales y dominio permitido |
| igual | `parse_non_negative_int` | 6 → 4 | Conversión estricta de booleanos/negativos con el mismo default/error |

Los retornos tempranos se conservan donde son útiles, pero no se cuenta un cambio
de indentación como reducción de decisiones. Las tablas de dispatch/whitelists
reemplazan reglas genuinamente repetidas, no eval ni condiciones ocultas.

## 5. Ejecución incremental y regresiones

| Grupo | Cambios | Tests afectados aprobados | Complejidad total / no-test | Duplicación |
|---|---|---:|---:|---:|
| Inicial | Medición completa antes de producción | 367, 9 skips | 188 / 58 | 8,298555 % |
| 1 | Parser de demos y descubrimiento | 65 | 183 / 53 | 8,277826 % |
| 2 | Identidad HMAC y outbox | 43 | 180 / 50 | 8,255397 % |
| 3a | Steam/OpenID, validadores, medios, workshop | 118 | 172 / 42 | 8,211679 % |
| 3b | Serializadores y partidas | 72 | 166 / 36 | 8,224543 % |
| 3c | Almacenamiento de demos | 35 | 163 / 32 | 8,199210 % |
| 3d | Matchmaking y validación común de sharecodes | 57 | 157 / 26 | 8,139535 % |
| 3e | Cliente realtime, propuestas y query FACEIT | 58 | 154 / 23 | 8,078357 % |

Los JSON `quality-evaluation-session-group*.json` y
`coverage-evaluation-session-group*-targeted.json` conservan cada medición.
En 3e se conservó el resumen de la salida medida; el inventario intermedio
completo fue sobrescrito por el final y no se reconstruyen hashes ficticios.
**La cobertura de suites dirigidas no se presenta como cobertura global**;
la global se obtiene con la suite completa inicial y final.
En 3b subió levemente el porcentaje por reducir líneas normalizadas, con las
mismas 1.890 líneas duplicadas; no se oculta ni se refactoriza por duplicación
cuando el criterio ya cumple. En 3c se agregó una prueba completa de limpieza
con complejidad 6: se conserva aunque aumente el contador de tests.
En conjunto se eliminan **35 hallazgos de producción** y se incorpora uno de
test: la reducción neta del alcance completo es **34**, no 35.

Pruebas nuevas significativas:

- `test_demo_parser.py`: payload completo de rondas/muertes/daño/MVP, floats,
  booleanos, NaN, falta de identidad/rondas, errores opcionales y fallback de versión.
  Junto con los diez casos nuevos de discovery, pasaron **37 casos antes del
  refactor productivo** y siguieron pasando después.
- `test_matchmaking_discovery.py`: diez casos agregados; HTTP 202/204, cuerpo
  vacío, precedence nextcode/next_code y JSON/esquema inválidos.
- `test_identity_contract.py`: JSON inválido/UTF-8/lista/null, user_id inválido,
  mensajes exactos de headers/firma y consumo de nonce aun con payload inválido.
- `test_validation_contracts.py`: esquema/dominio/credenciales/límite URL,
  contadores inválidos, IP privada y precedencia de errores de medios, PATCH parcial.
- `test_steam_api_contract.py`: respuesta/identidad inválida, shape de biblioteca,
  distinción privada/vacía, filtro por app, 403/429/500, red y JSON inválido.
- `test_storage_contract.py`: vacío/exceso de tamaño sin `.part` residual,
  deduplicación, archivos parciales/usuarios inválidos, reintento de archivo bloqueado,
  descompresión corrupta y limpieza ante fallo del consumidor.
- `test_faceit_query_contract.py`: defaults, query inválida/vacía, filtros limpios
  y prohibición de consulta sin JWT.

No se eliminó ningún nombre de función de test previo ni se cambiaron exclusiones
de cobertura. Las regresiones verifican contratos existentes; no se presentan
como bugs nuevos demostrados por tests rojos antes del refactor.

En la revisión posterior se detectó una regresión propia en la precedencia de
headers: una configuración de plazo inválida podía evaluarse antes de rechazar
credenciales ausentes. El caso nuevo **falló antes de la corrección** y después
pasaron **20 tests de identidad/realtime**. Se restauró el orden original antes
de leer el body, calcular HMAC o consumir nonce; luego se repitió la integración
NestJS y la suite completa. No se cambió el manejo de una configuración inválida
en peticiones que sí traen headers. Esta corrección no cambia el conteo de
complejidad; añade cinco líneas normalizadas al cierre frente al snapshot 3e.

## 6. Medición final y cobertura

| Métrica local, mismo estimador | Inicial | Final |
|---|---:|---:|
| Archivos Python (tests/migraciones/herramienta incluidos) | 155 | 161 |
| LOC no vacías | 28.136 | 28.470 |
| Funciones complejas, alcance completo | 188 | 154 |
| Funciones complejas en `app/` | 48 | 13 |
| Funciones complejas en scripts preexistentes | 4 | 4 |
| Funciones complejas en estimador nuevo | 6 | 6 |
| Funciones complejas en tests | 130 | 131 |
| Métodos largos / funciones largas / parámetros excesivos | 0 / 144 / 56 | 0 / 128 / 60 |
| Tamaño total | 200 | 188 |
| Acoplamiento: clases CBO ≥ 8, proxy AST | 3 | 3 |
| Cohesión baja, proxy AST | 0 | 0 |
| SEC / SQL / DBG crudos | 6 / 16 / 4 | 6 / 16 / 4 |
| Líneas duplicadas únicas / normalizadas | 1.889 / 22.763 | 1.864 / 23.079 |
| Duplicación | 8,298555 % | 8,076606 % |

La meta local normalizada final es `floor(28470/1000 × 5) = 142`:
**154 todavía la excede y también excede el objetivo absoluto 90**.
Tamaño final 188 ≤ 284 y CBO 3 ≤ 56 cumplen el proxy local, pero no sustituyen
los valores oficiales 131 y 33. Los cuatro parámetros excesivos adicionales
están en tests nuevos, no se ocultaron para mejorar el total.

**Cobertura inicial:** 8.147 / 9.906 líneas ejecutables = **82,243085 %**;
367 passed, 9 skipped. Alcance íntegro `--source=app`, incluidos módulos sin
ejecutar. Las cuatro exclusiones `pragma: no cover` ya existían y se conservan.

**Suite/cobertura final:** **460 passed, 9 skipped**, 284,97 s; **8.526 / 10.037
líneas ejecutables = 84,945701 %**. Umbral `--fail-under=80` aprobado.
Son **93 casos adicionales**, sin eliminación de tests. Se comprobó el mismo
conjunto de **98 módulos de producción** y las mismas cuatro líneas excluidas.

| Módulo | Cobertura inicial → final |
|---|---:|
| `services/matchmaking/demo_parser.py` | 13,55 % → 89,77 % |
| `services/matchmaking/discovery.py` | 79,73 % → 98,65 % |
| `services/matchmaking/storage.py` | 76,97 % → 90,64 % |
| `services/steam_api.py` | 25,00 % → 97,20 % |
| `realtime/identity.py` | 87,34 % → 98,97 % |
| `validators.py` | 75,71 % → 91,67 % |

Evidencias: `coverage-evaluation-session-initial.json` y
`coverage-evaluation-session-final.json`. Los datos `.coverage` de cada ejecución
van a rutas separadas en el temporal autorizado de OpenCode, preservando el
`.coverage` existente del usuario.

## 7. Seguridad, acoplamiento y contratos

- **SEC:** los seis matches crudos son claves ficticias de `TestingConfig`
  (`app/config.py`) y `BrowserConfig` (`scripts/faceit_browser_fixture.py`).
  No son secretos reales; revisión contextual = 0 hallazgos nuevos/reales.
  No se alteraron esas claves para evadir regex. Ubicaciones exactas en JSON.
- **SQL:** los 16 matches son llamadas HTTP `client.delete` con rutas interpoladas
  dentro de tests, no SQL concatenado. Revisado = 0. Ninguna consulta ni migración
  histórica fue cambiada para mejorar la señal.
- **DBG:** los cuatro `print` de `scripts/verify_faceit_oauth_runtime.py`
  (52,61,64,66) son diagnóstico operativo preexistente. `app/` = 0. **Se mantienen
  en el contador completo**; no se sustituyen por stdout/otra API para evadirlo.
  El oficial informó cero: no se infiere su matcher/exclusión exactos.
- **CBO:** los tres matches AST son `Config`, `TestingConfig` y `BrowserConfig`,
  afectados por constantes de configuración en mayúsculas. Todas esas clases
  quedan sin cambios. El oficial informó 33; la diferencia impide afirmar que
  el valor oficial final es tres. No se cambiaron modelos/clases para falsearlo.
- **HTTP:** catálogo de rutas inicial/final idéntico: **128 reglas**, incluyendo
  estáticos de Flask; **127 sin static**. Mismos paths, endpoints y métodos.
- **Capas:** se conservan presentación (`app/routes`), negocio (`app/services`)
  y datos (`app/models`): tres capas reconocibles, sin `no_layering`. HTTP en
  componentes/Any/BigC no son problemas aplicables al backend Python.
- Las pruebas mantienen JWT, ownership y separación de equipos, campos privados,
  códigos/formatos JSON y errores, HMAC/replay, atomización de outbox y demos.
  No se modificó React ni NestJS, ni los contratos de comunicación entre ambos.

## 8. Integración disponible con NestJS

Ejecutada la prueba existente:

```powershell
# Desde D:\back-y-front
python -m pytest scripts/tests/test_flask_nestjs_integration.py -ra
```

**1 passed, 34,91 s en la repetición final** (primera ejecución: 52,72 s):
servidor NestJS real transitorio con Socket.IO, JWT emitido
por Flask, verificación de identidad Flask por HMAC, SQLite en directorio temporal,
puertos efímeros y claves exclusivas de prueba. No modifica fuentes de NestJS,
secretos existentes ni PostgreSQL. No equivale a una sincronización Steam/FACEIT
real: los tests de esos proveedores usan respuestas simuladas.

## 9. Índice estimado y discrepancia con la cátedra

Se respeta el mínimo oficial **50** transcrito por el usuario. La guía disponible
del 28/10/2026 dice **60** y describe estos pesos:

```text
W = 20 SEC + 15 SQL + 10 no_layering + 8 (Coh + Acop) + 6 BigC
  + 5 (métodos_largos + complejidad) + 4 (funciones_largas + parámetros)
  + 3 HTTP + 2 Any + 2 DBG + 1,5 duplicación_%
índice = round(4000 / (W + 40))
```

| Estimación con pesos de esa guía | Inicial | Final |
|---|---:|---:|
| Peso crudo local | 2144,447832 | 1926,114910 |
| Índice crudo local | 2 | 2 |
| Peso revisado, sin SEC ficticio/SQL de tests HTTP | 1784,447832 | 1566,114910 |
| Índice revisado local | 2 | 2 |

No hay tope duro por duplicación (<15 %). Se conserva DBG y CBO en la lectura
revisada, incluso aunque sean ruido operativo/configuración.

**La fórmula no reconstruye el 14 oficial** a partir de sus contadores:
solo 143×5 + 131×4 + 33×8 + 8,6×1,5 ya da 1515,9 de peso mínimo e índice ≈3.
Tampoco bastaría llegar a 90 funciones para índice 50: 90×5 da índice ≈8 aun
con todos los demás hallazgos en cero. No se inventa una fórmula para obtener
50; se requiere confirmar versión/pesos del evaluador con la cátedra.

La reevaluación del `main` publicado es la única confirmación oficial. Esta
ejecución no publica código ni puede declarar 143 → 17 oficial.

## 10. Pendientes exactos

Quedan **154 funciones complejas** en el alcance local completo: **13 de app,
4 de scripts previos, 6 de la herramienta y 131 tests**. El JSON del inventario
enumera todas, con archivo, nombre, línea y complejidad; no se omiten tests.

| Archivo / función fuera de tests | CC | Motivo / próximo paso mantenible |
|---|---:|---|
| `app/cli.py::register_cli` | 15 | Incluye ramas de callbacks; evaluar comandos Click de nivel módulo con tests CLI |
| `app/config.py::_resolve_secret_key` | 8 | Validaciones de seguridad de claves; conservar hasta ampliar matriz de errores |
| `app/db_bootstrap.py::_type_matches` | 6 | Compatibilidad de tipos; revisar por familias con PostgreSQL aislado |
| `app/db_bootstrap.py::classify_database` | 6 | Clasificador de esquema; requiere tests PostgreSQL omitidos |
| `app/notifications/catalog.py::render_notification` | 8 | Seis formatos de mensajes; posible dispatch por evento con snapshots cruzados NestJS |
| `app/permissions/policies.py::can_view` | 8 | Matriz pública/privada/equipo; priorizar legibilidad y tabla exhaustiva de permisos |
| `app/realtime/events.py::record_activity` | 9 | Persistencia + sobre de actividad; futura separación conservando transacción/audiencia |
| `app/serializers/steam.py::serialize_steam_account` | 6 | Fallback de avatar y campos de propietario; cohesivo, preservar privacidad |
| `app/serializers/team_lineups.py::serialize_team_lineup` | 6 | Proyección de titulares/suplentes; no dividir artificialmente |
| `app/serializers/teams.py::serialize_team` | 6 | Proyección/visibilidad/listas; mantener contrato y assertions |
| `app/services/matchmaking/demo_parser.py::_clean` | 6 | Normalización corta de None/NaN/texto; no fragmentar solo para umbral |
| `app/services/matchmaking/sharecode.py::encode_share_code` | 6 | Algoritmo binario cohesivo, no modificar protocolo por métrica |
| `app/worker/matchmaking.py::_process_job` | 6 | Orquestación procesado; trabajo previo conservado |
| `scripts/faceit_browser_fixture.py::main` | 6 | Fixture con setup/assertions/ciclo; mantener verificaciones |
| `scripts/phase8_browser_fixture.py::main` | 6 | Fixture de navegador; mantener verificaciones |
| `scripts/verify_faceit_oauth_runtime.py::configuration_errors` | 6 | Diagnóstico de configuración; revisar reglas sin leer/alterar secretos reales |
| `scripts/verify_faceit_oauth_runtime.py::main` | 7 | Diagnóstico operativo; no borrar salidas solo por DBG |
| `scripts/estimate_flask_quality.py::docstring_ranges` | 7 | Herramienta nueva congelada, incluida sin excepciones |
| igual `::normalized` | 10 | Igual; no retocar reglas después de medir |
| igual `::function_record` | 6 | Igual |
| igual `::class_record` | 10 | Igual, proxy CBO limitado |
| igual `::signal_records` | 7 | Igual, regex crudos revisados aparte |
| igual `::inspect_file` | 7 | Igual |

No se intenta bajar 131 hallazgos de tests eliminando assertions o repartiendo
archivos. Se debe confirmar con la cátedra si su extractor agrega assertions
y callbacks anidados exactamente como describe la guía. Tampoco se excluye la
herramienta del denominador final para favorecer porcentajes.

Los nueve skips siguen pendientes: ocho pruebas de migración/compatibilidad y
una de concurrencia táctica. Exigen PostgreSQL desechable; no se ejecutaron
contra producción. No se alteraron migraciones históricas.

La advertencia preexistente de clave configurada corta se conserva. No se
imprimió su valor, no se rotó y no se ocultó la advertencia de los tests.

## 11. Archivos modificados y preservación de trabajo

En esta sesión se modificaron **18 módulos de aplicación**:

```text
app/notifications/outbox.py
app/realtime/client.py
app/realtime/events.py
app/realtime/identity.py
app/routes/faceit.py
app/serializers/lineups.py
app/serializers/profiles.py
app/serializers/steam.py
app/services/match_service.py
app/services/matchmaking/demo_parser.py
app/services/matchmaking/discovery.py
app/services/matchmaking/storage.py
app/services/matchmaking_service.py
app/services/media_validation.py
app/services/steam_api.py
app/services/steam_openid.py
app/services/workshop_service.py
app/validators.py
```

Tests: seis archivos nuevos (`test_demo_parser.py`, `test_identity_contract.py`,
`test_validation_contracts.py`, `test_steam_api_contract.py`, `test_storage_contract.py`,
`test_faceit_query_contract.py`) y casos agregados a `test_matchmaking_discovery.py`.
Además, estimador nuevo y evidencias bajo `docs/`. El diff completo de Git incluye
trabajo previo **que no se atribuye a esta sesión**.

Comprobaciones guardadas en `evaluation-session-verification.json`:
los **15 archivos de aplicación previamente modificados** permanecen idénticos,
**451 hashes de archivos de React/NestJS** coinciden con el inicio, los nombres
de tests previos se conservan y el catálogo de rutas no cambia.
Tres checks independientes del estimador verificaron comentarios/docstrings,
unión de ventanas superpuestas y suma de decisiones AST; no se retocó su código.
Sin commits, push, cambios de historial/autoría, secretos, base PostgreSQL,
volúmenes ni endpoints eliminados.

## 12. Reproducción

Desde `back/`, Python **3.12.3**, pytest **9.1.1**, coverage **7.17.2**:

```powershell
$env:TEST_DATABASE_URL='sqlite://'
Remove-Item Env:TEST_POSTGRES_URL -ErrorAction SilentlyContinue
$env:COVERAGE_FILE='C:\Users\rnfac\AppData\Local\Temp\opencode\flask-evaluation-reproduced.coverage'
python scripts/estimate_flask_quality.py docs/quality-evaluation-reproduced.json
python -m coverage run --source=app -m pytest -ra
python -m coverage json -o docs/coverage-evaluation-reproduced.json
python -m coverage report --fail-under=80
```

Los comandos de reproducción no reconstruyen retrospectivamente el estado
inicial: para ese estado se conservan hashes e informes ejecutados antes de
los cambios. No se hicieron commits para inventar un baseline histórico.

Los nombres `*-targeted.json` son coverage de grupos, no un sustituto del final
completo. El estimador se mantiene intacto; las diferencias frente al motor
oficial quedan explícitas, sin afirmar aprobación de la cátedra.

La repetición `quality-evaluation-session-reproduced.json` resultó idéntica
al snapshot final. Hashes SHA256 de la herramienta congelada y guía consultada:

```text
scripts/estimate_flask_quality.py
004a4fd0a44eda28087e2a5ba42711dc8d0ff4b7dd518a95f38b742d319d9661
COMO-ESTIMAR-TUS-METRICAS-ALUMNOS.md (28/10/2026)
90f1dad08ec112d3f0aae49759c52ad5c29eee2d285509374534e25006c636f4
```
