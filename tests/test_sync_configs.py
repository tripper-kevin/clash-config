import hashlib
import importlib.util
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import yaml

spec = importlib.util.spec_from_file_location('sync', Path(__file__).resolve().parents[1] / 'scripts/sync_configs.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class ConversionTests(unittest.TestCase):
    def report(self):
        return {'rule_replacements': [], 'skipped_rules': []}

    def test_regex_and_timeout(self):
        group = {'name': '香港', 'type': 'url-test', 'include-all': True,
                 'filter': '(?i)(香港|HK)', 'exclude-filter': '(?i)过期|0\\.5倍',
                 'timeout': 5000, 'interval': 300}
        line = sync.group_line(group, [])
        pattern = line.split('policy-regex-filter=')[1].split(',')[0]
        self.assertTrue(re.search(pattern, 'hk 01'))
        self.assertFalse(re.search(pattern, '香港 过期'))
        self.assertFalse(re.search(pattern, '香港 0.5倍'))
        self.assertFalse(re.search(pattern, '日本 01'))
        self.assertIn('timeout=5,', line)

    def test_full_configuration_preserves_policy_and_order(self):
        config = yaml.safe_load((sync.ROOT / 'Merge.yaml').read_text(encoding='utf-8'))
        mapping = json.loads((sync.ROOT / 'scripts/shadowrocket-rule-map.json').read_text(encoding='utf-8'))
        policies = {g['name'] for g in config['proxy-groups']} | {'DIRECT', 'REJECT', 'PROXY'}
        report = self.report()
        categories = sync.geosite_categories(config) - mapping.keys()
        sources = {category: (f'https://test.test/{category}.list', 'DOMAIN,example.org\n')
                   for category in categories}
        rows = sync.render_rules(config, mapping, policies, report, geosite_sources=sources)
        text = '\n'.join(rows)
        self.assertNotIn('GEOSITE,', text)
        self.assertNotIn('DOMAIN-REGEX,', text)
        self.assertTrue(all(x['rule'].startswith('PROCESS-NAME,') for x in report['skipped_rules']))
        self.assertEqual(rows[-1], 'FINAL,🐟 其他')

        def position(category, policy):
            return rows.index(f'RULE-SET,{sources[category][0]},{policy}')

        google = position('google', '🌐 Google')
        self.assertLess(position('youtube', '🎬 流媒体'), google)
        academic_path = sync.ROOT / 'rules/AcademicTools.yaml'
        academic_data = academic_path.read_bytes()
        tools = yaml.safe_load(academic_data)['payload']
        expected = [f'{rule},📚 科研工具' for rule in tools]
        start = rows.index(expected[0])
        self.assertEqual(rows[start:start + len(expected)], expected)
        scholar = position('category-scholar-!cn', '📖 学术资源')
        self.assertLess(google, start)
        self.assertLess(start + len(expected) - 1, scholar)
        self.assertIn({
            'category': 'rule-set:academic-tools',
            'policy': '📚 科研工具',
            'source_path': 'rules/AcademicTools.yaml',
            'source_rule_count': len(tools),
            'source_sha256': hashlib.sha256(academic_data).hexdigest(),
        }, report['rule_replacements'])
        self.assertLess(position('category-dev@cn', 'DIRECT'), position('category-dev', '💻 软件开发'))
        self.assertLess(position('github-copilot', '💻 软件开发'), position('github', '💻 软件开发'))
        self.assertLess(position('category-games@cn', 'DIRECT'), position('category-games-!cn', '🎮 游戏平台'))
        self.assertLess(position('category-ai-!cn', '🤖 人工智能'), position('microsoft', 'Ⓜ️ Microsoft'))
        self.assertEqual(text.count('RULE-SET,https://anti-ad.net/surge.txt,REJECT'), 1)

    def test_local_provider_rejects_invalid_payloads(self):
        provider = {'type': 'http', 'behavior': 'classical', 'format': 'yaml',
                    'url': f'{sync.RAW}/{sync.DEFAULT_REPO}/main/rules/Test.yaml'}
        config = {'rules': ['RULE-SET,test,DIRECT', 'MATCH,DIRECT'], 'rule-providers': {'test': provider}}
        with TemporaryDirectory() as workdir:
            root = Path(workdir)
            path = root / 'rules/Test.yaml'
            path.parent.mkdir()
            for payload in ('- DOMAIN,example.org\n', 'payload: []\n', 'payload: [null]\n',
                            'payload:\n  - DOMAIN,example.org,DIRECT\n', 'payload:\n  - PROCESS-NAME,app.exe\n'):
                path.write_text(payload, encoding='utf-8')
                with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, 'rules/Test.yaml:'):
                    sync.render_rules(config, {}, {'DIRECT'}, self.report(), root=root)

    def test_unknown_or_nonlocal_provider_fails(self):
        config = {'rules': ['RULE-SET,test,DIRECT', 'MATCH,DIRECT']}
        with self.assertRaisesRegex(ValueError, 'Undefined rule provider: test'):
            sync.render_rules(config, {}, {'DIRECT'}, self.report())
        config['rule-providers'] = {'test': {'type': 'http', 'behavior': 'classical', 'format': 'yaml'}}
        for url in ('https://example.com/rules/Test.yaml',
                    f'{sync.RAW}/{sync.DEFAULT_REPO}/main/rules/../Test.yaml'):
            config['rule-providers']['test']['url'] = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'Unmapped rule provider: test'):
                sync.render_rules(config, {}, {'DIRECT'}, self.report())

    def test_composite_mapping_preserves_policy_and_order(self):
        config = {'rules': ['DOMAIN,first.test,DIRECT', 'GEOSITE,test,AI', 'MATCH,DIRECT']}
        mapping = {'test': {'urls': ['https://test.test/a.list', 'https://test.test/b.list'],
                            'rules': ['DOMAIN-SUFFIX,supplement.test']}}
        rows = sync.render_rules(config, mapping, {'DIRECT', 'AI'}, self.report())
        self.assertEqual(rows, ['DOMAIN,first.test,DIRECT', 'RULE-SET,https://test.test/a.list,AI',
            'RULE-SET,https://test.test/b.list,AI', 'DOMAIN-SUFFIX,supplement.test,AI', 'FINAL,DIRECT'])

    def test_new_category_uses_same_name_at_validated_revision(self):
        config = {'rules': ['GEOSITE,new@cn,DIRECT', 'MATCH,DIRECT']}
        revision = 'a' * 40
        url = f'{sync.RAW}/{sync.METACUBEX_REPO}/{revision}/geo/geosite/classical/new@cn.list'
        with patch.object(sync, 'fetch', side_effect={
            sync.METACUBEX_META_HEAD: json.dumps({'sha': revision}),
            url: 'DOMAIN,example.org\n',
        }.__getitem__):
            sources = sync.load_geosite_sources(config, {})
        report = self.report()
        rows = sync.render_rules(config, {}, {'DIRECT'}, report, geosite_sources=sources)
        self.assertEqual(rows, [f'RULE-SET,{url},DIRECT', 'FINAL,DIRECT'])
        self.assertEqual(report['rule_replacements'][0]['source_rule_count'], 1)

    def test_mixed_geosite_keeps_rules_expands_finite_regex_and_reports_other_regex(self):
        config = {'rules': ['GEOSITE,new,DIRECT', 'MATCH,REJECT']}
        omitted = r'DOMAIN-REGEX,^cdn\d+\.example\.org$'
        expanded = r'DOMAIN-REGEX,^api[1-2]?\.example\.org$'
        body = '\n'.join(['DOMAIN-SUFFIX,a.example.org', expanded, omitted, 'DOMAIN,other.example.org'])
        report = self.report()
        rows = sync.render_rules(config, {}, {'DIRECT', 'REJECT'}, report,
                                 geosite_sources={'new': ('https://test.test/new.list', body)})
        self.assertEqual(rows, [
            'DOMAIN-SUFFIX,a.example.org,DIRECT', 'DOMAIN,api.example.org,DIRECT',
            'DOMAIN,api1.example.org,DIRECT', 'DOMAIN,api2.example.org,DIRECT',
            'DOMAIN,other.example.org,DIRECT', 'FINAL,REJECT',
        ])
        source = report['rule_replacements'][0]
        self.assertEqual(source['omitted_domain_regex'], [omitted])
        self.assertEqual(source['expanded_domain_regex'], [{'rule': expanded, 'generated_domain_count': 3}])
        self.assertEqual(sync.expand_domain_regex(r'^api\d\d\d\.example\.org$'), [])

    def test_missing_or_unusable_geosite_leaves_generated_files_intact(self):
        with TemporaryDirectory() as workdir:
            root = Path(workdir)
            (root / 'scripts').mkdir()
            (root / 'scripts/shadowrocket-rule-map.json').write_text('{}')
            (root / 'Merge.yaml').write_text('proxy-groups: []\nrules: ["GEOSITE,new,DIRECT", "MATCH,DIRECT"]\n')
            targets = [root / name for name in ('Merge.json', 'Shadowrocket.conf', 'conversion-report.json')]
            for path in targets:
                path.write_text('previous version')
            for upstream in (HTTPError('https://test.test/new.list', 404, 'Not Found', {}, None),
                             r'DOMAIN-REGEX,^api\d+\.example\.org$'):
                with self.subTest(upstream=upstream), patch.object(sync, 'ROOT', root), patch.object(
                    sync, 'fetch', side_effect=[json.dumps({'sha': 'a' * 40}), upstream],
                ), self.assertRaisesRegex(ValueError, 'GEOSITE new'):
                    sync.build()
                self.assertTrue(all(path.read_text() == 'previous version' for path in targets))

    def test_unknown_rule_type_fails(self):
        with self.assertRaises(ValueError):
            sync.render_rules({'rules': ['NEW-TYPE,x,DIRECT', 'MATCH,DIRECT']}, {}, {'DIRECT'}, self.report())

    def test_html_and_empty_downloads_are_rejected(self):
        for data in ['', '<html>404 Not Found</html>', '# empty list']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                sync.validate_native(data, 'https://test.test/a.list')

    def test_select_stays_manual(self):
        line = sync.group_line({'name': '固定', 'type': 'select', 'include-all': True}, [])
        self.assertTrue(line.startswith('固定 = select,'))
        self.assertNotIn('interval=', line)


if __name__ == '__main__':
    unittest.main()
