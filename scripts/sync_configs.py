"""Build JSON and an iPhone Shadowrocket adaptation; never export subscription secrets."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW = 'https://raw.githubusercontent.com'
DEFAULT_REPO = 'tripper-kevin/clash-config'
REPO = os.environ.get('GITHUB_REPOSITORY', DEFAULT_REPO)
SUPPORTED = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'DOMAIN-WILDCARD'}
METACUBEX_REPO = 'MetaCubeX/meta-rules-dat'
METACUBEX_META_HEAD = f'https://api.github.com/repos/{METACUBEX_REPO}/commits/meta'
REGEX_TOKEN = re.compile(r'(\\\.|\\d|\[[a-z0-9-]+\]|[a-z0-9-])(\?)?')
DOMAIN_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
REGEX_EXPANSION_LIMIT = 128
ANTI_AD_CLASH_URL = 'https://anti-ad.net/clash.yaml'
ANTI_AD_MRS_URLS = (
    'https://anti-ad.net/mihomo.mrs',
    'https://raw.githubusercontent.com/privacy-protection-tools/anti-ad.github.io/master/docs/mihomo.mrs',
)
ANTI_AD_SHADOWROCKET_URL = 'https://anti-ad.net/surge.txt'
ANTI_AD_MRS_PATH = 'rules/anti-ad.mrs'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'clash-config-sync'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode('utf-8-sig')
        except urllib.error.HTTPError as error:
            if error.code == 404 or attempt == 2:
                raise
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



def geosite_categories(config):
    return {parts[1].strip() for rule in config['rules']
            if (parts := rule.split(','))[0].strip() == 'GEOSITE'}


def load_geosite_sources(config, mapping):
    categories = sorted(geosite_categories(config) - mapping.keys())
    if not categories:
        return {}
    for category in categories:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_!@-]*', category):
            raise ValueError(f'Invalid GEOSITE category: {category!r}')

    revision = json.loads(fetch(METACUBEX_META_HEAD)).get('sha', '')
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('Cannot resolve the MetaCubeX meta revision')

    def load(category):
        url = f'{RAW}/{METACUBEX_REPO}/{revision}/geo/geosite/classical/{category}.list'
        try:
            return url, fetch(url)
        except OSError as error:
            raise ValueError(f'Could not load GEOSITE {category} from {url}: {error}') from error

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(categories, pool.map(load, categories)))


def expand_domain_regex(pattern):
    """Expand a bounded sequence of literals, character classes and optional tokens."""
    if not (pattern.startswith('^') and pattern.endswith('$')):
        return []
    try:
        matcher = re.compile(pattern, re.ASCII)
    except re.error:
        return []
    body = pattern[1:-1]
    domains = ['']
    position = 0
    while position < len(body):
        match = REGEX_TOKEN.match(body, position)
        if not match:
            return []
        token, optional = match.groups()
        if token.startswith('['):
            characters = [char for char in 'abcdefghijklmnopqrstuvwxyz0123456789-'
                          if re.fullmatch(token, char, re.ASCII)]
        elif token == r'\d':
            characters = list('0123456789')
        else:
            characters = [token.removeprefix('\\')]
        if optional:
            characters.append('')
        if len(domains) * len(characters) > REGEX_EXPANSION_LIMIT:
            return []
        domains = [prefix + char for prefix in domains for char in characters]
        position = match.end()
    return sorted({domain for domain in domains if len(domain) <= 253
                   and matcher.fullmatch(domain)
                   and all(DOMAIN_LABEL.fullmatch(label) for label in domain.split('.'))})


def geosite_replacement(category, url, text):
    source_rows = entries(text)
    rules = []
    expanded = []
    omitted = []
    for row in source_rows:
        kind, sep, value = row.partition(',')
        if not sep or not value:
            raise ValueError(f'Invalid GEOSITE rule in {category}: {row!r}')
        if kind == 'DOMAIN-REGEX':
            domains = expand_domain_regex(value)
            if domains:
                rules.extend(f'DOMAIN,{domain}' for domain in domains)
                expanded.append({'rule': row, 'generated_domain_count': len(domains)})
            else:
                omitted.append(row)
        elif kind in SUPPORTED and ',' not in value and not any(c.isspace() for c in value):
            rules.append(row)
        else:
            raise ValueError(f'Invalid or unsupported GEOSITE rule in {category}: {row!r}')
    if not rules:
        raise ValueError(f'GEOSITE {category} has no Shadowrocket-compatible rules: {url}')
    details = {
        'source_url': url, 'source_rule_count': len(source_rows),
        'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'expanded_domain_regex': expanded, 'omitted_domain_regex': omitted,
    }
    if expanded or omitted:
        details['rendered_as'] = 'inline'
        return rules, details
    details['rendered_as'] = 'remote'
    return [f'RULE-SET,{field(url)}'], details


def validate_native(text, url):
    rows = entries(text)
    kinds = SUPPORTED | {'IP-CIDR', 'IP-CIDR6', 'IP-ASN', 'GEOIP', 'USER-AGENT', 'URL-REGEX'}
    if not rows or any(row.split(',', 1)[0] not in kinds for row in rows):
        raise ValueError(f'Invalid native rule set: {url}')
    return {'url': url, 'checked_rule_count': len(rows),
            'checked_sha256': hashlib.sha256(text.encode()).hexdigest()}


def anti_ad_format(provider):
    """Recognize the upstream rule sets or the documented local conversion."""
    if provider.get('behavior') == 'domain':
        if (provider.get('type'), provider.get('format', 'yaml'), provider.get('url')) == (
                'http', 'yaml', ANTI_AD_CLASH_URL):
            return 'yaml'
        if (provider.get('type'), provider.get('format')) == ('http', 'mrs') and provider.get('url') in ANTI_AD_MRS_URLS:
            return 'mrs'
        if (provider.get('type'), provider.get('format')) == ('file', 'mrs') and provider.get('path') in (
                ANTI_AD_MRS_PATH, './' + ANTI_AD_MRS_PATH):
            return 'mrs'
    raise ValueError('Unmapped rule provider: anti-ad (expected official YAML/MRS or local rules/anti-ad.mrs)')


def local_classical_rules(name, provider, root):
    """Read a same-repository classical provider from the checked-out revision."""
    url = provider.get('url', '')
    path = None
    if (provider.get('type'), provider.get('behavior'), provider.get('format')) == ('http', 'classical', 'yaml'):
        for repo in (REPO, DEFAULT_REPO):
            prefix = f'{RAW}/{repo}/main/'
            if url.startswith(prefix):
                path = url[len(prefix):]
                break
    if not path or not re.fullmatch(r'rules/[A-Za-z0-9_-]+\.yaml', path):
        raise ValueError(f'Unmapped rule provider: {name}')

    source = (root / path).read_bytes()
    document = yaml.safe_load(source.decode('utf-8-sig'))
    payload = document.get('payload') if isinstance(document, dict) else None
    if not isinstance(payload, list) or not payload:
        raise ValueError(f'{path}: expected a non-empty payload list')

    rules = []
    for row in payload:
        if not isinstance(row, str):
            raise ValueError(f'{path}: invalid classical rule: {row!r}')
        kind, sep, value = row.partition(',')
        if kind not in SUPPORTED or not sep or not value or ',' in value or any(c.isspace() for c in value):
            raise ValueError(f'{path}: unsupported classical rule: {row!r}')
        rules.append(row)
    return rules, path, hashlib.sha256(source).hexdigest()


def render_rules(config, mapping, policies, report, *, root=ROOT, geosite_sources=None):
    geosite_sources = geosite_sources or {}
    output = []
    seen = set()
    converted_geosites = {}

    def emit(line):
        # Exact duplicates with the same policy cannot change first-match routing.
        if line not in seen:
            seen.add(line)
            output.append(line)

    def expand(key, policy):
        if key not in mapping:
            raise ValueError(f'Add native mapping for: {key}')
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
            category = parts[1]
            if category in mapping:
                expand(category, policy)
                continue
            if category not in converted_geosites:
                if category not in geosite_sources:
                    raise ValueError(f'Missing MetaCubeX source for GEOSITE {category}')
                converted_geosites[category] = geosite_replacement(category, *geosite_sources[category])
            rows, details = converted_geosites[category]
            for row in rows:
                emit(f'{row},{policy}')
            report['rule_replacements'].append({'category': category, 'policy': policy, **details})
        elif kind == 'GEOIP' and not re.fullmatch('[A-Z]{2}', parts[1]):
            expand('geoip:' + parts[1], policy)
        elif kind == 'RULE-SET':
            name = parts[1]
            provider = config.get('rule-providers', {}).get(name)
            if not isinstance(provider, dict):
                raise ValueError(f'Undefined rule provider: {name}')
            if name == 'anti-ad':
                source_format = anti_ad_format(provider)
                emit(f'RULE-SET,{ANTI_AD_SHADOWROCKET_URL},{policy}')
                if source_format == 'mrs':
                    report['rule_replacements'].append({
                        'category': 'rule-set:anti-ad', 'policy': policy, 'source_format': source_format,
                        **({'source_url': provider['url']} if provider['type'] == 'http'
                           else {'source_path': provider['path']}),
                        'urls': [ANTI_AD_SHADOWROCKET_URL],
                        'note': 'Shadowrocket uses the upstream text list; the MRS is not read or bundled.',
                    })
            else:
                rows, path, digest = local_classical_rules(name, provider, root)
                for row in rows:
                    emit(f'{row},{policy}')
                report['rule_replacements'].append({
                    'category': 'rule-set:' + name, 'policy': policy, 'source_path': path,
                    'source_rule_count': len(rows), 'source_sha256': digest,
                })
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
    source = (ROOT / 'Merge.yaml').read_bytes()
    config = yaml.safe_load(source.decode('utf-8-sig'))
    if not isinstance(config, dict):
        raise ValueError('Merge.yaml must be a mapping')
    mapping = json.loads((ROOT / 'scripts/shadowrocket-rule-map.json').read_text(encoding='utf-8'))
    report = {'source_sha256': hashlib.sha256(source).hexdigest(),
              'skipped_rules': [], 'group_differences': [], 'rule_replacements': [], 'checked_sources': [],
              'notes': [
                  'GEOSITE uses same-name MetaCubeX rules unless an explicit mapping exists.',
                  'Mixed sources are inlined after finite regex expansion. Other regex rules are reported under omitted_domain_regex.',
                  'Local classical domain providers are inlined from the checked-out revision.',
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
    geosite_sources = load_geosite_sources(config, mapping)
    geosite_text_by_url = dict(geosite_sources.values())
    rules = render_rules(config, mapping, policies, report, root=ROOT, geosite_sources=geosite_sources)
    urls = sorted({r.split(',')[1] for r in rules if r.startswith('RULE-SET,')})
    checked = {url: validate_native(geosite_text_by_url[url], url) for url in urls if url in geosite_text_by_url}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch, url): url for url in urls if url not in checked}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            checked[url] = validate_native(future.result(), url)
            print(f'Checked {len(checked)}/{len(urls)} remote rule sets', flush=True)
    report['checked_sources'] = [checked[url] for url in urls]
    base = f'{RAW}/{REPO}/main'
    output = ['# Generated from Merge.yaml using same-name MetaCubeX rules and explicit overrides.',
              '[General]', 'bypass-system = true',
              'dns-server = https://dns.alidns.com/dns-query,https://doh.pub/dns-query',
              f'update-url = {base}/Shadowrocket.conf', '', '[Proxy Group]']
    output += [group_line(g, report['group_differences']) for g in groups]
    output += ['', '[Rule]', *rules]
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=ROOT) as temp:
        stage = Path(temp)
        (stage / 'Merge.json').write_text(json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
        (stage / 'Shadowrocket.conf').write_text('\n'.join(output) + '\n', encoding='utf-8', newline='\n')
        (stage / 'conversion-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
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
