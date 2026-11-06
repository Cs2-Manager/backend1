"""Almacenamiento local de demos autorizadas.

Los archivos nunca se sirven por HTTP. Cada usuario tiene una carpeta de
ingesta (`inbox/<user_id>/`) y los demos se archivan por hash SHA-256 para
deduplicar: el mismo archivo subido dos veces no se procesa dos veces.

La carpeta se comparte entre el backend y el worker mediante el volumen
`matchmaking_storage` de Docker Compose.
"""

import bz2
import hashlib
import os
import shutil
import uuid
from contextlib import contextmanager

from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_SUFFIXES = (".dem", ".dem.bz2")
PARTIAL_SUFFIXES = (".part", ".tmp", ".crdownload")
CHUNK_SIZE = 1024 * 1024


class StorageError(Exception):
    """Archivo inválido, demasiado grande o fuera del almacenamiento."""


def storage_root():
    root = str(current_app.config.get("MATCHMAKING_STORAGE_DIR", "")).strip()
    if not root:
        raise StorageError("MATCHMAKING_STORAGE_DIR no está configurado")
    return os.path.abspath(root)


def inbox_root():
    configured = str(
        current_app.config.get("MATCHMAKING_INBOX_DIR", "")
    ).strip()
    root = (
        os.path.abspath(configured)
        if configured
        else os.path.join(storage_root(), "inbox")
    )
    ensure_within_storage(root)
    return root


def demos_root():
    return os.path.join(storage_root(), "demos")


def ensure_dirs():
    os.makedirs(storage_root(), exist_ok=True)
    os.makedirs(inbox_root(), exist_ok=True)
    os.makedirs(demos_root(), exist_ok=True)


def ensure_within_storage(path):
    root = os.path.abspath(storage_root())
    candidate = os.path.abspath(path)
    if os.path.commonpath([root, candidate]) != root:
        raise StorageError("La ruta queda fuera del almacenamiento")
    return candidate


def user_inbox(user_id):
    path = os.path.join(inbox_root(), str(int(user_id)))
    ensure_within_storage(path)
    os.makedirs(path, exist_ok=True)
    return path


def is_demo_filename(filename):
    lowered = str(filename or "").lower()
    return lowered.endswith(ALLOWED_SUFFIXES) and not lowered.endswith(
        PARTIAL_SUFFIXES
    )


def safe_name(filename, fallback="demo.dem"):
    name = secure_filename(str(filename or "")) or fallback
    if not is_demo_filename(name):
        raise StorageError("El archivo debe ser .dem o .dem.bz2")
    return name[:255]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_bytes():
    try:
        megabytes = int(
            current_app.config.get("MATCHMAKING_MAX_UPLOAD_MB", 512)
        )
    except (TypeError, ValueError):
        megabytes = 512
    return max(1, megabytes) * 1024 * 1024


def save_upload(user_id, file_storage):
    """Guarda una subida de forma atómica en la carpeta del usuario."""
    if file_storage is None or not file_storage.filename:
        raise StorageError("Falta el archivo de demo")
    name = safe_name(file_storage.filename)
    ensure_dirs()
    folder = user_inbox(user_id)
    final_path = os.path.join(folder, f"{uuid.uuid4().hex}-{name}")
    temp_path = f"{final_path}.part"
    written = 0
    try:
        with open(temp_path, "wb") as handle:
            while True:
                chunk = file_storage.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > _max_bytes():
                    raise StorageError(
                        "La demo supera el tamaño máximo permitido"
                    )
                handle.write(chunk)
        if written == 0:
            raise StorageError("El archivo de demo está vacío")
        os.replace(temp_path, final_path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    return final_path


def _iter_inbox_files():
    root = inbox_root()
    if not os.path.isdir(root):
        return
    for entry in sorted(os.listdir(root)):
        user_dir = os.path.join(root, entry)
        if not entry.isdigit() or not os.path.isdir(user_dir):
            continue
        user_id = int(entry)
        for name in sorted(os.listdir(user_dir)):
            if not is_demo_filename(name):
                continue
            path = os.path.join(user_dir, name)
            if os.path.isfile(path):
                yield user_id, path, name


def scan_inbox():
    """Archiva los demos pendientes y devuelve la lista de ingesta.

    Cada elemento incluye `duplicate=True` cuando el mismo contenido ya estaba
    archivado; en ese caso el archivo de la bandeja se elimina y no se crea un
    trabajo nuevo.
    """
    ensure_dirs()
    archived = {}
    for name in os.listdir(demos_root()):
        if not is_demo_filename(name):
            continue
        path = os.path.join(demos_root(), name)
        if os.path.isfile(path):
            archived[name.split(".")[0]] = path

    results = []
    for user_id, path, original_name in _iter_inbox_files():
        try:
            digest = sha256_file(path)
            suffix = ".dem.bz2" if original_name.lower().endswith(".dem.bz2") else ".dem"
            destination = os.path.join(demos_root(), f"{digest}{suffix}")
            size = os.path.getsize(path)
            duplicate = digest in archived or os.path.exists(destination)
            if not duplicate:
                os.replace(path, destination)
                archived[digest] = destination
            else:
                os.remove(path)
            results.append(
                {
                    "user_id": user_id,
                    "path": destination if not duplicate else archived[digest],
                    "original_name": original_name,
                    "sha256": digest,
                    "size_bytes": size,
                    "duplicate": duplicate,
                }
            )
        except OSError:
            # Un archivo bloqueado o ilegible se reintenta en la próxima pasada.
            continue
    return results


@contextmanager
def prepared_demo(path):
    """Entrega un `.dem` descomprimido y limpia el temporal al salir."""
    ensure_within_storage(path)
    if not os.path.isfile(path):
        raise StorageError("La demo ya no está disponible")
    if not path.lower().endswith(".bz2"):
        yield path
        return

    temp_path = os.path.join(
        demos_root(), f".tmp-{uuid.uuid4().hex}.dem"
    )
    try:
        with bz2.open(path, "rb") as source, open(temp_path, "wb") as target:
            shutil.copyfileobj(source, target, CHUNK_SIZE)
        yield temp_path
    except (OSError, EOFError) as error:
        raise StorageError("No se pudo descomprimir la demo") from error
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def remove_stored(path):
    if not path:
        return
    try:
        ensure_within_storage(path)
    except StorageError:
        return
    if os.path.isfile(path):
        os.remove(path)
