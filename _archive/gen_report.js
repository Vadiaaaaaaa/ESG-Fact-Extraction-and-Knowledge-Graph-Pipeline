const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, LevelFormat
} = require('docx');
const fs = require('fs');

// Colour map by normalization_decision
const COLOURS = {
  normalized: 'C6EFCE',         // green
  partial: 'FFEB9C',            // yellow
  out_of_scope_financial: 'EDEDED', // grey
  drop: 'FFC7CE',               // pink/red
  new_metric: 'BDD7EE',         // blue
};
const COLOUR_LABELS = {
  normalized: 'Normalized',
  partial: 'Partial',
  out_of_scope_financial: 'Out of scope (financial)',
  drop: 'Drop',
  new_metric: 'New metric',
};

const data = JSON.parse(fs.readFileSync('nestle_first5_data.json', 'utf8'));

const border = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const borders = { top: border, bottom: border, left: border, right: border };

function cell(text, shading, bold, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: shading ? { fill: shading, type: ShadingType.CLEAR } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: [new TextRun({ text: String(text ?? ''), bold: !!bold, size: 18 })] })],
  });
}

function headerCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: '2E75B6', type: ShadingType.CLEAR },
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, size: 18, color: 'FFFFFF' })] })],
  });
}

function metaTable(chunk) {
  const rows = [
    ['Doc ID', chunk.doc_id],
    ['Section ID', chunk.section_id],
    ['Chunk ID', chunk.chunk_id],
    ['Prev Chunk ID', chunk.prev_chunk_id ?? 'null'],
    ['Next Chunk ID', chunk.next_chunk_id ?? 'null'],
    ['Page(s)', chunk.page_start === chunk.page_end ? String(chunk.page_start) : `${chunk.page_start}-${chunk.page_end}`],
    ['Chunk Type', chunk.chunk_type],
    ['Characters', String(chunk.char_count)],
    ['Token Estimate', String(chunk.token_estimate)],
    ['Primary Period', chunk.temporal_context?.primary_period ?? ''],
  ];
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2800, 6560],
    rows: rows.map(([f, v]) => new TableRow({ children: [cell(f, 'F2F2F2', true, 2800), cell(v, null, false, 6560)] })),
  });
}

function factsTable(facts) {
  const cols = [1200, 1100, 800, 1100, 1300, 1000, 800, 1060, 1000];
  const headers = ['Fact ID', 'Metric', 'Raw Value', 'Raw Unit', 'Normalised Value', 'Norm Unit', 'Period', 'Decision', 'Canonical ID'];
  const headerRow = new TableRow({ children: headers.map((h, i) => headerCell(h, cols[i])) });
  const dataRows = facts.map(f => {
    const dec = f.normalization_decision || 'drop';
    const shade = COLOURS[dec] || 'FFFFFF';
    return new TableRow({
      children: [
        cell(f.fact_id, shade, false, cols[0]),
        cell(f.metric, shade, false, cols[1]),
        cell(f.raw_value, shade, false, cols[2]),
        cell(f.raw_unit, shade, false, cols[3]),
        cell(f.normalised_value != null ? String(f.normalised_value) : 'null', shade, false, cols[4]),
        cell(f.normalised_unit_symbol ?? '', shade, false, cols[5]),
        cell(f.period_label, shade, false, cols[6]),
        cell(dec, shade, true, cols[7]),
        cell(f.canonical_id ?? '', shade, false, cols[8]),
      ],
    });
  });
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: cols,
    rows: [headerRow, ...dataRows],
  });
}

function chunkSection(chunkId, entry) {
  const { chunk, facts } = entry;
  const elements = [];
  elements.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: `Chunk: ${chunkId}`, bold: true, size: 28 })] }));
  elements.push(new Paragraph({ children: [new TextRun({ text: 'Chunk Metadata', bold: true, size: 22 })] }));
  elements.push(metaTable(chunk));
  elements.push(new Paragraph({ spacing: { before: 200 }, children: [new TextRun({ text: 'Chunk Text', bold: true, size: 22 })] }));
  // Chunk text as a bordered paragraph
  elements.push(new Paragraph({
    border: { top: border, bottom: border, left: border, right: border },
    shading: { fill: 'FAFAFA', type: ShadingType.CLEAR },
    spacing: { before: 60, after: 60 },
    children: [new TextRun({ text: chunk.content, size: 18 })],
  }));
  elements.push(new Paragraph({ spacing: { before: 200 }, children: [new TextRun({ text: `Extracted Facts (${facts.length})`, bold: true, size: 22 })] }));
  elements.push(factsTable(facts));
  elements.push(new Paragraph({ spacing: { before: 300 }, children: [] }));
  return elements;
}

function legendTable() {
  const entries = Object.entries(COLOUR_LABELS);
  const cols = entries.map(() => Math.floor(9360 / entries.length));
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: cols,
    rows: [
      new TableRow({ children: entries.map(([dec], i) => new TableCell({ borders, width: { size: cols[i], type: WidthType.DXA }, shading: { fill: COLOURS[dec], type: ShadingType.CLEAR }, margins: { top: 60, bottom: 60, left: 100, right: 100 }, children: [new Paragraph({ children: [new TextRun({ text: COLOUR_LABELS[dec], bold: true, size: 18 })] })] })) }),
    ],
  });
}

const children = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: 'Nestle India — First 5 Chunks: Extracted Facts Report', bold: true, size: 36 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 }, children: [new TextRun({ text: 'Pipeline Output: Pass 1 + Pass 2 | Annual Report FY2024', size: 24, color: '595959' })] }),
];

for (const [chunkId, entry] of Object.entries(data)) {
  children.push(...chunkSection(chunkId, entry));
}

children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: 'Colour Legend', bold: true, size: 26 })] }));
children.push(legendTable());

const doc = new Document({
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 720, bottom: 1080, left: 720 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('nestle_first5_chunks_report.docx', buf);
  console.log('Done: nestle_first5_chunks_report.docx');
});
