def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size=10, config=None):
    conf = config or {}
    min_score = int(conf.get("min_score", 6))
    exit_type = conf.get("exit_type", "trailing_atr")
    sl_pct, tp_pct = float(conf.get("sl_pct", 5)) / 100, float(conf.get("tp_pct", 15)) / 100
    comm_val = float(conf.get("comm_val", 0))
    pos_size_pct = pos_size / 100.0

    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=years * 365)
    
    # Förbered index-data
    idx_ticker = "^OMX" if conf.get("market") == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=400), end=end_dt)
    if not idx_df.empty:
        if idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
        idx_df.index = idx_df.index.normalize()
        idx_df["MA200"] = idx_df.Close.rolling(200).mean()

    # Förbered aktiedata
    all_data = {}
    print(f"DEBUG: Laddar data för {len(symbols_dict)} aktier...")
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=400), end=end_dt)
            if not df.empty and len(df) > 100:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df.index = df.index.normalize()
                df["MA10"], df["MA20"], df["MA50"], df["MA200"] = df.Close.rolling(10).mean(), df.Close.rolling(20).mean(), df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
                df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
                df["MACD"], df["MACD_sig"], _ = calc_macd(df.Close)
                df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
                df["BB_width"] = (df["BB_upper"] - df["BB_lower"]) / (df["BB_mid"] + 1e-9)
                all_data[sym] = df
        except: continue

    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []
    last_buy_date = start_dt - timedelta(days=10)

    while current_date <= end_dt:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1); continue
        
        # Kolla marknadstrend
        m_data = {"bull": True, "idx_return": 0, "ticker": idx_ticker}
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_data["bull"] = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True

        # 1. Kolla Exits (Varje dag)
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            # Hitta data för IDAG
            day_data = df[df.index == current_date]
            if day_data.empty: still_holding.append(h); continue
            row = day_data.iloc[0]
            
            exit_p, exit_r = None, None
            if exit_type != "hold":
                # Trailing logic
                if row.High > h["hwm"]:
                    h["hwm"] = row.High
                    if exit_type == "trailing_atr":
                        h["sl"] = max(h["sl"] or 0, row.High - (2.0 * row.ATR))
                    elif exit_type == "trailing":
                        h["sl"] = max(h["sl"] or 0, row.High * (1 - sl_pct))
                
                if h["sl"] and row.Low <= h["sl"]: exit_p, exit_r = h["sl"], "Stop-Loss"
                elif h["tp"] and row.High >= h["tp"]:
                    if not pd.isna(row.MA10) and row.Close > row.MA10: h["tp"], h["sl"] = None, row.MA10
                    else: exit_p, exit_r = h["tp"], "Take-Profit"
                elif h["tp"] is None and not pd.isna(row.MA10) and row.Close < row.MA10:
                    exit_p, exit_r = row.Close, "Momentum-tapp (MA10)"
            
            if exit_p:
                cash += (h["qty"] * exit_p) - comm_val
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": current_date.strftime("%Y-%m-%d"), "pl": round((exit_p - h["entry_price"]) * h["qty"] - (2*comm_val), 2), "pl_pct": round(((exit_p/h["entry_price"])-1)*100, 2), "reason": exit_r})
            else:
                still_holding.append(h)
        holdings = still_holding

        # 2. Köp ny (Om minst 7 dagar sedan sist och vi har cash)
        if (current_date - last_buy_date).days >= 7:
            cur_v = cash + sum(h["qty"] * float(all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].Close.iloc[-1]) for h in holdings if not all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].empty)
            target_pos = cur_v * pos_size_pct
            
            if cash >= target_pos + comm_val:
                candidates = []
                for sym, df in all_data.items():
                    if any(h["symbol"] == sym for h in holdings): continue
                    past = df[df.index <= current_date]
                    if len(past) < 50: continue
                    try:
                        sw = calc_swing_score(past, gen_signal(past), m_data)
                        if sw["score"] >= min_score:
                            candidates.append({"sym": sym, "score": sw["score"], "atr": past.ATR.iloc[-1]})
                    except: continue
                
                if candidates:
                    candidates.sort(key=lambda x: x["score"], reverse=True)
                    best = candidates[0]
                    # Hitta dagens kurs för köp
                    row = all_data[best["sym"]][all_data[best["sym"]].index == current_date]
                    if not row.empty:
                        entry = float(row.iloc[0].Close)
                        sl = entry - (2.0 * best["atr"])
                        holdings.append({"symbol": best["sym"], "entry_price": entry, "sl": sl, "tp": entry * (1+tp_pct), "qty": target_pos / entry, "entry_date": current_date, "hwm": entry})
                        cash -= (target_pos + comm_val)
                        last_buy_date = current_date

        if current_date.weekday() == 0: history.append({"date": current_date.strftime("%Y-%m-%d"), "value": round(cash + sum(h["qty"] * float(all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].Close.iloc[-1]) for h in holdings if not all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].empty), 2)})
        current_date += timedelta(days=1)

    return {"final_value": round(cash, 2), "total_return_pct": round((cash/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
