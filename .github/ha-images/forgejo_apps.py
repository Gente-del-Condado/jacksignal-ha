#!/usr/bin/env python3
"""Lee dos principales de Forgejo y publica solo sus aplicaciones ya verificadas."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request

API = 'https://gentedelcondado.es/forgejo/api/v1/repos/wolfbelmi88/'
APPS = {'pivigia': 'pivigia', 'jacksignal': 'jacksignal_installer'}
SHA = re.compile(r'[0-9a-f]{40}')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(repo, path, binary=False):
    if repo not in APPS:
        raise ValueError('Origen de Forgejo no autorizado')
    token = os.environ.get('FORGEJO_APPS_READ_TOKEN', '')
    if not token:
        raise ValueError('Falta FORGEJO_APPS_READ_TOKEN en Mis_app_ha')
    request = urllib.request.Request(API + repo + path,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
            limit = 64 * 1024 * 1024 if binary else 1024 * 1024
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('Respuesta de Forgejo demasiado grande')
            if binary:
                return raw
            if 'application/json' not in response.headers.get('Content-Type', ''):
                raise ValueError('Forgejo no devuelve JSON; revisar SSO')
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        raise ValueError('Lectura de Forgejo rechazada (HTTP ' + str(error.code) + ')') from None
    except urllib.error.URLError:
        raise ValueError('Forgejo no está disponible') from None


def current(repo):
    document = get(repo, '/branches/main')
    sha = document['commit']['id']
    if document.get('name') != 'main' or not SHA.fullmatch(sha):
        raise ValueError('Forgejo no devuelve el main esperado')
    return sha


def extract(raw, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('El destino de fuentes debe ser nuevo')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        members = archive.getmembers()
        if not members or len(members) > 10000 or sum(m.size for m in members) > 128 * 1024 * 1024:
            raise ValueError('Archivo fuera de los límites')
        roots = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (not path.parts or path.is_absolute() or '..' in path.parts or '.git' in path.parts
                    or '\\' in member.name or not (member.isfile() or member.isdir())):
                raise ValueError('Ruta o enlace no permitido en los fuentes')
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise ValueError('Se exige una raíz única')
        destination.mkdir(parents=True)
        for member in members:
            parts = PurePosixPath(member.name).parts[1:]
            if not parts:
                continue
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream:
                    target.write_bytes(stream.read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def download(repo, destination, expected_sha=None):
    sha = current(repo)
    if expected_sha and sha != expected_sha:
        raise ValueError('El main ha cambiado después de planificar')
    previous = subprocess.run(['git', 'show', 'origin/build-source:.sources/' + repo + '.json'],
                              capture_output=True, text=True)
    changed = previous.returncode != 0 or json.loads(previous.stdout).get('sha') != sha or json.loads(previous.stdout).get('distribution_format') != 2
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('changed=' + str(changed).lower() + '\n')
    if not changed:
        print('ORIGEN_YA_VERIFICADO:', repo, sha)
        return
    extract(get(repo, '/archive/' + sha + '.tar.gz', binary=True), destination)
    # Git efímero sin historial remoto: los publicadores existentes usan git archive.
    for args in [('init', '-q'), ('add', '--all'),
                 ('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fuentes de ' + sha)]:
        git(destination, *args)
    Path(str(destination) + '.json').write_text(json.dumps({'repo': repo, 'sha': sha}) + '\n')
    print('FUENTES_FIJADOS:', repo, sha)


def inventory(folder, application=True):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('El contexto debe ser una carpeta real')
    files = {}
    for file in sorted(folder.rglob('*')):
        if file.is_symlink():
            raise ValueError('No se publican enlaces')
        if not file.is_file():
            continue
        relative = file.relative_to(folder).as_posix()
        if set(file.relative_to(folder).parts) & {'.git', '.env', 'data', 'certs', '__pycache__'}:
            raise ValueError('Archivo privado en el contexto publicable')
        data = file.read_bytes()
        if re.search(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}', data):
            raise ValueError('No se publica material de clave privada')
        files[relative] = hashlib.sha256(data).hexdigest()
    if application and not {'config.yaml', 'Dockerfile', 'README.md', 'icon.png', 'logo.png'} <= files.keys():
        raise ValueError('Faltan fuentes, licencia o recursos del paquete')
    if application and folder.name == 'pivigia' and 'LICENSE' not in files:
        raise ValueError('Falta la licencia de PiVigia')
    return files


def prepare(repo, source, output):
    # Solo se ejecuta después de calidad y sin token Forgejo/GitHub en el entorno.
    source, output = Path(source).resolve(), Path(output).resolve()
    record = json.loads(Path(str(source) + '.json').read_text())
    if record['repo'] != repo or not SHA.fullmatch(record['sha']):
        raise ValueError('Recibo de fuentes no válido')
    if output.exists():
        raise ValueError('El paquete de transferencia debe ser nuevo')
    output.mkdir(parents=True)
    (output / 'repository.yaml').write_text('name: Transferencia aislada\n')
    git(output, 'init', '-q')
    git(output, 'add', '--all')
    git(output, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
    if repo == 'pivigia':
        subprocess.run(['python3', str(source / 'scripts/publish_store.py'), str(output)], check=True)
    elif repo == 'jacksignal':
        subprocess.run(['bash', str(source / 'scripts/publish-store.sh'), str(output)], check=True)
    else:
        raise ValueError('Origen no autorizado')
    (output / 'repository.yaml').unlink()
    shutil.rmtree(output / '.git')
    record['files'] = inventory(output / APPS[repo])
    record['modes'] = {name: 0o755 if (output / APPS[repo] / name).stat().st_mode & 0o111 else 0o644
                       for name in record['files']}
    from distributions import prepare as prepare_distributions
    prepare_distributions(repo, source, output)
    payload = output / 'distributions'
    record['distributions'] = inventory(payload, application=False)
    record['distribution_modes'] = {name: 0o755 if (payload / name).stat().st_mode & 0o111 else 0o644
                                    for name in record['distributions']}
    (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')


def validate(folder, repo):
    folder = Path(folder)
    if repo not in APPS:
        raise ValueError('Origen no autorizado')
    record = json.loads((folder / 'receipt.json').read_text())
    if record['repo'] != repo or not SHA.fullmatch(record['sha']):
        raise ValueError('Recibo de transferencia no válido')
    if record['files'] != inventory(folder / APPS[repo]):
        raise ValueError('La transferencia no coincide con sus sumas')
    if (record['modes'].keys() != record['files'].keys()
            or any(mode not in (0o644, 0o755) for mode in record['modes'].values())):
        raise ValueError('Permisos de transferencia no válidos')
    if 'distributions' in record:
        if (inventory(folder / 'distributions', application=False) != record['distributions']
                or record['distribution_modes'].keys() != record['distributions'].keys()
                or any(mode not in (0o644, 0o755) for mode in record['distribution_modes'].values())):
            raise ValueError('Distribuciones alteradas durante la transferencia')
        for name, mode in record['distribution_modes'].items():
            (folder / 'distributions' / name).chmod(mode)
    return record


def check(artifacts):
    for repo in APPS:
        folder = Path(artifacts) / repo
        if folder.exists():
            record = validate(folder, repo)
            if current(repo) != record['sha']:
                raise ValueError('El main de Forgejo ha cambiado; se conserva la tienda')


def stage(artifacts):
    # Este proceso solo copia archivos comprobados. No ejecuta código del artefacto.
    records = []
    for repo, app in APPS.items():
        folder = Path(artifacts) / repo
        if folder.exists():
            record = validate(folder, repo)
            records.append((repo, app, folder, record))
    for attempt in range(3):
        git('.', 'fetch', 'origin', '+refs/heads/build-source:refs/remotes/origin/build-source')
        git('.', 'checkout', '-B', 'stage-apps', 'origin/build-source')
        for repo, app, folder, record in records:
            target = Path(app)
            if target.is_symlink():
                raise ValueError('Destino enlazado en la tienda')
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(folder / app, target)
            for name, mode in record['modes'].items():
                (target / name).chmod(mode)
            receipt = Path('.sources') / (repo + '.json')
            receipt.parent.mkdir(exist_ok=True)
            receipt.write_text(json.dumps({'repo': repo, 'sha': record['sha'], 'distribution_format': 2}, indent=2) + '\n')
            git('.', 'add', '--', app, str(receipt))
        if subprocess.run(['git', 'diff', '--cached', '--quiet']).returncode == 0:
            output('images_changed', pending_images())
            return
        git('.', '-c', 'user.name=github-actions[bot]',
            '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
            'commit', '-m', 'Preparar aplicaciones verificadas desde Forgejo sin Actions privados')
        if subprocess.run(['git', 'push', 'origin', 'HEAD:build-source']).returncode == 0:
            git('.', 'fetch', 'origin', '+refs/heads/build-source:refs/remotes/origin/build-source')
            output('images_changed', pending_images())
            return
    raise ValueError('No se pudo actualizar build-source sin forzar Git')



def output(name, value):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write(name + '=' + (str(value).lower() if isinstance(value, bool) else value) + '\n')


def pending_images():
    for app in ('headscale_gateway', 'jacksignal_installer', 'pivigia', 'private_git_manager'):
        tree = git('.', 'rev-parse', 'origin/build-source:' + app)
        record = subprocess.run(['git', 'show', 'origin/main:.images/' + app + '.json'], capture_output=True, text=True)
        if record.returncode or json.loads(record.stdout)['tree'] != tree:
            return True
    return False


def plan():
    git('.', 'fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main',
        '+refs/heads/build-source:refs/remotes/origin/build-source')
    choices = []
    # Una aplicación cambia de productor solo al activar explícitamente su migración.
    from public_apps import selected
    migrated = selected()
    for repo in APPS:
        if repo in migrated:
            continue
        sha = current(repo)
        previous = subprocess.run(['git', 'show', 'origin/build-source:.sources/' + repo + '.json'], capture_output=True, text=True)
        record = json.loads(previous.stdout) if previous.returncode == 0 else {}
        if record.get('sha') != sha or record.get('distribution_format') != 2:
            choices.append({'repo': repo, 'sha': sha, 'python': '3.12' if repo == 'pivigia' else '3.14'})
    output('matrix', json.dumps({'include': choices}, separators=(',', ':')))
    output('changed', bool(choices))
    output('images_pending', pending_images())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'download', 'prepare', 'check', 'stage'])
    parser.add_argument('--repo', choices=APPS)
    parser.add_argument('--sha')
    parser.add_argument('--source', default='source')
    parser.add_argument('--output', default='prepared')
    parser.add_argument('--artifacts', default='prepared')
    args = parser.parse_args()
    try:
        if args.action == 'plan':
            plan()
        elif args.action == 'download':
            download(args.repo, args.source, args.sha)
        elif args.action == 'prepare':
            prepare(args.repo, args.source, args.output)
        elif args.action == 'check':
            check(args.artifacts)
        else:
            stage(args.artifacts)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
