# ── Indikatorer ───────────────────────────────────────────────────────────────

def calc_rsi(s, n=14):
    """Beräknar RSI med Wilder's Smoothing (standard)."""
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/n, adjust=False).mean()
    rsi = 100 - 100 / (1 + g / l.replace(0, 1e-9))
    return rsi

def calc_macd(s, fast=12, slow=26, sig=9):
    m = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    sl = m.ewm(span=sig, adjust=False).mean()
    return m, sl, m - sl

def calc_bb(close, n=20, num_std=2):
    ma  = close.rolling(n).mean()
    std = close.rolling(n).std()
    return ma + num_std * std, ma, ma - num_std * std

def calc_atr(df, n=14):
    """Beräknar ATR med Wilder's Smoothing."""
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def calc_obv(df):
    """Beräknar On-Balance Volume (OBV)."""
    obv = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
    return obv

# ... resten av dina befintliga hjälpfunktioner (gen_signal, calc_sltp, fetch_market_data etc) ...

# ── Portfolio Strategy Backtest ───────────────────────────────────────────────

def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size=10, config=None):
    """
    Simulerar en portföljstrategi med anpassningsbara parametrar och courtage.
    """
    conf = config or {}
    min_score = int(conf.get("min_score", 7))
    exit_type = conf.get("exit_type", "sltp") # sltp, trailing, fixed, hold
    sl_pct    = float(conf.get("sl_pct", 5)) / 100
    tp_pct    = float(conf.get("tp_pct", 10)) / 100
    
    # Courtage-inställningar
    comm_type = conf.get("comm_type", "fixed")
    comm_val  = float(conf.get("comm_val", 0))

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=years * 365)
    
    all_data = {}
    print(f"Hämtar historik för {len(symbols_dict)} aktier...")
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=250), end=end_dt)
            if not df.empty and len(df) > 100:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df["MA50"]  = df.Close.rolling(50).mean()
                df["MA200"] = df.Close.rolling(200).mean()
                df["RSI"]   = calc_rsi(df.Close)
                df["MACD"], df["MACD_sig"], _ = calc_macd(df.Close)
                df["ATR"]   = calc_atr(df)
                df["BB_upper"], _, df["BB_lower"] = calc_bb(df.Close)
                all_data[sym] = df
        except Exception: continue

    if not all_data:
        return {"error": "Ingen data kunde hämtas"}

    current_date = start_dt
    cash = capital
    trades = []
    active_trade = None 
    history = []

    def calc_fee(amount):
        if comm_type == "pct": return amount * (comm_val / 100)
        return comm_val

    while current_date < end_dt:
        if current_date.weekday() != 0:
            current_date += timedelta(days=1)
            continue

        day_str = current_date.strftime("%Y-%m-%d")

        # A. Uppdatera pågående trade
        if active_trade:
            sym = active_trade["symbol"]
            df = all_data[sym]
            week_data = df[(df.index >= current_date) & (df.index < current_date + timedelta(days=7))]
            
            exit_price = None
            exit_reason = None
            exit_date = None
            
            if exit_type != "hold":
                for d, row in week_data.iterrows():
                    if row.High > active_trade.get("high_water_mark", 0):
                        active_trade["high_water_mark"] = row.High
                        if exit_type == "trailing":
                            new_sl = row.High * (1 - sl_pct)
                            if active_trade["sl"] is None or new_sl > active_trade["sl"]:
                                active_trade["sl"] = new_sl

                    if active_trade["sl"] and row.Low <= active_trade["sl"]:
                        exit_price = active_trade["sl"]
                        exit_reason = "Stop-Loss"
                        exit_date = d
                        break
                    if active_trade["tp"] and row.High >= active_trade["tp"]:
                        exit_price = active_trade["tp"]
                        exit_reason = "Take-Profit"
                        exit_date = d
                        break
            
            if exit_price:
                sell_fee = calc_fee(active_trade["qty"] * exit_price)
                profit = (exit_price - active_trade["entry_price"]) * active_trade["qty"] - sell_fee - active_trade["buy_fee"]
                cash += (active_trade["qty"] * exit_price) - sell_fee
                trades.append({
                    "symbol": sym, "entry_date": active_trade["entry_date"].strftime("%Y-%m-%d"),
                    "exit_date": exit_date.strftime("%Y-%m-%d"), "pl": round(profit, 2),
                    "pl_pct": round(((exit_price * active_trade["qty"] - sell_fee) / (active_trade["entry_price"] * active_trade["qty"] + active_trade["buy_fee"]) - 1)*100, 2), 
                    "reason": exit_reason
                })
                active_trade = None

        # B. Kör screener
        best_sym, best_score, best_sltp = None, -1, None
        for sym, df in all_data.items():
            past_df = df[df.index <= current_date]
            if len(past_df) < 60: continue
            try:
                sig = gen_signal(past_df)
                m_bull = float(past_df.MA50.iloc[-1]) > float(past_df.MA200.iloc[-1])
                swing = calc_swing_score(past_df, sig, {"bull": m_bull, "idx_return": 0, "ticker": "INDEX"})
                if swing["score"] > best_score:
                    best_score, best_sym = swing["score"], sym
                    best_sltp = calc_sltp(past_df, float(past_df.Close.iloc[-1]))
            except Exception: continue
        
        is_new_better = exit_type != "hold" and active_trade and best_sym != active_trade["symbol"] and best_score >= min_score + 1
        
        if (not active_trade or is_new_better) and best_sym and best_score >= min_score:
            if active_trade:
                df_old = all_data[active_trade["symbol"]]
                exit_row = df_old[df_old.index > current_date].head(1)
                if not exit_row.empty:
                    cur_p = float(exit_row.Open.iloc[0])
                    sell_fee = calc_fee(active_trade["qty"] * cur_p)
                    profit = (cur_p - active_trade["entry_price"]) * active_trade["qty"] - sell_fee - active_trade["buy_fee"]
                    cash += (active_trade["qty"] * cur_p) - sell_fee
                    trades.append({
                        "symbol": active_trade["symbol"], "entry_date": active_trade["entry_date"].strftime("%Y-%m-%d"),
                        "exit_date": exit_row.index[0].strftime("%Y-%m-%d"), "pl": round(profit, 2),
                        "pl_pct": round(((cur_p * active_trade["qty"] - sell_fee) / (active_trade["entry_price"] * active_trade["qty"] + active_trade["buy_fee"]) - 1)*100, 2),
                        "reason": "Screener-byte"
                    })
                    active_trade = None

            df_new = all_data[best_sym]
            tue = df_new[df_new.index > current_date].head(1)
            if not tue.empty:
                entry = float(tue.Open.iloc[0])
                qty = pos_size / entry
                buy_fee = calc_fee(pos_size)
                sl, tp = None, None
                if exit_type == "sltp":
                    sl, tp = best_sltp["stop_loss"], best_sltp["take_profit_2"]
                elif exit_type == "fixed" or exit_type == "trailing":
                    sl, tp = entry * (1 - sl_pct), entry * (1 + tp_pct)
                    if exit_type == "trailing": tp = None

                if cash >= pos_size + buy_fee:
                    cash -= (pos_size + buy_fee)
                    active_trade = {
                        "symbol": best_sym, "entry_price": entry, "sl": sl, "tp": tp,
                        "qty": qty, "entry_date": tue.index[0], "high_water_mark": entry, "buy_fee": buy_fee
                    }

        current_val = cash
        if active_trade:
            last_p = float(all_data[active_trade["symbol"]][all_data[active_trade["symbol"]].index <= current_date].Close.iloc[-1])
            current_val += (active_trade["qty"] * last_p)
        history.append({"date": day_str, "value": round(current_val, 2)})
        current_date += timedelta(days=7)

    if active_trade:
        df_end = all_data[active_trade["symbol"]]
        last_p = float(df_end.Close.iloc[-1])
        sell_fee = calc_fee(active_trade["qty"] * last_p)
        profit = (last_p - active_trade["entry_price"]) * active_trade["qty"] - sell_fee - active_trade["buy_fee"]
        trades.append({
            "symbol": active_trade["symbol"], "entry_date": active_trade["entry_date"].strftime("%Y-%m-%d"),
            "exit_date": df_end.index[-1].strftime("%Y-%m-%d"), "pl": round(profit, 2),
            "pl_pct": round(((last_p * active_trade["qty"] - sell_fee) / (active_trade["entry_price"] * active_trade["qty"] + active_trade["buy_fee"]) - 1)*100, 2),
            "reason": "Testslut (Innehav)"
        })
        current_val = cash + (active_trade["qty"] * last_p) - sell_fee

    return {
        "final_value": round(current_val, 2), "total_return_pct": round((current_val/capital - 1) * 100, 2),
        "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0
    }
