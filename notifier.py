import os
import requests
from datetime import datetime, timezone


def _webhook() -> str | None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        print("DISCORD_WEBHOOK_URL not set — skipping Discord notification")
    return url


def _post(payload: dict):
    url = _webhook()
    if not url:
        return
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code not in (200, 204):
        print(f"Discord error {resp.status_code}: {resp.text}")


# ── Competition mode: single best trade alert ─────────────────────────────────

def send_best_trade_alert(best: dict, alternatives: list[dict] | None = None):
    """One bold embed for the single best trade, plus runner-up alternatives."""
    is_future = best.get("instrument_type") == "future"
    is_buy    = best["direction"] == "BUY"
    qty_label = "contracts" if is_future else "shares"
    unit      = "" if is_future else "$"
    name      = best.get("display_name", best["ticker"])
    venue     = "Futures" if is_future else "Stock"

    color = 0x00C853 if is_buy else 0xF44336
    emoji = "🟢" if is_buy else "🔴"

    strat_lines = []
    for t in best["triggered"]:
        sign = "▲" if t["score"] > 0 else "▼"
        for sig in t["signals"]:
            strat_lines.append(f"{sign} **{t['name']}**: {sig}")
    strat_text = "\n".join(strat_lines[:8]) or "—"

    target_str = (
        f"**{best['target']:,.2f}** (+{best.get('reward_points',0):.2f} pts)" if is_future
        else f"**${best['target']:,.2f}** (+{best['target_pct']:.1f}%)"
    )
    stop_str = (
        f"**{best['stop_loss']:,.2f}** (-{best.get('risk_points',0):.2f} pts)" if is_future
        else f"**${best['stop_loss']:,.2f}** (-{best['stop_pct']:.1f}%)"
    )
    entry_str = f"**{best['entry']:,.2f}**" if is_future else f"**${best['entry']:,.2f}**"

    alt_text = ""
    if alternatives:
        alt_lines = []
        for a in alternatives:
            a_emoji = "🟢" if a["direction"] == "BUY" else "🔴"
            a_name  = a.get("display_name", a["ticker"])
            alt_lines.append(
                f"{a_emoji} {a_name} {a['direction']} — comp score {a['competition_score']:.1f}, "
                f"R:R {a['rr_ratio']:.1f}:1"
            )
        alt_text = "\n".join(alt_lines)

    fields = [
        {"name": "📥 Entry",  "value": entry_str,  "inline": True},
        {"name": "🎯 Target", "value": target_str,  "inline": True},
        {"name": "🛑 Stop",   "value": stop_str,    "inline": True},
        {"name": "⚖️ R:R",    "value": f"**{best['rr_ratio']:.1f}:1**", "inline": True},
        {"name": "🏆 Comp Score", "value": f"**{best['competition_score']:.1f}**", "inline": True},
        {"name": "📊 RSI",    "value": f"{best['rsi']:.1f}" if best.get("rsi") else "N/A", "inline": True},
        {"name": "💰 Position",
         "value": f"${best['risk_usd']:.2f} risk  ·  {best['shares']:.4f} {qty_label}  ·  ${best['position_usd']:,.2f} notional",
         "inline": False},
        {"name": f"📈 Strategies (score {best['strategy_score']:+.1f})",
         "value": strat_text, "inline": False},
        {"name": "📰 News", "value": f"**{best['news_sentiment']}** ({best['news_score']:+.1f})", "inline": False},
    ]
    if alt_text:
        fields.append({"name": "🥈 Runner-up Alternatives", "value": alt_text, "inline": False})

    embed = {
        "title": f"⚡ BEST TRADE RIGHT NOW — {emoji} {best['direction']} {name} ({venue})",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
        "footer": {
            "text": (
                f"Ranked across stocks + futures · 5×ATR target / 1×ATR stop · "
                "NOT financial advice — you decide"
            )
        },
    }
    _post({"embeds": [embed]})
    print(f"  ✓ Discord alert sent — BEST TRADE: {best['ticker']} {best['direction']}")


# ── Main trade alert ───────────────────────────────────────────────────────────

def send_trade_alert(setup: dict):
    ticker     = setup["ticker"]
    direction  = setup["direction"]
    mode       = setup.get("mode", "market")
    is_futures = setup.get("instrument_type") == "future"
    entry      = setup["entry"]
    stop       = setup["stop_loss"]
    target     = setup["target"]
    rr         = setup["rr_ratio"]
    rsi        = setup["rsi"]
    atr        = setup["atr"]
    risk_usd   = setup["risk_usd"]
    shares     = setup["shares"]              # contracts, for futures
    pos_usd    = setup["position_usd"]
    reason     = setup["reason"]
    score      = setup["strategy_score"]
    triggered  = setup["triggered"]
    sentiment  = setup["news_sentiment"]
    articles   = setup["news_articles"]
    key_level  = setup.get("key_level")
    pm         = setup.get("premarket") or {}
    stop_pct   = setup.get("stop_pct", 0)
    tgt_pct    = setup.get("target_pct", 5.0)
    display    = setup.get("display_name", ticker)

    is_buy        = direction == "BUY"
    is_premarket  = mode == "premarket"
    color         = 0x00C853 if is_buy else 0xF44336
    emoji         = "🟢" if is_buy else "🔴"
    dir_label     = "BUY / LONG" if is_buy else "SELL / SHORT"
    mode_label    = (
        "🌐 FUTURES" if is_futures else
        "⏰ PRE-MARKET" if is_premarket else
        "📈 MARKET"
    )
    qty_label  = "contracts" if is_futures else "shares"
    venue      = "Futures" if is_futures else "NASDAQ"

    # Futures use point-based target/stop, not %
    target_value_str = (
        f"**{target:,.2f}** (+{setup.get('reward_points',0):.2f} pts)" if is_futures
        else f"**${target:,.2f}** (+{tgt_pct:.0f}%)"
    )
    stop_value_str = (
        f"**{stop:,.2f}** (-{setup.get('risk_points',0):.2f} pts)" if is_futures
        else f"**${stop:,.2f}** (-{stop_pct:.1f}%)"
    )
    entry_value_str = f"**{entry:,.2f}**" if is_futures else f"**${entry:,.2f}**"

    # ── Strategy signals ───────────────────────────────────────────────────────
    strat_lines = []
    for t in triggered:
        sign = "▲" if t["score"] > 0 else "▼"
        for sig in t["signals"]:
            strat_lines.append(f"{sign} **{t['name']}**: {sig}")
    strat_text = "\n".join(strat_lines[:10]) or "No specific signal details"

    # ── News headlines ─────────────────────────────────────────────────────────
    relevant = [a for a in articles if (a["score"] > 0 if is_buy else a["score"] < 0)]
    news_text = (
        "\n".join(
            f"• [{a['title'][:75]}]({a['link']}) — *{a['source']}*"
            for a in relevant[:4]
        ) if relevant else f"{sentiment} market sentiment."
    )

    # ── Pre-market block ────────────────────────────────────────────────────────
    pm_change  = pm.get("pre_change_pct", 0)
    pm_price   = pm.get("pre_price")
    pm_vol_pct = pm.get("vol_ratio_pct", 0)
    prev_close = pm.get("prev_close")

    pm_line = ""
    if is_premarket and pm_price:
        sign   = "+" if pm_change >= 0 else ""
        pm_line = (
            f"**Pre-mkt:** ${pm_price:.2f} ({sign}{pm_change:.2f}% vs close ${prev_close:.2f})"
        )
        if pm_vol_pct:
            pm_line += f"  |  vol {pm_vol_pct:.0f}% of avg"

    key_str = f"${key_level:,.2f}" if key_level else "N/A"

    fields = []

    if pm_line:
        fields.append({"name": "🌅 Pre-Market Data", "value": pm_line, "inline": False})

    fields += [
        {"name": "📥 Entry",     "value": entry_value_str,        "inline": True},
        {"name": "🎯 Target",    "value": target_value_str,       "inline": True},
        {"name": "🛑 Stop Loss", "value": stop_value_str,         "inline": True},
        {"name": "⚖️ R:R",       "value": f"**{rr:.1f}:1**",        "inline": True},
        {"name": "📊 RSI (14)",  "value": f"{rsi:.1f}" if rsi else "N/A",  "inline": True},
        {"name": "🔑 Key Level", "value": key_str,                  "inline": True},
        {"name": "💰 Position",
         "value": (
             f"${risk_usd:.2f} risk  ·  {shares:.2f} {qty_label}  ·  ${pos_usd:,.2f} notional"
         ),
         "inline": False},
        {"name": f"📈 Strategies  (score {score:+.1f})", "value": strat_text, "inline": False},
        {"name": "📰 News Sentiment",
         "value": f"**{sentiment}** (score {setup['news_score']:+.1f})", "inline": False},
        {"name": "🗞️ Headlines", "value": news_text, "inline": False},
    ]

    embed = {
        "title":     f"{emoji} {mode_label}  {dir_label} — {display} ({venue})",
        "color":     color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields":    fields,
        "footer":    {
            "text": (
                f"ATR {atr}  ·  {reason[:110]}  ·  "
                "NOT financial advice — execute at own discretion"
            )
        },
    }

    _post({"embeds": [embed]})
    print(f"  ✓ Discord alert sent  {ticker} {direction} ({mode})")


# ── Pre-market morning briefing ────────────────────────────────────────────────

def send_premarket_briefing(setups: list[dict], market_summary: dict):
    """
    Single embed sent at 08:00 ET summarising all pre-market setups
    and the overnight macro picture.
    """
    url = _webhook()
    if not url or not setups:
        return

    lines = []
    for s in setups:
        pm = s.get("premarket") or {}
        pm_change = pm.get("pre_change_pct", 0)
        pm_sign   = "+" if pm_change >= 0 else ""
        emoji     = "🟢" if s["direction"] == "BUY" else "🔴"
        strats    = ", ".join(t["name"] for t in s["triggered"][:3])
        lines.append(
            f"{emoji} **{s['ticker']}** {s['direction']} "
            f"  Entry ${s['entry']:,.2f} → Target ${s['target']:,.2f}  "
            f"  Stop ${s['stop_loss']:,.2f}  |  R:R {s['rr_ratio']:.1f}:1  "
            f"  |  Pre-mkt {pm_sign}{pm_change:.1f}%"
        )
        lines.append(f"    ↳ {strats}  ·  News: {s['news_sentiment']}")

    qqq_pm  = market_summary.get("QQQ_pm_change", 0)
    spy_pm  = market_summary.get("SPY_pm_change", 0)
    qqq_sign = "+" if qqq_pm >= 0 else ""
    spy_sign = "+" if spy_pm >= 0 else ""

    macro = (
        f"**QQQ pre-mkt:** {qqq_sign}{qqq_pm:.2f}%   "
        f"**SPY pre-mkt:** {spy_sign}{spy_pm:.2f}%"
    )

    embed = {
        "title":       f"🌅 Pre-Market Briefing — {len(setups)} Setup(s)",
        "description": macro + "\n\n" + "\n".join(lines),
        "color":       0xF59E0B,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "footer":      {
            "text": (
                "Scanned 8:00 ET  ·  Market opens 9:30 ET  ·  "
                "5% target  ·  NOT financial advice"
            )
        },
    }
    _post({"embeds": [embed]})


# ── Market-hours summary ───────────────────────────────────────────────────────

def send_daily_summary(setups: list[dict]):
    url = _webhook()
    if not url or not setups:
        return

    lines = []
    any_futures = any(s.get("instrument_type") == "future" for s in setups)
    for s in setups:
        emoji   = "🟢" if s["direction"] == "BUY" else "🔴"
        strats  = ", ".join(t["name"] for t in s["triggered"][:3])
        name    = s.get("display_name", s["ticker"])
        is_fut  = s.get("instrument_type") == "future"
        prefix  = "$" if not is_fut else ""
        qty_lbl = "ct" if is_fut else "sh"
        lines.append(
            f"{emoji} **{name}** {s['direction']} @ {prefix}{s['entry']:,.2f} "
            f"→ {prefix}{s['target']:,.2f}  stop {prefix}{s['stop_loss']:,.2f}  "
            f"R:R {s['rr_ratio']:.1f}:1  score {s['strategy_score']:+.1f}  "
            f"({s['shares']:.0f}{qty_lbl})"
        )
        lines.append(f"   ↳ {strats}")

    title = "📋 Futures Scan" if any_futures else "📋 NASDAQ Scan"

    embed = {
        "title":       f"{title} — {len(setups)} Signal(s)",
        "description": "\n".join(lines),
        "color":       0x5865F2,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "footer":      {"text": "Detailed breakdowns follow ↓"},
    }
    _post({"embeds": [embed]})


# ── No-signal message ──────────────────────────────────────────────────────────

def send_no_signals_message(mode: str = "market"):
    url = _webhook()
    if not url:
        return

    if mode == "premarket":
        title = "🌅 Pre-Market Scan — No High-Conviction Setups"
        desc  = (
            "No stocks met the pre-market criteria today:\n"
            "• Strategy score ≥ 6 (high conviction)\n"
            "• ATR stop ≤ 3.5% from entry\n"
            "• Minimum 1.5:1 R:R on 5% target\n"
            "• News sentiment checked\n\n"
            "**Market opens 09:30 ET — hourly scans will continue.**"
        )
        footer = "5% profit target · 3.5% max stop · Consistent wins"
    elif mode == "futures":
        title = "🌐 Futures Scan — No Signals"
        desc  = (
            "No futures contracts reached the signal threshold this cycle.\n\n"
            "**Watching:** ES, MES, NQ, MNQ, YM, MYM, RTY, M2K, EMD, NIY, MNI\n"
            "**Target:** 2× ATR  ·  **Stop:** 1× ATR  ·  Min R:R 1.5:1"
        )
        footer = "Futures scan every 30 min · nearly 24/5"
    elif mode == "competition":
        title = "⚡ Competition Scan — Nothing Qualified"
        desc  = (
            "No stock or future cleared the bar right now:\n"
            "• Min strategy score ±3\n"
            "• Min 3:1 reward-to-risk on a 5×ATR target\n\n"
            "Try again shortly — markets move fast."
        )
        footer = "Scanned full universe: stocks + futures"
    else:
        title = "📊 Hourly Scan — No Signals"
        desc  = "No stocks reached the signal threshold this hour. Watching…"
        footer = "Scanning every hour during market hours (09:30–16:00 ET)"

    embed = {
        "title":       title,
        "description": desc,
        "color":       0x607D8B,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "footer":      {"text": footer},
    }
    _post({"embeds": [embed]})
