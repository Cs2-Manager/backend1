<!-- calidad:inicio -->
![Calidad](https://img.shields.io/badge/Calidad-25%2F100-red) ![Aprobado](https://img.shields.io/badge/Aprobado-NO-red) ![Cumple](https://img.shields.io/badge/Cumple-11%2F15-yellow) ![Duplicación](https://img.shields.io/badge/Duplicaci%C3%B3n-1.3%25-green) ![SEC](https://img.shields.io/badge/SEC-0-green) ![SQL](https://img.shields.io/badge/SQL-0-green) ![DBG](https://img.shields.io/badge/DBG-1-red) ![Capas](https://img.shields.io/badge/Capas-3-green) ![Tests](https://img.shields.io/badge/Tests-7-green) ![Cob](https://img.shields.io/badge/Cob-sin%20medir-lightgrey) ![EP](https://img.shields.io/badge/EP-24-green)

**Calidad de servicios (heurístico):** índice **25/100** · cumple **11/15** · aprobado **NO** · capas **3**
Detalle completo en [`docs/EVALUACION.md`](docs/EVALUACION.md).
<!-- calidad:fin -->

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
