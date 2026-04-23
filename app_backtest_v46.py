def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size=10, config=None):
    conf = config or {}
    min_score = int(conf.get("min_score", 6))
    exit_type = conf.get("exit_type", "trailing_atr")
    sl_pct, tp_pct = float(conf.get("sl_pct", 5)) / 100, float(conf.get("tp_pct", 15)) / 100
    comm_type, comm_val = conf.get("comm_type", "fixed"), float(conf.get("comm_val", 0))
    market = conf.get("market", "omxs")
    pos_size_pct = pos_size / 100.0

    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=years * 365)
    
    idx_ticker = "^OMX" if market == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=400), end=end_dt)
    if not idx_df.empty:
        if idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
        idx_df.index = idx_df.index.normalize()
        idx_df["MA200"] = idx_df.Close.rolling(200).mean()

    all_data = {}
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=400), end=end_dt)
            if not df.empty and len(df) > 150:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df.index = df.index.normalize()
                df["MA10"], df["MA20"], df["MA50"], df["MA200"] = df.Close.rolling(10).mean(), df.Close.rolling(20).mean(), df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
                df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
                df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
                df["BB_width"] = (df["BB_upper"] - df["BB_lower"]) / (df["BB_mid"] + 1e-9)
                all_data[sym] = df
        except: continue

    def calc_fee(amt): return amt * (comm_val / 100) if comm_type == "pct" else comm_val
    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []
    last_buy_week = -1

    while current_date <= end_dt:
        if current_date.weekday() >= 5: current_date += timedelta(days=1); continue
        day_str = current_date.strftime("%Y-%m-%d")
        current_week = current_date.isocalendar()[1]
        
        m_data = {"bull": True, "idx_return": 0, "ticker": idx_ticker}
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_data["bull"] = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True

        # 1. Hantera exits
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            rows = df[df.index == current_date]
            if rows.empty: still_holding.append(h); continue
            row = rows.iloc[0]
            
            exit_p, exit_r = None, None
            if exit_type != "hold":
                if row.High > h["hwm"]:
                    h["hwm"] = row.High
                    if exit_type == "trailing_atr":
                        nsl = row.High - (2.0 * row.ATR)
                        if h["sl"] is None or nsl > h["sl"]: h["sl"] = nsl
                
                if h["sl"] and row.Low <= h["sl"]: exit_p, exit_r = h["sl"], "Stop-Loss"
                elif h["tp"] and row.High >= h["tp"]:
                    if not pd.isna(row.MA10) and row.Close > row.MA10: h["tp"], h["sl"] = None, row.MA10
                    else: exit_p, exit_r = h["tp"], "Take-Profit"
                elif h["tp"] is None and not pd.isna(row.MA10) and row.Close < row.MA10:
                    exit_p, exit_r = row.Close, "MA10-Break"
            
            if exit_p:
                fee = calc_fee(h["qty"] * exit_p)
                cash += (h["qty"] * exit_p) - fee
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": day_str, "pl": round((exit_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((exit_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": exit_r})
            else: still_holding.append(h)
        holdings = still_holding

        # 2. Köp ny (Max 1 per vecka)
        cur_v = cash + sum(h["qty"] * float(all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].Close.iloc[-1]) for h in holdings if not all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].empty)
        target_pos = cur_v * pos_size_pct
        
        if last_buy_week != current_week and cash >= target_pos + calc_fee(target_pos):
            candidates = []
            for sym, df in all_data.items():
                if any(h["symbol"] == sym for h in holdings): continue
                past = df[df.index <= current_date]
                if len(past) < 100: continue
                r = past.iloc[-1]
                
                # BASIC TREND FILTER (Viktigt men inte för strikt)
                if r.Close < r.MA200 * 0.95: continue # Tillåt 5% under MA200 för bottenfiske
                
                try:
                    sw = calc_swing_score(past, gen_signal(past), m_data)
                    if sw["score"] >= min_score:
                        candidates.append({"sym": sym, "score": sw["score"], "sltp": calc_sltp(past, float(past.Close.iloc[-1])), "atr": r.ATR})
                except: continue
            
            if candidates:
                candidates.sort(key=lambda x: x["score"], reverse=True)
                best = candidates[0]
                row = all_data[best["sym"]][all_data[best["sym"]].index == current_date].iloc[0]
                entry, fee = float(row.Close), calc_fee(target_pos)
                sl = entry - (2.0 * row.ATR)
                holdings.append({"symbol": best["sym"], "entry_price": entry, "sl": sl, "tp": entry * (1+tp_pct), "qty": target_pos / entry, "entry_date": current_date, "hwm": entry, "buy_fee": fee})
                cash -= (target_pos + fee)
                last_buy_week = current_week

        if current_date.weekday() == 0: history.append({"date": day_str, "value": round(cur_v, 2)})
        current_date += timedelta(days=1)

    for h in holdings:
        last_p = float(all_data[h["symbol"]].Close.iloc[-1])
        fee = calc_fee(h["qty"] * last_p)
        trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": end_dt.strftime("%Y-%m-%d"), "pl": round((last_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((last_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": "Testslut"})
        cash += (h["qty"] * last_p) - fee
    return {"final_value": round(cash, 2), "total_return_pct": round((cash/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
