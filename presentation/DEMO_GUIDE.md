# BatteryOS — Demo & Presentation Guide

## Quick Start

### 1. Start the UI (for live demo)
```bash
cd src/ui
npm install  # if not already done
npm run dev
```
Open the URL shown in the terminal (usually `http://localhost:5173`).

### 2. Generate fresh demo data (optional)
```bash
# Solar flood day (default — great for showing arbitrage)
python3 demo_generator.py --profile solar --risk 0.5

# Winter peak day (sustained high prices)
python3 demo_generator.py --profile winter --risk 0.5

# Volatile day (spikes and crashes — shows robustness value)
python3 demo_generator.py --profile volatile --risk 0.5

# Risk-neutral comparison
python3 demo_generator.py --profile solar --risk 0.0

# Auto-start UI after generating
python3 demo_generator.py --profile solar --risk 0.5 --serve
```

### 3. Build for static hosting
```bash
cd src/ui
npm run build
# Serve dist/ folder with any static server
```

---

## Presentation Flow (15 minutes total)

### Part 1: The Story (Slides 1-4) — 2 minutes
1. **Title slide** — "BatteryOS: Intelligent dispatch optimization"
2. **Problem** — Batteries are dumb, markets are volatile
3. **Pain** — What happens without optimization (missed arbitrage, cycle waste, risk blindness)
4. **Solution** — One pipeline: data → features → forecast → optimize → profit

**Speaker notes:**
> "Greece now has a 15-minute Day-Ahead Market. A 100MW battery must make 96 decisions per day. Most operators use Excel. We built an optimizer that uses the same math as Tesla Autobidder."

---

### Part 2: The Optimizer (Slides 5-9) — 3 minutes
5. **Mean-CVaR** — Show the formula, explain λ (lambda)
6. **Risk profiles** — Same battery, different appetite. λ=0.5 is the sweet spot.
7. **Scenario reduction** — 1,000 paths → 20 scenarios. <1s solve time.
8. **Rainflow degradation** — Don't pretend aging is flat. Deep cycles cost 4x more.
9. **Robustness** — What if efficiency is 86% not 90%? We verify.

**Speaker notes:**
> "The key insight is Mean-CVaR. Most optimizers just maximize average profit. We also protect the worst 10% of days. That's the difference between surviving a bad month and going broke."

---

### Part 3: The Pipeline (Slides 10-11) — 2 minutes
10. **Step by step** — Ingest 7 data sources, engineer leakage-safe features, forecast with ML, optimize with physics constraints, backtest on history.
11. **Live MVP** — Transition to the dashboard.

---

### Part 4: LIVE DEMO (5 minutes) — THIS IS THE CORE

**Navigate to the dashboard at `http://localhost:5173`**

#### Minute 1 — Dashboard Overview
> "This is the actual optimizer output for April 29, 2026. A 100MW/200MWh lithium-ion battery."

**Show:**
- KPIs at top: Expected profit €22,606, Realized €22,400+, Worst-case €16,398
- Live dispatch chart: "Blue bars = charge, amber = discharge"
- Point out: "Charging at night when prices are ~70 EUR/MWh"

#### Minute 2 — The Two Peaks
> "The optimizer found two arbitrage opportunities."

**Morning peak (7:00-8:00):**
- "Discharged from 141 MWh down to 20 MWh during the morning price spike"
- "Prices went from 78 to 134 EUR/MWh — that's a €56 spread"

**Midday solar flood (12:00-14:00):**
- "Prices crashed to 47 EUR/MWh because solar flooded the grid"
- "The optimizer recharged the battery fully — from 20 MWh back to 180 MWh"
- "This is the arbitrage most manual operators miss"

**Evening peak (19:00-20:00):**
- "Discharged again at 178 EUR/MWh evening peak"
- "That's the second arbitrage cycle"

#### Minute 3 — State of Charge + Profit
**Switch to SoC chart:**
> "Watch the battery breathe. Full at night, empty at morning peak, full at midday, empty at evening peak."

**Switch to profit chart:**
> "Period profit in green/red. Cumulative profit line ends at €22,600. The optimizer captured 72% of what a perfect crystal ball would have made."

#### Minute 4 — Under the Hood (Analytics page)
**Click Analytics → Optimizer V1**

> "Let's look under the hood. The optimizer receives 20 price scenarios — each a full 96-period path with a probability weight."

**Scroll through workflow steps:**
1. **External scenarios** — Show the spaghetti chart
2. **Battery constraints** — Power, energy, efficiency, cycles
3. **Mean-CVaR objective** — "λ=0.5 means equal weight on average profit and tail protection"
4. **Dispatch schedule** — The charge/discharge bars
5. **Feasibility** — "Every schedule is checked against physics. No impossible plans."
6. **Economics** — Period profit calculation
7. **Rainflow** — "Aging cost is €861. Without rainflow, we'd underestimate by 3x."
8. **Robustness** — "Even if our battery is 5% less efficient than spec, we still make €16k."

#### Minute 5 — Business Story (Pitch page)
**Click Pitch in sidebar**

> "Who pays for this? Greek BESS operators. Greece targets 3GW of batteries by 2030."

**Show:**
- TAM card: "€20-50M/year opportunity in Greece alone"
- Pricing: "SaaS at €0.50-2.00 per MWh. For a 100MW battery, that's €100-400/day."
- ROI: "15% profit uplift on €5M annual revenue = €750k extra. Customer pays €146k. Net gain €604k."
- Moat: "Multi-source data, leakage-safe features, cross-border signals, backtested economics"
- Ask: "We need introductions to Greek BESS operators and historical HEnEx data."

---

### Part 5: Closing (Slides 18-20) — 3 minutes
- **The ask** — Introductions, data, mentorship, funding
- **Team** — Who you are
- **Closing** — "BatteryOS: Turn market uncertainty into battery profit."

---

## Demo Data Scenarios

| Profile | Best For | Expected Profit | Key Feature |
|---|---|---|---|
| `solar` (default) | Showing arbitrage | €22,606 | Midday price crash + evening peak |
| `winter` | Sustained high prices | €22,056 | Long discharge window |
| `volatile` | Showing robustness value | €38,134 | Multiple spikes and crashes |
| `solar --risk 0.0` | Risk-neutral comparison | €22,673 | More aggressive dispatch |

---

## Keyboard Shortcuts During Demo

- **Arrow Left/Right** — Navigate between 15-minute periods on Dashboard
- No other shortcuts needed — everything is click-based

---

## Troubleshooting

### UI won't start
```bash
cd src/ui
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### Demo data looks wrong
```bash
python3 demo_generator.py --profile solar --risk 0.5
# Check src/ui/public/data/schedule.json exists and has 96 rows
```

### Build fails
Make sure you're using a recent Node version (18+):
```bash
node -v
```

---

## Files You Need

| File | Purpose |
|---|---|
| `presentation/BatteryOS_Presentation.md` | Complete Canva slide content |
| `demo_generator.py` | Generate synthetic demo data |
| `src/ui/src/main.jsx` | React dashboard with Pitch page |
| `src/ui/src/styles.css` | Dashboard styles |
| `src/ui/public/data/*.json` | Demo artifacts consumed by UI |

---

## One-Liner Pitch

> "BatteryOS is an intelligent dispatch optimizer for Greek battery operators. It uses Mean-CVaR stochastic optimization — the same math as Tesla Autobidder — to turn uncertain price forecasts into profitable, physically feasible battery schedules. We don't just predict prices. We optimize batteries for profit."

---

**Good luck with the presentation! 🚀**
