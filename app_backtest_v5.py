def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size=10, config=None):
    conf = config or {}
    min_score, exit_type = int(conf.get("min_score", 7)), conf.get("exit_type", "sltp")
    sl_pct, tp_pct = float(conf.get("sl_pct", 5)) / 100, float(conf.get("tp_pct", 10)) / 100
    comm_type, comm_val = conf.get("comm_type", "fixed"), float(conf.get("comm_val", 0))
    market = conf.get("market", "omxs")

    end_dt, start_dt = datetime.now(), datetime.now() - timedelta(days=years * 365)
    idx_ticker = "^OMX" if market == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=300), end=end_dt)
    if not idx_df.empty and idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
    if not idx_df.empty: idx_df["MA200"] = idx_df.Close.rolling(200).mean()

    all_data = {}
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=250), end=end_dt)
            if not df.empty and len(df) > 100:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df["MA50"], df["MA200"] = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
                df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
                df["MACD"], df["MACD_sig"], _ = calc_macd(df.Close)
                df["BB_upper"], _, df["BB_lower"] = calc_bb(df.Close)
                all_data[sym] = df
        except: continue

    def calc_fee(amt): return amt * (comm_val / 100) if comm_type == "pct" else comm_val
    
    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []

    while current_date < end_dt:
        if current_date.weekday() != 0:
            current_date += timedelta(days=1); continue
        
        m_data = {"bull": True, "idx_return": 0, "ticker": idx_ticker}
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_data["bull"] = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True

        # 1. Hantera exits för existerande innehav
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            week_data = df[(df.index >= current_date) & (df.index < current_date + timedelta(days=7))]
            exit_p, exit_r, exit_d = None, None, None
            
            if exit_type != "hold":
                for d, row in week_data.iterrows():
                    if row.High > h["hwm"]:
                        h["hwm"] = row.High
                        if exit_type == "trailing":
                            nsl = row.High * (1 - sl_pct)
                            if h["sl"] is None or nsl > h["sl"]: h["sl"] = nsl
                    if h["sl"] and row.Low <= h["sl"]:
                        exit_p, exit_r, exit_d = h["sl"], "Stop-Loss", d; break
                    if h["tp"] and row.High >= h["tp"]:
                        exit_p, exit_r, exit_d = h["tp"], "Take-Profit", d; break
            
            if exit_p:
                fee = calc_fee(h["qty"] * exit_p)
                cash += (h["qty"] * exit_p) - fee
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": exit_d.strftime("%Y-%m-%d"), "pl": round((exit_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((exit_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": exit_r})
            else:
                still_holding.append(h)
        holdings = still_holding

        # 2. Köp nya om vi har cash (max en per vecka för realism)
        if cash >= pos_size + calc_fee(pos_size):
            candidates = []
            for sym, df in all_data.items():
                if any(h["symbol"] == sym for h in holdings): continue
                past_df = df[df.index <= current_date]
                if len(past_df) < 60: continue
                try:
                    sig = gen_signal(past_df)
                    sw = calc_swing_score(past_df, sig, m_data)
                    if sw["score"] >= min_score:
                        candidates.append({"sym": sym, "score": sw["score"], "sltp": calc_sltp(past_df, float(past_df.Close.iloc[-1]))})
                except: continue
            
            if candidates:
                candidates.sort(key=lambda x: x["score"], reverse=True)
                best = candidates[0]
                df_c = all_data[best["sym"]]
                tue = df_c[df_c.index > current_date].head(1)
                if not tue.empty:
                    entry = float(tue.Open.iloc[0])
                    buy_fee = calc_fee(pos_size)
                    sl, tp = None, None
                    if exit_type == "sltp": sl, tp = best["sltp"]["stop_loss"], best["sltp"]["take_profit_2"]
                    elif exit_type in ["fixed", "trailing"]:
                        sl, tp = entry * (1 - sl_pct), entry * (1 + tp_pct)
                        if exit_type == "trailing": tp = None
                    holdings.append({"symbol": best["sym"], "entry_price": entry, "sl": sl, "tp": tp, "qty": pos_size / entry, "entry_date": tue.index[0], "hwm": entry, "buy_fee": buy_fee})
                    cash -= (pos_size + buy_fee)

        # 3. Logga historiskt värde
        v = cash
        for h in holdings:
            p_val = all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date]
            if not p_val.empty: v += (h["qty"] * float(p_val.Close.iloc[-1]))
        history.append({"date": current_date.strftime("%Y-%m-%d"), "value": round(v, 2)})
        current_date += timedelta(days=7)

    # Stäng kvarvarande innehav vid testslut
    for h in holdings:
        last_p = float(all_data[h["symbol"]].Close.iloc[-1])
        fee = calc_fee(h["qty"] * last_p)
        trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": end_dt.strftime("%Y-%m-%d"), "pl": round((last_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((last_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": "Testslut (Innehav)"})
        cash += (h["qty"] * last_p) - fee

    return {"final_value": round(cash, 2), "total_return_pct": round((cash/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
