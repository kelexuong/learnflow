# 资料库与来源定位

在需要导入、查找或核对多份资料时使用。本扩展提供本地工具，不增加教学前置问卷，不更改原教材顺序、等级或会话边界。

## 工作区与环境

使用用户指定或获准创建的本地学习目录，必须在 Skill 目录之外。工具只处理明确提供的文件/目录，不默认遍历整个电脑。原资料保留原位；规范化快照、索引和学习档案都留在资料工作区，不写入可公开技能包。

先运行 `python <skill-dir>/scripts/learnflow.py doctor`。若所在平台已提供所需依赖，直接使用；否则在学习工作区的虚拟环境安装 `<skill-dir>/requirements.txt`。无需设置 API key、启动服务器、连接第三方账户或改全局规则。

以下命令中的 `<workspace>` 是实际资料工作区；应使用当前平台可用的 Python，不把示例路径当成固定配置。

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> import <教材或文件夹> --role book
python <skill-dir>/scripts/learnflow.py --workspace <workspace> catalog
python <skill-dir>/scripts/learnflow.py --workspace <workspace> outline --source <资料ID>
python <skill-dir>/scripts/learnflow.py --workspace <workspace> read --source <资料ID> --section "当前章节"
```

## 格式与保真

- MD、Markdown、TXT：保留正文顺序、标题和行号。默认 UTF-8；其他编码需要明确指定 `--encoding`，不静默猜成乱码。
- DOCX：保留正文段落、简单表格及可提取的内嵌图片。段落锚点不是页码。复杂公式、合并表格和版面须对照原文，无法确认的部分标待核对。
- PDF：逐页提取文字，保留从 1 开始的文件页码；不推算书内印刷页码。`--pages 1-5,8` 可只导入选定范围，其他页明确标为未导入。
- 扫描或文字过少的页：默认报告缺口并拒绝将其作为完整可读资料。用户明确选择部分范围时，可用 `--allow-partial` 保存缺口标记；缺口不参与正文检索，也不能被当作已读。
- OCR：`--ocr` 仅在缺少正文的 PDF 页调用本机 Tesseract；可用 `--tesseract <实际路径>`、`--language chi_sim+eng`。需要已有识别引擎和语言包。缺少依赖或识别失败就报告，不声称已识别；OCR 内容标注来源，关键字和公式须核对。
- 图片、公式、表格需要核实时，用 `render-page --source <资料ID> --page <文件页码>` 生成本地原页图片，实际查看后再解释。工具不能凭提取的文字证明版面正确。

技术块仅用于存储和读取。章、节与教学单元仍按原设定区分，不能把技术切块标题冒充原书标题。

## 多资料与长资料

批量导入按文件处理，单个失败不把其他成功文件伪装成失败，也不把失败文件当可用资料。输出中逐项列出成功、未变与错误。默认单文件读取体积限额是 256 MiB，可明确调节 `--max-mb`；这不是教学时长或课程范围设定。

先查看目录，再读取当前所需范围。读取默认限制 8 个存储块和 16000 字符，响应给出 `next_block`；预算不够时分页继续，不能声称已读剩余部分。`--from-block` 恢复位置，`--limit` 和 `--max-chars` 调节本次读取预算。

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> search "充分条件" --source <主教材ID>
python <skill-dir>/scripts/learnflow.py --workspace <workspace> read --source <主教材ID> --from-block <锚点>
```

检索是本地中文/英文词项定位，不是已证明能理解全库的语义系统。命中后读取上下文并核对版本；没有命中不能断言材料中不存在该观点。按书学习优先限定主教材，不用检索相关性重排原书章节。资料数量不等于已经阅读或掌握的数量。

## 来源与版本

每份资料具有稳定 ID，每次导入范围/原文件版本具有版本 ID，正文具有块锚点。面向用户优先显示书名、章节和可核实页码，机器定位保存在记录中。引用格式可用 `[来源:资料ID@完整版本ID#块ID]`。

`catalog` 可查看历史版本和导入警告。`verify` 对比原文件 SHA-256 与快照校验值；`read` 默认拒绝静默使用变化或缺失的原文件。明确选择旧快照时用 `--allow-stale`，并告诉用户正在依据旧版。

原文件变化后，先核对目录和锚点。明确导入新版本时加 `--new-version`；旧快照保留，学习进度不会被清空、迁移或自动推进。新旧页码不直接通用。

## 进度存续

工具可保存结构化快照，字段含义以原 [learning-record.md](../templates/learning-record.md) 为准：阅读位置、掌握证据、下一入口分别记录。最小数据样例见 [progress.json](../examples/progress.json)。样例是结构演示，不代表用户真实表现。

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> progress save --topic <主题ID> --input <实际快照.json>
python <skill-dir>/scripts/learnflow.py --workspace <workspace> progress show --topic <主题ID>
python <skill-dir>/scripts/learnflow.py --workspace <workspace> progress save --topic <主题ID> --input <实际快照.json> --event pause
python <skill-dir>/scripts/learnflow.py --workspace <workspace> review --topic <主题ID> --on <用户当地日期>
```

默认 `snapshot` 只记录，不自动结束或进入下一点。只有用户明确暂停/结束时才选择 `pause`/`end`；恢复用 `resume`。保存成功后才报告位置与版本号。工具不编写用户答案、不计算掌握等级、不创建提醒。

原始证据按 ID 追加，已保存作答不可覆盖；纠正用新 ID 关联原证据。修改时可带 `--expected-revision`，防止覆盖其他操作的新进度。学习状态的校验只排除明显不一致，不能替代原能力判定协议，也不能证明输入证据真实。

出题后可在快照写入 `checkpoint`：`concept` 是知识点，`question` 是待答题原文。按书时填 `step`（1–5 的整数），课程填 `phase`（讲、练、测或评）；位置字段二选一。补讲时在 `next_step` 保留返回入口。保存时整个断点替换；不提供则保留；设为 `null` 可清除。替换或清除旧断点时，未提供新 `next_step` 就清除旧文字，避免回到已答题。旧记录仍可从 `next_step` 恢复。

证据的 `support` 记录作答方式；`correct: true/false` 记录是否达到该题的正确标准，未判定则省略。应用及以上默认用不同的 `task_id` 标明不同任务。L4 需正确迁移（`transfer: true`），L5 需正确的实际隔时复测（`delayed: true`），这两类证据均需独立作答。旧记录保留原样；读取时若有 `mastery_warnings`，将对应等级视为待复核，不拿它当已掌握的依据。可追加新证据或明确调整等级状态。

### 课程断点与正式测验

使用上面的 `progress save` 写入这些字段。按实际学习范围填，不保存未发生的进度。

| 字段 | 何时写入 | 最小示例 |
|---|---|---|
| `course` | 在课程开始、换阶段或暂停时，整体保存当前计划。保留 `checkpoint` 里的待答原题；补讲写清返回点。 | `{"goal":"能算整趟平均速度","phase":"测","remaining":["答第 2 题","看学情反馈"],"exam_id":"ride-1","return_to":"回到第 2 题"}` |
| `exam_plan` | **发题和作答之前单独保存**。同 ID 的题目、满分和评分规则不允许改；换题用新 ID。 | `{"id":"ride-1","sections":[{"title":"应用","items":[{"task_id":"Q2","question":"停顿算不算在用时内？","max_points":10,"criteria":"判断 4 分，口径和理由 6 分"}]}]}` |
| `evidence` | 收到正式作答后按原题记录；标注 `activity:"exam"`、`exam_id`、同题 `task_id`、真实作答和支持程度。看过答案也记录，不能随后当首次独立作答。 | `[{"id":"E2","exam_id":"ride-1","task_id":"Q2","activity":"exam","learner_answer":"算，因为要求的是全程用时。","support":"independent","correct":true}]` |
| `exam_grades` | 依据已锁定标准判题后保存给分，可与作答同次保存；更正给分附 `reason`，历史保留。 | `[{"exam_id":"ride-1","task_id":"Q2","evidence_id":"E2","points":10}]` |

`course` 可选 `time_plan`（约定的时间预算）和 `return_to`。不提供 `course` 时保留旧值，显式 `null` 清除。续学先看 `checkpoint`、`course` 和 `exam_resume`（未作答与未评分题号），沿原计划推进。未作答时不要把评分依据中的答案要点贴给用户。需要给学情单时用 `report --exam ride-1`。旧记录仍可用于过程反馈，未事先锁定的旧测验不补造正式分数。
