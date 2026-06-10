from pathlib import Path

import ingest

ROOT = Path(__file__).resolve().parent

# Place the source PDF in ROOT/pdfs/ or update INPUT_PDF to the actual location.
INPUT_PDF = ROOT / "pdfs" / "2024-annual report nestle.pdf"
OUTPUT_JSON = ROOT / "workspace_test_outputs" / "nestle_merged_output.json"


def main() -> None:
    ingest.process_pdf(INPUT_PDF, OUTPUT_JSON)
    print(f"Done {OUTPUT_JSON.stat().st_size}")


if __name__ == "__main__":
    main()
