# Consumer Ontology Seed Notes

This seed was built from recurring wording and concept families observed across four consumer-company report JSONs:
- Coca-Cola
- Nike
- PepsiCo
- Target

Design choices:
- Keep financial backbone concepts separate from operational concepts.
- Treat dimensions as first-class registry artifacts, not ad hoc labels.
- Treat drivers as a separate causal vocabulary, not as metrics.
- Use this as a v0 seed, not a final ontology.

Most reliable early families:
- Financial backbone: revenue/sales, gross margin, operating income/profit, cash flow, inventory, EPS.
- Operational performance: organic growth, pricing, volume, mix.
- Channel/route to market: digital, direct-to-consumer, wholesale, store traffic.
- Dimension axes: geography, segment, channel, brand, category.
- Driver families: pricing, volume, mix, demand, inflation, commodity cost, tariff, digital shift, inventory actions, productivity.

Recommended next step:
Use these seeds to create a shortlist retrieval layer for Pass 2/Pass 3 rather than sending a large flat registry to the model.
