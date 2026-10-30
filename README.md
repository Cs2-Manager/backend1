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
- **cli.py** — comandos administrativos (`set-admin`).
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

## Migraciones

El esquema se gestiona con **Alembic** (no se usa `db.create_all()` en el
arranque). La primera revisión (`1d65f5c82647`) es el baseline del esquema
existente, la segunda (`ea783557e94b`) agrega `users.is_admin` con
`server_default=false` y la tercera (`d3900c44a271`) agrega los perfiles de
jugador y el historial de partidas.

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
docker compose up -d --build
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

```bash
cp .env.example .env
docker compose up -d --build
```

La API queda disponible en http://localhost:5000.

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
