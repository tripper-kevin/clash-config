from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_sync_configs import sync


class AntiAdProviderTests(unittest.TestCase):
    def render(self, provider, root):
        config = {
            'rule-providers': {'anti-ad': provider},
            'rules': ['DOMAIN,first.test,DIRECT', 'RULE-SET,anti-ad,REJECT', 'MATCH,DIRECT'],
        }
        report = {'rule_replacements': [], 'skipped_rules': []}
        rules = sync.render_rules(config, {}, {'DIRECT', 'REJECT'}, report, root=root)
        return rules, report['rule_replacements']

    def test_local_mrs_matches_upstream_yaml_without_reading_binary(self):
        url = 'https://anti-ad.net/surge.txt'
        with TemporaryDirectory() as temp:
            root = Path(temp)
            expected, _ = self.render({'type': 'http', 'behavior': 'domain', 'format': 'yaml',
                                       'url': 'https://anti-ad.net/clash.yaml'}, root)
            self.assertEqual(expected, ['DOMAIN,first.test,DIRECT', f'RULE-SET,{url},REJECT', 'FINAL,DIRECT'])
            for path in ('./rules/anti-ad.mrs', 'rules/anti-ad.mrs'):
                with self.subTest(path=path):
                    actual, replacements = self.render({'type': 'file', 'behavior': 'domain', 'format': 'mrs',
                                                        'path': path}, root)
                    self.assertEqual(actual, expected)
                    self.assertEqual(len(replacements), 1)
                    self.assertEqual(replacements[0]['source_format'], 'mrs')
                    self.assertEqual(replacements[0]['source_path'], path)
                    self.assertEqual(replacements[0]['urls'], [url])

    def test_official_remote_mrs_uses_text_in_shadowrocket(self):
        for url in ('https://anti-ad.net/mihomo.mrs',
                    'https://raw.githubusercontent.com/privacy-protection-tools/anti-ad.github.io/master/docs/mihomo.mrs'):
            with self.subTest(url=url):
                rules, replacements = self.render({'type': 'http', 'behavior': 'domain',
                                                    'format': 'mrs', 'url': url}, sync.ROOT)
                self.assertEqual(rules[1], 'RULE-SET,https://anti-ad.net/surge.txt,REJECT')
                self.assertEqual(replacements[0]['source_url'], url)
                self.assertNotIn('source_path', replacements[0])

    def test_unknown_sources_are_not_silently_substituted(self):
        mrs = {'type': 'file', 'behavior': 'domain', 'format': 'mrs', 'path': './rules/anti-ad.mrs'}
        for override in ({'path': './rules/another.mrs'}, {'behavior': 'ipcidr'},
                         {'type': 'http', 'url': 'https://example.org/anti-ad.mrs'},
                         {'type': 'http', 'format': 'yaml', 'url': 'https://example.org/clash.yaml'}):
            with self.subTest(override=override), self.assertRaisesRegex(ValueError, 'Unmapped rule provider: anti-ad'):
                self.render({**mrs, **override}, sync.ROOT)
