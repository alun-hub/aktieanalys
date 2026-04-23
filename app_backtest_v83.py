def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size_val=10, config=None):
    conf = config or {}
    comm_val = float(conf.get("comm_val", 0))
    pos_size_pct = 0.20 # Vi kör fast 20% per aktie (max 5 st) för bäst riskspridning

    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=years * 365)
    
    idx_ticker = "^OMX" if conf.get("market") == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=400), end=end_dt)
    if not idx_df.empty:
        if idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
        idx_df.index = idx_df.index.normalize()
        idx_df["MA200"] = idx_df.Close.rolling(200).mean()

    all_data = {}
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=400), end=end_dt)
            if not df.empty and len(df) > 200:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df.index = df.index.normalize()
                df["MA50"], df["MA200"] = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
                df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
                df["MACD"], df["MACD_sig"] = calc_macd(df.Close)
                all_data[sym] = df
        except: continue

    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []

    while current_date <= end_dt:
        if current_date.weekday() >= 5: current_date += timedelta(days=1); continue
        
        m_bull = True
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_bull = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True

        # 1. Hantera exits
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            rows = df[df.index == current_date]
            if rows.empty: still_holding.append(h); continue
            row = rows.iloc[0]
            h["days_held"] += 1
            
            exit_p, exit_r = None, None
            # Stop-loss (4x ATR - Mycket utrymme för att undvika brus)
            if row.Low <= h["sl"]: exit_p, exit_r = h["sl"], "Stop-Loss (4xATR)"
            # Time exit (20 dagar gav bäst resultat i analysen)
            elif h["days_held"] >= 20: exit_p, exit_r = row.Close, "Time Exit (20d)"
            
            if exit_p:
                cash += (h["qty"] * exit_p) - comm_val
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": current_date.strftime("%Y-%m-%d"), "pl": round((exit_p - h["entry_price"]) * h["qty"] - (2*comm_val), 2), "pl_pct": round(((exit_p/h["entry_price"])-1)*100, 2), "reason": exit_r})
            else: still_holding.append(h)
        holdings = still_holding

        # 2. Köp ny (Endast i BULL-marknad och vid "Miner's Edge")
        cur_v = cash + sum(h["qty"] * float(all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].Close.iloc[-1]) for h in holdings if not all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].empty)
        target_pos = cur_v * pos_size_pct
        
        if m_bull and cash >= target_pos + comm_val:
            best_sym = None
            for sym, df in all_data.items():
                if any(h["symbol"] == sym for h in holdings): continue
                past = df[df.index <= current_date]
                if len(past) < 60: continue
                try:
                    r = past.iloc[-1]
                    # "Miner's Edge" - Översålt (RSI < 35) + Stark trend (MA50 > MA200)
                    if r.RSI < 35 and r.MA50 > r.MA200:
                        best_sym = sym; break 
                except: continue
            
            if best_sym:
                row = all_data[best_sym][all_data[best_sym].index == current_date].iloc[0]
                entry = float(row.Close)
                holdings.append({"symbol": best_sym, "entry_price": entry, "sl": entry - (4.0 * row.ATR), "qty": target_pos / entry, "entry_date": current_date, "days_held": 0, "buy_fee": comm_val, "hwm": entry})
                cash -= (target_pos + comm_val)

        if current_date.weekday() == 0: history.append({"date": current_date.strftime("%Y-%m-%d"), "value": round(cur_v, 2)})
        current_date += timedelta(days=1)

    for h in holdings:
        last_p = float(all_data[h["symbol"]].Close.iloc[-1])
        trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": end_dt.strftime("%Y-%m-%d"), "pl": round((last_p - h["entry_price"]) * h["qty"] - (2*comm_val), 2), "pl_pct": round(((last_p/h["entry_price"])-1)*100, 2), "reason": "Testslut"})
        cash += (h["qty"] * last_p) - comm_val
    return {"final_value": round(cash, 2), "total_return_pct": round((cash/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
