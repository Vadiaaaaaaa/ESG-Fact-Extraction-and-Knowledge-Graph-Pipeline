from pathlib import Path

import ingest


INPUT_PDF = Path(
    r"C:\Users\Vedika.Sahoo\OneDrive - GlobalData PLC\Desktop\2024-annual report nestle.pdf"
)
OUTPUT_JSON = Path(
    r"C:\Users\Vedika.Sahoo\test\nestle_merged_output.json"
)


def main() -> None:
    ingest.process_pdf(INPUT_PDF, OUTPUT_JSON)
    print(f"Done {OUTPUT_JSON.stat().st_size}")


if __name__ == "__main__":
    main()
