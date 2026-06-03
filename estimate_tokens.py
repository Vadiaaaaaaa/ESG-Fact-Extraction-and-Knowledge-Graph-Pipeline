import json, re
from pathlib import Path
from collections import defaultdict

ROOT   = Path(__file__).resolve().parent
OUTDIR = ROOT / "workspace_test_outputs"

chunks  = json.loads((OUTDIR / "nestle_india_rerun_fast_chunks.json").read_text(encoding="utf-8"))
p1_raw  = json.loads((OUTDIR / "nestle_india_pass1_rerun.json").read_text(encoding="utf-8"))
p2_raw  = json.loads((OUTDIR / "nestle_india_pass2_rerun.json").read_text(encoding="utf-8"))
sys_src = (ROOT / "pass1_prompt_lean.py").read_text(encoding="utf-8")
tel_path = OUTDIR / "nestle_india_pass1_rerun_telemetry.json"

p1_facts = p1_raw if isinstance(p1_raw, list) else p1_raw.get("facts", [])
p2_facts = p2_raw if isinstance(p2_raw, list) else p2_raw.get("facts", [])

# Extract prompt template text
m = re.search(r'"""(.*?)"""', sys_src, re.DOTALL)
prompt_text = m.group(1) if m else sys_src
sys_prompt_tokens = len(prompt_text) // 4

# ── Pass 1 ────────────────────────────────────────────────────────────────────
facts_by_chunk = defaultdict(list)
for f in p1_facts:
    cid = f.get("chunk_id") or ""
    if cid:
        facts_by_chunk[cid].append(f)

chunk_input_tokens, chunk_output_tokens = [], []
for ch in chunks:
    cid  = ch["chunk_id"]
    text = ch.get("content", "")
    inp  = sys_prompt_tokens + len(text) // 4
    chunk_input_tokens.append(inp)
    raw_facts = [f.get("raw", f) for f in facts_by_chunk[cid]]
    out = len(json.dumps(raw_facts, ensure_ascii=False)) // 4
    chunk_output_tokens.append(out)

n_chunks         = len(chunks)
total_p1_in      = sum(chunk_input_tokens)
total_p1_out     = sum(chunk_output_tokens)
avg_in           = total_p1_in  // n_chunks
avg_out          = total_p1_out // n_chunks
avg_content      = sum(len(ch["content"]) // 4 for ch in chunks) // n_chunks

# Rescue pass
rescue_in = rescue_out = 0
if tel_path.exists():
    tel = json.loads(tel_path.read_text(encoding="utf-8"))
    rescue_sent = tel.get("neighbor_rescue", {}).get("sent", 0) if isinstance(tel, dict) else 0
    print(f"Telemetry: rescue_sent={rescue_sent}")
else:
    rescue_sent = 11  # from the run log output we saw rescue: sent=11
    print(f"Using run-log rescue count: {rescue_sent}")

rescue_in  = rescue_sent * int(avg_in * 2.5)
rescue_out = rescue_sent * int(avg_out * 0.5)

total_p1_in_all  = total_p1_in  + rescue_in
total_p1_out_all = total_p1_out + rescue_out

print()
print("=== Pass 1 token estimate -- Nestle India FY2024 ===")
print(f"  Chunks processed:           {n_chunks}")
print(f"  System prompt tokens:       {sys_prompt_tokens:,}  (per chunk)")
print(f"  Avg chunk content tokens:   {avg_content:,}")
print(f"  Avg chunk input tokens:     {avg_in:,}  (prompt + content)")
print(f"  Avg chunk output tokens:    {avg_out:,}")
print(f"  Total input tokens:         {total_p1_in:,}")
print(f"  Total output tokens:        {total_p1_out:,}")
print(f"  Rescue pass input tokens:   {rescue_in:,}  ({rescue_sent} rescue calls x 2.5x input)")
print(f"  Rescue pass output tokens:  {rescue_out:,}")
print(f"  TOTAL Pass 1 tokens:        {total_p1_in_all:,} input + {total_p1_out_all:,} output")

# ── Pass 2 ────────────────────────────────────────────────────────────────────
tiebreaker_facts = [
    f for f in p2_facts
    if f.get("tiebreaker_used") is True
    or str(f.get("normalization_decision", "")).lower() == "partial"
]
n_tb         = len(tiebreaker_facts)
tb_inp_each  = 400
tb_out_each  = 100
total_p2_in  = n_tb * tb_inp_each
total_p2_out = n_tb * tb_out_each

print()
print("=== Pass 2 token estimate -- Nestle India FY2024 ===")
print(f"  Total facts in pass2:       {len(p2_facts)}")
print(f"  Tiebreaker calls (partial): {n_tb}")
print(f"  Avg tiebreaker input:       ~{tb_inp_each} tokens")
print(f"  Avg tiebreaker output:      ~{tb_out_each} tokens")
print(f"  Total Pass 2 tokens:        {total_p2_in:,} input + {total_p2_out:,} output")

# ── Totals + cost ─────────────────────────────────────────────────────────────
total_in  = total_p1_in_all  + total_p2_in
total_out = total_p1_out_all + total_p2_out

models = {
    "gpt-4o-mini (current)": {"input": 0.15,  "output": 0.60},
    "gpt-4.1-mini":          {"input": 0.40,  "output": 1.60},
    "gpt-4.1-nano":          {"input": 0.10,  "output": 0.40},
    "gpt-4.5-mini (est.)":   {"input": 1.10,  "output": 4.40},
}
# Note: gpt-4.5-mini is not a released OpenAI product as of Jun 2026.
# The price used is a hypothetical estimate. gpt-4.1-nano is the real low-cost option.

print()
print("=== Cost comparison -- Nestle India FY2024 (one full pipeline run) ===")
print()
print("Total tokens:")
print(f"  Pass 1 input:    {total_p1_in_all:>10,}")
print(f"  Pass 1 output:   {total_p1_out_all:>10,}")
print(f"  Pass 2 input:    {total_p2_in:>10,}")
print(f"  Pass 2 output:   {total_p2_out:>10,}")
print(f"  TOTAL input:     {total_in:>10,}")
print(f"  TOTAL output:    {total_out:>10,}")
print()
print(f"  {'Model':<44}  {'Input':>10}  {'Output':>10}  {'Total':>10}")
print(f"  {'-'*44}  {'-'*10}  {'-'*10}  {'-'*10}")
per_run = {}
for name, p in models.items():
    ic = total_in  / 1_000_000 * p["input"]
    oc = total_out / 1_000_000 * p["output"]
    tc = ic + oc
    per_run[name] = tc
    print(f"  {name:<44}  ${ic:>9.4f}  ${oc:>9.4f}  ${tc:>9.4f}")

print()
print("Projected cost -- all 4 companies (3.5x Nestle tokens):")
print(f"  {'Model':<44}  {'Per run':>10}  {'4 cos':>10}  {'10 cos':>10}")
print(f"  {'-'*44}  {'-'*10}  {'-'*10}  {'-'*10}")
for name, tc in per_run.items():
    c4  = tc * 3.5
    c10 = tc * 3.5 / 4 * 10
    print(f"  {name:<44}  ${tc:>9.4f}  ${c4:>9.4f}  ${c10:>9.4f}")

print()
nano   = per_run["gpt-4.1-nano"]
mini   = per_run["gpt-4o-mini (current)"]
mini41 = per_run["gpt-4.1-mini"]
print("=== Quality vs cost recommendation ===")
print()
print(
    f"The absolute cost per Nestle run is tiny: gpt-4o-mini ${mini:.4f}, "
    f"gpt-4.1-nano ${nano:.4f}. The dollar difference between these two models "
    f"is under a cent per run and under ${nano/4*10:.2f} for ten full 4-company "
    f"reruns, making nano an easy cost-saving swap if quality holds. "
    f"gpt-4.1-mini at ${mini41:.4f}/run is ~{mini41/mini:.1f}x the current cost "
    f"and should only be considered if a side-by-side quality audit on dense ESG "
    f"tables or multi-year comparatives shows measurable extraction improvements "
    f"over gpt-4o-mini -- cost is not the constraint here, quality is. "
    f"Note: gpt-4.5-mini does not appear to be a released model as of June 2026; "
    f"the price used above is hypothetical. "
    f"Cost only becomes a real consideration beyond ~200 companies/month, at which "
    f"point gpt-4.1-nano would save roughly ${(mini-nano)/4*10*20:.0f}/month vs gpt-4o-mini "
    f"for 10-company monthly reruns."
)
