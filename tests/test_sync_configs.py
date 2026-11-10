import importlib.util
import json
from pathlib import Path
import re
import unittest
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

    def test_full_configuration_has_no_geosite_dependencies(self):
        config = yaml.safe_load((sync.ROOT / 'Merge.yaml').read_text())
        mapping = json.loads((sync.ROOT / 'scripts/shadowrocket-rule-map.json').read_text())
        policies = {g['name'] for g in config['proxy-groups']} | {'DIRECT', 'REJECT', 'PROXY'}
        report = self.report()
        rows = sync.render_rules(config, mapping, policies, report)
        text = '\n'.join(rows)
        self.assertNotIn('MetaCubeX', text)
        self.assertNotIn('GEOSITE,', text)
        self.assertNotIn('DOMAIN-REGEX,', text)
        self.assertTrue(all(x['rule'].startswith('PROCESS-NAME,') for x in report['skipped_rules']))
        self.assertEqual(rows[-1], 'FINAL,🐟 其他')
        self.assertLess(text.index('/SteamCN/'), text.index('/Steam/'))
        self.assertLess(text.index('/OpenAI/'), text.index('/Microsoft/'))
        self.assertEqual(text.count('RULE-SET,https://anti-ad.net/surge.txt,REJECT'), 1)

    def test_composite_mapping_preserves_policy_and_order(self):
        config = {'rules': ['DOMAIN,first.test,DIRECT', 'GEOSITE,test,AI', 'MATCH,DIRECT']}
        mapping = {'test': {'urls': ['https://test.test/a.list', 'https://test.test/b.list'],
                            'rules': ['DOMAIN-SUFFIX,supplement.test']}}
        rows = sync.render_rules(config, mapping, {'DIRECT', 'AI'}, self.report())
        self.assertEqual(rows, ['DOMAIN,first.test,DIRECT', 'RULE-SET,https://test.test/a.list,AI',
            'RULE-SET,https://test.test/b.list,AI', 'DOMAIN-SUFFIX,supplement.test,AI', 'FINAL,DIRECT'])

    def test_unknown_category_fails_instead_of_disappearing(self):
        with self.assertRaises(ValueError):
            sync.render_rules({'rules': ['GEOSITE,new,DIRECT', 'MATCH,DIRECT']}, {}, {'DIRECT'}, self.report())

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
