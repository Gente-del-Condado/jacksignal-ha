"""El lector público nunca amplía el origen ni reenvía el Bearer a codeload."""
import os
import unittest
from unittest.mock import patch
import urllib.request

from github_mirror import ArchiveRedirect, Mirror


class MirrorTests(unittest.TestCase):
    def reader(self):
        with patch.dict(os.environ, {'MIRROR_READ_TOKEN': 'fixture-not-a-real-token'}):
            return Mirror('jacksignal')

    def test_missing_token_and_unknown_repository_fail_before_network(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            Mirror('jacksignal')
        with self.assertRaises(ValueError):
            Mirror('CopiasHA')

    def test_branch_requires_exact_private_repository_identity(self):
        reader = self.reader()
        metadata = {'id': 1453028133, 'full_name': 'Gente-del-Condado/jacksignal', 'private': True}
        with patch.object(reader, 'request', side_effect=[metadata, {'name': 'main', 'commit': {'sha': 'a'*40}}]):
            self.assertEqual(reader.branch(), 'a'*40)
        for changes in [{'id': 123}, {'private': False}, {'full_name': 'another/jacksignal'}]:
            reader = self.reader()
            with patch.object(reader, 'request', return_value=dict(metadata, **changes)), self.assertRaises(ValueError):
                reader.branch()

    def test_candidate_and_commit_are_validated_before_download(self):
        reader = self.reader()
        with patch.object(reader, 'request') as request:
            for name in ['other', '../main', 'codex/../../main']:
                with self.assertRaises(ValueError):
                    reader.branch(name)
            for sha in ['main', '../secret', 'a'*39]:
                with self.assertRaises(ValueError):
                    reader.archive(sha)
            request.assert_not_called()

    def test_annotated_tag_is_resolved_without_trusting_response_url(self):
        reader = self.reader()
        reader.verified = True
        with patch.object(reader, 'request', side_effect=[
                {'object': {'type': 'tag', 'sha': 'a'*40, 'url': 'https://evil.invalid'}},
                {'object': {'type': 'commit', 'sha': 'b'*40}}]) as request:
            self.assertEqual(reader.tag('v1.2.3'), 'b'*40)
            self.assertEqual(request.call_args.args, ('/git/tags/' + 'a'*40,))

    def test_redirect_drops_authorization_on_codeload(self):
        request = urllib.request.Request('https://api.github.com/repos/owner/name/tarball/'+'a'*40,
                                         headers={'Authorization': 'Bearer fixture'})
        redirected = ArchiveRedirect().redirect_request(request, None, 302, 'Found', {},
                         'https://codeload.github.com/owner/name/legacy.tar.gz/'+'a'*40)
        self.assertIsNone(redirected.get_header('Authorization'))

    def test_redirect_rejects_other_hosts_plain_http_and_credentials(self):
        request = urllib.request.Request('https://api.github.com/repos/owner/name/tarball/main')
        for url in ['https://evil.invalid/a', 'http://codeload.github.com/a',
                    'https://api.github.com.evil.invalid/a', 'https://user@api.github.com/a',
                    'https://api.github.com:444/a']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                ArchiveRedirect().redirect_request(request, None, 302, 'Found', {}, url)


if __name__ == '__main__':
    unittest.main()
