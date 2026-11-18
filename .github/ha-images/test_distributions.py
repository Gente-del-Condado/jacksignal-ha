"""Regresiones de publicación: otros componentes, etiquetas y trabajos sin cambios."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import distributions as dist
import forgejo_apps as apps


class DistributionsTest(unittest.TestCase):
    def fixture(self, root, version='1.0.0'):
        component = root / 'custom_components/pivigia'
        component.mkdir(parents=True)
        (component / 'manifest.json').write_text(json.dumps({'domain': 'pivigia', 'version': version}))
        (root / 'hacs.json').write_text('{}\n')
        (root / 'README.md').write_text('fixture')
        return component

    def test_copy_preserves_other_integrations_and_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared, destination = root / 'prepared', root / 'destination'
            self.fixture(prepared)
            other = destination / 'custom_components/other'
            other.mkdir(parents=True)
            (other / 'manifest.json').write_text('other')
            (destination / 'repository.json').write_text('controller')
            paths = dist.copy_managed(prepared, destination, 'pivigia')
            self.assertEqual((other / 'manifest.json').read_text(), 'other')
            self.assertEqual((destination / 'repository.json').read_text(), 'controller')
            self.assertEqual(dist.version(destination / 'custom_components/pivigia', 'pivigia'), '1.0.0')
            self.assertNotIn('repository.json', paths)

    def test_wrong_domain_and_symlink_destination_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = self.fixture(root / 'prepared')
            with self.assertRaises(ValueError):
                dist.version(component, 'jacksignal')
            destination = root / 'target'
            destination.mkdir()
            (destination / 'custom_components').symlink_to(component.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                dist.copy_managed(root / 'prepared', destination, 'pivigia')

    def test_published_tag_rejects_changed_integration_and_keeps_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = self.fixture(root)
            dist.git(root, 'init', '-q')
            dist.git(root, 'add', '--all')
            dist.git(root, '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
            dist.git(root, 'tag', 'v1.0.0')
            sha = dist.git(root, 'rev-parse', 'v1.0.0')
            self.assertTrue(dist.check_tag(root, 'v1.0.0', 'pivigia'))
            (component / 'modified.py').write_text('changed')
            dist.git(root, 'add', '--all')
            with self.assertRaisesRegex(ValueError, 'otros fuentes'):
                dist.check_tag(root, 'v1.0.0', 'pivigia')
            self.assertEqual(dist.git(root, 'rev-parse', 'v1.0.0'), sha)

    def test_foreign_destination_fails_before_network(self):
        with patch.object(dist, 'command') as command:
            with self.assertRaises(ValueError):
                dist.publish_one('other', Path('fixture'), 'pivigia', {})
            command.assert_not_called()

    def plan(self, records, pending=False):
        outputs = {}
        def previous(args, **kwargs):
            repo = args[-1].rsplit('/', 1)[-1][:-5]
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(records[repo]))
        with patch.object(apps, 'git'), patch.object(apps, 'current', return_value='a' * 40), \
             patch.object(apps, 'pending_images', return_value=pending), \
             patch.object(apps.subprocess, 'run', side_effect=previous), \
             patch.object(apps, 'output', side_effect=lambda k, v: outputs.update({k: v})):
            apps.plan()
        return outputs

    def test_unchanged_sources_skip_quality_and_images(self):
        records = {repo: {'sha': 'a' * 40, 'distribution_format': 2} for repo in apps.APPS}
        outputs = self.plan(records)
        self.assertFalse(outputs['changed'])
        self.assertFalse(outputs['images_pending'])
        self.assertEqual(json.loads(outputs['matrix']), {'include': []})

    def test_migration_checks_sources_once_and_retries_pending_images(self):
        records = {repo: {'sha': 'a' * 40, 'distribution_format': 2} for repo in apps.APPS}
        records['pivigia'].pop('distribution_format')
        outputs = self.plan(records)
        self.assertEqual([x['repo'] for x in json.loads(outputs['matrix'])['include']], ['pivigia'])
        records['pivigia']['distribution_format'] = 2
        outputs = self.plan(records, pending=True)
        self.assertFalse(outputs['changed'])
        self.assertTrue(outputs['images_pending'])


if __name__ == '__main__':
    unittest.main()
