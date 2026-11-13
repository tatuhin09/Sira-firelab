"""Private runtime layout and SIRA-root isolation checks."""
from __future__ import annotations

import os
from pathlib import Path
import stat


_ALLOWED_SIRA_ROOT_NAMES = {".cache"}
_ALLOWED_CACHE_NAMES = {"opportunity_provider_cooldowns"}


def _shared_runtime_parent(path: Path) -> Path:
    """Ensure the repository runtime parent exists without changing its mode."""
    path = Path(path).absolute()
    if os.path.lexists(path) and path.is_symlink():
        raise RuntimeError("repository runtime directory may not be a symlink")
    if os.path.lexists(path) and not path.is_dir():
        raise RuntimeError("repository runtime path is not a directory")
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _private_directory(path: Path) -> Path:
    path = Path(path).absolute()
    if os.path.lexists(path) and path.is_symlink():
        raise RuntimeError("FireLab runtime directories may not be symlinks")
    if os.path.lexists(path) and not path.is_dir():
        raise RuntimeError("FireLab runtime path is not a directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


class FireLabPaths:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        if not self.repo_root.is_dir():
            raise FileNotFoundError("repository root is unavailable")
        self.runtime_parent = self.repo_root / "runtime"
        self.runtime_dir = self.runtime_parent / "firelab"
        self.worker_cwd = self.runtime_dir / "worker_cwd"
        self.worker_home = self.runtime_dir / "worker_home"
        self.worker_tmp = self.runtime_dir / "worker_tmp"
        self.sira_root = self.runtime_dir / "sira_root"
        self.database = self.runtime_dir / "firelab.sqlite3"
        self.worker_script = self.repo_root / "firelab_service" / "paper_search" / "research_worker.py"
        self.repo_src = self.repo_root / "src"
        self.site_root = self.repo_root / "firelab_site"

    def prepare(self) -> None:
        _shared_runtime_parent(self.runtime_parent)
        _private_directory(self.runtime_dir)
        for directory in (self.worker_cwd, self.worker_home, self.worker_tmp, self.sira_root):
            _private_directory(directory)
        if self.worker_script.is_symlink() or not self.worker_script.is_file():
            raise RuntimeError("FireLab research worker is unavailable")
        if self.repo_src.is_symlink() or not self.repo_src.is_dir():
            raise RuntimeError("SIRA source package directory is unavailable")
        if self.site_root.is_symlink() or not self.site_root.is_dir():
            raise RuntimeError("FireLab static site directory is unavailable or unsafe")
        self.assert_isolated_sira_root()

    def assert_isolated_sira_root(self) -> None:
        if self.sira_root.is_symlink() or not self.sira_root.is_dir():
            raise RuntimeError("isolated SIRA root is unavailable")
        names = {child.name for child in self.sira_root.iterdir()}
        if not names.issubset(_ALLOWED_SIRA_ROOT_NAMES):
            raise RuntimeError("isolated SIRA root contains unexpected state")
        cache = self.sira_root / ".cache"
        if cache.exists():
            if cache.is_symlink() or not cache.is_dir() or (stat.S_IMODE(os.lstat(cache).st_mode) & 0o077):
                raise RuntimeError("isolated cache path is unsafe")
            cache_names = {child.name for child in cache.iterdir()}
            if not cache_names.issubset(_ALLOWED_CACHE_NAMES):
                raise RuntimeError("isolated SIRA cache contains unexpected state")
            cooldowns = cache / "opportunity_provider_cooldowns"
            if cooldowns.exists():
                if cooldowns.is_symlink() or not cooldowns.is_dir() or (stat.S_IMODE(os.lstat(cooldowns).st_mode) & 0o077):
                    raise RuntimeError("isolated cooldown path is unsafe")
                for child in cooldowns.iterdir():
                    info = os.lstat(child)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or stat.S_ISLNK(info.st_mode)
                        or len(child.name) != 69
                        or child.suffix != ".json"
                        or any(char not in "0123456789abcdef" for char in child.stem)
                        or info.st_size > 16 * 1024
                        or (stat.S_IMODE(info.st_mode) & 0o077)
                    ):
                        raise RuntimeError("isolated cooldown directory contains an unexpected file")
