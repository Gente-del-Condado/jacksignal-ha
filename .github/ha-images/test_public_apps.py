"""Aislamiento del publicador, corte por aplicación y salida pública íntegra."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import forgejo_apps as apps
import public_app
import public_apps


class PublicAppsTest(unittest.TestCase):
    def fixture(self, root):
        app = root / 'pivigia'
        app.mkdir()
        for name in ('config.yaml', 'Dockerfile', 'README.md', 'LICENSE', 'icon.png', 'logo.png'):
            (app / name).write_text('fixture\n')
        dist = root / 'distributions'
        dist.mkdir()
        (dist / 'example').write_text('fixture\n')
        files, distributions = apps.inventory(app), apps.inventory(dist, application=False)
        record = {'repo': 'pivigia', 'sha': 'a' * 40, 'files': files,
                  'modes': dict.fromkeys(files, 0o644), 'distributions': distributions,
                  'distribution_modes': dict.fromkeys(distributions, 0o644),
                  'public_format': 1, 'source_repository': 'Gente-del-Condado/pivigia'}
        (root / 'receipt.json').write_text(json.dumps(record))
        return record

    def archive(self, folder):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            archive.add(folder, arcname='public')
        return data.getvalue()

    def test_controller_cannot_run_in_private_or_unrelated_repository(self):
        for repository in ('Gente-del-Condado/pivigia', 'someone/pivigia_ha', 'Gente-del-Condado/Mis_app_ha'):
            with patch.dict(os.environ, {'GITHUB_REPOSITORY': repository}):
                with self.assertRaisesRegex(ValueError, 'autorizado'):
                    public_app.project()
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'Gente-del-Condado/pivigia_ha'}):
            self.assertEqual(public_app.project(), 'pivigia')

    def test_selection_rejects_unknowns_and_duplicates(self):
        with patch.dict(os.environ, {'PUBLIC_APP_MIGRATIONS': ''}):
            self.assertEqual(public_apps.selected(), [])
        with patch.dict(os.environ, {'PUBLIC_APP_MIGRATIONS': ' jacksignal, pivigia '}):
            self.assertEqual(public_apps.selected(), ['jacksignal', 'pivigia'])
        for value in ('pivigia,pivigia', 'other'):
            with patch.dict(os.environ, {'PUBLIC_APP_MIGRATIONS': value}):
                with self.assertRaises(ValueError):
                    public_apps.selected()

    def test_changed_mirror_rejected_before_archive_download(self):
        with patch.object(public_app, 'Mirror') as mirror, patch.object(apps, 'extract') as extract:
            mirror.return_value.branch.return_value = 'b' * 40
            with self.assertRaisesRegex(ValueError, 'cambiado'):
                public_app.download('pivigia', 'a' * 40, Path('unused'))
            mirror.return_value.archive.assert_not_called()
            extract.assert_not_called()

    def test_private_root_file_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(public_app, 'publish_one') as publish:
            root = Path(temporary)
            self.fixture(root)
            (root / 'internal-notes.txt').write_text('private fixture')
            with self.assertRaisesRegex(ValueError, 'Contenido no autorizado'):
                public_app.snapshot('pivigia', root)
            publish.assert_not_called()

    def test_distribution_cannot_omit_its_inventory(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(public_app, 'publish_one') as publish:
            root = Path(temporary)
            record = self.fixture(root)
            del record['distributions']
            del record['distribution_modes']
            (root / 'receipt.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'Contenido no autorizado'):
                public_app.snapshot('pivigia', root)
            publish.assert_not_called()

    def test_public_consumer_verifies_bytes_and_origin_without_credentials(self):
        for case in ('valid', 'modified', 'wrong-origin'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / 'source'
                source.mkdir()
                record = self.fixture(source)
                if case == 'modified':
                    (source / 'pivigia/README.md').write_text('tampered')
                if case == 'wrong-origin':
                    record['source_repository'] = 'someone/other'
                    (source / 'receipt.json').write_text(json.dumps(record))
                raw = self.archive(source)
                with patch.object(apps, 'git', return_value='b' * 40 + '\trefs/heads/public-source'), \
                     patch.object(public_apps.urllib.request, 'build_opener') as opener:
                    opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(raw)
                    if case == 'valid':
                        self.assertEqual(public_apps.download('pivigia', root / 'out')['sha'], 'a' * 40)
                    else:
                        with self.assertRaises(ValueError):
                            public_apps.download('pivigia', root / 'out')
                    requested = opener.return_value.open.call_args.args[0]
                    self.assertEqual(requested, 'https://api.github.com/repos/Gente-del-Condado/pivigia_ha/tarball/' + 'b' * 40)

    def test_migrated_application_is_not_read_from_forgejo(self):
        with patch.dict(os.environ, {'PUBLIC_APP_MIGRATIONS': 'pivigia,jacksignal'}), \
             patch.object(apps, 'git'), patch.object(apps, 'current') as current, \
             patch.object(apps, 'output') as output, patch.object(apps, 'pending_images', return_value=False):
            apps.plan()
            current.assert_not_called()
            output.assert_any_call('changed', False)


if __name__ == '__main__':
    unittest.main()
