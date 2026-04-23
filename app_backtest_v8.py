def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size_val=10, config=None):
    conf = config or {}
    # Vi ignorerar min_score från UI och kör på den vetenskapliga Score 7
    min_score = 7 
    comm_val = float(conf.get("comm_val", 0))
    pos_size_pct = (pos_size_val / 100.0) if pos_size_val <= 100 else (pos_size_val / capital)

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
            if not df.empty and len(df) > 100:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df.index = df.index.normalize()
                df["MA50"], df["MA200"] = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
                df["RSI"], df["ATR"] = calc_rsi(df.Close), calc_atr(df)
                df["MACD"], df["MACD_sig"] = calc_macd(df.Close)
                df["BB_up"], _, df["BB_low"] = calc_bb(df.Close)
                all_data[sym] = df
        except: continue

    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []

    while current_date <= end_dt:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1); continue
        
        m_data = {"bull": True, "idx_return": 0, "ticker": idx_ticker}
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_data["bull"] = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True

        # 1. Hantera exits
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            day_rows = df[df.index == current_date]
            if day_rows.empty: still_holding.append(h); continue
            row = day_rows.iloc[0]
            h["days_held"] += 1
            
            exit_p, exit_r = None, None
            
            # EXIT 1: Stop-loss (3x ATR)
            if row.Low <= h["sl"]: exit_p, exit_r = h["sl"], "Stop-Loss (3xATR)"
            # EXIT 2: Time-based (12 dagar var optimalt i analysen)
            elif h["days_held"] >= 12: exit_p, exit_r = row.Close, "Time Exit (12d)"
            # EXIT 3: Score Weakness
            else:
                try:
                    past = df[df.index <= current_date]
                    # Vi använder den förenklade scoren från data_miner
                    score = 0
                    r = past.iloc[-1]
                    if r.MA50 > r.MA200: score += 2
                    if 32 <= r.RSI <= 52: score += 2
                    if r.MACD > r.MACD_sig: score += 2
                    if abs(r.Close - r.MA50)/r.MA50 < 0.04: score += 2
                    if r.Volume > past.Volume.rolling(20).mean().iloc[-1]: score += 2
                    
                    if score < 5: exit_p, exit_r = row.Close, "Weak Score (<5)"
                except: pass

            if exit_p:
                cash += (h["qty"] * exit_p) - comm_val
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": current_date.strftime("%Y-%m-%d"), "pl": round((exit_p - h["entry_price"]) * h["qty"] - (2*comm_val), 2), "pl_pct": round(((exit_p/h["entry_price"])-1)*100, 2), "reason": exit_r})
            else:
                still_holding.append(h)
        holdings = still_holding

        # 2. Köp ny (Max 1 per dag, endast vid Score 7)
        cur_v = cash + sum(h["qty"] * float(all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].Close.iloc[-1]) for h in holdings if not all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date].empty)
        target_pos = cur_v * 0.25 # Vi kör fast 25% per aktie för bäst effekt
        
        if cash >= target_pos + comm_val:
            best_sym = None
            for sym, df in all_data.items():
                if any(h["symbol"] == sym for h in holdings): continue
                past = df[df.index <= current_date]
                if len(past) < 60: continue
                try:
                    r = past.iloc[-1]
                    score = 0
                    if r.MA50 > r.MA200: score += 2
                    if 32 <= r.RSI <= 52: score += 2
                    if r.MACD > r.MACD_sig: score += 2
                    if abs(r.Close - r.MA50)/r.MA50 < 0.04: score += 2
                    if r.Volume > past.Volume.rolling(20).mean().iloc[-1]: score += 2
                    
                    if score == 7: # SNIPER ENTRY
                        best_sym = sym; break 
                except: continue
            
            if best_sym:
                row = all_data[best_sym][all_data[best_sym].index == current_date].iloc[0]
                entry = float(row.Close)
                holdings.append({"symbol": best_sym, "entry_price": entry, "sl": entry - (3.0 * row.ATR), "qty": target_pos / entry, "entry_date": current_date, "days_held": 0, "buy_fee": comm_val})
                cash -= (target_pos + comm_val)

        if current_date.weekday() == 0: history.append({"date": current_date.strftime("%Y-%m-%d"), "value": round(cur_v, 2)})
        current_date += timedelta(days=1)

    return {"final_value": round(cur_v, 2), "total_return_pct": round((cur_v/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
