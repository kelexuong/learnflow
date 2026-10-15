# LearnFlow

用独立输出、迁移和延迟复测验证掌握的中文学习教练技能。适用于系统学习、备考、语言练习、深度阅读、技能训练与断点续学。

当前版本：**v1.2.1**，基于《通用学习流程操作手册 V1.2》。所有执行规则已包含在仓库内，不需要额外下载手册。

## 安装

下载 [v1.2.1 发布包](https://github.com/kelexuong/learnflow/releases/tag/v1.2.1)，解压后把完整的 `learnflow` 文件夹放入 Codex 的技能目录：

- Windows：`%USERPROFILE%\.codex\skills\learnflow`
- macOS / Linux：`~/.codex/skills/learnflow`
- 如果已设置 `CODEX_HOME`，使用 `$CODEX_HOME/skills/learnflow`。

保留 `SKILL.md`、`agents/`、`assets/`、`references/`、`templates/` 和 `examples/` 的相对位置。也可将本仓库地址交给 Codex 的 skill-installer 技能安装。其他支持 `SKILL.md` 的工具可使用相同技能文件；具体安装位置和工具权限由所在平台决定。

## 开始使用

```text
使用 $learnflow 带我学习充分条件与必要条件。先用一个小任务看看基础。
```

```text
使用 $learnflow 按这本书的目录顺序持续带我学。正文以我提供的文件为准，分别记录阅读进度和掌握证据。
```

```text
使用 $learnflow 根据这份学习记录继续，从记录里的下一步开始。
```

可以随时要求直接讲解、看答案、跳过测试或暂停。“记录一下”只更新快照；“记录，不进入下一点”会停在当前知识点。只有明确暂停、结束或达到约定范围时，才收尾整次学习。

## 工作方式与边界

- 九步闭环按需要使用：目标、诊断、知识地图、教学、独立输出、错因诊断、训练、迁移复测与复盘。
- L0–L6 按知识点和任务证据记录；看过答案、单题正确和即时换题不能证明长期掌握。
- 按书学习须有实际可读正文；没有正文时只规划路线或提供明确标注的一般解释。
- 学习记录用于恢复上下文，不保证跨会话自动记忆。保存和提醒只有在工具执行成功后才算完成。
- 真实学习档案应放在仓库外；`templates/learning-record.md` 是空白模板。

## 验证

需要 Python 3.10 或以上版本：

```sh
python -m pip install -r requirements-dev.txt
python scripts/validate.py
```

校验覆盖技能元数据、界面简介长度、本地引用与图标有效性。GitHub Actions 在推送和拉取请求中运行同一校验。结构校验不代表模型教学效果已通过实测，也不能证明所有平台都兼容。

本次修复了手册版本引用、界面简介长度，以及模式表容易混淆单元完成与会话结束的问题，保留原有自动发现策略和产品元数据。

行为检查可使用 [examples/validation-cases.md](examples/validation-cases.md)；常见使用示例见 [examples/scenarios.md](examples/scenarios.md)。
