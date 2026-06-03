const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
} = require('docx');
const fs = require('fs');

const COLOURS = {
  normalized: 'C6EFCE',
  partial: 'FFEB9C',
  out_of_scope_financial: 'EDEDED',
  drop: 'FFC7CE',
  new_metric: 'BDD7EE',
  quarantine: 'E2CFEE',
};

const border = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const borders = { top: border, bottom: border, left: border, right: border };

function cell(text, fill, bold, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: fill ? { fill, type: ShadingType.CLEAR } : undefined,
    margins: { top: 55, bottom: 55, left: 90, right: 90 },
    children: [new Paragraph({ children: [new TextRun({ text: String(text ?? ''), bold: !!bold, size: 17 })] })],
  });
}

function hCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: '1F4E79', type: ShadingType.CLEAR },
    margins: { top: 55, bottom: 55, left: 90, right: 90 },
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, size: 17, color: 'FFFFFF' })] })],
  });
}

function metaTable(chunk) {
  const rows = [
    ['Chunk ID', chunk.chunk_id],
    ['Doc ID', chunk.doc_id],
    ['Section ID', chunk.section_id],
    ['Prev Chunk', chunk.prev_chunk_id ?? 'null'],
    ['Next Chunk', chunk.next_chunk_id ?? 'null'],
    ['Pages', chunk.page_start === chunk.page_end ? String(chunk.page_start) : `${chunk.page_start}–${chunk.page_end}`],
    ['Chars / Tokens', `${chunk.char_count} / ${chunk.token_estimate}`],
    ['Period', chunk.temporal_context?.primary_period ?? ''],
  ];
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2200, 7160],
    rows: rows.map(([f, v]) => new TableRow({ children: [cell(f, 'EBF3FB', true, 2200), cell(v, null, false, 7160)] })),
  });
}

function factsTable(facts) {
  const widths = [900, 1300, 800, 700, 1200, 800, 700, 1000, 960, 1000];
  const headers = ['Fact ID', 'Metric', 'Raw Value', 'Raw Unit', 'Norm Value', 'Norm Unit', 'Period', 'Decision', 'Canonical ID', 'Confidence'];
  const hRow = new TableRow({ children: headers.map((h, i) => hCell(h, widths[i])) });
  const dRows = facts.map(f => {
    const dec = f.normalization_decision || 'drop';
    const shade = COLOURS[dec] || 'FFFFFF';
    return new TableRow({ children: [
      cell(f.fact_id, shade, false, widths[0]),
      cell(f.metric, shade, false, widths[1]),
      cell(f.raw_value, shade, false, widths[2]),
      cell(f.raw_unit, shade, false, widths[3]),
      cell(f.normalised_value != null ? String(f.normalised_value) : '—', shade, false, widths[4]),
      cell(f.normalised_unit_symbol ?? '—', shade, false, widths[5]),
      cell(f.period_label, shade, false, widths[6]),
      cell(dec, shade, true, widths[7]),
      cell(f.canonical_id ?? '—', shade, false, widths[8]),
      cell(f.normalisation_confidence ?? '—', shade, false, widths[9]),
    ]});
  });
  return new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: widths, rows: [hRow, ...dRows] });
}

function legendTable() {
  const entries = Object.entries(COLOURS);
  const labels = { normalized: 'Normalized', partial: 'Partial', out_of_scope_financial: 'Out of scope (financial)', drop: 'Drop', new_metric: 'New metric', quarantine: 'Quarantine' };
  const w = Math.floor(9360 / entries.length);
  const widths = entries.map((_, i) => i === entries.length - 1 ? 9360 - w * (entries.length - 1) : w);
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: widths,
    rows: [new TableRow({ children: entries.map(([dec], i) => new TableCell({
      borders, width: { size: widths[i], type: WidthType.DXA },
      shading: { fill: COLOURS[dec], type: ShadingType.CLEAR },
      margins: { top: 55, bottom: 55, left: 90, right: 90 },
      children: [new Paragraph({ children: [new TextRun({ text: labels[dec], bold: true, size: 17 })] })],
    }))})],
  });
}

function buildDoc(company, chunks, factsArr, title) {
  // Index facts by chunk_id
  const factsByChunk = {};
  for (const f of factsArr) {
    const cid = f.chunk_id;
    if (!factsByChunk[cid]) factsByChunk[cid] = [];
    factsByChunk[cid].push(f);
  }

  const children = [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 }, children: [new TextRun({ text: title, bold: true, size: 34 })] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 }, children: [new TextRun({ text: `${chunks.length} chunks | ${factsArr.length} facts | Pass 1 + Pass 2 | FY2024`, size: 22, color: '595959' })] }),
    new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: 'Legend:', bold: true, size: 20 })] }),
    legendTable(),
    new Paragraph({ spacing: { before: 400 }, children: [] }),
  ];

  for (const chunk of chunks) {
    const cid = chunk.chunk_id;
    const facts = factsByChunk[cid] || [];
    children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 300, after: 120 }, children: [new TextRun({ text: cid, bold: true, size: 26 })] }));
    children.push(new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text: 'Metadata', bold: true, size: 20 })] }));
    children.push(metaTable(chunk));
    children.push(new Paragraph({ spacing: { before: 160, after: 80 }, children: [new TextRun({ text: 'Chunk Text', bold: true, size: 20 })] }));
    children.push(new Paragraph({
      border: { top: border, bottom: border, left: { style: BorderStyle.THICK, size: 6, color: '2E75B6' }, right: border },
      shading: { fill: 'FAFAFA', type: ShadingType.CLEAR },
      spacing: { before: 60, after: 60 },
      children: [new TextRun({ text: chunk.content, size: 17 })],
    }));
    if (facts.length === 0) {
      children.push(new Paragraph({ spacing: { before: 120 }, children: [new TextRun({ text: 'No facts extracted from this chunk.', italics: true, size: 18, color: '888888' })] }));
    } else {
      children.push(new Paragraph({ spacing: { before: 160, after: 80 }, children: [new TextRun({ text: `Extracted Facts (${facts.length})`, bold: true, size: 20 })] }));
      children.push(factsTable(facts));
    }
    children.push(new Paragraph({ spacing: { before: 240 }, border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: 'CCCCCC' } }, children: [] }));
  }

  return new Document({
    sections: [{
      properties: { page: { size: { width: 15840, height: 12240 }, margin: { top: 900, right: 720, bottom: 900, left: 720 }, orientation: 'landscape' } },
      children,
    }],
  });
}

async function main() {
  const nestleChunks = JSON.parse(fs.readFileSync('workspace_test_outputs/nestle_india_rerun_fast_chunks.json', 'utf8'));
  const nestleFacts = (() => { const d = JSON.parse(fs.readFileSync('workspace_test_outputs/nestle_india_pass2_rerun.json', 'utf8')); return Array.isArray(d) ? d : (d.facts || []); })();

  const tataChunks = JSON.parse(fs.readFileSync('workspace_test_outputs/tata_consumer_rerun_fast_chunks.json', 'utf8'));
  const tataFacts = (() => { const d = JSON.parse(fs.readFileSync('workspace_test_outputs/tata_consumer_pass2_rerun.json', 'utf8')); return Array.isArray(d) ? d : (d.facts || []); })();

  const nestleDoc = buildDoc('nestle_india', nestleChunks, nestleFacts, 'Nestle India — All Chunks & Facts | Annual Report FY2024');
  const tataDoc = buildDoc('tata_consumer', tataChunks, tataFacts, 'Tata Consumer — All Chunks & Facts | Annual Report FY2024');

  await Packer.toBuffer(nestleDoc).then(buf => fs.writeFileSync('nestle_india_full_report_v2.docx', buf));
  console.log('Done: nestle_india_full_report.docx');

  await Packer.toBuffer(tataDoc).then(buf => fs.writeFileSync('tata_consumer_full_report_v2.docx', buf));
  console.log('Done: tata_consumer_full_report.docx');
}

main().catch(console.error);
