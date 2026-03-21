const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle,
  WidthType, ShadingType, PageNumber, PageBreak, LevelFormat,
  TabStopType, TabStopPosition
} = require("docx");

// ── Colors ──
const ACCENT = "1B6B4A";
const DARK = "1A1A2E";
const SUBTLE = "6B7280";
const LIGHT_BG = "F0F7F4";
const TABLE_HEAD = "1B6B4A";
const TABLE_HEAD_TEXT = "FFFFFF";
const BORDER_COLOR = "D1D5DB";

const border = { style: BorderStyle.SINGLE, size: 1, color: BORDER_COLOR };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 100, bottom: 100, left: 140, right: 140 };

// ── Helper functions ──
function heading1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    children: [new TextRun({ text, bold: true, size: 36, font: "Arial", color: DARK })],
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160 },
    children: [new TextRun({ text, bold: true, size: 28, font: "Arial", color: ACCENT })],
  });
}

function body(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 160, line: 340 },
    children: [new TextRun({ text, size: 22, font: "Arial", color: opts.color || "333333", ...opts })],
  });
}

function bodyRuns(runs) {
  return new Paragraph({
    spacing: { after: 160, line: 340 },
    children: runs.map(r => new TextRun({ size: 22, font: "Arial", color: "333333", ...r })),
  });
}

function calloutBox(text) {
  return new Paragraph({
    spacing: { before: 200, after: 200 },
    indent: { left: 360, right: 360 },
    border: { left: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 8 } },
    shading: { fill: LIGHT_BG, type: ShadingType.CLEAR },
    children: [new TextRun({ text, size: 22, font: "Arial", color: DARK, italics: true })],
  });
}

function headerCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: TABLE_HEAD, type: ShadingType.CLEAR },
    margins: cellMargins,
    verticalAlign: "center",
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text, bold: true, size: 20, font: "Arial", color: TABLE_HEAD_TEXT })],
    })],
  });
}

function dataCell(text, width, opts = {}) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: opts.shading ? { fill: opts.shading, type: ShadingType.CLEAR } : undefined,
    margins: cellMargins,
    children: [new Paragraph({
      alignment: opts.center ? AlignmentType.CENTER : AlignmentType.LEFT,
      children: [new TextRun({ text, size: 20, font: "Arial", color: "333333" })],
    })],
  });
}

// ── Build document ──
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: DARK },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: ACCENT },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "flow-steps",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
    ],
  },
  sections: [
    // ── COVER PAGE ──
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      children: [
        new Paragraph({ spacing: { before: 3600 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
          children: [new TextRun({ text: "PolyArb", size: 72, bold: true, font: "Arial", color: ACCENT })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 120 },
          children: [new TextRun({ text: "\u9884\u6D4B\u5E02\u573A\u7EC4\u5408\u5957\u5229\u7CFB\u7EDF", size: 36, font: "Arial", color: DARK })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 600 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 3, color: ACCENT, space: 12 } },
          children: [new TextRun({ text: "\u901A\u4FD7\u7248\u6280\u672F\u8BF4\u660E", size: 28, font: "Arial", color: SUBTLE })],
        }),
        new Paragraph({ spacing: { before: 400 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "\u672C\u6587\u6863\u7528\u65E5\u5E38\u8BED\u8A00\u89E3\u91CA PolyArb \u7CFB\u7EDF\u7684\u5DE5\u4F5C\u539F\u7406\uFF0C", size: 22, font: "Arial", color: SUBTLE })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "\u4E0D\u9700\u8981\u4EFB\u4F55\u91D1\u878D\u6216\u7F16\u7A0B\u80CC\u666F\u3002", size: 22, font: "Arial", color: SUBTLE })],
        }),
        new Paragraph({ spacing: { before: 1200 } }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "2026\u5E743\u6708", size: 22, font: "Arial", color: SUBTLE })],
        }),
      ],
    },

    // ── MAIN CONTENT ──
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            alignment: AlignmentType.RIGHT,
            children: [new TextRun({ text: "PolyArb \u00B7 \u901A\u4FD7\u6280\u672F\u8BF4\u660E", size: 18, font: "Arial", color: SUBTLE, italics: true })],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: "\u2014 ", size: 18, font: "Arial", color: SUBTLE }),
              new TextRun({ children: [PageNumber.CURRENT], size: 18, font: "Arial", color: SUBTLE }),
              new TextRun({ text: " \u2014", size: 18, font: "Arial", color: SUBTLE }),
            ],
          })],
        }),
      },
      children: [
        // ─── Section 1: 什么是预测市场 ───
        heading1("\u4E00\u3001\u4EC0\u4E48\u662F\u9884\u6D4B\u5E02\u573A\uFF1F"),

        body("\u60F3\u8C61\u4F60\u548C\u670B\u53CB\u4E4B\u95F4\u6253\u8D4C\uFF1A\u201C\u660E\u5929\u4F1A\u4E0B\u96E8\u5417\uFF1F\u201D\u4F60\u4EEC\u5404\u4E70\u4E00\u5F20\u201C\u4F1A\u201D\u6216\u8005\u201C\u4E0D\u4F1A\u201D\u7684\u5F69\u7968\uFF0C\u7B49\u7ED3\u679C\u63ED\u6653\u540E\uFF0C\u731C\u5BF9\u7684\u4EBA\u62FF\u94B1\u3002"),

        body("\u9884\u6D4B\u5E02\u573A\u5C31\u662F\u8FD9\u4E2A\u6982\u5FF5\u7684\u7F51\u7EDC\u5347\u7EA7\u7248\u3002Polymarket \u662F\u76EE\u524D\u6700\u5927\u7684\u9884\u6D4B\u5E02\u573A\u5E73\u53F0\uFF0C\u4E0A\u9762\u6709\u6570\u4E07\u4E2A\u5E02\u573A\uFF0C\u8986\u76D6\u4F53\u80B2\u3001\u653F\u6CBB\u3001\u52A0\u5BC6\u8D27\u5E01\u3001\u5929\u6C14\u7B49\u5404\u79CD\u8BDD\u9898\u3002\u6BCF\u4E2A\u5E02\u573A\u5C31\u662F\u4E00\u4E2A\u662F\u975E\u9898\uFF0C\u4EF7\u683C\u53CD\u6620\u4E86\u5927\u5BB6\u8BA4\u4E3A\u8BE5\u4E8B\u4EF6\u53D1\u751F\u7684\u6982\u7387\u3002"),

        calloutBox("\u4E3E\u4E2A\u4F8B\u5B50\uFF1A\u5982\u679C\u201CFC\u4E1C\u4EAC vs FC\u753A\u7530\u6CFD\u5C14\u7EF4\u4E9A\uFF1A\u603B\u8FDB\u7403\u6570 > 1.5\u201D\u7684\u4EF7\u683C\u662F 0.65\uFF0C\u610F\u5473\u7740\u5E02\u573A\u8BA4\u4E3A\u8FD9\u573A\u6BD4\u8D5B\u8FDB 2 \u4E2A\u6216\u4EE5\u4E0A\u7403\u7684\u6982\u7387\u662F 65%\u3002"),

        // ─── Section 2: 什么是套利 ───
        heading1("\u4E8C\u3001\u4EC0\u4E48\u662F\u5957\u5229\uFF1F\u4E3A\u4EC0\u4E48\u80FD\u8D5A\u94B1\uFF1F"),

        body("\u5047\u8BBE\u4F60\u53D1\u73B0\u4E24\u5BB6\u5546\u5E97\u5356\u540C\u4E00\u6B3E\u624B\u673A\uFF1AA \u5E97\u5356 3000 \u5143\uFF0CB \u5E97\u5356 3500 \u5143\u3002\u4F60\u53EF\u4EE5\u5728 A \u5E97\u4E70\u5165\uFF0C\u7ACB\u523B\u62FF\u5230 B \u5E97\u5356\u51FA\uFF0C\u51C0\u8D5A 500 \u5143\u3002\u8FD9\u5C31\u662F\u5957\u5229\u2014\u2014\u5229\u7528\u4EF7\u683C\u5DEE\u5F02\u65E0\u98CE\u9669\u83B7\u5229\u3002"),

        body("\u5728\u9884\u6D4B\u5E02\u573A\u91CC\uFF0C\u5957\u5229\u66F4\u5DE7\u5999\u3002\u5F88\u591A\u5E02\u573A\u4E4B\u95F4\u5B58\u5728\u903B\u8F91\u5173\u7CFB\uFF0C\u800C\u5B83\u4EEC\u7684\u4EF7\u683C\u5374\u6CA1\u6709\u5B8C\u7F8E\u53CD\u6620\u8FD9\u79CD\u5173\u7CFB\u3002\u8FD9\u5C31\u662F PolyArb \u53D1\u73B0\u673A\u4F1A\u7684\u5730\u65B9\u3002"),

        calloutBox("\u6BD4\u5982\u201C\u603B\u8FDB\u7403 > 1.5\u201D\u548C\u201C\u603B\u8FDB\u7403 > 2.5\u201D\u8FD9\u4E24\u4E2A\u5E02\u573A\uFF1A\u5982\u679C\u8FDB\u7403\u8D85\u8FC7 2.5\uFF0C\u90A3\u5FC5\u7136\u8D85\u8FC7 1.5\u3002\u6240\u4EE5\u201C> 2.5\u201D\u7684\u4EF7\u683C\u4E0D\u53EF\u80FD\u6BD4\u201C> 1.5\u201D\u8D35\u3002\u5982\u679C\u5E02\u573A\u5B9A\u4EF7\u8FDD\u53CD\u4E86\u8FD9\u4E2A\u903B\u8F91\uFF0C\u5C31\u5B58\u5728\u5957\u5229\u673A\u4F1A\u3002"),

        // ─── Section 3: PolyArb 做什么 ───
        heading1("\u4E09\u3001PolyArb \u505A\u4EC0\u4E48\uFF1F"),

        body("PolyArb \u662F\u4E00\u4E2A\u81EA\u52A8\u5316\u7CFB\u7EDF\uFF0C\u5B83\u76D1\u63A7\u8FD1 38,000 \u4E2A Polymarket \u5E02\u573A\uFF0C\u81EA\u52A8\u627E\u51FA\u5B9A\u4EF7\u4E0D\u5408\u7406\u7684\u5E02\u573A\u5BF9\uFF0C\u8BA1\u7B97\u6700\u4F18\u4EA4\u6613\u65B9\u6848\uFF0C\u7136\u540E\u7528\u865A\u62DF\u8D44\u91D1\u6A21\u62DF\u4EA4\u6613\u3002\u5B83\u4E0D\u4F1A\u52A8\u7528\u4EFB\u4F55\u771F\u5B9E\u7684\u94B1\u2014\u2014\u5B8C\u5168\u662F\u201C\u7EB8\u4E0A\u4EA4\u6613\u201D\uFF0C\u76EE\u7684\u662F\u9A8C\u8BC1\u7B56\u7565\u662F\u5426\u771F\u7684\u6709\u6548\u3002"),

        body("\u7CFB\u7EDF\u90E8\u7F72\u5728\u672C\u5730\u670D\u52A1\u5668\uFF08NAS\uFF0C192.168.5.100\uFF09\u4E0A\uFF0C\u901A\u8FC7 Docker \u5BB9\u5668\u5316\u8FD0\u884C\uFF0C\u5305\u542B 6 \u4E2A\u72EC\u7ACB\u670D\u52A1\u3002"),

        // ─── Section 4: 系统组件 ───
        heading1("\u56DB\u3001\u7CFB\u7EDF\u7EC4\u4EF6\uFF1A\u5982\u4F55\u5DE5\u4F5C\uFF1F"),

        heading2("4.1 \u6570\u636E\u91C7\u96C6\u5668\uFF08Ingestor\uFF09"),
        body("\u6570\u636E\u91C7\u96C6\u5668\u5C31\u50CF\u4E00\u4E2A\u52E4\u52B3\u7684\u4FE1\u606F\u5458\uFF0C\u6BCF 30 \u79D2\u4ECE Polymarket \u7684\u63A5\u53E3\u83B7\u53D6\u6240\u6709\u5E02\u573A\u7684\u6700\u65B0\u6570\u636E\u3002"),

        new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 80, line: 340 },
          children: [new TextRun({ text: "\u4ECE Gamma API \u83B7\u53D6\u5E02\u573A\u5143\u6570\u636E\uFF08\u95EE\u9898\u3001\u63CF\u8FF0\u3001\u6D41\u52A8\u6027\uFF09", size: 22, font: "Arial", color: "333333" })],
        }),
        new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 80, line: 340 },
          children: [new TextRun({ text: "\u4ECE CLOB API \u83B7\u53D6\u4EF7\u683C\u5FEB\u7167\uFF08\u524D 100 \u4E2A\u6700\u6D3B\u8DC3\u7684\u5E02\u573A + \u5DF2\u914D\u5BF9\u7684\u5E02\u573A\uFF09", size: 22, font: "Arial", color: "333333" })],
        }),
        new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 160, line: 340 },
          children: [new TextRun({ text: "\u7528 OpenAI \u5C06\u6BCF\u4E2A\u5E02\u573A\u7684\u95EE\u9898\u8F6C\u6362\u4E3A 384 \u7EF4\u5411\u91CF\uFF08\u50CF\u7ED9\u6BCF\u4E2A\u5E02\u573A\u7F16\u4E00\u4E2A\u201C\u8BED\u4E49\u6307\u7EB9\u201D\uFF09", size: 22, font: "Arial", color: "333333" })],
        }),

        calloutBox("\u201C\u8BED\u4E49\u6307\u7EB9\u201D\u7C7B\u6BD4\uFF1A\u5C31\u50CF\u4EBA\u7684\u6307\u7EB9\u53EF\u4EE5\u8BC6\u522B\u8EAB\u4EFD\uFF0C\u6BCF\u4E2A\u5E02\u573A\u7684\u5411\u91CF\u7F16\u7801\u4E86\u5B83\u7684\u201C\u542B\u4E49\u201D\u3002\u4E24\u4E2A\u542B\u4E49\u76F8\u8FD1\u7684\u5E02\u573A\uFF0C\u5B83\u4EEC\u7684\u6307\u7EB9\u4E5F\u4F1A\u5F88\u76F8\u4F3C\u3002"),

        heading2("4.2 \u68C0\u6D4B\u5668\uFF08Detector\uFF09"),
        body("\u68C0\u6D4B\u5668\u7684\u5DE5\u4F5C\u662F\u627E\u51FA\u54EA\u4E9B\u5E02\u573A\u4E4B\u95F4\u5B58\u5728\u903B\u8F91\u5173\u7CFB\u3002\u5B83\u5206\u4E24\u6B65\u5DE5\u4F5C\uFF1A"),

        bodyRuns([
          { text: "\u7B2C\u4E00\u6B65\uFF1A\u76F8\u4F3C\u5EA6\u641C\u7D22\u3002", bold: true },
          { text: "\u4ECE 38,000 \u4E2A\u5E02\u573A\u4E2D\uFF0C\u968F\u673A\u62BD\u53D6\u4E00\u6279\u5E02\u573A\uFF0C\u7528 pgvector \u6570\u636E\u5E93\u7684 KNN \u641C\u7D22\u627E\u5230\u5B83\u4EEC\u7684\u201C\u6700\u8FD1\u90BB\u5C45\u201D\u2014\u2014\u5373\u542B\u4E49\u6700\u76F8\u4F3C\u7684\u5E02\u573A\u3002\u53EA\u4FDD\u7559\u76F8\u4F3C\u5EA6\u8D85\u8FC7 82% \u7684\u914D\u5BF9\u3002" },
        ]),

        bodyRuns([
          { text: "\u7B2C\u4E8C\u6B65\uFF1A\u5173\u7CFB\u5206\u7C7B\u3002", bold: true },
          { text: "\u5BF9\u4E8E\u627E\u5230\u7684\u914D\u5BF9\uFF0C\u5148\u7528\u7B80\u5355\u89C4\u5219\u5224\u65AD\uFF08\u6BD4\u5982\u662F\u5426\u5C5E\u4E8E\u540C\u4E00\u4E8B\u4EF6\uFF09\uFF0C\u5982\u679C\u89C4\u5219\u5224\u65AD\u4E0D\u4E86\uFF0C\u5C31\u8BA9 GPT-4o-mini \u6765\u5206\u6790\u5B83\u4EEC\u7684\u903B\u8F91\u5173\u7CFB\u3002" },
        ]),

        // Dependency type table
        new Paragraph({ spacing: { before: 200, after: 100 }, children: [new TextRun({ text: "\u56DB\u79CD\u5173\u7CFB\u7C7B\u578B\uFF1A", bold: true, size: 22, font: "Arial", color: DARK })] }),

        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [1800, 2400, 3960, 1200],
          rows: [
            new TableRow({ children: [
              headerCell("\u5173\u7CFB\u7C7B\u578B", 1800),
              headerCell("\u901A\u4FD7\u89E3\u91CA", 2400),
              headerCell("\u4F8B\u5B50", 3960),
              headerCell("\u7EA6\u675F", 1200),
            ]}),
            new TableRow({ children: [
              dataCell("\u84B8\u6C7D\u5173\u7CFB\nImplication", 1800, { shading: "F9FAFB" }),
              dataCell("A \u53D1\u751F\u5219 B \u5FC5\u7136\u53D1\u751F", 2400, { shading: "F9FAFB" }),
              dataCell("\u8FDB\u7403 > 2.5 \u21D2 \u8FDB\u7403 > 1.5", 3960, { shading: "F9FAFB" }),
              dataCell("P(A)\u2264P(B)", 1200, { shading: "F9FAFB", center: true }),
            ]}),
            new TableRow({ children: [
              dataCell("\u4E92\u65A5\u5173\u7CFB\nMutual Exclusion", 1800),
              dataCell("A \u548C B \u4E0D\u80FD\u540C\u65F6\u4E3A\u771F", 2400),
              dataCell("BNB 8:10\u6DA8 vs BNB 8:50\u6DA8", 3960),
              dataCell("P(A)+P(B)\u22641", 1200, { center: true }),
            ]}),
            new TableRow({ children: [
              dataCell("\u5206\u5272\u5173\u7CFB\nPartition", 1800, { shading: "F9FAFB" }),
              dataCell("\u540C\u4E00\u4E8B\u4EF6\u7684\u4E0D\u540C\u7ED3\u679C", 2400, { shading: "F9FAFB" }),
              dataCell("\u9009\u4E3E\u4E2D A/B/C \u4E09\u4E2A\u5019\u9009\u4EBA", 3960, { shading: "F9FAFB" }),
              dataCell("\u603B\u548C = 1", 1200, { shading: "F9FAFB", center: true }),
            ]}),
            new TableRow({ children: [
              dataCell("\u6761\u4EF6\u5173\u7CFB\nConditional", 1800),
              dataCell("A \u7684\u6982\u7387\u53D7 B \u5F71\u54CD", 2400),
              dataCell("O/U 1.5 vs \u53CC\u65B9\u8FDB\u7403", 3960),
              dataCell("\u6982\u7387\u7EA6\u675F", 1200, { center: true }),
            ]}),
          ],
        }),

        new Paragraph({ spacing: { after: 100 } }),

        heading2("4.3 \u4F18\u5316\u5668\uFF08Optimizer\uFF09"),
        body("\u68C0\u6D4B\u5668\u627E\u5230\u4E86\u53EF\u7591\u7684\u5E02\u573A\u5BF9\uFF0C\u4F46\u8FD8\u4E0D\u77E5\u9053\u5177\u4F53\u600E\u4E48\u4EA4\u6613\u624D\u80FD\u8D5A\u94B1\u3002\u8FD9\u5C31\u662F\u4F18\u5316\u5668\u7684\u5DE5\u4F5C\u3002"),

        body("\u4F18\u5316\u5668\u4F7F\u7528\u4E00\u4E2A\u53EB\u505A Frank-Wolfe \u7684\u7B97\u6CD5\u3002\u7B80\u5355\u6765\u8BF4\uFF1A"),

        calloutBox("\u60F3\u8C61\u4F60\u7AD9\u5728\u5C71\u4E0A\uFF08\u5E02\u573A\u4EF7\u683C\uFF09\uFF0C\u60F3\u8D70\u5230\u8C37\u5E95\uFF08\u5408\u7406\u4EF7\u683C\uFF09\u3002Frank-Wolfe \u7B97\u6CD5\u5C31\u662F\u6BCF\u6B21\u627E\u5230\u6700\u9661\u7684\u4E0B\u5761\u65B9\u5411\uFF0C\u8D70\u4E00\u5C0F\u6B65\uFF0C\u53CD\u590D\u591A\u6B21\u76F4\u5230\u5230\u8FBE\u8C37\u5E95\u3002\u5C71\u9876\u548C\u8C37\u5E95\u4E4B\u95F4\u7684\u201C\u9AD8\u5EA6\u5DEE\u201D\u5C31\u662F\u53EF\u4EE5\u8D5A\u7684\u5229\u6DA6\u3002"),

        bodyRuns([
          { text: "\u5177\u4F53\u6765\u8BF4\uFF0C\u4F18\u5316\u5668\u4F1A\uFF1A" },
        ]),
        new Paragraph({
          numbering: { reference: "flow-steps", level: 0 },
          spacing: { after: 80, line: 340 },
          children: [new TextRun({ text: "\u62FF\u5230\u5E02\u573A\u5F53\u524D\u4EF7\u683C\u548C\u903B\u8F91\u7EA6\u675F\u77E9\u9635", size: 22, font: "Arial", color: "333333" })],
        }),
        new Paragraph({
          numbering: { reference: "flow-steps", level: 0 },
          spacing: { after: 80, line: 340 },
          children: [new TextRun({ text: "\u7528 Frank-Wolfe \u7B97\u6CD5\u627E\u5230\u6700\u63A5\u8FD1\u5F53\u524D\u4EF7\u683C\u3001\u4F46\u7B26\u5408\u903B\u8F91\u7684\u201C\u5408\u7406\u4EF7\u683C\u201D", size: 22, font: "Arial", color: "333333" })],
        }),
        new Paragraph({
          numbering: { reference: "flow-steps", level: 0 },
          spacing: { after: 80, line: 340 },
          children: [new TextRun({ text: "\u7528\u6574\u6570\u89C4\u5212\u6C42\u89E3\u5668\uFF08Google OR-Tools\uFF09\u6765\u5904\u7406\u590D\u6742\u7684\u903B\u8F91\u7EA6\u675F", size: 22, font: "Arial", color: "333333" })],
        }),
        new Paragraph({
          numbering: { reference: "flow-steps", level: 0 },
          spacing: { after: 160, line: 340 },
          children: [new TextRun({ text: "\u8BA1\u7B97\u6BCF\u4E2A\u7ED3\u679C\u7684\u201C\u504F\u5DEE\u201D\uFF08edge\uFF09\uFF0C\u751F\u6210\u5177\u4F53\u4EA4\u6613\u6307\u4EE4", size: 22, font: "Arial", color: "333333" })],
        }),

        heading2("4.4 \u6A21\u62DF\u5668\uFF08Simulator\uFF09"),
        body("\u6709\u4E86\u4EA4\u6613\u6307\u4EE4\uFF0C\u8FD8\u4E0D\u80FD\u76F4\u63A5\u4E0B\u573A\u3002\u6A21\u62DF\u5668\u7528\u865A\u62DF\u8D44\u91D1\uFF08\u9ED8\u8BA4 10,000 \u7F8E\u5143\uFF09\u6A21\u62DF\u771F\u5B9E\u4EA4\u6613\uFF0C\u5E76\u8003\u8651\u4EE5\u4E0B\u73B0\u5B9E\u56E0\u7D20\uFF1A"),

        new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 80, line: 340 },
          children: [
            new TextRun({ text: "\u6ED1\u70B9\uFF08Slippage\uFF09\uFF1A", bold: true, size: 22, font: "Arial", color: "333333" }),
            new TextRun({ text: "\u4E70\u5927\u91CF\u5408\u7EA6\u65F6\uFF0C\u4EF7\u683C\u4F1A\u88AB\u201C\u62AC\u9AD8\u201D\u3002\u7CFB\u7EDF\u7528 VWAP\uFF08\u6210\u4EA4\u91CF\u52A0\u6743\u5747\u4EF7\uFF09\u8BA1\u7B97\u771F\u5B9E\u6210\u672C\u3002", size: 22, font: "Arial", color: "333333" }),
          ],
        }),
        new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 80, line: 340 },
          children: [
            new TextRun({ text: "\u624B\u7EED\u8D39\uFF1A", bold: true, size: 22, font: "Arial", color: "333333" }),
            new TextRun({ text: "\u6BCF\u7B14\u4EA4\u6613\u6536\u53D6 2% \u624B\u7EED\u8D39\u3002", size: 22, font: "Arial", color: "333333" }),
          ],
        }),
        new Paragraph({
          numbering: { reference: "bullets", level: 0 },
          spacing: { after: 160, line: 340 },
          children: [
            new TextRun({ text: "\u8D44\u91D1\u7BA1\u7406\uFF1A", bold: true, size: 22, font: "Arial", color: "333333" }),
            new TextRun({ text: "\u5355\u7B14\u6700\u5927\u4ED3\u4F4D 100 \u7F8E\u5143\uFF0C\u4E0D\u4F1A\u628A\u6240\u6709\u94B1\u538B\u5728\u4E00\u4E2A\u673A\u4F1A\u4E0A\u3002", size: 22, font: "Arial", color: "333333" }),
          ],
        }),

        heading2("4.5 \u4EEA\u8868\u76D8\uFF08Dashboard\uFF09"),
        body("\u4EEA\u8868\u76D8\u662F\u7CFB\u7EDF\u7684\u201C\u63A7\u5236\u5BA4\u201D\uFF0C\u901A\u8FC7\u6D4F\u89C8\u5668\u8BBF\u95EE 192.168.5.100:8081\uFF0C\u53EF\u4EE5\u770B\u5230\uFF1A\u5DF2\u53D1\u73B0\u7684\u5E02\u573A\u5BF9\u3001\u5957\u5229\u673A\u4F1A\u3001\u4EA4\u6613\u8BB0\u5F55\u3001\u6295\u8D44\u7EC4\u5408\u72B6\u6001\u3001\u76C8\u4E8F\u548C\u80DC\u7387\u3002"),

        // ─── Section 5: 数据流 ───
        heading1("\u4E94\u3001\u6570\u636E\u6D41\u7A0B\uFF1A\u4ECE\u53D1\u73B0\u5230\u4EA4\u6613"),

        body("\u6574\u4E2A\u7CFB\u7EDF\u50CF\u4E00\u6761\u6D41\u6C34\u7EBF\uFF0C\u6570\u636E\u4ECE\u5DE6\u5230\u53F3\u6D41\u52A8\uFF1A"),

        // Flow diagram as table
        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [1872, 1872, 1872, 1872, 1872],
          rows: [
            new TableRow({ children: [
              new TableCell({
                borders, width: { size: 1872, type: WidthType.DXA },
                shading: { fill: "E8F5E9", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u91C7\u96C6\u5668", bold: true, size: 20, font: "Arial" })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u2193", size: 20 })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u83B7\u53D6\u6570\u636E", size: 18, font: "Arial", color: SUBTLE })] }),
                ],
              }),
              new TableCell({
                borders, width: { size: 1872, type: WidthType.DXA },
                shading: { fill: "E3F2FD", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u68C0\u6D4B\u5668", bold: true, size: 20, font: "Arial" })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u2193", size: 20 })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u627E\u914D\u5BF9", size: 18, font: "Arial", color: SUBTLE })] }),
                ],
              }),
              new TableCell({
                borders, width: { size: 1872, type: WidthType.DXA },
                shading: { fill: "FFF3E0", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u4F18\u5316\u5668", bold: true, size: 20, font: "Arial" })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u2193", size: 20 })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u8BA1\u7B97\u6700\u4F18\u89E3", size: 18, font: "Arial", color: SUBTLE })] }),
                ],
              }),
              new TableCell({
                borders, width: { size: 1872, type: WidthType.DXA },
                shading: { fill: "FCE4EC", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u6A21\u62DF\u5668", bold: true, size: 20, font: "Arial" })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u2193", size: 20 })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u6A21\u62DF\u4EA4\u6613", size: 18, font: "Arial", color: SUBTLE })] }),
                ],
              }),
              new TableCell({
                borders, width: { size: 1872, type: WidthType.DXA },
                shading: { fill: "F3E5F5", type: ShadingType.CLEAR }, margins: cellMargins,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u4EEA\u8868\u76D8", bold: true, size: 20, font: "Arial" })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u2193", size: 20 })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "\u5C55\u793A\u7ED3\u679C", size: 18, font: "Arial", color: SUBTLE })] }),
                ],
              }),
            ]}),
          ],
        }),

        new Paragraph({ spacing: { after: 80 } }),
        body("\u670D\u52A1\u4E4B\u95F4\u901A\u8FC7 Redis \u6D88\u606F\u961F\u5217\u901A\u4FE1\u3002\u6BD4\u5982\u91C7\u96C6\u5668\u5B8C\u6210\u540C\u6B65\u540E\uFF0C\u4F1A\u53D1\u5E03\u4E00\u4E2A\u201C\u6570\u636E\u5DF2\u66F4\u65B0\u201D\u7684\u4FE1\u53F7\uFF0C\u68C0\u6D4B\u5668\u6536\u5230\u540E\u7ACB\u523B\u5F00\u59CB\u5DE5\u4F5C\u3002"),

        // ─── Section 6: 当前状态 ───
        heading1("\u516D\u3001\u5F53\u524D\u8FD0\u884C\u72B6\u6001"),

        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [3120, 6240],
          rows: [
            new TableRow({ children: [
              headerCell("\u6307\u6807", 3120),
              headerCell("\u72B6\u6001", 6240),
            ]}),
            new TableRow({ children: [
              dataCell("\u5DF2\u540C\u6B65\u5E02\u573A", 3120, { shading: "F9FAFB" }),
              dataCell("37,750 \u4E2A", 6240, { shading: "F9FAFB" }),
            ]}),
            new TableRow({ children: [
              dataCell("\u5DF2\u53D1\u73B0\u914D\u5BF9", 3120),
              dataCell("17 \u5BF9\uFF08\u5305\u62EC\u4F53\u80B2\u548C\u52A0\u5BC6\u8D27\u5E01\u5E02\u573A\uFF09", 6240),
            ]}),
            new TableRow({ children: [
              dataCell("\u5411\u91CF\u7EF4\u5EA6", 3120, { shading: "F9FAFB" }),
              dataCell("384 \u7EF4\uFF08OpenAI text-embedding-3-small\uFF09", 6240, { shading: "F9FAFB" }),
            ]}),
            new TableRow({ children: [
              dataCell("\u8F6E\u8BE2\u9891\u7387", 3120),
              dataCell("\u6BCF 30 \u79D2\u91C7\u96C6\u4E00\u6B21\u4EF7\u683C", 6240),
            ]}),
            new TableRow({ children: [
              dataCell("\u6A21\u62DF\u8D44\u91D1", 3120, { shading: "F9FAFB" }),
              dataCell("$10,000 \u865A\u62DF\u7F8E\u5143", 6240, { shading: "F9FAFB" }),
            ]}),
            new TableRow({ children: [
              dataCell("\u90E8\u7F72\u4F4D\u7F6E", 3120),
              dataCell("\u672C\u5730 NAS\uFF08192.168.5.100\uFF09\uFF0CDocker \u5BB9\u5668\u5316", 6240),
            ]}),
          ],
        }),

        new Paragraph({ spacing: { after: 100 } }),

        // ─── Section 7: 技术栈 ───
        heading1("\u4E03\u3001\u6280\u672F\u6808\u4E00\u89C8"),

        new Table({
          width: { size: 9360, type: WidthType.DXA },
          columnWidths: [2340, 2340, 4680],
          rows: [
            new TableRow({ children: [
              headerCell("\u7EC4\u4EF6", 2340),
              headerCell("\u6280\u672F", 2340),
              headerCell("\u4F5C\u7528", 4680),
            ]}),
            new TableRow({ children: [
              dataCell("\u6570\u636E\u5E93", 2340, { shading: "F9FAFB" }),
              dataCell("PostgreSQL + pgvector", 2340, { shading: "F9FAFB" }),
              dataCell("\u5B58\u50A8\u5E02\u573A\u6570\u636E\u3001\u4EF7\u683C\u5FEB\u7167\u548C\u5411\u91CF\u7D22\u5F15", 4680, { shading: "F9FAFB" }),
            ]}),
            new TableRow({ children: [
              dataCell("\u6D88\u606F\u961F\u5217", 2340),
              dataCell("Redis", 2340),
              dataCell("\u670D\u52A1\u95F4\u5B9E\u65F6\u901A\u4FE1\uFF08\u53D1\u5E03/\u8BA2\u9605\u6A21\u5F0F\uFF09", 4680),
            ]}),
            new TableRow({ children: [
              dataCell("\u5D4C\u5165\u5411\u91CF", 2340, { shading: "F9FAFB" }),
              dataCell("OpenAI API", 2340, { shading: "F9FAFB" }),
              dataCell("\u5C06\u5E02\u573A\u95EE\u9898\u8F6C\u4E3A\u53EF\u8BA1\u7B97\u7684\u6570\u5B57\u5411\u91CF", 4680, { shading: "F9FAFB" }),
            ]}),
            new TableRow({ children: [
              dataCell("\u5206\u7C7B\u5668", 2340),
              dataCell("GPT-4o-mini", 2340),
              dataCell("\u5224\u65AD\u5E02\u573A\u5BF9\u4E4B\u95F4\u7684\u903B\u8F91\u5173\u7CFB", 4680),
            ]}),
            new TableRow({ children: [
              dataCell("\u4F18\u5316\u5F15\u64CE", 2340, { shading: "F9FAFB" }),
              dataCell("Frank-Wolfe + OR-Tools", 2340, { shading: "F9FAFB" }),
              dataCell("\u627E\u5230\u6700\u4F18\u4EA4\u6613\u65B9\u6848\uFF0C\u5904\u7406\u590D\u6742\u7EA6\u675F", 4680, { shading: "F9FAFB" }),
            ]}),
            new TableRow({ children: [
              dataCell("\u5BB9\u5668\u5316", 2340),
              dataCell("Docker Compose", 2340),
              dataCell("6 \u4E2A\u670D\u52A1\u72EC\u7ACB\u8FD0\u884C\uFF0C\u4E92\u4E0D\u5E72\u6270", 4680),
            ]}),
            new TableRow({ children: [
              dataCell("\u540E\u7AEF\u8BED\u8A00", 2340, { shading: "F9FAFB" }),
              dataCell("Python (asyncio)", 2340, { shading: "F9FAFB" }),
              dataCell("\u5F02\u6B65\u67B6\u6784\uFF0C\u9AD8\u5E76\u53D1\u6570\u636E\u5904\u7406", 4680, { shading: "F9FAFB" }),
            ]}),
          ],
        }),

        new Paragraph({ spacing: { after: 100 } }),

        // ─── Section 8: 重要说明 ───
        heading1("\u516B\u3001\u91CD\u8981\u8BF4\u660E"),

        bodyRuns([
          { text: "\u8FD9\u662F\u4E00\u4E2A\u7814\u7A76/\u5B9E\u9A8C\u9879\u76EE\uFF0C\u4E0D\u662F\u6295\u8D44\u5EFA\u8BAE\u3002", bold: true },
          { text: "\u7CFB\u7EDF\u76EE\u524D\u5B8C\u5168\u4F7F\u7528\u865A\u62DF\u8D44\u91D1\uFF0C\u4E0D\u6D89\u53CA\u4EFB\u4F55\u771F\u5B9E\u8D44\u91D1\u64CD\u4F5C\u3002\u5B83\u7684\u76EE\u7684\u662F\u9A8C\u8BC1\u7B56\u7565\u7684\u6709\u6548\u6027\uFF0C\u5E76\u79EF\u7D2F\u5B9E\u9A8C\u6570\u636E\u3002\u5728\u8003\u8651\u4EFB\u4F55\u771F\u5B9E\u4EA4\u6613\u4E4B\u524D\uFF0C\u9700\u8981\u81F3\u5C11 30\u201360 \u5929\u7684\u7EB8\u4E0A\u4EA4\u6613\u6570\u636E\u6765\u9A8C\u8BC1\u7B56\u7565\u7684\u7A33\u5B9A\u6027\u3002" },
        ]),

        new Paragraph({ spacing: { after: 160 } }),

        body("\u9884\u6D4B\u5E02\u573A\u7684\u76D1\u7BA1\u73AF\u5883\u5728\u4E0D\u540C\u56FD\u5BB6\u6709\u6240\u4E0D\u540C\u3002\u4F8B\u5982\uFF0C\u6CD5\u56FD\u5DF2\u5C06\u9884\u6D4B\u5E02\u573A\u5E73\u53F0\u5F52\u7C7B\u4E3A\u975E\u6CD5\u535A\u5F69\uFF0C\u800C\u7F8E\u56FD\u5219\u901A\u8FC7 CFTC \u76D1\u7BA1\u6846\u67B6\u63D0\u4F9B\u5408\u89C4\u8DEF\u5F84\u3002\u5728\u4F7F\u7528\u672C\u7CFB\u7EDF\u4E4B\u524D\uFF0C\u8BF7\u786E\u4FDD\u4E86\u89E3\u5E76\u9075\u5B88\u5F53\u5730\u6CD5\u5F8B\u6CD5\u89C4\u3002"),
      ],
    },
  ],
});

// ── Write file ──
Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/confident-vigilant-noether/mnt/polyarb/PolyArb_说明文档.docx", buffer);
  console.log("OK: PolyArb_说明文档.docx created");
});
