#!/usr/bin/env python3
"""PolyArb Daily Performance Report Generator.

Fetches data from the dashboard API and produces both a markdown summary
and a self-contained HTML report with inline charts.
"""

import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

API_BASE = "http://$NAS_HOST:8081/api"
REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(path: str) -> dict:
    url = f"{API_BASE}{path}"
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_all():
    stats = api_get("/stats")
    opps = api_get("/opportunities?limit=500")
    trades = api_get("/trades?limit=500")
    pairs = api_get("/pairs?limit=200")
    history = api_get("/portfolio/history?hours=24")
    return stats, opps, trades, pairs, history


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def analyze_opportunities(opps_data):
    opps = opps_data.get("opportunities", [])
    if not opps:
        return {"total": 0}

    statuses = Counter(o["status"] for o in opps)
    types = Counter(o["type"] for o in opps)
    dep_types = Counter(o["pair"]["dependency_type"] for o in opps if o.get("pair"))

    profits = [o["estimated_profit"] for o in opps if o["estimated_profit"] and o["estimated_profit"] > 0]
    theo_profits = [o["theoretical_profit"] for o in opps if o["theoretical_profit"] and o["theoretical_profit"] > 0]

    convergence_rates = {}
    for status, count in statuses.items():
        convergence_rates[status] = count

    gaps = [o["bregman_gap"] for o in opps if o.get("bregman_gap") is not None]
    iters = [o["fw_iterations"] for o in opps if o.get("fw_iterations") is not None]

    return {
        "total": len(opps),
        "statuses": dict(statuses),
        "types": dict(types),
        "dependency_types": dict(dep_types),
        "profitable_count": len(profits),
        "avg_estimated_profit": sum(profits) / len(profits) if profits else 0,
        "max_estimated_profit": max(profits) if profits else 0,
        "total_estimated_profit": sum(profits),
        "avg_theoretical_profit": sum(theo_profits) / len(theo_profits) if theo_profits else 0,
        "avg_bregman_gap": sum(gaps) / len(gaps) if gaps else 0,
        "median_bregman_gap": sorted(gaps)[len(gaps) // 2] if gaps else 0,
        "avg_fw_iterations": sum(iters) / len(iters) if iters else 0,
        "convergence_rate": statuses.get("optimized", 0) / len(opps) * 100 if opps else 0,
        "simulated_rate": statuses.get("simulated", 0) / len(opps) * 100 if opps else 0,
    }


def analyze_trades(trades_data):
    trades = trades_data.get("trades", [])
    if not trades:
        return {"total": 0}

    sides = Counter(t["side"] for t in trades)
    total_volume = sum(t["size"] * t["entry_price"] for t in trades)
    total_fees = sum(t["fees"] for t in trades)
    slippages = [t["slippage"] for t in trades if t["slippage"] is not None]
    sizes = [t["size"] for t in trades]

    return {
        "total": len(trades),
        "sides": dict(sides),
        "total_volume": total_volume,
        "total_fees": total_fees,
        "avg_slippage": sum(slippages) / len(slippages) if slippages else 0,
        "max_slippage": max(slippages) if slippages else 0,
        "avg_size": sum(sizes) / len(sizes) if sizes else 0,
        "max_size": max(sizes) if sizes else 0,
    }


def analyze_pairs(pairs_data):
    pairs = pairs_data.get("pairs", [])
    if not pairs:
        return {"total": 0}

    dep_types = Counter(p["dependency_type"] for p in pairs)
    confidences = [p["confidence"] for p in pairs if p["confidence"] is not None]
    opp_counts = [p["opportunity_count"] for p in pairs if p.get("opportunity_count") is not None]
    verified_count = sum(1 for p in pairs if p.get("verified"))

    return {
        "total": len(pairs),
        "dependency_types": dict(dep_types),
        "verified_count": verified_count,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else 0,
        "avg_opportunities_per_pair": sum(opp_counts) / len(opp_counts) if opp_counts else 0,
        "most_active_pair": max(pairs, key=lambda p: p.get("opportunity_count", 0)) if pairs else None,
    }


def analyze_portfolio(history_data, stats):
    snapshots = history_data.get("history", [])
    portfolio = stats.get("portfolio", {}) or {}

    if not snapshots:
        return {
            "current_value": portfolio.get("total_value", 0),
            "pnl": portfolio.get("realized_pnl", 0),
            "total_trades": portfolio.get("total_trades", 0),
            "winning_trades": portfolio.get("winning_trades", 0),
            "snapshots": 0,
        }

    values = [s["total_value"] for s in snapshots]
    pnls = [s["realized_pnl"] for s in snapshots]

    return {
        "current_value": values[-1] if values else 0,
        "start_value": values[0] if values else 0,
        "pnl_change_24h": (pnls[-1] - pnls[0]) if len(pnls) >= 2 else 0,
        "max_value": max(values) if values else 0,
        "min_value": min(values) if values else 0,
        "drawdown": (max(values) - min(values)) / max(values) * 100 if values and max(values) > 0 else 0,
        "pnl": portfolio.get("realized_pnl", 0),
        "total_trades": portfolio.get("total_trades", 0),
        "winning_trades": portfolio.get("winning_trades", 0),
        "win_rate": portfolio.get("winning_trades", 0) / portfolio.get("total_trades", 1) * 100 if portfolio.get("total_trades", 0) > 0 else 0,
        "snapshots": len(snapshots),
        "history": snapshots,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_markdown(stats, opp_analysis, trade_analysis, pair_analysis, port_analysis):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# PolyArb Daily Report — {now}",
        "",
        "## Portfolio Summary",
        f"- **Current Value**: ${port_analysis['current_value']:,.2f}",
        f"- **Realized PnL**: ${port_analysis['pnl']:,.2f}",
        f"- **Win Rate**: {port_analysis['win_rate']:.1f}% ({port_analysis['winning_trades']}/{port_analysis['total_trades']})",
    ]

    if port_analysis.get("drawdown"):
        lines.append(f"- **24h Drawdown**: {port_analysis['drawdown']:.2f}%")

    lines += [
        "",
        "## System Overview",
        f"- **Active Markets**: {stats.get('active_markets', 0):,}",
        f"- **Detected Pairs**: {stats.get('market_pairs', 0)}",
        f"- **Total Opportunities**: {stats.get('total_opportunities', 0)}",
        f"- **Total Trades**: {stats.get('total_trades', 0)}",
        "",
        "## Opportunity Analysis",
        f"- **Recent Opportunities**: {opp_analysis['total']}",
        f"- **Convergence Rate**: {opp_analysis.get('convergence_rate', 0):.1f}% optimized",
        f"- **Simulation Rate**: {opp_analysis.get('simulated_rate', 0):.1f}% simulated",
        f"- **Profitable**: {opp_analysis.get('profitable_count', 0)} opportunities with est. profit > 0",
        f"- **Avg Estimated Profit**: ${opp_analysis.get('avg_estimated_profit', 0):.4f}",
        f"- **Max Estimated Profit**: ${opp_analysis.get('max_estimated_profit', 0):.4f}",
        f"- **Avg Bregman Gap**: {opp_analysis.get('avg_bregman_gap', 0):.6f}",
        f"- **Avg FW Iterations**: {opp_analysis.get('avg_fw_iterations', 0):.0f}",
    ]

    if opp_analysis.get("statuses"):
        lines.append("")
        lines.append("**Status Breakdown:**")
        for status, count in sorted(opp_analysis["statuses"].items(), key=lambda x: -x[1]):
            pct = count / opp_analysis["total"] * 100
            lines.append(f"  - {status}: {count} ({pct:.0f}%)")

    if opp_analysis.get("dependency_types"):
        lines.append("")
        lines.append("**Dependency Types:**")
        for dep, count in sorted(opp_analysis["dependency_types"].items(), key=lambda x: -x[1]):
            lines.append(f"  - {dep}: {count}")

    lines += [
        "",
        "## Trade Execution",
        f"- **Recent Trades**: {trade_analysis['total']}",
        f"- **Total Volume**: ${trade_analysis.get('total_volume', 0):.4f}",
        f"- **Total Fees**: ${trade_analysis.get('total_fees', 0):.4f}",
        f"- **Avg Slippage**: {trade_analysis.get('avg_slippage', 0):.4f}",
        f"- **Max Slippage**: {trade_analysis.get('max_slippage', 0):.4f}",
        f"- **Avg Position Size**: {trade_analysis.get('avg_size', 0):.4f}",
    ]

    if trade_analysis.get("sides"):
        lines.append(f"- **Buy/Sell Split**: {trade_analysis['sides'].get('BUY', 0)} buys / {trade_analysis['sides'].get('SELL', 0)} sells")

    lines += [
        "",
        "## Pair Detection",
        f"- **Total Pairs**: {pair_analysis['total']}",
        f"- **Verified**: {pair_analysis.get('verified_count', 0)}",
        f"- **Avg Confidence**: {pair_analysis.get('avg_confidence', 0):.2f}",
        f"- **Avg Opportunities/Pair**: {pair_analysis.get('avg_opportunities_per_pair', 0):.1f}",
    ]

    if pair_analysis.get("most_active_pair"):
        p = pair_analysis["most_active_pair"]
        ma = p.get("market_a", {}) or {}
        mb = p.get("market_b", {}) or {}
        lines.append(f"- **Most Active Pair**: {ma.get('question', 'N/A')[:60]} ↔ {mb.get('question', 'N/A')[:60]} ({p.get('opportunity_count', 0)} opps)")

    # Actionable insights
    lines += [
        "",
        "## Key Observations",
    ]

    insights = []
    if opp_analysis.get("convergence_rate", 0) < 50:
        unconverged = opp_analysis.get("statuses", {}).get("unconverged", 0)
        insights.append(f"⚠️  Low convergence rate ({opp_analysis['convergence_rate']:.0f}%). {unconverged} opportunities failed to converge — consider increasing FW_MAX_ITERATIONS or relaxing FW_GAP_TOLERANCE.")

    if opp_analysis.get("avg_bregman_gap", 0) > 0.01:
        insights.append(f"⚠️  High average Bregman gap ({opp_analysis['avg_bregman_gap']:.4f}). Optimizer is not finding tight solutions.")

    if trade_analysis.get("avg_slippage", 0) > 0.01:
        insights.append(f"⚠️  High average slippage ({trade_analysis['avg_slippage']:.4f}). Consider reducing MAX_POSITION_SIZE or targeting higher-liquidity markets.")

    if port_analysis.get("win_rate", 0) == 0 and port_analysis.get("total_trades", 0) > 20:
        insights.append("⚠️  Win rate is 0% despite significant trade count. Review trade resolution logic and PnL accounting.")

    if opp_analysis.get("profitable_count", 0) / max(opp_analysis.get("total", 1), 1) < 0.1:
        insights.append(f"📊 Only {opp_analysis.get('profitable_count', 0)}/{opp_analysis['total']} opportunities have positive estimated profit. Market efficiency may be high or edge detection needs tuning.")

    if port_analysis.get("drawdown", 0) > 5:
        insights.append(f"📉 24h drawdown is {port_analysis['drawdown']:.1f}%. Monitor risk exposure.")

    if not insights:
        insights.append("✅ System operating within normal parameters.")

    for insight in insights:
        lines.append(f"- {insight}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def generate_html(stats, opp_analysis, trade_analysis, pair_analysis, port_analysis, history_data):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    snapshots = history_data.get("history", [])

    # Prepare chart data
    chart_labels = json.dumps([s["timestamp"][11:16] for s in snapshots])
    chart_values = json.dumps([s["total_value"] for s in snapshots])
    chart_pnl = json.dumps([s["realized_pnl"] for s in snapshots])

    # Status breakdown for donut chart
    status_labels = json.dumps(list(opp_analysis.get("statuses", {}).keys()))
    status_values = json.dumps(list(opp_analysis.get("statuses", {}).values()))

    dep_labels = json.dumps(list(opp_analysis.get("dependency_types", {}).keys()))
    dep_values = json.dumps(list(opp_analysis.get("dependency_types", {}).values()))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PolyArb Daily Report — {now}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0f; color: #e0e0e0; padding: 24px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ color: #00ff88; font-size: 28px; margin-bottom: 4px; }}
  .subtitle {{ color: #888; font-size: 14px; margin-bottom: 32px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #14141f; border: 1px solid #2a2a3a; border-radius: 12px; padding: 20px; }}
  .card h2 {{ color: #00ff88; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }}
  .metric {{ margin-bottom: 12px; }}
  .metric .label {{ color: #888; font-size: 12px; }}
  .metric .value {{ font-size: 24px; font-weight: 700; color: #fff; }}
  .metric .value.green {{ color: #00ff88; }}
  .metric .value.red {{ color: #ff4444; }}
  .metric .value.yellow {{ color: #ffaa00; }}
  .metric .value.sm {{ font-size: 16px; }}
  .chart-container {{ background: #14141f; border: 1px solid #2a2a3a; border-radius: 12px; padding: 20px; margin-bottom: 24px; }}
  .chart-container h2 {{ color: #00ff88; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }}
  .chart-row {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 24px; }}
  .insight {{ background: #1a1a2a; border-left: 3px solid #ffaa00; padding: 12px 16px; margin-bottom: 8px; border-radius: 0 8px 8px 0; font-size: 14px; }}
  .insight.ok {{ border-color: #00ff88; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; color: #888; padding: 8px 12px; border-bottom: 1px solid #2a2a3a; font-size: 11px; text-transform: uppercase; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #1a1a2a; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .badge.optimized {{ background: rgba(0,255,136,0.15); color: #00ff88; }}
  .badge.simulated {{ background: rgba(0,136,255,0.15); color: #0088ff; }}
  .badge.unconverged {{ background: rgba(255,68,68,0.15); color: #ff4444; }}
  .badge.detected {{ background: rgba(255,170,0,0.15); color: #ffaa00; }}
  @media (max-width: 768px) {{ .chart-row {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <h1>PolyArb Daily Report</h1>
  <p class="subtitle">{now} &middot; Paper Trading</p>

  <!-- KPI Cards -->
  <div class="grid">
    <div class="card">
      <h2>Portfolio</h2>
      <div class="metric">
        <div class="label">Total Value</div>
        <div class="value">${port_analysis['current_value']:,.2f}</div>
      </div>
      <div class="metric">
        <div class="label">Realized PnL</div>
        <div class="value {'green' if port_analysis['pnl'] >= 0 else 'red'}">${port_analysis['pnl']:,.2f}</div>
      </div>
      <div class="metric">
        <div class="label">Win Rate</div>
        <div class="value sm">{port_analysis['win_rate']:.1f}% ({port_analysis['winning_trades']}/{port_analysis['total_trades']})</div>
      </div>
    </div>
    <div class="card">
      <h2>Markets</h2>
      <div class="metric">
        <div class="label">Active Markets</div>
        <div class="value">{stats.get('active_markets', 0):,}</div>
      </div>
      <div class="metric">
        <div class="label">Detected Pairs</div>
        <div class="value sm">{stats.get('market_pairs', 0)}</div>
      </div>
      <div class="metric">
        <div class="label">Avg Confidence</div>
        <div class="value sm">{pair_analysis.get('avg_confidence', 0):.0%}</div>
      </div>
    </div>
    <div class="card">
      <h2>Opportunities</h2>
      <div class="metric">
        <div class="label">Total</div>
        <div class="value">{opp_analysis['total']}</div>
      </div>
      <div class="metric">
        <div class="label">Convergence Rate</div>
        <div class="value sm {'green' if opp_analysis.get('convergence_rate', 0) > 50 else 'yellow'}">{opp_analysis.get('convergence_rate', 0):.0f}%</div>
      </div>
      <div class="metric">
        <div class="label">Avg Est. Profit</div>
        <div class="value sm">${opp_analysis.get('avg_estimated_profit', 0):.4f}</div>
      </div>
    </div>
    <div class="card">
      <h2>Execution</h2>
      <div class="metric">
        <div class="label">Trades</div>
        <div class="value">{trade_analysis['total']}</div>
      </div>
      <div class="metric">
        <div class="label">Total Volume</div>
        <div class="value sm">${trade_analysis.get('total_volume', 0):.2f}</div>
      </div>
      <div class="metric">
        <div class="label">Avg Slippage</div>
        <div class="value sm {'green' if trade_analysis.get('avg_slippage', 0) < 0.005 else 'yellow'}">{trade_analysis.get('avg_slippage', 0):.4f}</div>
      </div>
    </div>
  </div>

  <!-- Charts -->
  <div class="chart-row">
    <div class="chart-container">
      <h2>Portfolio Value (24h)</h2>
      <canvas id="portfolioChart" height="200"></canvas>
    </div>
    <div class="chart-container">
      <h2>Opportunity Status</h2>
      <canvas id="statusChart" height="200"></canvas>
    </div>
  </div>

  <div class="chart-row">
    <div class="chart-container">
      <h2>Realized PnL (24h)</h2>
      <canvas id="pnlChart" height="200"></canvas>
    </div>
    <div class="chart-container">
      <h2>Dependency Types</h2>
      <canvas id="depChart" height="200"></canvas>
    </div>
  </div>

  <!-- Optimizer Performance -->
  <div class="chart-container">
    <h2>Optimizer Performance</h2>
    <table>
      <tr>
        <th>Metric</th><th>Value</th><th>Assessment</th>
      </tr>
      <tr>
        <td>Avg FW Iterations</td>
        <td>{opp_analysis.get('avg_fw_iterations', 0):.0f} / 200</td>
        <td>{'🟢 Good' if opp_analysis.get('avg_fw_iterations', 0) < 150 else '🟡 High — many hitting max iterations'}</td>
      </tr>
      <tr>
        <td>Avg Bregman Gap</td>
        <td>{opp_analysis.get('avg_bregman_gap', 0):.6f}</td>
        <td>{'🟢 Tight' if opp_analysis.get('avg_bregman_gap', 0) < 0.005 else '🟡 Loose — consider tuning tolerance'}</td>
      </tr>
      <tr>
        <td>Convergence Rate</td>
        <td>{opp_analysis.get('convergence_rate', 0):.0f}%</td>
        <td>{'🟢 Healthy' if opp_analysis.get('convergence_rate', 0) > 60 else '🟡 Low — review difficult pairs'}</td>
      </tr>
      <tr>
        <td>Profitable Opps</td>
        <td>{opp_analysis.get('profitable_count', 0)} / {opp_analysis['total']}</td>
        <td>{'🟢 Good signal' if opp_analysis.get('profitable_count', 0) > opp_analysis['total'] * 0.2 else '🟡 Low edge detection rate'}</td>
      </tr>
      <tr>
        <td>Avg Slippage</td>
        <td>{trade_analysis.get('avg_slippage', 0):.4f}</td>
        <td>{'🟢 Minimal' if trade_analysis.get('avg_slippage', 0) < 0.005 else '🟡 Review position sizing'}</td>
      </tr>
      <tr>
        <td>Fee Drag</td>
        <td>${trade_analysis.get('total_fees', 0):.4f}</td>
        <td>{'🟢 Manageable' if trade_analysis.get('total_fees', 0) < 10 else '🟡 Fees eating into profit'}</td>
      </tr>
    </table>
  </div>

</div>

<script>
  Chart.defaults.color = '#888';
  Chart.defaults.borderColor = '#2a2a3a';

  // Portfolio Value Chart
  new Chart(document.getElementById('portfolioChart'), {{
    type: 'line',
    data: {{
      labels: {chart_labels},
      datasets: [{{
        label: 'Portfolio Value',
        data: {chart_values},
        borderColor: '#00ff88',
        backgroundColor: 'rgba(0,255,136,0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 0,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 12 }} }},
        y: {{ beginAtZero: false }}
      }}
    }}
  }});

  // PnL Chart
  new Chart(document.getElementById('pnlChart'), {{
    type: 'line',
    data: {{
      labels: {chart_labels},
      datasets: [{{
        label: 'Realized PnL',
        data: {chart_pnl},
        borderColor: '#0088ff',
        borderDash: [5, 5],
        tension: 0.3,
        pointRadius: 0,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 12 }} }}
      }}
    }}
  }});

  // Status Donut
  new Chart(document.getElementById('statusChart'), {{
    type: 'doughnut',
    data: {{
      labels: {status_labels},
      datasets: [{{
        data: {status_values},
        backgroundColor: ['#00ff88', '#0088ff', '#ff4444', '#ffaa00', '#aa44ff'],
        borderWidth: 0,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 12 }} }} }},
      cutout: '60%',
    }}
  }});

  // Dependency Types Donut
  new Chart(document.getElementById('depChart'), {{
    type: 'doughnut',
    data: {{
      labels: {dep_labels},
      datasets: [{{
        data: {dep_values},
        backgroundColor: ['#00ff88', '#0088ff', '#ffaa00', '#ff4444', '#aa44ff'],
        borderWidth: 0,
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 12 }} }} }},
      cutout: '60%',
    }}
  }});
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Fetching data from PolyArb API...")
    try:
        stats, opps, trades, pairs, history = fetch_all()
    except URLError as e:
        print(f"ERROR: Could not connect to API at {API_BASE}: {e}")
        sys.exit(1)

    print("Analyzing data...")
    opp_analysis = analyze_opportunities(opps)
    trade_analysis = analyze_trades(trades)
    pair_analysis = analyze_pairs(pairs)
    port_analysis = analyze_portfolio(history, stats)

    # Ensure reports directory exists
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")

    # Write markdown
    md = generate_markdown(stats, opp_analysis, trade_analysis, pair_analysis, port_analysis)
    md_path = REPORT_DIR / f"report-{date_str}.md"
    md_path.write_text(md)
    print(f"Markdown report: {md_path}")

    # Write HTML
    html = generate_html(stats, opp_analysis, trade_analysis, pair_analysis, port_analysis, history)
    html_path = REPORT_DIR / f"report-{date_str}.html"
    html_path.write_text(html)
    print(f"HTML report: {html_path}")

    # Print summary to stdout for the scheduled task notification
    print("\n" + "=" * 60)
    print(md)

    return md, html_path


if __name__ == "__main__":
    main()
