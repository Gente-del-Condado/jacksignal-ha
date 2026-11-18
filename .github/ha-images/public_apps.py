#!/usr/bin/env python3
"""La tienda consume contextos públicos por SHA, sin leer repositorios privados."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

import forgejo_apps as apps
from github_mirror import ArchiveRedirect


def selected():
    names = os.environ.get('PUBLIC_APP_MIGRATIONS', '').split(',')
    names = [name.strip() for name in names if name.strip()]
    if len(names) != len(set(names)) or set(names) - apps.APPS.keys():
        raise ValueError('Migración de aplicaciones no autorizada')
    return names


def validate_export(folder, repo):
    folder = Path(folder)
    record = apps.validate(folder, repo)
    if (not isinstance(record.get('distributions'), dict) or not record['distributions']
            or not isinstance(record.get('distribution_modes'), dict)
            or {p.name for p in folder.iterdir()} != {apps.APPS[repo], 'distributions', 'receipt.json'}):
        raise ValueError('Contenido no autorizado en la exportación')
    return record


def download(repo, output):
    if repo not in apps.APPS:
        raise ValueError('Aplicación no autorizada')
    repository = 'Gente-del-Condado/' + repo + '_ha'
    ref = apps.git('.', 'ls-remote', '--heads', 'https://github.com/' + repository + '.git',
                   'refs/heads/public-source').split()
    if len(ref) != 2 or not re.fullmatch(r'[0-9a-f]{40}', ref[0]):
        raise ValueError('Todavía no existe el contexto público de ' + repo)
    url = 'https://api.github.com/repos/' + repository + '/tarball/' + ref[0]
    # No se adjunta ningún token. Solo se acepta un archivo público de GitHub.
    with urllib.request.build_opener(ArchiveRedirect()).open(url, timeout=120) as response:
        raw = response.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError('Contexto público demasiado grande')
    folder = Path(output) / repo
    apps.extract(raw, folder)
    record = validate_export(folder, repo)
    if (record.get('public_format') != 1
            or record.get('source_repository') != 'Gente-del-Condado/' + repo):
        raise ValueError('Recibo público no autorizado')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog', action='store_true')
    args = parser.parse_args()
    target = 'Mis_componente_ha' if args.catalog else 'Mis_app_ha'
    if os.environ.get('GITHUB_REPOSITORY') != 'Gente-del-Condado/' + target:
        raise ValueError('Consumidor público no autorizado')
    names = selected()
    if not names:
        apps.output('changed', False)
        return
    if args.catalog:
        from distributions import publish_one
        subprocess.run(['gh', 'auth', 'setup-git'], check=True)
        for name in names:
            record = download(name, args.output)
            publish_one(target, args.output / name / 'distributions/component', name, record, catalog=True)
        return
    apps.git('.', 'fetch', '--no-tags', 'origin', '+refs/heads/build-source:refs/remotes/origin/build-source',
             '+refs/heads/main:refs/remotes/origin/main')
    changed = False
    for name in names:
        record = download(name, args.output)
        previous = subprocess.run(['git', 'show', 'origin/build-source:.sources/' + name + '.json'],
                                  capture_output=True, text=True)
        if previous.returncode or json.loads(previous.stdout).get('sha') != record['sha']:
            changed = True
    apps.output('changed', changed)
    apps.stage(args.output)


if __name__ == '__main__':
    main()
