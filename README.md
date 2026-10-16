# LearnFlow

用独立输出、迁移和延迟复测验证掌握的中文学习教练技能。适用于系统学习、备考、语言练习、深度阅读、技能训练与断点续学。

当前版本：**v1.3.0**，基于《通用学习流程操作手册 V1.2》。在 v1.2.1 的教学设定上增加可选工具，原有教学规则、L0–L6 定义、教材顺序、会话边界与界面元数据保持原样。所有执行规则已包含在仓库内，不需要额外下载手册。

## 安装

取得本版本的完整目录或发布包，解压后把完整的 `learnflow` 文件夹放入 Codex 的技能目录。已公开的历史版本见 [GitHub Releases](https://github.com/kelexuong/learnflow/releases)。

- Windows：`%USERPROFILE%\.codex\skills\learnflow`
- macOS / Linux：`~/.codex/skills/learnflow`
- 如果已设置 `CODEX_HOME`，使用 `$CODEX_HOME/skills/learnflow`。

保留目录内所有文件的相对位置，特别是 `scripts/` 和 `assets/`。也可将本仓库地址交给 Codex 的 skill-installer 技能安装。其他支持 `SKILL.md` 的工具可使用相同技能文件；具体安装位置和工具权限由所在平台决定。

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
python -m unittest discover -s tests -v
```

校验覆盖技能元数据、本地引用、界面与图标，以及资料导入、版本保留、检索、进度存续、导出和成果封装。设置保护测试逐字节核对 v1.2.1 的 12 份原有配套文件，并核对仅去除版本号差异的原 SKILL 正文；改动不能悄悄替换教学设定。GitHub Actions 在推送和拉取请求中运行同一组校验。

这些检查验证工具行为和设定保留，不能代替真实教学对话的效果评估，也不能证明所有平台都兼容。

行为检查可使用 [examples/validation-cases.md](examples/validation-cases.md)；常见使用示例见 [examples/scenarios.md](examples/scenarios.md)。

## v1.3.0 新增能力

| 能力 | 用途与边界 |
|---|---|
| 本地资料库 | 批量导入 MD、TXT、DOCX、PDF，保存来源、版本、章节/页码锚点；按当前范围读取和中英文检索。检索命中不算完整阅读。 |
| 原页与 OCR 接口 | 渲染 PDF 原页核对公式和图表；扫描页可接本机 Tesseract。引擎、语言包需要另外具备，不随技能安装。 |
| 进度存续与复习队列 | 保存真实作答、阅读位置和下一入口，保留修订历史；记录不会自动结束、跳课、升级或创建提醒。 |
| 多资料整合 | 合并课件、转写、笔记与主教材，标注冲突和补充；保留原章节顺序，并按答案含义判断。 |
| 学习产物 | 笔记与知识地图模板、Markdown 转 Word、五类离线交互页，以及按明确清单封装知识包/Skill；不自动发布。 |

扩展均按需要调用；普通问答无需先导入资料、配置数据库或生成学习产物。详细操作见 [资料库](references/source-library.md)、[多资料学习](references/material-workflows.md) 和 [学习产物](references/learning-outputs.md)。

工具需要 Python 3.10 或以上版本；在学习工作区的虚拟环境安装运行依赖即可：

```sh
python -m pip install -r <skill-dir>/requirements.txt
python <skill-dir>/scripts/learnflow.py doctor
python <skill-dir>/scripts/learnflow.py --workspace <资料工作区> import <教材文件或目录> --role book
python <skill-dir>/scripts/learnflow.py --workspace <资料工作区> catalog
```

资料工作区必须在 Skill 目录之外。原文件保留原位，索引和学习档案留在工作区；不会默认遍历电脑、连接账户或上传资料。默认单文件限额为 256 MiB，可明确调整；长资料采用限定范围读取，并不一次装入全部模型上下文。复杂公式、图文与 OCR 结果仍需核对原页。
