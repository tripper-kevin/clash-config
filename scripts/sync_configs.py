"""Build JSON and an iPhone Shadowrocket adaptation; never export subscription secrets."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = 'https://raw.githubusercontent.com'
REPO = os.environ.get('GITHUB_REPOSITORY', 'tripper-kevin/clash-config')
SUPPORTED = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'DOMAIN-WILDCARD'}


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'clash-config-sync'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode('utf-8-sig')
        except OSError:
            if attempt == 2:
                raise


def entries(text):
    return [s.strip() for s in text.splitlines() if s.strip() and not s.lstrip().startswith('#')]


def field(value):
    value = str(value)
    if any(c in value for c in ',\r\n'):
        raise ValueError(f'Unescaped Shadowrocket field: {value!r}')
    return value


def group_line(group, notes):
    kind = group['type']
    if kind not in {'select', 'url-test', 'fallback'}:
        raise ValueError(f'Unsupported group type: {kind}')
    options = [kind, *map(field, group.get('proxies', []))]
    if group.get('include-all') or group.get('filter'):
        def scoped(pattern):
            return '(?i:' + pattern[4:] + ')' if pattern.startswith('(?i)') else '(?:' + pattern + ')'
        pattern = '^(?=.*' + scoped(group.get('filter', '.*')) + ')'
        if group.get('exclude-filter'):
            pattern += '(?!.*' + scoped(group['exclude-filter']) + ')'
        pattern += '.*$'
        re.compile(pattern)
        options.append('policy-regex-filter=' + field(pattern))
    if kind != 'select':
        options += [
            'url=' + field(group.get('url', 'https://www.gstatic.com/generate_204')),
            'interval=' + str(int(group.get('interval', 300))),
            'timeout=' + format(group.get('timeout', 5000) / 1000, 'g'),
        ]
        if kind == 'url-test':
            options.append('tolerance=' + str(int(group.get('tolerance', 50))))
    elif group.get('default-selected'):
        options.append('policy-select-name=' + field(group['default-selected']))
    if group.get('hidden'):
        options.append('hidden=1')
    omitted = {k: group[k] for k in ('lazy', 'max-failed-times', 'expected-status', 'empty-fallback', 'exclude-type') if k in group}
    if omitted:
        notes.append({'group': group['name'], 'not_translated': omitted})
    return field(group['name']) + ' = ' + ','.join(options)



def required_mappings(config):
    keys = set()
    for rule in config['rules']:
        parts = [p.strip() for p in rule.split(',')]
        if parts[0] == 'GEOSITE':
            keys.add(parts[1])
        elif parts[0] == 'GEOIP' and not re.fullmatch('[A-Z]{2}', parts[1]):
            keys.add('geoip:' + parts[1])
    return keys


def validate_native(text, url):
    rows = entries(text)
    kinds = SUPPORTED | {'IP-CIDR', 'IP-CIDR6', 'IP-ASN', 'GEOIP', 'USER-AGENT', 'URL-REGEX'}
    if not rows or any(row.split(',', 1)[0] not in kinds for row in rows):
        raise ValueError(f'Invalid native rule set: {url}')
    return {'url': url, 'checked_rule_count': len(rows),
            'checked_sha256': hashlib.sha256(text.encode()).hexdigest()}


def render_rules(config, mapping, policies, report):
    missing = required_mappings(config) - mapping.keys()
    if missing:
        raise ValueError(f'Add native mappings for: {sorted(missing)}')
    output = []
    seen = set()

    def emit(line):
        # Exact duplicates with the same policy cannot change first-match routing.
        if line not in seen:
            seen.add(line)
            output.append(line)

    def expand(key, policy):
        item = mapping[key]
        if not item.get('urls') and not item.get('rules'):
            raise ValueError(f'Empty mapping: {key}')
        for url in item.get('urls', []):
            if not url.startswith('https://'):
                raise ValueError(f'Expected HTTPS URL: {url}')
            emit(f'RULE-SET,{field(url)},{policy}')
        for rule in item.get('rules', []):
            kind, sep, value = rule.partition(',')
            if kind not in SUPPORTED or not sep or not value or ',' in value:
                raise ValueError(f'Invalid supplemental rule: {rule}')
            emit(f'{rule},{policy}')
        report['rule_replacements'].append({'category': key, 'policy': policy, **item})

    parts_list = [[p.strip() for p in rule.split(',')] for rule in config['rules']]
    for original, parts in zip(config['rules'], parts_list):
        kind = parts[0]
        if kind == 'PROCESS-NAME':
            report['skipped_rules'].append({'rule': original, 'reason': 'Windows process rule does not apply to iPhone'})
            continue
        policy = parts[1] if kind == 'MATCH' else parts[2]
        if policy not in policies:
            raise ValueError(f'Undefined policy: {policy}')
        if kind == 'GEOSITE':
            expand(parts[1], policy)
        elif kind == 'GEOIP' and not re.fullmatch('[A-Z]{2}', parts[1]):
            expand('geoip:' + parts[1], policy)
        elif kind == 'RULE-SET':
            provider = config['rule-providers'][parts[1]]
            if parts[1] != 'anti-ad' or provider.get('url') != 'https://anti-ad.net/clash.yaml':
                raise ValueError(f'Unmapped rule provider: {parts[1]}')
            emit(f'RULE-SET,https://anti-ad.net/surge.txt,{policy}')
        elif kind == 'MATCH':
            emit(f'FINAL,{policy}')
        elif kind in SUPPORTED | {'GEOIP', 'IP-CIDR', 'IP-CIDR6'}:
            emit(original)
        else:
            raise ValueError(f'Unsupported rule: {original}')
    if sum(p[0] == 'MATCH' for p in parts_list) != 1 or parts_list[-1][0] != 'MATCH':
        raise ValueError('Expected exactly one final MATCH rule')
    return output


def build():
    config = yaml.safe_load((ROOT / 'Merge.yaml').read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('Merge.yaml must be a mapping')
    mapping = json.loads((ROOT / 'scripts/shadowrocket-rule-map.json').read_text(encoding='utf-8'))
    report = {'source_sha256': hashlib.sha256((ROOT / 'Merge.yaml').read_bytes()).hexdigest(),
              'skipped_rules': [], 'group_differences': [], 'rule_replacements': [], 'checked_sources': [],
              'notes': [
                  'Purpose-based Shadowrocket rule mapping; no GeoSite conversion or regular-expression omission.',
                  'Maintained remote rule sets plus a small set of supplemental domains; no MetaCubeX dependency at build or runtime.',
                  'DNS uses an independent baseline; Mihomo DNS policies are not exported.',
                  'Import node subscriptions separately. Client-specific group differences are listed below.',
                  'Remote rule URLs update independently; on-device loading and routing have not been tested.',
              ]}
    groups = config['proxy-groups']
    names = {g['name'] for g in groups}
    if len(names) != len(groups):
        raise ValueError('Duplicate group name')
    policies = names | {'DIRECT', 'REJECT', 'PROXY'}
    for group in groups:
        for policy in group.get('proxies', []):
            if policy not in policies:
                raise ValueError(f'Explicit node {policy!r} needs a subscription mapping')
    rules = render_rules(config, mapping, policies, report)
    urls = sorted({r.split(',')[1] for r in rules if r.startswith('RULE-SET,')})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch, url): url for url in urls}
        checked = {}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            checked[url] = validate_native(future.result(), url)
            print(f'Checked {len(checked)}/{len(urls)} remote rule sets', flush=True)
    report['checked_sources'] = [checked[url] for url in urls]
    base = f'{RAW}/{REPO}/main'
    output = ['# Generated from Merge.yaml using purpose-based native rules.',
              '[General]', 'bypass-system = true',
              'dns-server = https://dns.alidns.com/dns-query,https://doh.pub/dns-query',
              f'update-url = {base}/Shadowrocket.conf', '', '[Proxy Group]']
    output += [group_line(g, report['group_differences']) for g in groups]
    output += ['', '[Rule]', *rules]
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=ROOT) as temp:
        stage = Path(temp)
        (stage / 'Merge.json').write_text(json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        (stage / 'Shadowrocket.conf').write_text('\n'.join(output) + '\n', encoding='utf-8')
        (stage / 'conversion-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for name in ('Merge.json', 'Shadowrocket.conf', 'conversion-report.json'):
            (stage / name).replace(ROOT / name)
    # This directory was owned by earlier generator versions. Keep a migration
    # marker so git add records removal of the obsolete generated rule copies.
    old_dir = ROOT / 'shadowrocket-rules'
    if old_dir.exists():
        shutil.rmtree(old_dir)
    old_dir.mkdir()
    (old_dir / 'README.md').write_text('旧版生成的规则副本已移除。现用维护者的远程规则；映射见 scripts/shadowrocket-rule-map.json。\n', encoding='utf-8')
    print(f'Generated {len(groups)} groups, {len(report["rule_replacements"])} mappings, {len(urls)} remote sources; skipped {len(report["skipped_rules"])} platform-specific rules.')


if __name__ == '__main__':
    build()
