def run_strategy_backtest(symbols_dict, years=1, capital=100, pos_size=10, config=None):
    conf = config or {}
    min_score = int(conf.get("min_score", 7))
    exit_type = conf.get("exit_type", "sltp")
    sl_pct, tp_pct = float(conf.get("sl_pct", 5)) / 100, float(conf.get("tp_pct", 10)) / 100
    comm_type, comm_val = conf.get("comm_type", "fixed"), float(conf.get("comm_val", 0))

    end_dt, start_dt = datetime.now(), datetime.now() - timedelta(days=years * 365)
    market = conf.get("market", "omxs")
    idx_ticker = "^OMX" if market == "omxs" else "^NDX"
    idx_df = yf.Ticker(idx_ticker).history(start=start_dt - timedelta(days=300), end=end_dt)
    if not idx_df.empty:
        if idx_df.index.tzinfo: idx_df.index = idx_df.index.tz_localize(None)
        idx_df["MA200"] = idx_df.Close.rolling(200).mean()

    all_data = {}
    for sym in symbols_dict:
        try:
            df = yf.Ticker(sym).history(start=start_dt - timedelta(days=250), end=end_dt)
            if not df.empty and len(df) > 100:
                if df.index.tzinfo: df.index = df.index.tz_localize(None)
                df["MA50"], df["MA200"] = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
                df["RSI"] = calc_rsi(df.Close)
                df["MACD"], df["MACD_sig"], _ = calc_macd(df.Close)
                df["ATR"] = calc_atr(df)
                df["BB_upper"], _, df["BB_lower"] = calc_bb(df.Close)
                all_data[sym] = df
        except: continue

    def calc_fee(amt): return amt * (comm_val / 100) if comm_type == "pct" else comm_val

    current_date, cash, trades, active_trade, history = start_dt, capital, [], None, []

    while current_date < end_dt:
        if current_date.weekday() != 0:
            current_date += timedelta(days=1); continue
        day_str = current_date.strftime("%Y-%m-%d")
        m_data = {"bull": True, "idx_return": 0, "ticker": idx_ticker}
        if not idx_df.empty:
            p_idx = idx_df[idx_df.index <= current_date]
            if not p_idx.empty:
                m_data["bull"] = bool(p_idx.Close.iloc[-1] > p_idx.MA200.iloc[-1]) if not pd.isna(p_idx.MA200.iloc[-1]) else True
                if len(p_idx) > 65: m_data["idx_return"] = (p_idx.Close.iloc[-1] / p_idx.Close.iloc[-65] - 1) * 100

        if active_trade:
            sym, df = active_trade["symbol"], all_data[active_trade["symbol"]]
            week_data = df[(df.index >= current_date) & (df.index < current_date + timedelta(days=7))]
            exit_p, exit_r, exit_d = None, None, None
            if exit_type != "hold":
                for d, row in week_data.iterrows():
                    if row.High > active_trade["hwm"]:
                        active_trade["hwm"] = row.High
                        if exit_type == "trailing":
                            new_sl = row.High * (1 - sl_pct)
                            if active_trade["sl"] is None or new_sl > active_trade["sl"]: active_trade["sl"] = new_sl
                    if active_trade["sl"] and row.Low <= active_trade["sl"]:
                        exit_p, exit_r, exit_d = active_trade["sl"], "Stop-Loss", d; break
                    if active_trade["tp"] and row.High >= active_trade["tp"]:
                        exit_p, exit_r, exit_d = active_trade["tp"], "Take-Profit", d; break
            if exit_p:
                fee = calc_fee(active_trade["qty"] * exit_p)
                profit = (exit_p - active_trade["entry_price"]) * active_trade["qty"] - fee - active_trade["buy_fee"]
                cash += (active_trade["qty"] * exit_p) - fee
                trades.append({"symbol": sym, "entry_date": active_trade["entry_date"].strftime("%Y-%m-%d"), "exit_date": exit_d.strftime("%Y-%m-%d"), "pl": round(profit, 2), "pl_pct": round(((exit_p * active_trade["qty"] - fee) / (active_trade["entry_price"] * active_trade["qty"] + active_trade["buy_fee"]) - 1)*100, 2), "reason": exit_r})
                active_trade = None

        best_sym, best_score, best_sltp = None, -1, None
        for sym, df in all_data.items():
            past_df = df[df.index <= current_date]
            if len(past_df) < 60: continue
            try:
                sig = gen_signal(past_df)
                swing = calc_swing_score(past_df, sig, m_data)
                if swing["score"] > best_score: best_score, best_sym = swing["score"], sym; best_sltp = calc_sltp(past_df, float(past_df.Close.iloc[-1]))
            except: continue
        
        sell_current = False
        if active_trade and exit_type != "hold":
            cur_df = all_data[active_trade["symbol"]]
            cur_past = cur_df[cur_df.index <= current_date]
            try:
                cur_sig = gen_signal(cur_past)
                cur_score = calc_swing_score(cur_past, cur_sig, m_data)["score"]
                if (best_sym != active_trade["symbol"] and best_score >= cur_score + 2) or (cur_score < min_score):
                    sell_current = True
                    exit_reason = "Screener-byte" if best_score >= cur_score + 2 else "Svaghet"
            except: pass

        if sell_current and active_trade:
            df_old = all_data[active_trade["symbol"]]
            exit_row = df_old[df_old.index > current_date].head(1)
            if not exit_row.empty:
                cur_p = float(exit_row.Open.iloc[0])
                fee = calc_fee(active_trade["qty"] * cur_p)
                profit = (cur_p - active_trade["entry_price"]) * active_trade["qty"] - fee - active_trade["buy_fee"]
                cash += (active_trade["qty"] * cur_p) - fee
                trades.append({"symbol": active_trade["symbol"], "entry_date": active_trade["entry_date"].strftime("%Y-%m-%d"), "exit_date": exit_row.index[0].strftime("%Y-%m-%d"), "pl": round(profit, 2), "pl_pct": round(((cur_p * active_trade["qty"] - fee) / (active_trade["entry_price"] * active_trade["qty"] + active_trade["buy_fee"]) - 1)*100, 2), "reason": exit_reason})
                active_trade = None

        if not active_trade and best_sym and best_score >= min_score:
            df_new = all_data[best_sym]
            tue = df_new[df_new.index > current_date].head(1)
            if not tue.empty:
                entry = float(tue.Open.iloc[0])
                qty, buy_fee = pos_size / entry, calc_fee(pos_size)
                sl, tp = None, None
                if exit_type == "sltp": sl, tp = best_sltp["stop_loss"], best_sltp["take_profit_2"]
                elif exit_type in ["fixed", "trailing"]:
                    sl, tp = entry * (1 - sl_pct), entry * (1 + tp_pct)
                    if exit_type == "trailing": tp = None
                if cash >= pos_size + buy_fee:
                    cash -= (pos_size + buy_fee)
                    active_trade = {"symbol": best_sym, "entry_price": entry, "sl": sl, "tp": tp, "qty": qty, "entry_date": tue.index[0], "hwm": entry, "buy_fee": buy_fee}

        current_val = cash
        if active_trade:
            p_val = all_data[active_trade["symbol"]][all_data[active_trade["symbol"]].index <= current_date]
            if not p_val.empty: current_val += (active_trade["qty"] * float(p_val.Close.iloc[-1]))
        history.append({"date": day_str, "value": round(current_val, 2)})
        current_date += timedelta(days=7)

    if active_trade:
        df_end = all_data[active_trade["symbol"]]
        last_p = float(df_end.Close.iloc[-1])
        fee = calc_fee(active_trade["qty"] * last_p)
        trades.append({"symbol": active_trade["symbol"], "entry_date": active_trade["entry_date"].strftime("%Y-%m-%d"), "exit_date": df_end.index[-1].strftime("%Y-%m-%d"), "pl": round((last_p - active_trade["entry_price"]) * active_trade["qty"] - fee - active_trade["buy_fee"], 2), "pl_pct": round(((last_p * active_trade["qty"] - fee) / (active_trade["entry_price"] * active_trade["qty"] + active_trade["buy_fee"]) - 1)*100, 2), "reason": "Testslut"})
        current_val = cash + (active_trade["qty"] * last_p) - fee

    return {"final_value": round(current_val, 2), "total_return_pct": round((current_val/capital - 1) * 100, 2), "trades": trades, "history": history, "win_rate": round(len([t for t in trades if t["pl"] > 0]) / len(trades) * 100, 1) if trades else 0}
