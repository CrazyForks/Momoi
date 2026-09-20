"""Exercise the actual script embedded in the Chrome Dockerfile."""
from pathlib import Path
import socket


SCRIPT = (Path(__file__).resolve().parents[1] / 'Dockerfile.chrome').read_text().split(
    "COPY --chmod=755 <<'PY' /usr/local/bin/momoi-chrome-entrypoint\n", 1
)[1].split('\nPY\n', 1)[0]


def entrypoint():
    namespace = {'__name__': 'test_entrypoint'}
    exec(compile(SCRIPT, 'momoi-chrome-entrypoint', 'exec'), namespace)
    return namespace['recover_profiles']


def profile(home):
    path = home / '.momoi/chrome'
    path.mkdir(parents=True)
    (path / 'SingletonLock').symlink_to('old-container-140')
    (path / 'SingletonCookie').symlink_to('old-cookie')
    (path / 'SingletonSocket').symlink_to('/nonexistent/chrome/socket')
    (path / 'Cookies').write_text('preserve login')
    return path


def test_stale_locks_are_backed_up_and_restart_is_idempotent(tmp_path):
    path = profile(tmp_path)
    recover = entrypoint()
    recover(tmp_path)
    assert not (path / 'SingletonLock').is_symlink()
    backups = list(path.glob('.stale-chrome-locks-*'))
    assert len(backups) == 1
    assert (backups[0] / 'SingletonLock').readlink() == Path('old-container-140')
    assert (path / 'Cookies').read_text() == 'preserve login'
    recover(tmp_path)
    assert list(path.glob('.stale-chrome-locks-*')) == backups


def test_active_socket_is_preserved(tmp_path):
    import tempfile
    path = profile(tmp_path)
    # macOS Unix socket paths have a short length limit.
    with tempfile.TemporaryDirectory(dir='/tmp') as directory:
        address = str(Path(directory) / 'socket')
        (path / 'SingletonSocket').unlink()
        (path / 'SingletonSocket').symlink_to(address)
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(address)
            server.listen(1)
            entrypoint()(tmp_path)
            assert (path / 'SingletonLock').is_symlink()
            assert not list(path.glob('.stale-chrome-locks-*'))


def test_regular_files_are_not_removed(tmp_path):
    path = profile(tmp_path)
    (path / 'SingletonCookie').unlink()
    (path / 'SingletonCookie').write_text('unexpected file')
    entrypoint()(tmp_path)
    assert (path / 'SingletonLock').is_symlink()
    assert (path / 'SingletonCookie').read_text() == 'unexpected file'
