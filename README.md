<!-- calidad:inicio -->
![Calidad](https://img.shields.io/badge/Calidad-14%2F100-red) ![Aprobado](https://img.shields.io/badge/Aprobado-NO-red) ![Cumple](https://img.shields.io/badge/Cumple-12%2F15-green) ![Duplicación](https://img.shields.io/badge/Duplicaci%C3%B3n-8.5%25-green) ![SEC](https://img.shields.io/badge/SEC-0-green) ![SQL](https://img.shields.io/badge/SQL-0-green) ![DBG](https://img.shields.io/badge/DBG-3-red) ![Capas](https://img.shields.io/badge/Capas-3-green) ![Tests](https://img.shields.io/badge/Tests-32-green) ![Cob](https://img.shields.io/badge/Cob-80.6%25-green) ![EP](https://img.shields.io/badge/EP-121-green)

**Calidad de servicios (heurístico):** índice **14/100** · cumple **12/15** · aprobado **NO** · capas **3**
Detalle completo en [`docs/EVALUACION.md`](docs/EVALUACION.md).
<!-- calidad:fin -->

# CS2 Manager — Backend

API REST en Flask con SQLAlchemy, PostgreSQL, JWT y bcrypt.

## Arquitectura

- **routes/** — controladores finos: parsean la request y delegan en servicios.
- **services/** — lógica de negocio y acceso a datos (auth, mapas, lineups, workshop).
- **models/** — modelos SQLAlchemy.
- **permissions/** — visibilidad (`PUBLIC`, `PRIVATE`, `TEAM`), roles de equipo y
  políticas de autorización reutilizables.
- **serializers/** — representaciones explícitas por contexto: pública, privada
  y administrativa.
- **cli.py** — comandos administrativos (`set-admin`, `steam-sync`).
- **migrations/** — migraciones Alembic versionadas.
- **errors.py / validators.py / pagination.py** — utilidades transversales.

## Seguridad y permisos

La autenticación JWT existente se mantiene. `app/security.py` expone:

- `@jwt_required()` — exige token válido y pasa el usuario a la vista.
- `@jwt_optional()` — permite usuarios anónimos o autenticados.
- `@admin_required()` — exige token válido y `users.is_admin = true`.

Las lecturas del catálogo (mapas, callouts, lineups y workshop maps) siguen
siendo públicas. **Todas las escrituras del catálogo global requieren
administrador**: un usuario autenticado sin `is_admin` recibe `403` y un
usuario anónimo recibe `401`.

Los serializadores públicos de usuario (`serialize_user_public`) nunca incluyen
email ni `password_hash`. Los contextos privado y administrativo incluyen email
solo cuando corresponde.

## Integración con Steam

La autenticación con Steam usa **OpenID 2.0** y la verificación de identidad se
completa en el backend; el frontend nunca envía un SteamID64 que se tome como
válido. El flujo crea un `state` hasheado, valida `openid.return_to`, el
endpoint, la identidad y la firma (`check_authentication`), y entrega al
frontend un `handoff` de un solo uso que se canjea por el JWT existente.

La **Steam Web API** solo se usa para datos verificables: perfil público,
visibilidad, pertenencia a CS2 y tiempo de juego (`GetPlayerSummaries` y
`GetOwnedGames`, appid 730). Las estadísticas por jugador y el historial de
partidas de CS2 no están disponibles en la Web API oficial: se serializan como
`UNAVAILABLE` y no se completan con estimaciones. Los datos manuales se marcan
como `MANUAL` y los verificados como `VERIFIED_STEAM`.

| Método | Endpoint | Auth | Descripción |
| ------ | -------- | :--: | ----------- |
| GET | `/api/auth/steam/start` | No | Inicia OpenID (login/registro) |
| GET | `/api/auth/steam/callback` | No | Valida la respuesta de Steam |
| POST | `/api/auth/steam/exchange` | No | Canjea el handoff por JWT |
| GET | `/api/steam/status` | Sí | Estado del vínculo y sincronización |
| POST | `/api/steam/link` | Sí | Vincula una cuenta de Steam |
| DELETE | `/api/steam/account` | Sí | Desvincula sin borrar la cuenta local |
| POST | `/api/steam/sync` | Sí | Sincronización manual |

`steam_accounts.steam_id` y `steam_accounts.user_id` son únicos. Desvincular no
elimina la cuenta local ni el historial manual. La sincronización respeta un
intervalo mínimo, no duplica filas, borra el playtime cacheado si la biblioteca
pasa a privada y devuelve `OK`, `PARTIAL`, `ERROR` o `SKIPPED`. También puede
ejecutarse por CLI:

```bash
flask --app run.py steam-sync
flask --app run.py steam-sync --identifier <username-o-email>
```

La API key vive solo en el backend. Sin `STEAM_API_KEY`, los endpoints de Steam
responden `not_configured` y el resto de la plataforma funciona normalmente.
`STEAM_PUBLIC_BASE_URL` debe coincidir exactamente con el origen público del
frontend. Documentación completa: [`../docs/steam.md`](../docs/steam.md).

## Integración con FACEIT

Usa exclusivamente la **Data API v4** oficial y **FACEIT Connect** (OAuth2
Authorization Code + PKCE). La identidad se descubre desde el SteamID64 ya
verificado o se verifica con FACEIT Connect; el `player_id` enviado por el
frontend nunca determina la propiedad. Cada usuario tiene como máximo una cuenta
FACEIT y los datos viven en tablas `faceit_*` separadas de Steam y demos.

Las métricas ausentes se serializan como `null` y se muestran como no
disponibles; nunca se mezclan con `VERIFIED_STEAM`, `VERIFIED_DEMO` o `MANUAL`.
La sincronización es incremental, idempotente, protegida por lease y con backoff.
Los snapshots de ELO solo contienen valores realmente observados.

| Método | Endpoint | Auth | Descripción |
| ------ | -------- | :--: | ----------- |
| GET | `/api/faceit/status` | Sí | Sección FACEIT del usuario |
| POST | `/api/faceit/discover` | Sí | Descubrir por SteamID verificado |
| POST | `/api/faceit/link` | Sí | Vincular la cuenta descubierta |
| DELETE | `/api/faceit/account` | Sí | Desvincular y borrar datos FACEIT |
| POST | `/api/faceit/sync` | Sí | Sincronización manual |
| POST | `/api/faceit/oauth/start` | Sí | URL de FACEIT Connect con PKCE |
| GET | `/api/faceit/oauth/callback` | No | Callback de un solo uso |
| GET | `/api/faceit/matches` | Sí | Historial con filtros |
| GET | `/api/faceit/matches/<id>` | Sí | Detalle de una partida |
| GET | `/api/faceit/maps` | Sí | Agregados por mapa |
| GET | `/api/faceit/elo` | Sí | Snapshots reales de ELO |

La API key, el client secret y los tokens viven solo en el backend. Sin
`FACEIT_API_KEY` la sección responde `NOT_CONFIGURED` y el resto funciona.
Documentación completa: [`../docs/phase9-faceit.md`](../docs/phase9-faceit.md).

## Migraciones

El esquema se gestiona con **Alembic** (no se usa `db.create_all()` en el
arranque). La primera revisión (`1d65f5c82647`) es el baseline del esquema
existente, la segunda (`ea783557e94b`) agrega `users.is_admin` con
`server_default=false`, la tercera (`d3900c44a271`) agrega los perfiles de
jugador y el historial de partidas, la cuarta (`2d236ff229a2`) agrega equipos e
invitaciones, la quinta (`3c9a7e5b1d24`) agrega las alineaciones de equipo, la
sexta (`9b8f1c2d4e6a`) agrega la integración con Steam y la séptima
(`c4f2a8d6e1b9`) agrega las estadísticas de matchmaking de CS2.

El arranque del backend usa `python -m app.db_bootstrap`, que inspecciona el
esquema antes de migrar y elige una estrategia segura:

| Estado         | Situación                                              | Acción                          |
| -------------- | ------------------------------------------------------ | ------------------------------- |
| `EMPTY`        | No hay tablas de la aplicación                         | `alembic upgrade head`          |
| `ADOPTABLE`    | Esquema idéntico al baseline, sin `alembic_version`    | `stamp` del baseline + `upgrade` |
| `MANAGED`      | Ya existe una revisión registrada en `alembic_version` | `alembic upgrade head`          |
| `INCOMPATIBLE` | Tablas, columnas, índices o claves distintas           | Aborta sin modificar la base    |

La adopción **solo** se realiza cuando todas las tablas, columnas, tipos,
nullabilidad, índices, claves primarias y foráneas coinciden exactamente con el
baseline. Nunca se marca el baseline a partir del error de una migración. Si el
esquema es incompatible, el arranque falla mostrando las diferencias y no crea
ni modifica tablas.

```bash
cd back
$env:DATABASE_URL="postgresql://usuario:clave@localhost:5432/cs2_manager"
python -m app.db_bootstrap          # clasifica y migra de forma segura
python -m alembic upgrade head      # solo si la base ya está gestionada
python -m alembic downgrade -1      # revertir una revisión
python -m alembic current           # revisión actual
```

Las filas existentes de `users` reciben `is_admin = false` al aplicar la
migración `ea783557e94b`.

### Docker

El contenedor ejecuta `python -m app.db_bootstrap` antes de iniciar la API, por
lo que una base preexistente con el esquema original se adopta automáticamente
y conserva sus datos:

```bash
docker compose up -d --build   # desde back/
```

Para ejecutar el bootstrap manualmente dentro de la imagen:

```bash
docker compose run --rm backend python -m app.db_bootstrap
```

`SECRET_KEY` es obligatorio en Docker Compose: si falta, el arranque falla en
lugar de usar un secreto de desarrollo. Usar un valor aleatorio y privado.

## Administrador inicial

No se promueve automáticamente al primer usuario registrado y no hay
credenciales ni administradores hardcodeados. Después de registrarse:

```bash
cd back
flask --app run.py set-admin <username-o-email>
flask --app run.py set-admin <username-o-email> --revoke
```

El comando actualiza `users.is_admin` en la base de datos.

## Puesta en marcha con Docker

Cada aplicación tiene su propio `docker-compose.yml`. Este stack administra
Flask, PostgreSQL y las migraciones. El frontend (`front/docker-compose.yml`)
se conecta a la misma red externa compartida para que nginx alcance el backend
por su nombre DNS (`backend:5000`).

```bash
# Una sola vez: red compartida entre los dos stacks
docker network create cs2-network

# Backend + PostgreSQL (desde back/)
cp .env.example .env               # credenciales del stack (una sola vez)
docker compose up -d --build
```

La API no se publica en la LAN: nginx (puerto 80, stack `front`) es el único
punto de entrada y reenvía `/api/` al backend por la red `cs2-network`. El
puerto 5000 solo está disponible en loopback (127.0.0.1:5000) para desarrollo
local, igual que PostgreSQL en 127.0.0.1:5432.

El volumen `back_postgres_data` se reutiliza en cada arranque. Detener el stack
sin perder datos:

```bash
docker compose down        # NUNCA con -v: borraría el volumen
```

## Ejecución local

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Windows
.venv/bin/pip install -r requirements.txt            # Linux/macOS
.venv/Scripts/python -m app.db_bootstrap
.venv/Scripts/python run.py
```

## Tests

Los tests funcionales usan SQLite en memoria (no requieren Postgres).

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

Las pruebas de migraciones se ejecutan contra PostgreSQL real y se omiten si
`TEST_POSTGRES_URL` no está definida. Usar una base desechable:

```bash
$env:TEST_POSTGRES_URL="postgresql://usuario:clave@localhost:5432/cs2_manager_migrations_test"
python -m pytest tests/test_migrations.py
```

## Variables de entorno

| Variable              | Descripción                                 | Por defecto                    |
| --------------------- | ------------------------------------------- | ------------------------------ |
| `DATABASE_URL`        | Cadena de conexión de SQLAlchemy            | `postgresql://...@db:5432/...` |
| `SECRET_KEY`          | Clave para firmar los JWT (obligatoria en Docker) | `dev-secret-key` en local |
| `JWT_EXPIRATION_HOURS`| Horas de validez del token                  | `24`                           |
| `CORS_ORIGINS`        | Orígenes permitidos, separados por comas    | `http://localhost`             |
| `DEBUG`               | Modo depuración                             | `false`                        |
| `STEAM_API_KEY`       | API key de Steam (solo backend)             | vacío (`not_configured`)       |
| `STEAM_PUBLIC_BASE_URL` | Origen público exacto del frontend        | `http://localhost`             |
| `STEAM_SYNC_MIN_INTERVAL_SECONDS` | Intervalo mínimo entre syncs    | `300`                          |
| `STEAM_API_TIMEOUT_SECONDS` | Timeout de la Web API                 | `10`                           |
| `STEAM_OPENID_TIMEOUT_SECONDS` | Timeout de OpenID                  | `10`                           |
| `STEAM_AUTH_REQUEST_TTL_SECONDS` | Vigencia de la solicitud OpenID  | `600`                          |
| `STEAM_HANDOFF_TTL_SECONDS` | Vigencia del handoff de un solo uso    | `120`                          |
| `MATCHMAKING_ENABLED` | Habilita la sección CS2 MATCHMAKING        | `true`                         |
| `MATCHMAKING_STORAGE_DIR` | Raíz del volumen de demos              | `instance/matchmaking`         |
| `MATCHMAKING_INBOX_DIR` | Carpeta de ingesta manual                | `<storage>/inbox`              |
| `MATCHMAKING_MAX_UPLOAD_MB` | Tamaño máximo por demo             | `512`                          |
| `MATCHMAKING_MAX_ATTEMPTS` | Intentos por demo antes de `ERROR`  | `3`                            |
| `MATCHMAKING_SYNC_MIN_INTERVAL_SECONDS` | Intervalo mínimo entre syncs | `300`                    |
| `MATCHMAKING_DISCOVERY_INTERVAL_SECONDS` | Periodicidad del discovery  | `3600`                    |
| `MATCHMAKING_DISCOVERY_MAX_CODES` | Códigos por corrida             | `50`                           |
| `MATCHMAKING_WORKER_POLL_SECONDS` | Espera entre pasadas del worker  | `15`                           |
| `MATCHMAKING_DEMO_EXPIRY_DAYS` | Días antes de marcar `UNAVAILABLE` | `31`                        |
| `MATCHMAKING_API_TIMEOUT_SECONDS` | Timeout de la API de Valve     | `15`                           |
| `MATCHMAKING_SECRET_KEY` | Clave de cifrado del auth code         | `SECRET_KEY`                   |
| `FACEIT_ENABLED`      | Habilita la integración FACEIT              | `true`                         |
| `FACEIT_API_KEY`      | API key de la Data API v4 (solo backend)    | vacío (`NOT_CONFIGURED`)       |
| `FACEIT_SYNC_INTERVAL_SECONDS` | Intervalo objetivo entre syncs      | `1800`                         |
| `FACEIT_SYNC_MIN_INTERVAL_SECONDS` | Mínimo para sync manual          | `300`                          |
| `FACEIT_SYNC_BATCH_SIZE` | Cuentas por lote del worker              | `5`                            |
| `FACEIT_PUBLIC_BASE_URL` | Origen de retorno al frontend            | `STEAM_PUBLIC_BASE_URL`        |
| `FACEIT_OAUTH_CLIENT_ID` | Client ID de FACEIT Connect              | vacío                          |
| `FACEIT_OAUTH_CLIENT_SECRET` | Client secret (solo backend)         | vacío                          |
| `FACEIT_OAUTH_REDIRECT_URI` | Redirect URI registrada en FACEIT      | vacío                          |
| `FACEIT_SECRET_KEY`   | Cifrado del `code_verifier` PKCE            | `SECRET_KEY`                   |

Documentación completa de matchmaking:
[`../docs/cs2-matchmaking.md`](../docs/cs2-matchmaking.md). Configuración
completa de FACEIT: [`../docs/phase9-faceit.md`](../docs/phase9-faceit.md).
