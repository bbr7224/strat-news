# -*- coding: utf-8 -*-
"""
fetch_eod.py v2 — بيانات حقيقية مجانية لموقع THE STRAT - S&P 500 NEWS
=====================================================================
المصدر: Yahoo Finance (مجاني) عبر yfinance + قائمة S&P 500 من ويكيبيديا.
يجلب سنتين يوميتين لكل رمز ويبني الفواصل: يومي/أسبوعي/شهري/ربع سنوي/سنوي،
ويحسب استمرارية الأطر من الافتتاحات الحقيقية للفترات.

التثبيت (مرة واحدة):
    pip install yfinance pandas lxml requests

الاستخدام:
    python fetch_eod.py --sp500 --inject THE-STRAT-SP500-NEWS.html
    python fetch_eod.py --sp500 --details --inject THE-STRAT-SP500-NEWS.html   # + معلومات وأخبار (أبطأ)
    python fetch_eod.py --sp500                       # ينتج strat_data.json فقط
    python fetch_eod.py --tickers my_list.txt         # قائمة خاصة (رمز[,قطاع] لكل سطر)
    python fetch_eod.py --sp500 --limit 60            # للتجربة السريعة
"""
import argparse, json, re, sys, time
from datetime import datetime

try:
    import pandas as pd
    import yfinance as yf
except ImportError:
    sys.exit("ثبّت المتطلبات أولًا:  pip install yfinance pandas lxml requests")

INDICES = [("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ (Nasdaq 100)"),
           ("DIA", "SPDR Dow Jones ETF"), ("IWM", "iShares Russell 2000")]
SECTOR_ETFS = {"XLK": "Technology Select Sector SPDR", "XLC": "Communication Services SPDR",
    "XLY": "Consumer Discretionary SPDR", "XLF": "Financial Select SPDR", "XLV": "Health Care SPDR",
    "XLE": "Energy Select SPDR", "XLI": "Industrial Select SPDR", "XLB": "Materials Select SPDR",
    "XLU": "Utilities Select SPDR", "XLRE": "Real Estate Select SPDR", "XLP": "Consumer Staples SPDR"}
EXTRA_ETFS = {"SMH": "Semiconductors ETF", "XBI": "Biotech ETF", "ARKK": "Innovation ETF",
              "GLD": "Gold ETF", "USO": "Oil ETF", "UNG": "Natural Gas ETF",
              "IYT": "Transports ETF", "XRT": "Retail ETF"}
GICS_TO_ETF = {"Information Technology": "XLK", "Communication Services": "XLC",
    "Consumer Discretionary": "XLY", "Financials": "XLF", "Health Care": "XLV",
    "Energy": "XLE", "Industrials": "XLI", "Materials": "XLB",
    "Utilities": "XLU", "Real Estate": "XLRE", "Consumer Staples": "XLP"}

FALLBACK = "AAPL,XLK MSFT,XLK NVDA,XLK AVGO,XLK AMD,XLK CRM,XLK ORCL,XLK ADBE,XLK QCOM,XLK INTC,XLK CSCO,XLK MU,XLK PLTR,XLK NOW,XLK GOOGL,XLC META,XLC NFLX,XLC DIS,XLC TMUS,XLC CMCSA,XLC AMZN,XLY TSLA,XLY HD,XLY MCD,XLY NKE,XLY SBUX,XLY LOW,XLY BKNG,XLY JPM,XLF BAC,XLF WFC,XLF GS,XLF MS,XLF V,XLF MA,XLF AXP,XLF BLK,XLF UNH,XLV LLY,XLV JNJ,XLV PFE,XLV MRK,XLV ABBV,XLV TMO,XLV AMGN,XLV XOM,XLE CVX,XLE COP,XLE SLB,XLE OXY,XLE EOG,XLE DVN,XLE HAL,XLE CAT,XLI BA,XLI GE,XLI UPS,XLI HON,XLI DE,XLI LMT,XLI RTX,XLI LIN,XLB FCX,XLB NEM,XLB DOW,XLB SHW,XLB NEE,XLU DUK,XLU SO,XLU D,XLU PLD,XLRE AMT,XLRE O,XLRE SPG,XLRE PG,XLP KO,XLP PEP,XLP WMT,XLP COST,XLP PM,XLP".split()

# (bars kept per timeframe — يكفي للشارت والتصنيف ويُبقي حجم الملف معقولًا)
KEEP = {"d": 90, "w": 60, "m": 24, "q": 9, "y": 3}


def get_sp500():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        df = pd.read_html(url)[0]
        out = [(str(r["Symbol"]).replace(".", "-").strip(),
                GICS_TO_ETF.get(str(r["GICS Sector"]).strip(), "XLK"),
                str(r.get("Security", r["Symbol"])))
               for _, r in df.iterrows()]
        print(f"✓ قائمة S&P 500: {len(out)} سهمًا (ويكيبيديا)")
        return out
    except Exception as e:
        print(f"⚠ تعذّر جلب ويكيبيديا ({e}) — استخدام الاحتياط المدمج ({len(FALLBACK)} سهمًا)")
        return [(p.split(",")[0], p.split(",")[1], p.split(",")[0]) for p in FALLBACK]


def to_hist(df, dates=True):
    out = []
    for ts, r in df.iterrows():
        bar = [round(float(r["Open"]), 2), round(float(r["High"]), 2),
               round(float(r["Low"]), 2), round(float(r["Close"]), 2)]
        if dates:
            bar.append(ts.strftime("%Y-%m-%d"))
        out.append(bar)
    return out


def tfc_arrows(daily):
    """استمرارية حقيقية: آخر إغلاق مقابل افتتاح اليوم/الأسبوع/الشهر/الربع/السنة الفعلي."""
    c = float(daily["Close"].iloc[-1])
    last = daily.index[-1]
    def op(mask):
        sub = daily.loc[mask]
        return float(sub["Open"].iloc[0]) if len(sub) else float(daily["Open"].iloc[-1])
    iso = last.isocalendar()
    opens = [
        float(daily["Open"].iloc[-1]),
        op([(x.isocalendar().week == iso.week and x.isocalendar().year == iso.year) for x in daily.index]),
        op([(x.month == last.month and x.year == last.year) for x in daily.index]),
        op([((x.month - 1) // 3 == (last.month - 1) // 3 and x.year == last.year) for x in daily.index]),
        op([x.year == last.year for x in daily.index]),
    ]
    return [1 if c > o else -1 for o in opens]


def process(sym, daily):
    daily = daily.dropna(subset=["Open", "High", "Low", "Close"])
    if len(daily) < 60:
        return None
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    frames = {"d": daily,
              "w": daily.resample("W-FRI").agg(agg).dropna(),
              "m": daily.resample("MS").agg(agg).dropna(),
              "q": daily.resample("QS").agg(agg).dropna(),
              "y": daily.resample("YS").agg(agg).dropna()}
    hist, chg = {}, {}
    for tf, df in frames.items():
        df = df.tail(KEEP[tf])
        if len(df) < 2:
            return None
        hist[tf] = to_hist(df)
        c = df["Close"]
        chg[tf] = round((float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, 2)
    vol = round(float(daily["Volume"].tail(20).mean()) / 1e6, 1) if "Volume" in daily else 0
    return {"px": hist["d"][-1][3], "vol": vol, "chg": chg, "hist": hist, "tfc": tfc_arrows(daily)}


def download_batch(symbols, period="2y"):
    out, CHUNK = {}, 60
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        print(f"  تنزيل {i+1}-{i+len(chunk)} من {len(symbols)} ...")
        data = yf.download(chunk, period=period, interval="1d", group_by="ticker",
                           auto_adjust=False, threads=True, progress=False)
        for s in chunk:
            try:
                df = data[s] if len(chunk) > 1 else data
                if df is not None and len(df.dropna()) > 0:
                    out[s] = df
            except Exception:
                pass
        time.sleep(1)
    return out


def fetch_details(symbols):
    """معلومات + أخبار لكل رمز (طلب لكل سهم — بطيء، ~10-20 دقيقة لكامل القائمة)."""
    info_map, news_map = {}, {}
    for i, s in enumerate(symbols, 1):
        try:
            tk = yf.Ticker(s)
            fi = {}
            try:
                fi = dict(tk.fast_info) if tk.fast_info else {}
            except Exception:
                pass
            inf = {}
            try:
                raw = tk.info or {}
            except Exception:
                raw = {}
            inf["mcap"] = raw.get("marketCap") or fi.get("market_cap")
            inf["pe"] = raw.get("trailingPE")
            inf["hi52"] = raw.get("fiftyTwoWeekHigh") or fi.get("year_high")
            inf["lo52"] = raw.get("fiftyTwoWeekLow") or fi.get("year_low")
            inf["divY"] = raw.get("dividendYield")
            inf["ind"] = raw.get("industry")
            try:
                cal = tk.calendar
                ed = None
                if cal is not None:
                    if isinstance(cal, dict):
                        ed = cal.get("Earnings Date")
                        if isinstance(ed, (list, tuple)) and ed:
                            ed = ed[0]
                    elif hasattr(cal, "loc") and "Earnings Date" in getattr(cal, "index", []):
                        ed = cal.loc["Earnings Date"].iloc[0]
                if ed is not None:
                    inf["earn"] = str(ed)[:10]
            except Exception:
                pass
            info_map[s] = {k: v for k, v in inf.items() if v is not None}
            try:
                news = []
                for n in (tk.news or [])[:5]:
                    c = n.get("content", n)
                    title = c.get("title") or n.get("title")
                    url = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else n.get("link")
                    pub = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else n.get("publisher")
                    dt = c.get("pubDate") or ""
                    if title:
                        news.append({"t": title, "u": url or "", "p": pub or "", "d": str(dt)[:10]})
                if news:
                    news_map[s] = news
            except Exception:
                pass
        except Exception:
            pass
        if i % 25 == 0:
            print(f"  تفاصيل {i}/{len(symbols)} ...")
            time.sleep(1)
    return info_map, news_map


def build(args):
    universe = []
    if args.tickers:
        with open(args.tickers, encoding="utf-8") as f:
            for line in f:
                s = line.strip().upper()
                if s and not s.startswith("#"):
                    p = s.split(",")
                    universe.append((p[0], p[1] if len(p) > 1 else "XLK", p[0]))
        print(f"✓ {len(universe)} رمزًا من {args.tickers}")
    else:
        universe = get_sp500()
    if not args.no_extras and not args.tickers:
        EXTRAS = {
            "XLK": "COIN MSTR MARA RIOT IONQ RGTI ARM TSM ASML MRVL COHR APP SNOW NET DDOG ZS OKTA MDB TEAM U PATH TWLO ROKU AI SOUN ALAB CRDO PLUG",
            "XLC": "SNAP PINS SPOT RDDT",
            "XLY": "SHOP SE MELI BABA JD PDD NIO XPEV LI RIVN LCID CVNA ETSY DKNG RBLX GME AMC PTON",
            "XLF": "HOOD SOFI AFRM UPST XYZ NU",
            "XLV": "NVO HIMS TEM",
            "XLI": "JOBY ACHR RKLB ASTS LUNR UBER",
            "XLE": "SMR OKLO BE TLN"}
        have = {u[0] for u in universe}
        added = 0
        for sec, ts in EXTRAS.items():
            for s in ts.split():
                if s not in have:
                    universe.append((s, sec, s)); added += 1
        print(f"✓ أضيف {added} سهمًا نشطًا خارج القائمة (المجموع {len(universe)})")
    if args.limit:
        universe = universe[:args.limit]

    all_syms = ([s for s, _ in INDICES] + list(SECTOR_ETFS) + list(EXTRA_ETFS) + [u[0] for u in universe])
    print(f"إجمالي الرموز: {len(all_syms)} — تنزيل سنتين يوميتين ...")
    frames = download_batch(all_syms)
    print(f"✓ وصلت بيانات {len(frames)} رمزًا")

    info_map, news_map = {}, {}
    if args.details:
        print("جلب معلومات الأسهم والأخبار (--details) — قد يستغرق وقتًا ...")
        info_map, news_map = fetch_details([u[0] for u in universe])

    rows = []
    def add(sym, name, sector, kind):
        df = frames.get(sym)
        if df is None:
            return
        rec = process(sym, df)
        if rec:
            row = {"s": sym, "n": name, "sec": sector, "k": kind, **rec}
            if sym in info_map:
                row["info"] = info_map[sym]
            if sym in news_map:
                row["news"] = news_map[sym]
            rows.append(row)

    for s, n in INDICES: add(s, n, "INDEX", "index")
    for s, n in SECTOR_ETFS.items(): add(s, n, "SECTOR", "etf")
    for s, n in EXTRA_ETFS.items(): add(s, n, "ETF", "etf")
    for sym, sec, name in [(u[0], u[1], u[2] if len(u) > 2 else u[0]) for u in universe]:
        add(sym, name, sec, "stock")

    any_df = next(iter(frames.values())).dropna()
    last = any_df.index[-1]
    week_start = last - pd.Timedelta(days=last.weekday())
    data = {"demo": False,
            "asof": {"daily": last.strftime("%d-%b-%Y"), "weekly": week_start.strftime("%d-%b-%Y"),
                     "monthly": last.strftime("%b %Y"), "quarterly": f"Q{(last.month-1)//3+1} {last.year}",
                     "yearly": str(last.year)},
            "generated": datetime.now().isoformat(timespec="seconds"),
            "rows": rows}
    print(f"✓ جاهز: {len(rows)} صفًا ({sum(1 for r in rows if r['k']=='stock')} سهمًا)")
    return data


def inject(html_path, data):
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_html, n = re.subn(r"const DATA = \{.*?\};\n", f"const DATA = {payload};\n", html, count=1, flags=re.S)
    if n != 1:
        sys.exit("⚠ لم أجد كتلة const DATA — تأكد من مسار ملف الموقع.")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"✓ تم تحديث الموقع: {html_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="THE STRAT - S&P 500 NEWS | free EOD fetcher (Yahoo Finance)")
    ap.add_argument("--sp500", action="store_true", help="كامل S&P 500 (الافتراضي)")
    ap.add_argument("--tickers", help="ملف رموز خاص: رمز[,قطاع] لكل سطر")
    ap.add_argument("--limit", type=int, help="حد أقصى للأسهم (للتجربة)")
    ap.add_argument("--details", action="store_true", help="جلب معلومات وأخبار كل سهم (أبطأ)")
    ap.add_argument("--no-extras", action="store_true", help="بدون الأسهم النشطة الإضافية")
    ap.add_argument("--out", default="strat_data.json", help="ملف JSON الناتج")
    ap.add_argument("--inject", help="مسار ملف الموقع لتحديثه مباشرة")
    args = ap.parse_args()

    data = build(args)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ حُفظ {args.out} ({round(len(json.dumps(data))/1e6,1)} MB)")
    if args.inject:
        inject(args.inject, data)
    print("انتهى. حدّث الصفحة في المتصفح.")
