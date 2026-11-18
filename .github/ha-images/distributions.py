#!/usr/bin/env python3
"""Publica integraciones verificadas en tres destinos públicos, sin ejecutar sus fuentes."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

TARGETS = {'pivigia_ha': 1453193935, 'jacksignal_ha': 1453194213, 'Mis_componente_ha': 1450872286}
OWNER = 'Gente-del-Condado'


def command(*args, root=None):
    return subprocess.check_output([str(x) for x in args], cwd=root, text=True).strip()


def git(root, *args):
    return command('git', '-C', root, *args)


def prepare(repo, source, output):
    """Se llama desde calidad, sin credenciales; reutiliza los exportadores existentes."""
    source, output = Path(source), Path(output)
    destination = output / 'distributions/ha'
    destination.mkdir(parents=True)
    git(destination, 'init', '-q')
    if repo == 'pivigia':
        command('python3', source / 'scripts/publish_ha_repository.py', destination,
                '--domain', repo, '--readme', 'docs/INTEGRACION.md')
    elif repo == 'jacksignal':
        command('python3', source / 'scripts/prepare-ha-distribution.py', destination)
    else:
        raise ValueError('Integración no autorizada')
    shutil.rmtree(destination / '.git')
    component = output / 'distributions/component'
    shutil.copytree(source / 'custom_components' / repo, component,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('LICENSE', 'NOTICE'):
        if (source / name).is_file():
            shutil.copyfile(source / name, component / name)


def version(folder, repo):
    document = json.loads((Path(folder) / 'manifest.json').read_text())
    value = document.get('version', '')
    if document.get('domain') != repo or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('Manifiesto de integración no válido')
    return value


def copy_managed(prepared, destination, repo, catalog=False):
    """Solo sustituye la integración autorizada y los recursos públicos del paquete."""
    prepared, destination = Path(prepared), Path(destination)
    if repo not in ('pivigia', 'jacksignal'):
        raise ValueError('Integración no autorizada')
    component = destination / 'custom_components' / repo
    if (destination / 'custom_components').is_symlink() or component.is_symlink():
        raise ValueError('Destino enlazado')
    incoming = prepared if catalog else prepared / 'custom_components' / repo
    version(incoming, repo)
    if component.exists():
        shutil.rmtree(component)
    component.parent.mkdir(exist_ok=True)
    shutil.copytree(incoming, component)
    paths = ['custom_components/' + repo]
    if not catalog:
        for name in ('README.md', 'CHANGELOG.md', 'hacs.json', 'LICENSE', 'NOTICE', 'icon.png', 'logo.png'):
            if (prepared / name).is_file():
                if (destination / name).is_symlink():
                    raise ValueError('Recurso público enlazado')
                shutil.copyfile(prepared / name, destination / name)
                paths.append(name)
    return paths


def check_tag(root, tag, repo):
    if subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'refs/tags/' + tag],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        if subprocess.run(['git', '-C', str(root), 'diff', '--cached', '--quiet', tag, '--',
                           'custom_components/' + repo, 'hacs.json']).returncode:
            raise ValueError('La versión publicada tiene otros fuentes; aumenta la versión sin mover su etiqueta')
        return True
    return False


def publish_one(name, folder, repo, record, catalog=False):
    if name not in TARGETS or (not catalog and name != repo + '_ha'):
        raise ValueError('Repositorio de distribución no autorizado')
    resolved = command('gh', 'api', 'repositories/' + str(TARGETS[name]), '--jq', '.full_name')
    if resolved != OWNER + '/' + name:
        raise ValueError('El destino cambió de identidad')
    value = version(folder if catalog else folder / 'custom_components' / repo, repo)
    tag = 'v' + value
    with tempfile.TemporaryDirectory(prefix='ha-distribution-publish-') as temporary:
        root = Path(temporary) / 'repository'
        command('git', 'clone', '--quiet', '--branch', 'main', 'https://github.com/' + resolved + '.git', root)
        for attempt in range(3):
            git(root, 'fetch', 'origin', 'main', '--tags')
            git(root, 'reset', '--hard', 'origin/main')
            previous = root / 'custom_components' / repo
            if (previous / 'manifest.json').is_file():
                old_version = version(previous, repo)
                if tuple(map(int, value.split('.'))) < tuple(map(int, old_version.split('.'))):
                    raise ValueError('No se retrocede la integración a una versión anterior')
            paths = copy_managed(folder, root, repo, catalog)
            receipt = root / '.publication' / (repo + '.json')
            receipt.parent.mkdir(exist_ok=True)
            receipt.write_text(json.dumps({'repo': repo, 'sha': record['sha'], 'version': value,
                                           'distribution_format': 2}, indent=2) + '\n')
            git(root, 'add', '--', *paths, '.publication/' + repo + '.json')
            tagged = check_tag(root, tag, repo) if not catalog else False
            if subprocess.run(['git', '-C', str(root), 'diff', '--cached', '--quiet']).returncode:
                git(root, '-c', 'user.name=github-actions[bot]',
                    '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                    'commit', '-m', 'Publicar ' + repo + ' verificado desde Forgejo ' + record['sha'])
            arguments = ['git', '-C', str(root), 'push', '--atomic', 'origin', 'HEAD:main']
            # JackSignal ya utiliza tags y releases. PiVigia conserva su distribución de rama.
            if repo == 'jacksignal' and not catalog and not tagged:
                git(root, 'tag', tag)
                arguments.append('refs/tags/' + tag)
            if subprocess.run(arguments).returncode == 0:
                break
            if repo == 'jacksignal' and not catalog and not tagged:
                git(root, 'tag', '-d', tag)
        else:
            raise ValueError('No se pudo publicar sin forzar el historial')
        if repo == 'jacksignal' and not catalog:
            result = subprocess.run(['gh', 'release', 'view', tag, '--repo', resolved], capture_output=True, text=True)
            if result.returncode:
                if not any(s in result.stderr for s in ('HTTP 404', 'release not found')):
                    raise ValueError('No se pudo comprobar la release existente')
                command('gh', 'release', 'create', tag, '--repo', resolved, '--verify-tag',
                        '--title', 'JackSignal ' + value, '--notes-file', root / 'CHANGELOG.md')
    print('DISTRIBUCION_PUBLICADA_OK:', resolved, value, record['sha'])


def publish(artifacts):
    from forgejo_apps import APPS, validate
    if not os.environ.get('GH_TOKEN'):
        raise ValueError('Falta DISTRIBUTION_TOKEN para los tres destinos públicos')
    command('gh', 'auth', 'setup-git')
    for repo in APPS:
        folder = Path(artifacts) / repo
        if not folder.exists():
            continue
        record = validate(folder, repo)
        publish_one(repo + '_ha', folder / 'distributions/ha', repo, record)
        publish_one('Mis_componente_ha', folder / 'distributions/component', repo, record, catalog=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', required=True)
    args = parser.parse_args()
    publish(args.artifacts)
