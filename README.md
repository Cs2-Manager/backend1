# CS2 Manager — Backend

API REST en Flask con SQLAlchemy, PostgreSQL, JWT y bcrypt.

## Arquitectura

- **routes/** — controladores finos: parsean la request y delegan en servicios.
- **services/** — lógica de negocio y acceso a datos (auth, mapas, lineups, workshop).
- **models/** — modelos SQLAlchemy.
- **errors.py / validators.py / pagination.py** — utilidades transversales.

Las escrituras (POST/PUT/DELETE) están protegidas con JWT. La seguridad se
implementa en `app/security.py` con el decorador `@jwt_required()`.

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
.venv/Scripts/python run.py
```

## Tests

Los tests usan SQLite en memoria (no requieren Postgres).

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

## Variables de entorno

| Variable              | Descripción                                 | Por defecto                    |
| --------------------- | ------------------------------------------- | ------------------------------ |
| `DATABASE_URL`        | Cadena de conexión de SQLAlchemy            | `postgresql://...@db:5432/...` |
| `SECRET_KEY`          | Clave para firmar los JWT                   | `dev-secret-key`               |
| `JWT_EXPIRATION_HOURS`| Horas de validez del token                  | `24`                           |
| `CORS_ORIGINS`        | Orígenes permitidos, separados por comas    | `http://localhost`             |
| `DEBUG`               | Modo depuración                             | `false`                        |
