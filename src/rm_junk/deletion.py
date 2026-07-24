from __future__ import annotations

from pathlib import Path

from rm_junk.path_policy import PathPolicy


class DeletionError(Exception):
    pass


def delete_path(path: str | Path, policy: PathPolicy, *, to_trash: bool = True) -> None:
    target = Path(path)
    if not policy.may_delete(target):
        raise DeletionError(f"Refusing to delete protected path: {target}")
    if not target.exists() and not target.is_symlink():
        raise DeletionError(f"Path does not exist: {target}")

    if to_trash:
        try:
            from send2trash import send2trash
        except ImportError as exc:
            raise DeletionError(
                "send2trash is required for trash deletion; pip install send2trash"
            ) from exc
        send2trash(str(target))
        return

    # Permanent delete (only if user opts out of trash)
    if target.is_dir() and not target.is_symlink():
        import shutil

        shutil.rmtree(target)
    else:
        target.unlink()
