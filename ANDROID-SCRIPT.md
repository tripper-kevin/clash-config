# YAML 自动生成安卓覆写脚本

适用于 FlClash 等提供 JavaScript `main(config)` 订阅覆写入口的客户端。不是所有名为 Clash 的安卓客户端都支持此入口；JSON、YAML 导入入口不能直接导入 JS。

## 部署

把包内文件按相同路径上传到仓库根目录，原有 Merge.yaml 和小火箭工作流保留：

- `.github/workflows/android-script.yml`
- `scripts/generate_android_script.py`
- `android-tests/test_android_script.py`
- `Merge-Android.js`（已根据本次拉取的 YAML 生成，工作流会自动更新）

GitHub 新建工作流时，文件名输入完整路径 `.github/workflows/android-script.yml`。复制包内同名文件内容即可。其余文件和文件夹使用 Upload files 上传并保留结构。

提交 main 后，到 Actions 查看 **Generate Android override script** 是否成功，也可使用 Run workflow 手动生成。工作流每次修改 Merge.yaml 时执行，读取 YAML、解析锚点、生成脚本、检查 JavaScript 语法、运行节点保留和合并行为测试，再把有变化的 Merge-Android.js 提交回 main。不会重复生成无变化的提交。

小火箭/JSON 工作流与安卓工作流独立运行。两者同时推送发生冲突时，会从最新 main 重新生成再重试。机器人需要 contents: write；分支保护若禁止直接推送，需要改为 PR。

## 使用

部署成功后，远程脚本地址：

https://raw.githubusercontent.com/tripper-kevin/clash-config/main/Merge-Android.js

在 FlClash 的覆写脚本中导入或粘贴这个文件，并对目标订阅启用它；只有创建脚本但未对订阅启用时不会生效。节点仍由机场订阅提供。客户端若仅支持本地脚本，需要下载或粘贴更新；远程更新设置以客户端功能为准。

## 合并逻辑

YAML 先被解析为完整对象，锚点和正则字符串正确保留，然后嵌入 JS。`main(config)` 以订阅配置为基础：

- 映射对象逐层合并，YAML 中的值优先。
- 数组整段替换，因此业务分组和分流顺序由 YAML 决定。
- YAML 未定义的字段保留，包括当前配置没有定义的 proxies 和 proxy-providers。
- 输入配置不原地修改，重复运行不会重复追加分组或规则。

源 YAML 的 DNS、进程规则及其他 Mihomo 字段原样保留，客户端自身仍可能在脚本执行后覆写部分字段。脚本不会把小火箭版规则混入安卓配置。

本次测试使用 JavaScript 运行时验证，未做安卓设备真机验证。

## 本地生成

```sh
python -m pip install PyYAML==6.0.2
python scripts/generate_android_script.py
node --check Merge-Android.js
python -m unittest discover -s android-tests -v
```
