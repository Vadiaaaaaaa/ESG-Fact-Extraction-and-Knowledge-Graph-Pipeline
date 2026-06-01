import os
os.environ["HF_HUB_OFFLINE"] = "1"

from docling.document_converter import DocumentConverter
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling.document_converter import PdfFormatOption
import json

pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = False
pipeline_options.do_table_structure = True
pipeline_options.images_scale = 0.5

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)

print("Converting pages 1-10...")

from docling.datamodel.document import DocumentStream
from pathlib import Path

result = converter.convert(
    r"C:\Users\Vedika.Sahoo\OneDrive - GlobalData PLC\Desktop\Amazon-2025-Annual-Report.pdf",
    page_range=(1, 10)
)

with open(r"C:\Users\Vedika.Sahoo\test\amazon_output.json", "w", encoding="utf-8") as f:
    json.dump(result.document.export_to_dict(), f, indent=2, ensure_ascii=False)

print("Done! Check amazon_output.json in your test folder")
