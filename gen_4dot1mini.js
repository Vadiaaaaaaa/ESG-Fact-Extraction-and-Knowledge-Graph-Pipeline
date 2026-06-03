const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType } = require('docx');
const fs = require('fs');

const COLOURS = { normalized:'C6EFCE', partial:'FFEB9C', out_of_scope_financial:'EDEDED', drop:'FFC7CE', new_metric:'BDD7EE', quarantine:'E2CFEE' };
const LABELS  = { normalized:'Normalized', partial:'Partial', out_of_scope_financial:'Out of scope (financial)', drop:'Drop', new_metric:'New metric', quarantine:'Quarantine' };
const b = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const borders = { top:b, bottom:b, left:b, right:b };

const cell = (text, fill, bold, w) => new TableCell({ borders, width:{size:w,type:WidthType.DXA}, shading:fill?{fill,type:ShadingType.CLEAR}:undefined, margins:{top:55,bottom:55,left:90,right:90}, children:[new Paragraph({children:[new TextRun({text:String(text??''),bold:!!bold,size:17})]})] });
const hCell = (text, w) => new TableCell({ borders, width:{size:w,type:WidthType.DXA}, shading:{fill:'1F4E79',type:ShadingType.CLEAR}, margins:{top:55,bottom:55,left:90,right:90}, children:[new Paragraph({children:[new TextRun({text,bold:true,size:17,color:'FFFFFF'})]})] });

const chunks = JSON.parse(fs.readFileSync('workspace_test_outputs/nestle_india_rerun_fast_chunks.json','utf8'));
const rawFacts = JSON.parse(fs.readFileSync('workspace_test_outputs/nestle_india_4dot1mini_pass2.json','utf8'));
const factsArr = Array.isArray(rawFacts) ? rawFacts : (rawFacts.facts||[]);

const byChunk = {};
for (const f of factsArr) { const c=f.chunk_id; if(!byChunk[c]) byChunk[c]=[]; byChunk[c].push(f); }

const widths = [900,1300,800,700,1200,800,700,1100,900,1000];
const hdrs = ['Fact ID','Metric','Raw Value','Raw Unit','Norm Value','Norm Unit','Period','Decision','Canonical ID','Confidence'];

const totalKeep = factsArr.filter(f=>['normalized','partial','new_metric'].includes(f.normalization_decision)).length;

const legendCells = Object.entries(COLOURS).map(([dec,fill]) => {
  const w = Math.floor(9360/Object.keys(COLOURS).length);
  return new TableCell({borders,width:{size:w,type:WidthType.DXA},shading:{fill,type:ShadingType.CLEAR},margins:{top:55,bottom:55,left:90,right:90},children:[new Paragraph({children:[new TextRun({text:LABELS[dec],bold:true,size:17})]})]});
});

const children = [
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:160},children:[new TextRun({text:'Nestle India — gpt-4.1-mini | All Fixes Applied | FY2024',bold:true,size:34})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:200},children:[new TextRun({text:`${chunks.length} chunks | ${factsArr.length} facts | normalized=23  partial=49  new_metric=135  financial=234`,size:22,color:'595959'})]}),
  new Paragraph({spacing:{after:80},children:[new TextRun({text:'Legend:',bold:true,size:20})]}),
  new Table({width:{size:9360,type:WidthType.DXA},columnWidths:Array(Object.keys(COLOURS).length).fill(Math.floor(9360/Object.keys(COLOURS).length)),rows:[new TableRow({children:legendCells})]}),
  new Paragraph({spacing:{before:400},children:[]}),
];

for (const chunk of chunks) {
  const facts = byChunk[chunk.chunk_id] || [];
  children.push(new Paragraph({heading:HeadingLevel.HEADING_1,spacing:{before:300,after:100},children:[new TextRun({text:chunk.chunk_id,bold:true,size:26})]}));
  children.push(new Paragraph({spacing:{after:60},children:[new TextRun({text:`Page ${chunk.page_start}${chunk.page_end!==chunk.page_start?'-'+chunk.page_end:''}  |  ${facts.length} facts`,size:18,color:'595959'})]}));
  children.push(new Paragraph({border:{top:b,bottom:b,left:{style:BorderStyle.THICK,size:6,color:'2E75B6'},right:b},shading:{fill:'FAFAFA',type:ShadingType.CLEAR},spacing:{before:60,after:80},children:[new TextRun({text:chunk.content,size:17})]}));
  if (facts.length === 0) {
    children.push(new Paragraph({spacing:{before:60},children:[new TextRun({text:'No facts extracted.',italics:true,size:18,color:'888888'})]}));
  } else {
    const hRow = new TableRow({children: hdrs.map((h,i) => hCell(h, widths[i]))});
    const dRows = facts.map(f => {
      const dec = f.normalization_decision || 'drop';
      const shade = COLOURS[dec] || 'FFFFFF';
      return new TableRow({children:[
        cell(f.fact_id, shade, false, widths[0]),
        cell(f.metric, shade, false, widths[1]),
        cell(f.raw_value, shade, false, widths[2]),
        cell(f.raw_unit, shade, false, widths[3]),
        cell(f.normalised_value != null ? String(f.normalised_value) : '—', shade, false, widths[4]),
        cell(f.normalised_unit_symbol || '—', shade, false, widths[5]),
        cell(f.period_label || f.period, shade, false, widths[6]),
        cell(dec, shade, true, widths[7]),
        cell(f.canonical_id || '—', shade, false, widths[8]),
        cell(f.normalisation_confidence || '—', shade, false, widths[9]),
      ]});
    });
    children.push(new Table({width:{size:9360,type:WidthType.DXA},columnWidths:widths,rows:[hRow,...dRows]}));
  }
  children.push(new Paragraph({spacing:{before:200},border:{bottom:{style:BorderStyle.SINGLE,size:2,color:'CCCCCC'}},children:[]}));
}

const doc = new Document({sections:[{properties:{page:{size:{width:15840,height:12240},margin:{top:900,right:720,bottom:900,left:720}}},children}]});
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('nestle_india_4dot1mini_full_report.docx', buf);
  console.log(`Done: nestle_india_4dot1mini_full_report.docx (${(buf.length/1024).toFixed(0)} KB)`);
});
