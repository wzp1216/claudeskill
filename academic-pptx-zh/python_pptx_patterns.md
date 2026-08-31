# python-pptx 实现模式（学术演示文稿）

本文件给出用 **python-pptx** 生成学术演示文稿的代码模板，配合 `SKILL.md`（结构规范）与 `content_guidelines.md`（内容规范）使用。

**运行环境（本机）**：`/home/wzp/claudewzp/venv-doc/bin/python`（已装 python-pptx 1.0.2）。

---

## 0. 公共部分

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.oxml.ns import qn

# ---------- 全局常量（同 SKILL.md 设计标准） ----------
NAVY = RGBColor(0x1F, 0x4E, 0x79)      # 深藏青：标题
BLUE = RGBColor(0x2E, 0x75, 0xB6)      # 中蓝：强调/小节标题
BODY = RGBColor(0x2D, 0x2D, 0x2D)      # 近黑：正文
MUTED = RGBColor(0x77, 0x77, 0x77)     # 灰：页内引用、图注
RULE = RGBColor(0xCC, 0xCC, 0xCC)      # 浅灰：分隔线
HIGHLIGHT = RGBColor(0xFF, 0xF2, 0xCC) # 浅黄：关键发现批注框
FONT = "微软雅黑"                        # 通篇一种字体

def set_font(run, name=FONT):
    """同时设置西文与东亚字体——中文必须设置 a:ea，否则回退默认字体。"""
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn('a:ea'))
    if ea is None:
        ea = rPr.makeelement(qn('a:ea'), {})
        rPr.append(ea)
    ea.set('typeface', name)

def new_deck():
    """16:9 空白演示文稿。"""
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs

def add_textbox(slide, x, y, w, h, lines, size=20, bold=False, color=BODY,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    """lines: 字符串（\n 分行）或 [ (文本, 加粗) ] 列表。"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    if isinstance(lines, str):
        lines = [(ln, bold) for ln in lines.split("\n")]
    for i, (text, b) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = b
        run.font.color.rgb = color
        set_font(run)
    return tb

def add_notes(slide, text):
    """演讲者备注（不进正文）。"""
    slide.notes_slide.notes_text_frame.text = text

def add_rule(slide, x, y, w, color=RULE, h=0.03):
    """标题下细分隔线。"""
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid(); shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    return shp
```

---

## 1. 标题页（白底或深色底均可，默认深色底与结论页呼应）

```python
prs = new_deck()
slide = prs.slides.add_slide(prs.slide_layouts[6])          # 空白版式
bg = slide.background.fill
bg.solid(); bg.fore_color.rgb = NAVY

add_textbox(slide, 0.9, 2.0, 11.5, 2.0,
            "早期干预对 35 岁收入的长期影响：来自随机试验的证据",
            size=36, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
add_textbox(slide, 0.9, 4.3, 11.5, 0.5,
            "2026 年职业教育数字化年会 · 2026 年 5 月", size=16, color=RGBColor(0xA0, 0xBB, 0xDD))
add_textbox(slide, 0.9, 4.9, 11.5, 0.6,
            "万志平¹ · 李四²\n¹ 浙江工业职业技术学院   ² 合作单位", size=15, color=RGBColor(0xCA, 0xDC, 0xFC))
```

---

## 2. 动机/背景页（标题 + 正文要点，用自带项目符号的版式）

```python
slide = prs.slides.add_slide(prs.slide_layouts[1])          # 标题+内容版式（自带项目符号）
slide.shapes.title.text = "短期效果已充分证实，但长期持续性证据稀缺"   # 行动标题！
tf = slide.placeholders[1].text_frame
tf.word_wrap = True
items = [
    ("短期效果扎实：", True, " 元分析确认 5–8 岁阶段效应为正（张三等，2013）。"),
    ("长期证据稀缺：", True, " 仅有 3 项随机试验追踪到 25 岁以后，且均不覆盖低收入国家。"),
    ("机制未解：", True, " 认知 vs 非认知通道仍有争议（见附录 A）。"),
]
for i, (lead, b, rest) in enumerate(items):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    r1 = p.add_run(); r1.text = lead; r1.font.bold = True
    r2 = p.add_run(); r2.text = rest
    for r in (r1, r2):
        r.font.size = Pt(20); set_font(r)
# 页内引用（页底灰色小字）
add_textbox(slide, 0.5, 6.9, 12.3, 0.4, "张三等（2013），《教育研究》；李四（2007）",
            size=13, color=MUTED)
```

---

## 3. 研究问题页（独立成页 + 圆角高亮框）

```python
slide = prs.slides.add_slide(prs.slide_layouts[6])
slide.shapes.title = None if False else slide.shapes.title  # 空白版式无标题
add_textbox(slide, 0.5, 0.3, 12.3, 0.8,
            "本文研究问题：早期干预效应能否持续到 35 岁，通过何种通道实现？",
            size=26, bold=True, color=NAVY)
add_rule(slide, 0.5, 1.15, 12.3)

from pptx.enum.shapes import MSO_SHAPE
box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(2.0), Inches(1.6),
                             Inches(9.3), Inches(2.2))
box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xEB, 0xF3, 0xFA)
box.line.color.rgb = BLUE; box.line.width = Pt(1.5)
add_textbox(slide, 2.3, 1.75, 8.7, 1.9,
            "8 岁时的认知与社会情感技能效应，能否持续到 35 岁的收入、健康与犯罪结果？\n"
            "通道是技能本身，还是受教育程度？",
            size=19, color=NAVY, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
add_textbox(slide, 0.5, 4.2, 12.3, 1.0,
            [("贡献：", True), ("首个将 3–5 岁随机队列追踪到 35 岁的研究；行政收入与健康记录关联原始试验数据。", False)],
            size=20)
```

---

## 4. 方法页（双栏：设计 | 关键变量）

```python
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_textbox(slide, 0.5, 0.3, 12.3, 0.9,
            "断点回归利用陡峭的家庭收入门槛——门槛附近处理近似随机", size=26, bold=True, color=NAVY)
add_rule(slide, 0.5, 1.25, 12.3)

add_textbox(slide, 0.5, 1.5, 6.0, 0.4, "设计", size=22, bold=True, color=BLUE)
add_textbox(slide, 0.5, 2.0, 6.0, 3.0, [
    ("队列：", True), ("1985–90 年出生，三个县共 2400 名儿童。", False),
    ("分组：", True), ("3 岁家庭收入 <185% FPL 即符合资格（N=1150）。", False),
    ("随访：", True), ("5/8/18/25/35 岁，关联行政记录。", False),
], size=20)

add_textbox(slide, 7.0, 1.5, 6.0, 0.4, "关键结果", size=22, bold=True, color=BLUE)
add_textbox(slide, 7.0, 2.0, 6.0, 3.0, [
    ("主要：", True), ("35 岁收入（对数）、就业。", False),
    ("次要：", True), ("健康指数、犯罪记录。", False),
    ("机制：", True), ("8 岁认知得分、受教育年限。", False),
], size=20)

add_textbox(slide, 0.5, 6.9, 12.3, 0.4,
            "完整识别假设与稳健性检验 → 附录 B", size=13, color=MUTED)
```

---

## 5. 结果页（图左文右，图上直接标注关键发现）

```python
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_textbox(slide, 0.5, 0.3, 12.3, 0.85,
            "35 岁收入效应 18%，最低收入组（Q1）最大", size=26, bold=True, color=NAVY)
add_rule(slide, 0.5, 1.2, 12.3)

# ---- 左：图表 ----
chart_data = CategoryChartData()
chart_data.categories = ["Q1（最低）", "Q2", "Q3", "Q4（最高）"]
chart_data.add_series("处理效应 (%)", (28, 22, 15, 8))
gframe = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                                Inches(0.5), Inches(1.4), Inches(7.2), Inches(4.8), chart_data)
chart = gframe.chart
chart.has_legend = False
plot = chart.plots[0]
plot.gap_width = 60
ser = plot.series[0]
ser.format.fill.solid(); ser.format.fill.fore_color.rgb = BLUE

# ---- 图上关键发现批注（浅黄框）----
box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.7), Inches(1.5),
                             Inches(1.9), Inches(0.55))
box.fill.solid(); box.fill.fore_color.rgb = HIGHLIGHT
box.line.color.rgb = RGBColor(0xE6, 0xC8, 0x00)
add_textbox(slide, 0.7, 1.5, 1.9, 0.55, "↑ Q1 达 28%", size=14, bold=True,
            color=RGBColor(0x7A, 0x52, 0x00), align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# ---- 右：解读 ----
add_textbox(slide, 8.2, 1.4, 4.6, 0.4, "要点", size=22, bold=True, color=BLUE)
add_textbox(slide, 8.2, 1.9, 4.6, 3.0, [
    ("平均效应 18%（p < 0.001）", False),
    ("异质性：Q1 效应是 Q4 的 3.5 倍", False),
    ("合并估计 95% CI = [14%, 22%]", False),
], size=19)

# ---- 页内引用 ----
add_textbox(slide, 0.5, 6.9, 12.3, 0.4,
            "来源：社会保障局行政收入记录（2024 年获取）", size=13, color=MUTED)
```

---

## 6. 结论页（深色底，Q&A 期间停留在屏幕；末尾附联系方式）

```python
slide = prs.slides.add_slide(prs.slide_layouts[6])
slide.background.fill.solid(); slide.background.fill.fore_color.rgb = NAVY

add_textbox(slide, 0.5, 0.25, 12.3, 0.5, "结论", size=20, color=RGBColor(0xA0, 0xBB, 0xDD))
add_rule(slide, 0.5, 0.75, 12.3, color=BLUE)
add_textbox(slide, 0.5, 1.0, 12.3, 4.0, [
    ("1. 早期效应具有持续性：", True), ("处理后 30 年，35 岁时仍可检出显著收入溢价。", False),
    ("2. 弱势群体获益最大：", True), ("Q1 溢价（28%）是 Q4（8%）的 3.5 倍。", False),
    ("3. 通道是认知而非教育：", True), ("与技能互补模型一致。", False),
], size=21, color=RGBColor(0xFF, 0xFF, 0xFF))
add_textbox(slide, 0.5, 6.4, 12.3, 0.5,
            "wzp@zjipc.edu.cn  |  工作论文：bit.ly/wzp2026", size=14, color=RGBColor(0xA0, 0xBB, 0xDD))
```

---

## 7. 参考文献页与附录页

```python
# 参考文献页（浅色底）
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_textbox(slide, 0.5, 0.3, 12.3, 0.6, "参考文献", size=26, bold=True, color=NAVY)
add_rule(slide, 0.5, 1.0, 12.3)
refs = [
    "张三，李四（2013）．早期干预的长期回报．《教育研究》，34(2)，31–47．",
    "王五（2007）．技能形成的技术．《经济学（季刊）》．",
]
add_textbox(slide, 0.5, 1.2, 12.3, 5.5, "\n".join(refs), size=15, color=BODY)

# 附录页（明确标注）
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_textbox(slide, 0.5, 0.15, 12.3, 0.4, "附录 B — 稳健性检验", size=14, color=MUTED)
add_textbox(slide, 0.5, 0.6, 12.3, 0.8,
            "效应在不同带宽选择与多项式设定下保持稳定", size=24, bold=True, color=NAVY)
```

---

## 8. 生成、转换与 QA

```bash
# 1) 生成
/home/wzp/claudewzp/venv-doc/bin/python 生成脚本.py

# 2) 文本 QA（抽取全部文字核对标题、引用、乱码）
/home/wzp/claudewzp/venv-doc/bin/markitdown 输出.pptx

# 3) 转 PDF（python 驱动 WPS，替代 LibreOffice；需图形会话）
python /home/wzp/.claude/skills/academic-pptx-zh/convert_to_pdf.py 输出.pptx 输出.pdf

# 4) PDF 转图目检（Poppler）
pdftoppm -png -r 96 输出.pdf 页面预览

# 5) 生成后用官方 pptx 技能做结构校验（如已装）
python ~/.claude/skills/pptx/scripts/office/validate.py 输出.pptx
```

---

## 快速检查（交付前）

```
□ 每页内容页：行动标题（完整结论句，陈述发现/主张）
□ 幽灵演示测试：只看标题能串起完整论证
□ 结果页：一页一图，关键发现在图上直接标注
□ 借用图表/数据：页内引用；参考文献页完整
□ 结论页为最后一个正文页，Q&A 时停留屏幕
□ 末页/结论页含联系方式
□ 正文 ≥ 20pt（中文），标题 24–28pt
□ 通篇一种字体（微软雅黑），≤3 种颜色
□ 附录页已标注，含预建 Q&A 答案页
```
