# 可选学习产物

带学收尾默认给学情反馈；其他产物按用户请求或教学需要选用。不增加新的必修阶段，不把产物数量计入能力等级。

## 可视化学情反馈

带学达到约定范围、用户暂停或明确要求反馈时，从已记录的实际作答生成离线 HTML 学情单。包含各知识点的作答条、独立答对和判定总数、证据等级、待验证项和一个下一步。它不是自动判卷，也不改变学习记录。不把页面公开、上传或发给别人。

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> report --topic <主题ID> --title "本次学情" --concept "平均速度" --output reports/session-01.html
```

- 学习开始时若可访问已保存记录，记下当时的版本号；收尾用 `--since-revision <版本号>` 只统计该版本之后新增的作答。若无法定位当次范围，报告标为主题累计，或仅用当前对话的已知记录给反馈，不能把累计说成当次。等级显示为当前记录，可能来自历史证据。
- 保存作答时用证据的 `concept` 标明知识点，名称与掌握记录一致。按实际完成内容重复给 `--concept`，让只讲解、未作答的知识点也显示为「未测」。不猜旧作答的归属。可以用 `--next` 写一个有证据支持、无答案的下次任务。
- 独立正确率只计已判定的独立作答，包含实际补测；未作答、未判定、提示后作答和看过答案后作答不进入分母。显示比例与 L0–L6 分开。正式百分制需已有评分规则和真实成绩，不把时间比例或独立正确率当作结课总分。
- 正式结课加 `--exam <已锁定测验ID>`，只汇总该场已保存的首次独立作答给分。测验所有题评分完成才给总分；未测、未判定和受提示的题不自动填零。旧版的临时评分表不再作为正式成绩来源。见 [测验记录](source-library.md#课程断点与正式测验)。
- 在实际错误或受提示的证据中写简短 `feedback`（卡在哪里）和 `retry_question`（无答案的下一道复测题），学情单会按知识点显示。使用「曾卡在哪」描述观察，不把已经纠正的问题说成现在仍不会。不在反馈里粘贴原始作答或个人信息。
- 页面可通过浏览器打印或保存 PDF。无法生成文件时直接给可读的对比表，列明「学了什么｜实际作答｜待验证｜下一步」。没作答就明说未测，不显示虚构的 0 分；只要求记录时不借机追加题目。

## 学习计划与笔记

可按需要生成费曼笔记、知识地图、学习计划、错题复盘和复习速查表。使用 [lesson-notes.md](../templates/lesson-notes.md)、[knowledge-map.md](../templates/knowledge-map.md) 或原学习记录模板的相关部分。安排仍以用户目标、材料范围和可用条件为准，不套其他版本固定的阶段时间比例。

手册与笔记供预习、查阅和复习；教学继续按当前主线推进。只把实际读取且可追溯的材料写成“依据”，AI 生成的案例和自测题明确标识，参考答案与首次独立作答分开。

## Word 手册

先准备含来源的 Markdown 正文，再导出：

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> export-docx --input <已准备笔记.md> --output outputs/学习手册.docx
```

支持标题、普通段落、简单加粗、行内代码、列表、代码块和简单表格。不把数学公式排版、复杂图片或复杂表格的完整重建作为已实现能力。导出后核对正文及实际版面；生成器成功不等于内容或排版已完全正确。

## 离线交互页

页面无需服务器或外部 CDN，不上传学习材料。支持以下数据类型：

| kind | 数据数组 | 适合的学习目标 |
|---|---|---|
| concept-map | nodes: id/title/body；edges: from/to/label | 查看概念关系、依赖与边界 |
| process | steps: title/body | 按步骤观察过程 |
| compare | items: title/body | 并列比较条件、方法或案例 |
| flashcards | cards: front/back | 主动提取后翻看解释 |
| quiz | questions: prompt/answer；可附 explanation | 作答后再打开参考答案的自测 |
| drag-order | items: id/label；order: 正确顺序的 ID 数组 | 拖拽排列步骤，用理由解释顺序 |

顶层需 title，可附 intro、check；各项可附 source_refs 来源文字列表。完整演示见 [visual-examples.json](../examples/visual-examples.json)。

排序页需 2–12 张唯一 ID 的卡片，`items` 初始顺序要打乱；触屏或键盘可以用上移／下移。「复制本次作答」带上排序和是否查看过检查，用户粘贴回对话并补理由；剪贴板不可用会显示可手动复制的文字。支持浏览器本地存储时，刷新能恢复草稿和检查状态。页面不上传、不自动提交成绩；看到核对反馈后的重试不能当作首次独立作答。它用于练习，不用于保密的正式测验。

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> visual --input <本次学习页.json> --output visuals/当前知识点.html
```

根据当前学习目标选择一种合适媒介，文字已足够就继续文字教学。交互后的解释/迁移问题按原教学需要安排，不为完成页面而追加测验。自测页先隐藏参考答案，也保留“直接看答案”的选择；页内切题时保留当前作答草稿，关闭或刷新页面不会保存这些草稿。交互页不自动评判自由文本答案、不更新等级或进度；看过答案后若纳入学习记录，标明答案已暴露。

## 成果封装

只有用户明确要求把原创学习成果整理为课程、知识库或另一个 Skill 时，才进入此分支。沿用现有学习结果，不默认从目标、诊断等阶段重新走一遍，也不依赖一串额外技能才能完成。

准备可公开复用的成果文件，显式列入清单；不直接把原资料目录、学习档案、成绩、身份或聊天记录打进去。清单格式见 [product-manifest.json](../examples/product-manifest.json)。

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> product --manifest <成果清单.json> --output products/成果包.zip
```

kind 为 knowledge-pack 时按清单封装课程/笔记；kind 为 skill 时需包含实际完成的 SKILL.md、合法 name/description 和所有本地引用。目标成果名不改变本 LearnFlow 技能名和用户原设置。产物 ZIP 只保存在本地；发布、分享和售卖属于另外明确指定的动作，不在普通学习收尾时自动执行。

## 复习队列

复习依旧采用原 [review.md](review.md) 的规则。工具仅按记录中的建议/约定日期列出到期项，不强制补完积压，不自动安排固定打卡，也不把建议日期写成已创建提醒。
