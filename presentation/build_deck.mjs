import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { Presentation, PresentationFile } from "@oai/artifact-tool";


const workspaceDir = "/Users/ashleyvu/Documents/tariff-review";
const presentationDir = path.join(workspaceDir, "presentation");
const buildDir = path.join(presentationDir, "build");
const outputDir = presentationDir;
const finalPath = path.join(outputDir, "harbor-crane-tariff-audit-demo-v2.pptx");
const skillDir = "/Users/ashleyvu/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations";
const runtimePython = "/Users/ashleyvu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";

const {
  applyPresentationChartFont,
  finalizePresentation,
  resolvePresentationFont,
} = await import(pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href);

const FONT = resolvePresentationFont({ fontFamily: "Arial" });
const COLORS = {
  navy: "#0A2540",
  teal: "#00A6A6",
  cream: "#F6F3ED",
  ink: "#152536",
  muted: "#5E6B78",
  pale: "#DDE8E8",
  coral: "#D65F5F",
  gold: "#D79A2B",
  white: "#FFFFFF",
};

async function writeBlob(target, blob) {
  await fs.writeFile(target, new Uint8Array(await blob.arrayBuffer()));
}

function addText(slide, text, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: FONT,
    fontSize: style.fontSize ?? 24,
    bold: style.bold ?? false,
    color: style.color ?? COLORS.ink,
    alignment: style.alignment ?? "left",
  };
  shape.text.insets = style.insets ?? 0;
  return shape;
}

function addSlideTitle(slide, title, pageNumber, dark = false) {
  addText(slide, title, { left: 72, top: 54, width: 1040, height: 70 }, {
    fontSize: 44,
    bold: true,
    color: dark ? COLORS.white : COLORS.navy,
  });
  addText(slide, String(pageNumber).padStart(2, "0"), { left: 1160, top: 64, width: 48, height: 28 }, {
    fontSize: 16,
    bold: true,
    color: dark ? "#91A5B6" : "#8796A3",
    alignment: "right",
  });
}

function addFooter(slide, text, dark = false) {
  addText(slide, text, { left: 72, top: 665, width: 1136, height: 30 }, {
    fontSize: 15,
    color: dark ? "#A9BAC7" : "#6D7883",
  });
}

const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });

// Slide 1: minimal cover.
{
  const slide = deck.slides.add();
  slide.background.fill = COLORS.navy;
  slide.shapes.add({
    geometry: "rect",
    position: { left: 78, top: 150, width: 8, height: 290 },
    fill: COLORS.teal,
    line: { style: "solid", fill: "none", width: 0 },
  });
  addText(slide, "HARBOR & CRANE", { left: 106, top: 120, width: 360, height: 32 }, {
    fontSize: 18,
    bold: true,
    color: "#85D7D5",
  });
  addText(slide, "Potential duty differences,\nbacked by evidence", { left: 106, top: 176, width: 890, height: 190 }, {
    fontSize: 64,
    bold: true,
    color: COLORS.white,
  });
  addText(slide, "Premium tariff classification audit for Northfield Home Goods", { left: 108, top: 386, width: 760, height: 48 }, {
    fontSize: 27,
    color: "#C8D4DD",
  });
  addText(slide, "Five-minute demonstration · synthetic importer data", { left: 108, top: 610, width: 660, height: 32 }, {
    fontSize: 18,
    color: "#8EA3B2",
  });
  addText(slide, "2026", { left: 1120, top: 610, width: 86, height: 32 }, {
    fontSize: 18,
    bold: true,
    color: "#8EA3B2",
    alignment: "right",
  });
  slide.speakerNotes.text = [
    "Open with the importer outcome: a small evidence-backed review identifies both savings potential and compliance exposure.",
    "All importer and entry data in this deck are synthetic.",
  ];
}

// Slide 2: portfolio economics and illustrative service revenue.
{
  const slide = deck.slides.add();
  slide.background.fill = COLORS.cream;
  addSlideTitle(slide, "Synthetic portfolio economics", 2);

  const chart = slide.charts.add("bar", {
    position: { left: 64, top: 158, width: 690, height: 360 },
    categories: ["Potential overpayment", "Underpayment exposure"],
    series: [{
      name: "Base-duty difference",
      values: [20570, 14860],
      fill: COLORS.teal,
      points: [
        { idx: 0, fill: COLORS.teal },
        { idx: 1, fill: COLORS.coral },
      ],
    }],
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 55, varyColors: true },
    hasLegend: false,
    xAxis: {
      visible: true,
      min: 0,
      max: 25000,
      majorUnit: 5000,
      numberFormatCode: "$#,##0",
      textStyle: { fill: COLORS.muted, fontSize: 15 },
      majorGridlines: { style: "solid", fill: "#D6DAD8", width: 1 },
      line: { style: "solid", fill: "#ABB4B5", width: 1 },
    },
    yAxis: {
      textStyle: { fill: COLORS.ink, fontSize: 18, bold: true },
      line: { style: "solid", fill: "none", width: 0 },
    },
    dataLabels: {
      showValue: true,
      position: "outEnd",
      numberFormatCode: "$#,##0",
      textStyle: { fill: COLORS.ink, fontSize: 18, bold: true },
    },
    chartFill: "none",
    chartLine: { style: "solid", fill: "none", width: 0 },
    plotAreaFill: "none",
    plotAreaLine: { style: "solid", fill: "none", width: 0 },
  });
  applyPresentationChartFont(chart, { fontFamily: FONT });

  slide.shapes.add({
    geometry: "line",
    position: { left: 790, top: 170, width: 0, height: 350 },
    fill: "none",
    line: { style: "solid", fill: "#B8C1C1", width: 2 },
  });
  addText(slide, "$150K", { left: 830, top: 180, width: 340, height: 90 }, {
    fontSize: 70,
    bold: true,
    color: COLORS.navy,
  });
  addText(slide, "Illustrative annual audit revenue", { left: 832, top: 278, width: 350, height: 64 }, {
    fontSize: 26,
    bold: true,
    color: COLORS.ink,
  });
  addText(slide, "5 audits per quarter\n$7,500 fixed fee per audit\n4 quarters", { left: 832, top: 365, width: 340, height: 125 }, {
    fontSize: 23,
    color: COLORS.muted,
  });
  addText(slide, "Revenue does not depend on a refund outcome", { left: 832, top: 518, width: 350, height: 48 }, {
    fontSize: 19,
    bold: true,
    color: COLORS.teal,
  });
  addFooter(slide, "Duty figures use 12 synthetic SKUs and verified 2026 Column 1 General rates. Commercial assumptions are illustrative.");
  slide.speakerNotes.text = [
    "Potential overpayment and underpayment exposure remain separate. Do not net them.",
    "The $150,000 revenue example equals 5 audits per quarter times a $7,500 fixed fee times 4 quarters. It is an illustrative commercial assumption, not a forecast.",
    "Rate and ruling sources: https://hts.usitc.gov/ and https://rulings.cbp.gov/",
    "The duty calculation excludes Chapter 99 duties, trade remedies, preferences, origin, entry status, deadlines and recovery eligibility.",
  ];
}

// Slide 3: native editable architecture diagram.
{
  const slide = deck.slides.add();
  slide.background.fill = COLORS.white;
  addSlideTitle(slide, "Controlled review workflow", 3);

  const nodeData = [
    ["01", "Broker selects\nproducts and facts"],
    ["02", "Responses API\nuses restricted MCP"],
    ["03", "Application validates\nevidence and dollars"],
    ["04", "Broker approves\none local draft"],
  ];
  const nodes = [];
  nodeData.forEach((item, index) => {
    const left = 72 + index * 294;
    const node = slide.shapes.add({
      geometry: "roundRect",
      name: `workflow-node-${index + 1}`,
      position: { left, top: 220, width: 240, height: 176 },
      fill: index === 3 ? COLORS.navy : "#EDF3F2",
      line: { style: "solid", fill: index === 3 ? COLORS.navy : "#B7C9C7", width: 2 },
      borderRadius: "rounded-xl",
    });
    node.text = `${item[0]}\n${item[1]}`;
    node.text.style = {
      typeface: FONT,
      fontSize: 24,
      bold: true,
      color: index === 3 ? COLORS.white : COLORS.navy,
      alignment: "left",
    };
    node.text.insets = { left: 24, right: 18, top: 20, bottom: 16 };
    nodes.push(node);
  });
  for (let index = 0; index < nodes.length - 1; index += 1) {
    slide.shapes.connect(nodes[index], nodes[index + 1], {
      kind: "straight",
      fromSide: "right",
      toSide: "left",
      line: { style: "solid", fill: COLORS.teal, width: 4 },
      tail: { type: "arrow", width: "med", length: "med" },
    });
  }
  addText(slide, "The model proposes a classification.", { left: 118, top: 476, width: 520, height: 50 }, {
    fontSize: 29,
    bold: true,
    color: COLORS.navy,
  });
  addText(slide, "Application code checks fetched citations, computes the duty difference and enforces authorization.", { left: 118, top: 534, width: 980, height: 64 }, {
    fontSize: 24,
    color: COLORS.muted,
  });
  addFooter(slide, "Correction actions remain draft-only. OpenAI approval and the application’s single-use token both cover one exact tool call.");
  slide.speakerNotes.text = [
    "OpenAI Responses API MCP guide: https://developers.openai.com/api/docs/guides/tools-connectors-mcp",
    "Approval flow: https://developers.openai.com/api/docs/guides/tools-connectors-mcp#approvals",
    "Structured Outputs guide: https://developers.openai.com/api/docs/guides/structured-outputs",
    "The demo uses allowed_tools, strict text.format JSON Schema, previous_response_id and mcp_approval_response.",
  ];
}

// Slide 4: native evidence table and demo close.
{
  const slide = deck.slides.add();
  slide.background.fill = COLORS.cream;
  addSlideTitle(slide, "Five-minute demonstration", 4);
  const table = slide.tables.add({
    rows: 5,
    columns: 4,
    left: 72,
    top: 148,
    width: 1136,
    height: 320,
    columnWidths: [175, 350, 260, 351],
    values: [
      ["SKU", "Decisive fact", "Code review", "Broker view"],
      ["NF-DW-001", "No vacuum between walls", "9617 to 7323", "$12,480 potential overpayment"],
      ["NF-DW-002", "Vacuum confirmed", "7323 to 9617", "$6,240 underpayment exposure"],
      ["NF-DW-003", "Vacuum status unknown", "No proposed code", "Request supplier evidence"],
      ["NF-DW-004", "Vacuum confirmed", "9617 confirmed", "No correction indicated"],
    ],
  });
  table.borders.assign({ style: "solid", fill: "#C8D1D0", width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 4 }).assign({
    fill: COLORS.navy,
    textStyle: { typeface: FONT, fontSize: 20, bold: true, color: COLORS.white },
    margins: { left: 12, right: 12, top: 9, bottom: 9 },
  });
  table.cells.block({ row: 1, column: 0, rowCount: 4, columnCount: 4 }).assign({
    textStyle: { typeface: FONT, fontSize: 19, color: COLORS.ink },
    margins: { left: 12, right: 12, top: 9, bottom: 9 },
  });
  table.cells.block({ row: 1, column: 3, rowCount: 1, columnCount: 1 }).assign({
    fill: "#DDF1EE",
    textStyle: { typeface: FONT, fontSize: 19, bold: true, color: "#087A73" },
  });
  table.cells.block({ row: 2, column: 3, rowCount: 1, columnCount: 1 }).assign({
    fill: "#F8E2E2",
    textStyle: { typeface: FONT, fontSize: 19, bold: true, color: "#A54444" },
  });

  slide.shapes.add({
    geometry: "line",
    position: { left: 626, top: 508, width: 0, height: 112 },
    fill: "none",
    line: { style: "solid", fill: "#BCC5C4", width: 2 },
  });
  addText(slide, "Live fact edit", { left: 88, top: 505, width: 460, height: 38 }, {
    fontSize: 25,
    bold: true,
    color: COLORS.navy,
  });
  addText(slide, "Laboratory-confirmed vacuum construction changes NF-DW-003 from needs information to underpayment exposure.", { left: 88, top: 550, width: 490, height: 82 }, {
    fontSize: 20,
    color: COLORS.muted,
  });
  addText(slide, "Human approval", { left: 674, top: 505, width: 460, height: 38 }, {
    fontSize: 25,
    bold: true,
    color: COLORS.navy,
  });
  addText(slide, "Dana sees the exact draft arguments. Approval creates one local draft and never files it with CBP.", { left: 674, top: 550, width: 480, height: 82 }, {
    fontSize: 20,
    color: COLORS.muted,
  });
  addFooter(slide, "Measured: 14/14 deterministic evaluation cases and 14/14 tests. Live OpenAI metrics require credentials and remote MCP configuration.");
  slide.speakerNotes.text = [
    "Official ruling links for this scenario: https://rulings.cbp.gov/ruling/N224817, https://rulings.cbp.gov/ruling/N241154 and https://rulings.cbp.gov/ruling/N321134",
    "The displayed test and evaluation counts were measured locally on 2026-10-18. The evaluation covers deterministic fixture logic, not model correctness.",
    "Close with the next proof point: one live Responses API run through an authenticated remote MCP endpoint, followed by the approval continuation.",
  ];
}

await fs.mkdir(buildDir, { recursive: true });
await fs.mkdir(outputDir, { recursive: true });
for (const [index, slide] of deck.slides.items.entries()) {
  const file = path.join(buildDir, `slide-${String(index + 1).padStart(2, "0")}.png`);
  await writeBlob(file, await deck.export({ slide, format: "png", scale: 1 }));
  await fs.writeFile(
    path.join(buildDir, `slide-${String(index + 1).padStart(2, "0")}.layout.json`),
    await (await slide.export({ format: "layout" })).text(),
  );
}
await writeBlob(path.join(buildDir, "deck-montage.webp"), await deck.export({ format: "webp", montage: true }));

const requirements = {
  explicitTotalSlideCount: 4,
  requiredNativeTableOwnerSlides: [4],
  requiredNativeChartOwnerSlides: [2],
  requiredEmbeddedWorkbookChartOwnerSlides: [],
  materializeLiteralChartWorkbooks: true,
};
const fontPolicy = { basis: "design", families: [FONT] };
const candidatePath = path.join(buildDir, "candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidatePath);
await finalizePresentation({
  ...requirements,
  workspaceDir,
  candidatePath,
  finalPath,
  pythonExecutable: runtimePython,
  integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
    "--require-native-table-slide", "4",
  ],
  requiredNativeTableOwnerSlides: [4],
  fontPolicy,
  verifyArtifactToolImport: true,
  receiptPath: path.join(buildDir, "harbor-crane-tariff-audit-demo-v2.validation.json"),
});

console.log(finalPath);
