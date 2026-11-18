#!/usr/bin/env python3
"""Control por aplicación: espejo privado leído, distribución pública comprobada."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import forgejo_apps as apps
from github_mirror import Mirror
from distributions import publish_one


def project():
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    for name in apps.APPS:
        if repository == 'Gente-del-Condado/' + name + '_ha':
            return name
    raise ValueError('Controlador público no autorizado')


def download(repo, sha, destination):
    reader = Mirror(repo)
    if reader.branch() != sha:
        raise ValueError('El espejo ha cambiado desde la planificación')
    apps.extract(reader.archive(sha, limit=64 * 1024 * 1024).read(), destination)
    for arguments in [('init', '-q'), ('add', '--all'),
                      ('-c', 'user.name=source', '-c', 'user.email=source@example.invalid',
                       'commit', '-qm', 'Fuentes de ' + sha)]:
        apps.git(destination, *arguments)
    Path(str(destination) + '.json').write_text(json.dumps({'repo': repo, 'sha': sha}) + '\n')


def plan(repo):
    sha = Mirror(repo).branch()
    exists = apps.git('.', 'ls-remote', '--heads', 'origin', 'refs/heads/public-source')
    previous = {}
    if exists:
        apps.git('.', 'fetch', '--no-tags', 'origin', 'refs/heads/public-source')
        previous = json.loads(apps.git('.', 'show', 'FETCH_HEAD:receipt.json'))
    apps.output('repo', repo)
    apps.output('sha', sha)
    apps.output('changed', previous.get('sha') != sha or previous.get('public_format') != 1)


def snapshot(repo, folder):
    folder = Path(folder)
    record = apps.validate(folder, repo)
    expected = {apps.APPS[repo], 'distributions', 'receipt.json'}
    if {p.name for p in folder.iterdir()} != expected:
        raise ValueError('Contenido no autorizado en la exportación')
    record['public_format'] = 1
    record['source_repository'] = 'Gente-del-Condado/' + repo
    repository = 'Gente-del-Condado/' + repo + '_ha'
    # El propio repositorio recibe integración, etiqueta y release con su token
    # efímero. No se necesita una credencial de escritura entre repositorios.
    publish_one(repo + '_ha', folder / 'distributions/ha', repo, record)
    with tempfile.TemporaryDirectory(prefix='public-app-snapshot-') as temporary:
        root = Path(temporary)
        apps.git(root, 'init', '-q', '-b', 'public-source')
        apps.git(root, 'remote', 'add', 'origin', 'https://github.com/' + repository + '.git')
        if apps.git(root, 'ls-remote', '--heads', 'origin', 'refs/heads/public-source'):
            apps.git(root, 'fetch', '--depth=1', 'origin', 'refs/heads/public-source')
            apps.git(root, 'reset', '--hard', 'FETCH_HEAD')
        for path in root.iterdir():
            if path.name == '.git':
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        for name in (apps.APPS[repo], 'distributions'):
            shutil.copytree(folder / name, root / name)
        (root / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        apps.git(root, 'add', '--all')
        changed = subprocess.run(['git', '-C', str(root), 'diff', '--cached', '--quiet']).returncode
        if changed not in (0, 1):
            raise ValueError('No se pudo comparar el contexto público')
        if changed:
            apps.git(root, '-c', 'user.name=github-actions[bot]',
                     '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                     'commit', '-qm', 'Exportar contexto público de ' + repo + ' ' + record['sha'])
            apps.git(root, 'push', 'origin', 'HEAD:refs/heads/public-source')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'download', 'prepare', 'check', 'publish'])
    parser.add_argument('--sha')
    parser.add_argument('--source', type=Path, default=Path('source'))
    parser.add_argument('--output', type=Path, default=Path('prepared'))
    args = parser.parse_args()
    repo = project()
    if args.action == 'plan':
        plan(repo)
    elif args.action == 'download':
        download(repo, args.sha, args.source)
    elif args.action == 'prepare':
        apps.prepare(repo, args.source, args.output)
    elif args.action == 'check':
        record = apps.validate(args.output, repo)
        if Mirror(repo).branch() != record['sha']:
            raise ValueError('El espejo ha cambiado; no se publica el candidato')
    else:
        if os.environ.get('GITHUB_REF') != 'refs/heads/main':
            raise ValueError('Solo publica el controlador de main')
        subprocess.run(['gh', 'auth', 'setup-git'], check=True)
        snapshot(repo, args.output)


if __name__ == '__main__':
    main()
