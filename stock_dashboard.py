import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import re
import requests
import html  # 🌟 新增：用於解碼網頁 HTML 實體亂碼

# --- 1. 設定與觀察池資料存取 ---
WATCHLIST_FILE = 'my_watchlist.json'

def extract_ticker(display_name):
    """從 '穩懋 (3105.TWO)' 中萃取出 '3105.TWO'"""
    match = re.search(r'\((.*?)\)', display_name)
    return match.group(1) if match else display_name

def get_stock_name(ticker):
    """【五引擎強效抓取 - 上櫃股終極修正版】修復 .TWO 上櫃股票抓不到中文的 Bug"""
    clean_ticker = ticker.replace('.TW', '').replace('.TWO', '')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    def parse_title(html_text):
        # 1. 嚴格限制只抓取 <title> 和 </title> 之間的內容
        t_match = re.search(r'<title>(.*?)</title>', html_text, re.IGNORECASE | re.DOTALL)
        if t_match:
            # 2. 解碼 HTML 實體 (如 &#x5373; 轉回中文)
            raw_title = html.unescape(t_match.group(1).strip())
            # 3. 擷取數字或括號前的純中文名稱 (包含處理 -KY 這種後綴)
            name_match = re.search(r'^([^\(0-9]+)', raw_title)
            if name_match:
                name = name_match.group(1).strip()
                # 4. 排除無效的預設網站標題雜訊與防爬蟲頁面
                invalid_names = ['Yahoo', '玩股網', 'CMoney', '即時股價行情', '查無此股票', '404', '台股', 'Just a moment', 'Attention', '找不到']
                if name and not any(invalid in name for invalid in invalid_names):
                    return name
        return None

    # 引擎 1：Yahoo 台灣股市 (保留 .TWO 後綴，這是上櫃股抓不到的真正原因！)
    try:
        url = f"https://tw.stock.yahoo.com/quote/{ticker}"
        response = requests.get(url, headers=headers, timeout=5)
        name = parse_title(response.text)
        if name: return f"{name} ({ticker})"
    except Exception: pass

    # 引擎 2：Yahoo 台灣股市 (純數字備用)
    try:
        url = f"https://tw.stock.yahoo.com/quote/{clean_ticker}"
        response = requests.get(url, headers=headers, timeout=5)
        name = parse_title(response.text)
        if name: return f"{name} ({ticker})"
    except Exception: pass

    # 引擎 3：玩股網 Wantgoo
    try:
        url = f"https://www.wantgoo.com/stock/{clean_ticker}"
        response = requests.get(url, headers=headers, timeout=5)
        name = parse_title(response.text)
        if name: return f"{name} ({ticker})"
    except Exception: pass

    # 引擎 4：CMoney
    try:
        url = f"https://www.cmoney.tw/finance/{clean_ticker}"
        response = requests.get(url, headers=headers, timeout=5)
        name = parse_title(response.text)
        if name: return f"{name} ({ticker})"
    except Exception: pass

    # 引擎 5：yfinance 原生 (終極備用)
    try:
        info = yf.Ticker(ticker).info
        short_name = info.get('shortName', '')
        if short_name:
            return f"{short_name} ({ticker})"
    except Exception: pass
        
    return ticker

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return ["台積電 (2330.TW)", "鴻海 (2317.TW)", "聯發科 (2454.TW)"]

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(watchlist, f)

def send_line_notify(token, message):
    if not token:
        return False
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"message": message}
    try:
        response = requests.post(url, headers=headers, data=data)
        return response.status_code == 200
    except Exception:
        return False

# --- 2. 高階技術分析計算 ---
def calculate_indicators(df):
    """計算均線、高階K棒型態、指標與量價關係"""
    # 均線
    df['5MA'] = df['Close'].rolling(window=5).mean()
    df['10MA'] = df['Close'].rolling(window=10).mean()
    df['20MA'] = df['Close'].rolling(window=20).mean()
    df['60MA'] = df['Close'].rolling(window=60).mean()
    df['20MA_Slope'] = df['20MA'].diff()
    
    # KD
    df['9K_Min'] = df['Low'].rolling(window=9).min()
    df['9K_Max'] = df['High'].rolling(window=9).max()
    df['RSV'] = (df['Close'] - df['9K_Min']) / (df['9K_Max'] - df['9K_Min']) * 100
    df['RSV'] = df['RSV'].fillna(50)
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    
    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    # RSI (14)
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # CCI (14)
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    mad_tp = tp.rolling(14).apply(lambda x: pd.Series(x).sub(pd.Series(x).mean()).abs().mean(), raw=True)
    df['CCI'] = (tp - tp.rolling(14).mean()) / (0.015 * mad_tp)

    # OBV (能量潮指標)
    df['Direction'] = 0
    df.loc[df['Close'] > df['Close'].shift(1), 'Direction'] = 1
    df.loc[df['Close'] < df['Close'].shift(1), 'Direction'] = -1
    df['OBV'] = (df['Volume'] * df['Direction']).cumsum()
    df['OBV_20MA'] = df['OBV'].rolling(window=20).mean()

    # 布林通道 (20MA, 2 std)
    df['BB_std'] = df['Close'].rolling(window=20).std()
    df['BB_upper'] = df['20MA'] + (df['BB_std'] * 2)
    df['BB_lower'] = df['20MA'] - (df['BB_std'] * 2)
    df['BB_width'] = (df['BB_upper'] - df['BB_lower']) / df['20MA'] * 100

    # 量能與K棒
    df['Vol_5MA'] = df['Volume'].rolling(window=5).mean()
    df['Prev_Vol'] = df['Volume'].shift(1)
    df['Body'] = abs(df['Close'] - df['Open'])
    df['Total_Range'] = df['High'] - df['Low']
    df['Body_Pct'] = (df['Body'] / df['Open']) * 100 
    df['Upper_Shadow'] = df['High'] - df[['Open', 'Close']].max(axis=1)
    df['Lower_Shadow'] = df[['Open', 'Close']].min(axis=1) - df['Low']
    df['Is_Red'] = df['Close'] > df['Open']
    df['Is_Black'] = df['Close'] < df['Open']
    
    df['Gap_Up'] = df['Low'] > df['High'].shift(1)
    df['Gap_Down'] = df['High'] < df['Low'].shift(1)
    df['Drop_5_Days'] = (df['Close'].shift(1) - df['High'].shift(6)) / df['High'].shift(6) * 100

    last = df.iloc[-1]
    prev1 = df.iloc[-2]
    prev2 = df.iloc[-3]
    prev3 = df.iloc[-4]
    
    def is_star(row):
        return row['Body'] <= (row['Total_Range'] * 0.3) and row['Total_Range'] > 0

    # 整理訊號字典
    signals = {
        'is_bullish': (last['Close'] > last['5MA'] > last['20MA'] > last['60MA']),
        'break_5ma': last['Close'] < last['5MA'],
        'break_20ma': last['Close'] < last['20MA'],
        'huge_vol': last['Volume'] > (last['Vol_5MA'] * 2),
        
        # 指標訊號
        'kd_golden_cross': prev1['K'] <= prev1['D'] and last['K'] > last['D'],
        'kd_death_cross': prev1['K'] >= prev1['D'] and last['K'] < last['D'],
        'macd_red': last['MACD_Hist'] > 0 and last['MACD_Hist'] > prev1['MACD_Hist'],
        'macd_green': last['MACD_Hist'] < 0 and last['MACD_Hist'] < prev1['MACD_Hist'],
        'ma_golden_cross': prev1['5MA'] <= prev1['20MA'] and last['5MA'] > last['20MA'],
        'ma_death_cross': prev1['5MA'] >= prev1['20MA'] and last['5MA'] < last['20MA'],
        'bb_squeeze': last['BB_width'] < 10,
        
        'cci_buy': prev1['CCI'] < -100 and last['CCI'] >= -100,
        'cci_sell': prev1['CCI'] > 100 and last['CCI'] <= 100,
        'obv_bull': last['OBV'] > last['OBV_20MA'],
        'obv_bear': last['OBV'] < last['OBV_20MA'],

        # 轉折型態
        'abc_breakout': (last['20MA_Slope'] > 0) and (last['Body_Pct'] > 2) and (last['Volume'] > last['Prev_Vol'] * 1.3) and (last['Close'] > df['High'].shift(1).iloc[-1]) and last['Is_Red'],
        'island_bottom': last['Gap_Up'] and df['Gap_Down'].shift(2).iloc[-1] and last['Is_Red'],
        'v_reversal': (last['Drop_5_Days'] < -8) and (last['Volume'] > last['Vol_5MA'] * 1.5) and last['Is_Red'] and (last['Close'] > df['High'].shift(1).iloc[-1]),
        'hammer_bottom': (last['Lower_Shadow'] > last['Body'] * 2) and (last['Upper_Shadow'] < last['Body']) and (last['Close'] < last['20MA']),
        'n_bottom': (last['Low'] > df['Low'].rolling(10).min().iloc[-2]) and (last['Close'] > last['20MA']) and last['Is_Red'] and (prev1['Close'] < prev1['20MA']),
        'morning_star': prev2['Is_Black'] and is_star(prev1) and last['Is_Red'] and (last['Close'] > (prev2['Open'] + prev2['Close'])/2),

        'engulfing_bear': prev1['Is_Red'] and last['Is_Black'] and (last['Open'] > prev1['Close']) and (last['Close'] < prev1['Open']),
        'dark_cloud': prev1['Is_Red'] and last['Is_Black'] and (last['Open'] > prev1['Close']) and (last['Close'] < (prev1['Open'] + prev1['Close']) / 2),
        'harami_bear': prev1['Is_Red'] and (prev1['Body_Pct'] > 2) and (last['High'] < prev1['Close']) and (last['Low'] > prev1['Open']),
        'double_star_drop': prev3['Is_Red'] and (prev3['Body_Pct'] > 2) and is_star(prev2) and is_star(prev1) and last['Is_Black'] and (last['Close'] < prev3['Low']),
        'island_top': last['Gap_Down'] and df['Gap_Up'].shift(1).iloc[-1] and last['Is_Black'],
        'gravestone_top': (last['Upper_Shadow'] > last['Body'] * 2) and (last['Lower_Shadow'] < last['Body']) and (last['Close'] > last['20MA'])
    }

    return df, signals

# --- 3. UI 介面設計 ---
st.set_page_config(page_title="林穎流 - 個股觀察池", layout="wide")

# 注入防護代碼：試圖阻擋瀏覽器自動翻譯破壞網頁 DOM
st.markdown("""
    <meta name="google" content="notranslate">
    <style>
        .skiptranslate { display: none !important; }
    </style>
""", unsafe_allow_html=True)

st.title("📈 朱家泓 × 林穎：V4.0 專業操盤全智能雷達")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

with st.sidebar:
    st.header("📋 我的觀察池")
    new_stock = st.text_input("新增股票代號 (例: 2603 或 3105)").upper()
    
    if st.button("加入名單"):
        if new_stock:
            # 智慧判斷 上市(.TW) 還是 上櫃(.TWO)
            if new_stock.isdigit():
                with st.spinner("正在辨識上市或上櫃..."):
                    test_tw = yf.Ticker(f"{new_stock}.TW").history(period="1d")
                    if not test_tw.empty:
                        new_stock += ".TW"
                    else:
                        test_two = yf.Ticker(f"{new_stock}.TWO").history(period="1d")
                        if not test_two.empty:
                            new_stock += ".TWO"
                        else:
                            new_stock += ".TW"

            existing_tickers = [extract_ticker(s) for s in st.session_state.watchlist]
            if new_stock not in existing_tickers:
                with st.spinner("啟動四引擎抓取中文名稱中..."):
                    formatted_name = get_stock_name(new_stock)
                st.session_state.watchlist.append(formatted_name)
                save_watchlist(st.session_state.watchlist)
                st.success(f"已加入 {formatted_name}!")
                st.rerun()
            else:
                st.warning("該股票已在觀察池中！")

    st.divider()
    st.header("🗑️ 批次刪除區")
    st.write("💡 僅供刪除使用。欲切換分析，請至右側主畫面「下拉選單」。")
    
    selected_for_deletion = []
    for stock in st.session_state.watchlist:
        is_checked = st.checkbox(stock, key=f"del_{stock}")
        if is_checked:
            selected_for_deletion.append(stock)
            
    if st.button("🗑️ 刪除勾選的股票"):
        if selected_for_deletion:
            for s in selected_for_deletion:
                st.session_state.watchlist.remove(s)
            save_watchlist(st.session_state.watchlist)
            st.success("刪除成功！")
            st.rerun()
        else:
            st.warning("請先勾選要刪除的股票")

# --- 主畫面：個股資訊與圖表 ---
if not st.session_state.watchlist:
    st.info("你的觀察池目前是空的，請從左側新增股票！")
else:
    selected_stock = st.selectbox("📊 當前分析股名 (請下拉選擇)：", st.session_state.watchlist)
    st.markdown("---")
    
    ticker_symbol = extract_ticker(selected_stock)
    
    with st.spinner(f'正在分析 {selected_stock}...'):
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="6mo")
        
        if df.empty or len(df) < 20:
            st.error("找不到該股票資料，或上市時間過短無法計算。")
        else:
            df, sigs = calculate_indicators(df)
            
            # --- 最新股價與漲跌幅 ---
            last_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            price_change = last_price - prev_price
            pct_change = (price_change / prev_price) * 100
            
            # 台灣在地化配色
            if price_change > 0:
                price_color = "#ff4b4b" # 紅漲
                sign = "▲ +"
            elif price_change < 0:
                price_color = "#00cc96" # 綠跌
                sign = "▼ "
            else:
                price_color = "#888888" # 灰平
                sign = "➖ "
            
            st.markdown(f"### 💰 最新盤價：<span style='color:{price_color}; font-weight:bold;'>{last_price:.2f} ({sign}{price_change:.2f}, {sign}{pct_change:.2f}%)</span>", unsafe_allow_html=True)
            
            # --- 綜合診斷儀表板 ---
            st.markdown("##### 🩺 雙向診斷看板 (台股配色：🔴 多方 / 🟢 空方 / ⚪ 中性)")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**作多與底部訊號**")
                if sigs['v_reversal']: st.markdown("🔴 V型反轉起漲")
                elif sigs['morning_star']: st.markdown("🔴 晨星反轉打底")
                elif sigs['abc_breakout']: st.markdown("🔴 ABC強勢突破")
                elif sigs['n_bottom']: st.markdown("🔴 N字底雛形")
                elif sigs['ma_golden_cross']: st.markdown("🔴 5均上穿月線 (金叉)")
                elif sigs['cci_buy']: st.markdown("🔴 CCI 跌深反轉買點")
                elif sigs['is_bullish']: st.markdown("🔴 四線多頭排列")
                else: st.markdown("⚪ 無特殊多方訊號")
                
            with col2:
                st.markdown("**空方逃命與頭部**")
                if sigs['engulfing_bear']: st.markdown("🟢 長黑吞噬 (快逃)")
                elif sigs['island_top']: st.markdown("🟢 孤島夜星 (逃命)")
                elif sigs['double_star_drop']: st.markdown("🟢 雙星下殺 (轉弱)")
                elif sigs['harami_bear']: st.markdown("🟢 母子懷抱 (滯漲)")
                elif sigs['ma_death_cross']: st.markdown("🟢 5均下穿月線 (死叉)")
                elif sigs['cci_sell']: st.markdown("🟢 CCI 高檔回落賣點")
                else: st.markdown("⚪ 無特殊空方轉折")
                
            with col3:
                st.markdown("**防禦紀律與動能**")
                if sigs['huge_vol']: st.markdown("🟢 高檔爆量 (提防出貨)")
                if sigs['break_5ma']: st.markdown("🟢 跌破 5 日線 (短線弱)")
                if sigs['break_20ma']: st.markdown("🟢 跌破 20 日線 (中線弱)")
                if not (sigs['huge_vol'] or sigs['break_5ma'] or sigs['break_20ma']):
                    st.markdown("🔴 均線防守穩健")
                
                if sigs['obv_bull']: st.markdown("🔴 OBV 籌碼偏多")
                elif sigs['obv_bear']: st.markdown("🟢 OBV 籌碼偏空")
                
                if sigs['macd_red']: st.markdown("🔴 MACD 紅柱增強")
                elif sigs['macd_green']: st.markdown("🟢 MACD 綠柱增強")

            st.markdown("---")
            st.markdown("### 📝 今日操盤總結與行動建議")
            
            bull_score = sum([sigs['v_reversal'], sigs['abc_breakout'], sigs['n_bottom'], sigs['ma_golden_cross'], sigs['morning_star'], sigs['kd_golden_cross'], sigs['island_bottom'], sigs['hammer_bottom'], sigs['cci_buy']])
            bear_score = sum([sigs['engulfing_bear'], sigs['island_top'], sigs['double_star_drop'], sigs['dark_cloud'], sigs['ma_death_cross'], sigs['kd_death_cross'], sigs['harami_bear'], sigs['break_5ma'], sigs['cci_sell']])

            if bear_score > 0 and bear_score >= bull_score:
                msg = f"#### 🟢 **風險升溫**：今日浮現 {bear_score} 個空方或壓力訊號！\n> **👉 林穎老師行動建議**：手中多單請嚴格檢視停利/停損點（若已跌破5日線請果斷減碼或出場），切勿與趨勢作對。空手者請「多看少做」，絕不在此時摸底接刀。"
            elif bull_score > 0 and bull_score > bear_score:
                msg = f"#### 🔴 **轉強契機**：今日浮現 {bull_score} 個多方攻擊或底部抵抗訊號！\n> **👉 林穎老師行動建議**：多頭趨勢成型或底部轉強，可伺機於「回後買上漲」的時機小量試單，並以今日K線低點作為防守底線，享受波段獲利。"
            elif sigs['bb_squeeze']:
                msg = "#### ⚪ **暴風雨前的寧靜**：布林通道極度壓縮，籌碼正在沉澱。\n> **👉 林穎老師行動建議**：多空交戰即將分出勝負。請密切觀察後續：若是「帶量紅K突破上軌」可偏多操作；若「黑K跌破下軌」請嚴格避開。"
            else:
                msg = "#### ⚪ **震盪或延續趨勢**：今日無明顯極端反轉訊號。\n> **👉 林穎老師行動建議**：請跟隨目前的均線方向（如站穩5日線則安心續抱）。不需要因為盤中隨機的上下跳動而頻繁進出，按照紀律做個快樂的股市公務員。"
            
            st.markdown(msg)

            # --- 繪製七層專業看盤圖表 ---
            fig = make_subplots(rows=7, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.02, 
                                row_heights=[0.35, 0.1, 0.1, 0.1, 0.1, 0.1, 0.15],
                                subplot_titles=("", "", "", "", "", "", ""))
            
            # Row 1: K 線與均線
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['5MA'], line=dict(color='orange', width=1), name='5MA'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['20MA'], line=dict(color='yellow', width=1.5), name='20MA(月)'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['60MA'], line=dict(color='blue', width=2), name='60MA(季)'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_upper'], line=dict(color='rgba(150,150,150,0.5)', width=1, dash='dot'), name='布林上軌'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_lower'], fill='tonexty', fillcolor='rgba(150,150,150,0.1)', line=dict(color='rgba(150,150,150,0.5)', width=1, dash='dot'), name='布林下軌'), row=1, col=1)
            fig.update_yaxes(title_text="<b>K線與均線</b>", row=1, col=1)
            
            # Row 2: 成交量
            colors = ['red' if row['Close'] > row['Open'] else 'green' for index, row in df.iterrows()]
            fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
            fig.update_yaxes(title_text="<b>成交量</b>", row=2, col=1)
            
            # Row 3: OBV 能量潮
            fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], line=dict(color='purple', width=1.5), name='OBV'), row=3, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['OBV_20MA'], line=dict(color='orange', width=1, dash='dot'), name='OBV 20MA'), row=3, col=1)
            fig.update_yaxes(title_text="<b>OBV</b>", row=3, col=1)

            # Row 4: MACD
            macd_colors = ['red' if val >= 0 else 'green' for val in df['MACD_Hist']]
            fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], marker_color=macd_colors, name='MACD 柱狀體'), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='blue', width=1), name='DIF'), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], line=dict(color='orange', width=1), name='MACD'), row=4, col=1)
            fig.update_yaxes(title_text="<b>MACD</b>", row=4, col=1)
            
            # Row 5: KD
            fig.add_trace(go.Scatter(x=df.index, y=df['K'], line=dict(color='blue', width=1.5), name='K值'), row=5, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['D'], line=dict(color='orange', width=1.5), name='D值'), row=5, col=1)
            fig.add_hline(y=80, line_dash="dot", line_color="green", row=5, col=1)
            fig.add_hline(y=20, line_dash="dot", line_color="red", row=5, col=1)
            fig.update_yaxes(title_text="<b>KD(9)</b>", row=5, col=1)
            
            # Row 6: RSI
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='purple', width=1.5), name='RSI(14)'), row=6, col=1)
            fig.add_hline(y=80, line_dash="dot", line_color="green", row=6, col=1)
            fig.add_hline(y=20, line_dash="dot", line_color="red", row=6, col=1)
            fig.update_yaxes(title_text="<b>RSI(14)</b>", row=6, col=1)

            # Row 7: CCI
            fig.add_trace(go.Scatter(x=df.index, y=df['CCI'], line=dict(color='brown', width=1.5), name='CCI(14)'), row=7, col=1)
            fig.add_hline(y=100, line_dash="dot", line_color="green", row=7, col=1)
            fig.add_hline(y=-100, line_dash="dot", line_color="red", row=7, col=1)
            fig.update_yaxes(title_text="<b>CCI(14)</b>", row=7, col=1)
            
            fig.update_layout(
                height=1400, 
                xaxis_rangeslider_visible=False, 
                template="plotly_dark", 
                margin=dict(t=30, b=30),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
            )
            st.plotly_chart(fig, use_container_width=True)