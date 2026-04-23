def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size=10, config=None):
    conf = config or {}
    min_score, exit_type = int(conf.get("min_score", 6)), conf.get("exit_type", "sltp")
    sl_pct, tp_pct = float(conf.get("sl_pct", 5)) / 100, float(conf.get("tp_pct", 10)) / 100
    comm_type, comm_val = conf.get("comm_type", "fixed"), float(conf.get("comm_val", 0))
    market = conf.get("market", "omxs")

    # pos_size är nu procent (t.ex. 20 för 20%) av din AKTUELLA depå!
    pos_size_pct = pos_size / 100.0

    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=years * 365)
    
    idx_ticker = "^OMX" if market == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=350), end=end_dt)
    if not idx_df.empty:
        if idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
        idx_df.index = idx_df.index.normalize()
        idx_df["MA200"] = idx_df.Close.rolling(200).mean()

    all_data = {}
    print(f"Backtest PRO: Hämtar data för {len(symbols_dict)} aktier...")
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=300), end=end_dt)
            if not df.empty and len(df) > 150:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df.index = df.index.normalize()
                df["MA20"] = df.Close.rolling(20).mean()
                df["MA50"] = df.Close.rolling(50).mean()
                df["MA200"] = df.Close.rolling(200).mean()
                df["RSI"] = calc_rsi(df.Close)
                df["ATR"] = calc_atr(df)
                df["MACD"], df["MACD_sig"], _ = calc_macd(df.Close)
                df["BB_upper"], df["BB_mid"], df["BB_lower"] = calc_bb(df.Close)
                df["BB_width"] = (df["BB_upper"] - df["BB_lower"]) / df["BB_mid"]
                df["Mom_6m"] = df.Close.pct_change(125)
                all_data[sym] = df
        except: continue

    def calc_fee(amt): return amt * (comm_val / 100) if comm_type == "pct" else comm_val
    current_date, cash, trades, holdings, history = start_dt, capital, [], [], []

    while current_date <= end_dt:
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1); continue
        
        day_str = current_date.strftime("%Y-%m-%d")
        
        m_data = {"bull": True, "idx_return": 0, "ticker": idx_ticker, "idx_mom_6m": 0}
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_data["bull"] = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True
                if len(p_idx) > 125:
                    m_data["idx_mom_6m"] = (p_idx.Close.iloc[-1] / p_idx.Close.iloc[-125] - 1)
                if len(p_idx) > 65:
                    m_data["idx_return"] = (p_idx.Close.iloc[-1] / p_idx.Close.iloc[-65] - 1) * 100

        # Beräkna totalt portföljvärde för compounding (ränta på ränta)
        cur_val = cash
        for h in holdings:
            p_val = all_data[h["symbol"]][all_data[h["symbol"]].index <= current_date]
            if not p_val.empty: cur_val += (h["qty"] * float(p_val.Close.iloc[-1]))
        
        target_pos_size_sek = cur_val * pos_size_pct

        # 1. Hantera exits
        still_holding = []
        for h in holdings:
            df = all_data[h["symbol"]]
            day_rows = df[df.index == current_date]
            if day_rows.empty: still_holding.append(h); continue
            row = day_rows.iloc[0]
            
            exit_p, exit_r = None, None
            if exit_type != "hold":
                if row.High > h["hwm"]:
                    h["hwm"] = row.High
                    if exit_type == "trailing":
                        nsl = row.High * (1 - sl_pct)
                        if h["sl"] is None or nsl > h["sl"]: h["sl"] = nsl
                
                if h["sl"] and row.Low <= h["sl"]: 
                    exit_p, exit_r = h["sl"], "Stop-Loss"
                elif h["tp"] and row.High >= h["tp"]: 
                    # PRO-ENGINE: Trend-Riding - Om priset är över MA20, strunta i Take-Profit och rid trenden
                    if row.Close > row.MA20:
                        h["tp"] = None # Raderar TP
                        h["sl"] = row.MA20 # Trail Stop-Loss under MA20
                    else:
                        exit_p, exit_r = h["tp"], "Take-Profit"
                elif h["tp"] is None and row.Close < row.MA20:
                    exit_p, exit_r = row.Close, "Trendbrott (MA20)"
            
            if exit_p:
                fee = calc_fee(h["qty"] * exit_p)
                cash += (h["qty"] * exit_p) - fee
                trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": day_str, "pl": round((exit_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((exit_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": exit_r})
            else:
                # Sälj på svaghet
                if exit_type != "hold":
                    try:
                        past_df = df[df.index <= current_date]
                        cur_score = calc_swing_score(past_df, gen_signal(past_df), m_data)["score"]
                        if cur_score < (min_score - 1) and h["tp"] is not None:
                            exit_p = row.Close
                            fee = calc_fee(h["qty"] * exit_p)
                            cash += (h["qty"] * exit_p) - fee
                            trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": day_str, "pl": round((exit_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((exit_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": "Svaghet"})
                            continue
                    except: pass
                still_holding.append(h)
        holdings = still_holding

        # 2. Köp ny (Måndagar)
        if current_date.weekday() == 0 and cash >= target_pos_size_sek + calc_fee(target_pos_size_sek):
            candidates = []
            for sym, df in all_data.items():
                if any(h["symbol"] == sym for h in holdings): continue
                past_df = df[df.index <= current_date]
                if len(past_df) < 130: continue
                try:
                    # PRO-ENGINE 1: Alpha filter (Minst dubbla index-avkastningen senaste halvåret)
                    stock_mom = past_df.Mom_6m.iloc[-1]
                    idx_mom = m_data["idx_mom_6m"]
                    if idx_mom > 0 and stock_mom < idx_mom * 2: continue
                    if idx_mom <= 0 and stock_mom < 0: continue

                    # PRO-ENGINE 2: VCP Squeeze filter (Bollinger Band extremt smalt)
                    bb_w = past_df.BB_width.iloc[-1]
                    bb_w_min = past_df.BB_width.tail(100).min()
                    bb_w_max = past_df.BB_width.tail(100).max()
                    bb_rank = (bb_w - bb_w_min) / (bb_w_max - bb_w_min + 1e-9)
                    
                    sw = calc_swing_score(past_df, gen_signal(past_df), m_data)
                    
                    # Om vi har en VCP Squeeze (<20%), tvinga upp score!
                    if bb_rank < 0.20:
                        sw["score"] += 3
                        
                    if sw["score"] >= min_score:
                        candidates.append({"sym": sym, "score": sw["score"], "sltp": calc_sltp(past_df, float(past_df.Close.iloc[-1]))})
                except: continue
            
            if candidates:
                candidates.sort(key=lambda x: x["score"], reverse=True)
                best = candidates[0]
                row = all_data[best["sym"]][all_data[best["sym"]].index == current_date]
                if not row.empty:
                    entry, buy_fee = float(row.Close.iloc[0]), calc_fee(target_pos_size_sek)
                    sl, tp = None, None
                    if exit_type == "sltp": sl, tp = best["sltp"]["stop_loss"], best["sltp"]["take_profit_2"]
                    elif exit_type in ["fixed", "trailing"]:
                        sl, tp = entry * (1 - sl_pct), entry * (1 + tp_pct)
                        if exit_type == "trailing": tp = None
                    holdings.append({"symbol": best["sym"], "entry_price": entry, "sl": sl, "tp": tp, "qty": target_pos_size_sek / entry, "entry_date": current_date, "hwm": entry, "buy_fee": buy_fee})
                    cash -= (target_pos_size_sek + buy_fee)

        if current_date.weekday() == 0:
            history.append({"date": day_str, "value": round(cur_val, 2)})
        
        current_date += timedelta(days=1)

    for h in holdings:
        last_p = float(all_data[h["symbol"]].Close.iloc[-1])
        fee = calc_fee(h["qty"] * last_p)
        trades.append({"symbol": h["symbol"], "entry_date": h["entry_date"].strftime("%Y-%m-%d"), "exit_date": end_dt.strftime("%Y-%m-%d"), "pl": round((last_p - h["entry_price"]) * h["qty"] - fee - h["buy_fee"], 2), "pl_pct": round(((last_p * h["qty"] - fee) / (h["entry_price"] * h["qty"] + h["buy_fee"]) - 1)*100, 2), "reason": "Testslut (Innehav)"})
        cash += (h["qty"] * last_p) - fee

    return {"final_value": round(cash, 2), "total_return_pct": round((cash/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
