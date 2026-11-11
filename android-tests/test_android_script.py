import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('generator', ROOT / 'scripts/generate_android_script.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def apply(patch, base):
    script = generator.generate_script(patch)
    harness = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({});
vm.runInContext(input.script, context);
const before = JSON.stringify(input.config);
const result = context.main(input.config);
const twice = context.main(result);
process.stdout.write(JSON.stringify({result, twice, unchanged: before === JSON.stringify(input.config)}));
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps({'script': script, 'config': base}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class AndroidScriptTests(unittest.TestCase):
    def test_real_source_preserves_subscription_and_replaces_groups(self):
        patch = yaml.safe_load((ROOT / 'Merge.yaml').read_text())
        base = {'proxies': [{'name': '香港测试', 'type': 'ss', 'password': 'test-only'}],
                'proxy-providers': {'subscription': {'type': 'http', 'url': 'https://example.test/sub'}},
                'proxy-groups': [{'name': 'obsolete', 'type': 'select', 'proxies': ['DIRECT']}],
                'rules': ['MATCH,REJECT'], 'mixed-port': 7890}
        result = apply(patch, base)
        for key in ['proxies', 'proxy-providers', 'mixed-port']:
            self.assertEqual(result['result'][key], base[key])
        for key in ['proxy-groups', 'rules']:
            self.assertEqual(result['result'][key], patch[key])
        self.assertEqual(result['twice'], result['result'])
        self.assertTrue(result['unchanged'])

    def test_nested_merge_replaces_arrays_and_preserves_unmentioned_fields(self):
        result = apply({'dns': {'nameserver': ['new'], 'ipv6': False}, 'profile': {'store-selected': True}},
                       {'dns': {'nameserver': ['old'], 'cache-algorithm': 'arc'}, 'profile': {'other': True}})['result']
        self.assertEqual(result['dns'], {'nameserver': ['new'], 'cache-algorithm': 'arc', 'ipv6': False})
        self.assertEqual(result['profile'], {'other': True, 'store-selected': True})

    def test_provider_only_subscription_and_special_strings(self):
        text = "引号\" \\ ${doNotExecute()} \u2028 \u2029"
        patch = {'dns': {'nameserver': [text]}}
        base = {'proxy-providers': {'airport': {'url': 'https://example.test/sub'}}}
        result = apply(patch, base)['result']
        self.assertEqual(result['proxy-providers'], base['proxy-providers'])
        self.assertEqual(result['dns']['nameserver'], [text])

    def test_invalid_yaml_shape_is_rejected(self):
        with self.assertRaises(ValueError):
            generator.generate_script(['not a configuration'])


if __name__ == '__main__':
    unittest.main()
