"""Los fuentes privados no aportan historial, rutas externas ni credenciales."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import forgejo_apps as apps


class ForgejoAppsTest(unittest.TestCase):
    def archive(self, name='source/file.txt', kind=tarfile.REGTYPE, value=b'fixture'):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(value) if kind == tarfile.REGTYPE else 0
            archive.addfile(member, io.BytesIO(value) if member.size else None)
        return stream.getvalue()

    def test_extract_only_files_under_one_root_into_new_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'source'
            apps.extract(self.archive(), target)
            self.assertEqual((target / 'file.txt').read_bytes(), b'fixture')
            with self.assertRaisesRegex(ValueError, 'nuevo'):
                apps.extract(self.archive(), target)

    def test_archive_paths_links_and_git_history_are_rejected(self):
        cases = [('../file', tarfile.REGTYPE), ('/file', tarfile.REGTYPE),
                 ('source/.git/config', tarfile.REGTYPE), ('source/file', tarfile.SYMTYPE),
                 ('source/file', tarfile.LNKTYPE), ('source/../file', tarfile.REGTYPE)]
        for name, kind in cases:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError):
                    apps.extract(self.archive(name, kind), Path(temporary) / 'source')

    def fixture(self, root):
        folder = root / 'pivigia'
        folder.mkdir()
        for name in ['config.yaml', 'Dockerfile', 'README.md', 'LICENSE', 'icon.png', 'logo.png']:
            (folder / name).write_text('fixture\n')
        return folder

    def test_export_rejects_private_files_keys_and_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = self.fixture(Path(temporary))
            for name, data in [('.env', b'private'), ('key', b'-----BEGIN PRIVATE KEY-----'),
                               ('token', b'github_pat_' + b'x' * 60)]:
                file = folder / name
                file.write_bytes(data)
                with self.assertRaises(ValueError):
                    apps.inventory(folder)
                file.unlink()
            alias = folder.parent / 'alias'
            alias.symlink_to(folder, target_is_directory=True)
            with self.assertRaises(ValueError):
                apps.inventory(alias)
            (folder / 'link').symlink_to(folder / 'README.md')
            with self.assertRaises(ValueError):
                apps.inventory(folder)

    def test_receipt_validates_bytes_and_executable_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = self.fixture(root)
            files = apps.inventory(folder)
            record = {'repo': 'pivigia', 'sha': 'a' * 40, 'files': files,
                      'modes': dict.fromkeys(files, 0o644)}
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(record))
            self.assertEqual(apps.validate(root, 'pivigia')['sha'], 'a' * 40)
            record['modes']['README.md'] = 0o777
            receipt.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'Permisos'):
                apps.validate(root, 'pivigia')
            record['modes']['README.md'] = 0o644
            receipt.write_text(json.dumps(record))
            (folder / 'README.md').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'sumas'):
                apps.validate(root, 'pivigia')

    def test_foreign_origin_fails_before_network_and_no_token_is_exposed(self):
        with patch.dict(os.environ, {'FORGEJO_APPS_READ_TOKEN': 'do-not-print'}), \
             patch.object(apps.urllib.request, 'build_opener') as opener:
            with self.assertRaisesRegex(ValueError, 'autorizado'):
                apps.get('other', '/branches/main')
            opener.assert_not_called()
        with patch.dict(os.environ, {'FORGEJO_APPS_READ_TOKEN': ''}):
            with self.assertRaisesRegex(ValueError, 'Falta FORGEJO'):
                apps.get('pivigia', '/branches/main')


if __name__ == '__main__':
    unittest.main()
