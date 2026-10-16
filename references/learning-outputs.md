# 可选学习产物

仅在用户需要产物，或当前解释确实需要相应媒介时使用。不增加新的必修阶段，不把产物数量计入能力等级。

## 学习计划与笔记

可按需要生成费曼笔记、知识地图、学习计划、错题复盘和复习速查表。使用 [lesson-notes.md](../templates/lesson-notes.md)、[knowledge-map.md](../templates/knowledge-map.md) 或原学习记录模板的相关部分。安排仍以用户目标、材料范围和可用条件为准，不套其他版本固定的阶段时间比例。

手册与笔记是供预习、查阅和复习的资料；正式教学仍按原闭环执行。只把实际读取且可追溯的材料写成“依据”，AI 生成的案例和自测题明确标识，参考答案与首次独立作答分开。

## Word 手册

先准备含来源的 Markdown 正文，再导出：

```sh
python <skill-dir>/scripts/learnflow.py --workspace <workspace> export-docx --input <已准备笔记.md> --output outputs/学习手册.docx
```

支持标题、普通段落、简单加粗、行内代码、列表、代码块和简单表格。不把数学公式排版、复杂图片或复杂表格的完整重建作为已实现能力。导出后核对正文及实际版面；生成器成功不等于内容或排版已完全正确。

## 离线交互页

页面无需服务器或外部 CDN，不上传学习材料。支持五种数据类型：

| kind | 数据数组 | 适合的学习目标 |
|---|---|---|
| concept-map | nodes: id/title/body；edges: from/to/label | 查看概念关系、依赖与边界 |
| process | steps: title/body | 按步骤观察过程 |
| compare | items: title/body | 并列比较条件、方法或案例 |
| flashcards | cards: front/back | 主动提取后翻看解释 |
| quiz | questions: prompt/answer；可附 explanation | 作答后再打开参考答案的自测 |

顶层需 title，可附 intro、check；各项可附 source_refs 来源文字列表。完整演示见 [visual-examples.json](../examples/visual-examples.json)。

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
