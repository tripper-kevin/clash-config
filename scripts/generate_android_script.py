"""Generate a main(config) override for FlClash from Merge.yaml."""
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def generate_script(config):
    if not isinstance(config, dict):
        raise ValueError('Merge.yaml must contain a configuration mapping')
    # Embed data as a JSON string: quotes, backslashes and Unicode separators
    # cannot escape into executable JavaScript. Anchors are resolved by PyYAML.
    payload = json.dumps(json.dumps(config, ensure_ascii=False, allow_nan=False), ensure_ascii=True)
    return '''// Generated from Merge.yaml. Edit the YAML source, not this file.
// FlClash / clients supporting JavaScript main(config) profile overrides.
// Objects merge recursively; arrays and scalar values from the YAML replace
// subscription values. Subscription proxies/providers survive if not overridden.
function main(config) {
  "use strict";
  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }
  if (!isObject(config)) {
    throw new Error("Expected a subscription configuration object");
  }
  const patch = JSON.parse(''' + payload + ''');
  function merge(base, override) {
    if (!isObject(override)) {
      return Array.isArray(override) ? override.map(clone) : override;
    }
    const result = {};
    if (isObject(base)) {
      Object.keys(base).forEach(function (key) { set(result, key, clone(base[key])); });
    }
    Object.keys(override).forEach(function (key) {
      const previous = Object.prototype.hasOwnProperty.call(result, key) ? result[key] : undefined;
      set(result, key, merge(previous, override[key]));
    });
    return result;
  }
  function set(target, key, value) {
    Object.defineProperty(target, key, {
      value: value, enumerable: true, writable: true, configurable: true
    });
  }
  function clone(value) {
    return merge(undefined, value);
  }
  return merge(config, patch);
}
'''


def build():
    source = ROOT / 'Merge.yaml'
    config = yaml.safe_load(source.read_text(encoding='utf-8-sig'))
    target = ROOT / 'Merge-Android.js'
    content = generate_script(config)
    temporary = target.with_suffix('.js.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(target)
    print('Generated Merge-Android.js')


if __name__ == '__main__':
    build()
