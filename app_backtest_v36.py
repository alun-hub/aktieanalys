def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size=10, config=None):
    conf = config or {}
    min_score, exit_type = int(conf.get("min_score", 6)), conf.get("exit_type", "sltp")
    sl_pct, tp_pct = float(conf.get("sl_pct", 5)) / 100, float(conf.get("tp_pct", 10)) / 100
    comm_type, comm_val = conf.get("comm_type", "fixed"), float(conf.get("comm_val", 0))
    market = conf.get("market", "omxs")

    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=years * 365)
    
    idx_ticker = "^OMX" if market == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=350), end=end_dt)
    if not idx_df.empty:
        if idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
        idx_df.index = idx_df.index.normalize()
        idx_df["MA200"] = idx_df.Close.rolling(200).mean()

    all_data = {}
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=300), end=end_dt)
            if not df.empty and len(df) > 100:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df.index = df.index.normalize()
                df["MA50"], df["MA200"] = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
                df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
                df["MACD"], df["MACD_sig"], _ = calc_macd(df.Close)
                df["BB_upper"], _, df["BB_lower"] = calc_bb(df.Close)
                all_data[sym] = df
        except: continue

    def calc_fee(amt): return amt * (comm_val / 100) if comm_type == "pct" else comm_val
    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []

    while current_date <= end_dt:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1); continue
        
        m_data = {"bull": True, "idx_return": 0, "ticker": idx_ticker}
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_data["bull"] = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True

        # 1. Hantera exits (Daily check)
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            day_rows = df[df.index == current_date]
            if day_rows.empty: still_holding.append(h); continue
            row = day_rows.iloc[0]
            
            exit_p, exit_r = None, None
            if exit_type != "hold":
                # Trailing logic
                if row.High > h["hwm"]:
                    h["hwm"] = row.High
                    if exit_type == "trailing":
                        nsl = row.High * (1 - sl_pct)
                        if h["sl"] is None or nsl > h["sl"]: h["sl"] = nsl
                
                # Check Price exits (SL/TP)
                if h["sl"] and row.Low <= h["sl"]: exit_p, exit_r = h["sl"], "Stop-Loss"
                elif h["tp"] and row.High >= h["tp"]: exit_p, exit_r = h["tp"], "Take-Profit"
            
            if exit_p:
                fee = calc_fee(h["qty"] * exit_p)
                cash += (h["qty"] * exit_p) - fee
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": current_date.strftime("%Y-%m-%d"), "pl": round((exit_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((exit_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": exit_r})
            else:
                # Check Score Weakness exit (Hysteresis: sell if score < threshold - 1)
                if exit_type != "hold":
                    try:
                        past_df = df[df.index <= current_date]
                        cur_score = calc_swing_score(past_df, gen_signal(past_df), m_data)["score"]
                        if cur_score < (min_score - 1): # Buffert på 1 poäng
                            exit_p = row.Close
                            fee = calc_fee(h["qty"] * exit_p)
                            cash += (h["qty"] * exit_p) - fee
                            trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": current_date.strftime("%Y-%m-%d"), "pl": round((exit_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((exit_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": "Svaghet"})
                            continue
                    except: pass
                still_holding.append(h)
        holdings = still_holding

        # 2. Köp ny (Max 1 per vecka på Måndagar)
        if current_date.weekday() == 0 and cash >= pos_size + calc_fee(pos_size):
            candidates = []
            for sym, df in all_data.items():
                if any(h["symbol"] == sym for h in holdings): continue
                past_df = df[df.index <= current_date]
                if len(past_df) < 50: continue
                try:
                    sw = calc_swing_score(past_df, gen_signal(past_df), m_data)
                    if sw["score"] >= min_score:
                        candidates.append({"sym": sym, "score": sw["score"], "sltp": calc_sltp(past_df, float(past_df.Close.iloc[-1]))})
                except: continue
            
            if candidates:
                candidates.sort(key=lambda x: x["score"], reverse=True)
                best = candidates[0] # Bara den bästa
                row = all_data[best["sym"]][all_data[best["sym"]].index == current_date]
                if not row.empty:
                    entry, buy_fee = float(row.Close.iloc[0]), calc_fee(pos_size)
                    sl, tp = None, None
                    if exit_type == "sltp": sl, tp = best["sltp"]["stop_loss"], best["sltp"]["take_profit_2"]
                    elif exit_type in ["fixed", "trailing"]:
                        sl, tp = entry * (1 - sl_pct), entry * (1 + tp_pct)
                        if exit_type == "trailing": tp = None
                    holdings.append({"symbol": best["sym"], "entry_price": entry, "sl": sl, "tp": tp, "qty": pos_size / entry, "entry_date": current_date, "hwm": entry, "buy_fee": buy_fee})
                    cash -= (pos_size + buy_fee)

        if current_date.weekday() == 0:
            v = cash
            for h in holdings:
                p_val = all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date]
                if not p_val.empty: v += (h["qty"] * float(p_val.Close.iloc[-1]))
            history.append({"date": current_date.strftime("%Y-%m-%d"), "value": round(v, 2)})
        
        current_date += timedelta(days=1)

    for h in holdings:
        last_p = float(all_data[h["symbol"]].Close.iloc[-1])
        fee = calc_fee(h["qty"] * last_p)
        trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": end_dt.strftime("%Y-%m-%d"), "pl": round((last_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((last_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": "Testslut"})
        cash += (h["qty"] * last_p) - fee

    return {"final_value": round(cash, 2), "total_return_pct": round((cash/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
