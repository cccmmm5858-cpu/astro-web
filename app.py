from flask import Flask, render_template, request
import pandas as pd
import os
import datetime

app = Flask(__name__)

# --- الثوابت الفلكية (نفس الموجودة في البوت) ---
TRANSIT_PLANETS = [
    ("الشمس",  "Sun Lng"), ("القمر",  "Moon Lng"), ("عطارد",  "Mercury Lng"),
    ("الزهرة", "Venus Lng"), ("المريخ", "Mars Lng"), ("المشتري", "Jupiter Lng"),
    ("زحل",    "Saturn Lng"), ("أورانوس","Uranus Lng"), ("نبتون",  "Neptune Lng"),
    ("بلوتو",  "Pluto Lng"), ("العقدة الشمالية", "Lunar North Node (True) Lng"),
    ("العقدة الجنوبية", "Lunar South Node (True) Lng"),
]

TRANSIT_TIMEFRAMES = {
    "القمر": "15m / 1H", "الشمس": "4H / 10H", "عطارد": "1H / 4H",
    "الزهرة": "1H / 4H", "المريخ": "4H / 1Day", "المشتري": "1W",
    "زحل": "1W", "أورانوس": "1M", "نبتون": "1M", "بلوتو": "1M",
    "العقدة الشمالية": "1W", "العقدة الجنوبية": "1W",
}

ZODIAC_SIGNS = [
    "الحمل", "الثور", "الجوزاء", "السرطان", "الأسد", "العذراء",
    "الميزان", "العقرب", "القوس", "الجدي", "الدلو", "الحوت"
]

PLANET_DIGNITIES = {
    "الشمس":   {"home": ["الأسد"], "exalt": ["الحمل"], "fall": ["الميزان"], "detriment": ["الدلو"]},
    "القمر":   {"home": ["السرطان"], "exalt": ["الثور"], "fall": ["العقرب"], "detriment": ["الجدي"]},
    "عطارد":   {"home": ["الجوزاء", "العذراء"], "exalt": ["العذراء"], "fall": ["الحوت"], "detriment": ["القوس", "الحوت"]},
    "الزهرة":  {"home": ["الثور", "الميزان"], "exalt": ["الحوت"], "fall": ["العذراء"], "detriment": ["العقرب", "الحمل"]},
    "المريخ":  {"home": ["الحمل", "العقرب"], "exalt": ["الجدي"], "fall": ["السرطان"], "detriment": ["الميزان", "الثور"]},
    "المشتري": {"home": ["القوس", "الحوت"], "exalt": ["السرطان"], "fall": ["الجدي"], "detriment": ["الجوزاء", "العذراء"]},
    "زحل":     {"home": ["الجدي", "الدلو"], "exalt": ["الميزان"], "fall": ["الحمل"], "detriment": ["السرطان", "الأسد"]},
}

GLOBAL_STOCK_DF = None
GLOBAL_TRANSIT_DF = None

# --- دوال مساعدة ---
def get_sign_name(degree):
    try: return ZODIAC_SIGNS[int(degree // 30) % 12]
    except: return ""

def get_sign_degree(degree):
    return degree % 30

def get_planet_status(planet_name, sign_name):
    if planet_name not in PLANET_DIGNITIES: return ""
    d = PLANET_DIGNITIES[planet_name]
    if sign_name in d["home"]: return " (في بيته 🏠)"
    if sign_name in d["exalt"]: return " (في شرفه 👑)"
    if sign_name in d["fall"]: return " (في هبوطه 🔻)"
    if sign_name in d["detriment"]: return " (في وباله ⚠️)"
    return ""

def angle_diff(a, b):
    d = abs(a - b) % 360
    if d > 180: d = 360 - d
    return d

def get_aspect_details(angle, orb=1.0):
    aspects = [
        (0,   "اقتران", "🔥"), (60,  "تسديس",  "🟢"), (90,  "تربيع",  "🔴"), 
        (120, "تثليث",  "🟢"), (180, "مقابلة", "🔴"), 
    ]
    for exact, name, icon in aspects:
        diff = abs(angle - exact)
        if diff <= orb: return name, exact, diff, icon
    return None, None, None, None

def format_time_ar(dt):
    return dt.strftime("%I:%M %p").replace("AM", "صباحاً").replace("PM", "مساءً")

# --- تحميل البيانات ---
def load_data():
    global GLOBAL_STOCK_DF, GLOBAL_TRANSIT_DF
    if not os.path.exists("Stock.xlsx") or not os.path.exists("Transit.xlsx"): return 
    try:
        xls = pd.ExcelFile("Stock.xlsx")
        frames = []
        for sh in xls.sheet_names:
            df = xls.parse(sh, header=0)
            if df.shape[1] < 4: continue
            tmp = df.iloc[:, :4].copy()
            tmp.columns = ["السهم", "الكوكب", "البرج", "الدرجة الفلكية"]
            tmp["السهم"] = tmp["السهم"].fillna(sh).replace("", sh)
            tmp = tmp.dropna(subset=["الدرجة الفلكية"])
            tmp["الدرجة الفلكية"] = pd.to_numeric(tmp["الدرجة الفلكية"], errors='coerce')
            frames.append(tmp)
        if frames: GLOBAL_STOCK_DF = pd.concat(frames, ignore_index=True)
        
        df_trans = pd.read_excel("Transit.xlsx")
        df_trans["Datetime"] = pd.to_datetime(df_trans["Datetime"], errors="coerce")
        GLOBAL_TRANSIT_DF = df_trans.dropna(subset=["Datetime"])
    except Exception as e: print(f"Error: {e}")

# --- الحسابات ---
def calculate_ai_score(stock_results):
    score = 0
    planet_scores = {
        "المشتري": 3, "الزهرة": 2, "الشمس": 1, "القمر": 1, "عطارد": 0, "أورانوس": 0, "نبتون": 0,
        "المريخ": -1, "زحل": -2, "بلوتو": -1, "العقدة الشمالية": 1, "العقدة الجنوبية": -1
    }
    aspect_scores = {"تثليث": 2, "تسديس": 2, "اقتران": 0, "تربيع": -2, "مقابلة": -2}

    for res in stock_results:
        p_score = planet_scores.get(res["كوكب العبور"], 0)
        a_score = aspect_scores.get(res["العلاقة"], 0)
        if res["العلاقة"] == "اقتران":
            if p_score > 0: a_score = 2
            elif p_score < 0: a_score = -2
        score += p_score + a_score

    if score >= 4: return "⭐⭐⭐⭐⭐ (فرصة ذهبية!)", "text-green-400"
    elif score >= 2: return "⭐⭐⭐⭐ (فرصة قوية)", "text-green-300"
    elif score >= 0: return "⭐⭐⭐ (متوسطة)", "text-yellow-400"
    elif score >= -2: return "⭐⭐ (حذر)", "text-orange-400"
    else: return "⚠️ (سلبي/خطر)", "text-red-500"

def calc_stock_aspects(stock_name, target_date):
    if GLOBAL_STOCK_DF is None or GLOBAL_TRANSIT_DF is None: return [], None
    start_dt = target_date.replace(hour=0, minute=0, second=0)
    end_dt = target_date.replace(hour=23, minute=59, second=59)

    mask_stock = GLOBAL_STOCK_DF["السهم"].astype(str).str.contains(stock_name, case=False, regex=False)
    sdf = GLOBAL_STOCK_DF.loc[mask_stock].copy()
    if sdf.empty: return [], None

    mask_time = (GLOBAL_TRANSIT_DF["Datetime"] >= start_dt) & (GLOBAL_TRANSIT_DF["Datetime"] <= end_dt)
    tdf = GLOBAL_TRANSIT_DF.loc[mask_time].copy()
    if tdf.empty: return [], sdf["السهم"].iloc[0]

    results = []
    for _, srow in sdf.iterrows():
        for _, trow in tdf.iterrows():
            for t_name, col in TRANSIT_PLANETS:
                if col not in trow or pd.isna(trow[col]): continue
                ang = angle_diff(srow["الدرجة الفلكية"], float(trow[col]))
                asp, exact, dev, icon = get_aspect_details(ang)
                if asp:
                    results.append({
                        "السهم": srow["السهم"], "كوكب السهم": srow["الكوكب"],
                        "برج السهم": srow["البرج"], "كوكب العبور": t_name,
                        "العلاقة": asp, "الزاوية التامة": exact, "الرمز": icon,
                        "درجة المولد": srow["الدرجة الفلكية"], "درجة العبور": float(trow[col]),
                        "الوقت": trow["Datetime"], "deviation": dev
                    })
    return results, sdf["السهم"].iloc[0]

# --- المسارات (Routes) ---
@app.route('/')
def index():
    if GLOBAL_STOCK_DF is None: load_data()
    stocks = sorted(GLOBAL_STOCK_DF["السهم"].unique()) if GLOBAL_STOCK_DF is not None else []
    return render_template('index.html', stocks=stocks)

@app.route('/stock/<path:stock_name>')
def stock_detail(stock_name):
    if GLOBAL_STOCK_DF is None: load_data()
    date_str = request.args.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    
    results, real_name = calc_stock_aspects(stock_name, target_date)
    ai_rating, ai_color = calculate_ai_score(results) if results else ("⚪ (لا يوجد نشاط)", "text-gray-400")
    
    processed_results = []
    if results:
        df = pd.DataFrame(results).sort_values("الوقت")
        groups = df.groupby(["كوكب العبور", "كوكب السهم", "العلاقة"])
        for (tplanet, nplanet, aspect), g in groups:
            start_time = g.iloc[0]["الوقت"]
            end_time = g.iloc[-1]["الوقت"]
            best_row = g.loc[g['deviation'].idxmin()]
            duration_hours = (end_time - start_time).total_seconds() / 3600
            time_str = "🔄 مستمر طوال اليوم" if duration_hours > 20 else f"{format_time_ar(start_time)} ➔ {format_time_ar(end_time)}"
            t_deg = best_row['درجة العبور']
            t_sign = get_sign_name(t_deg)
            processed_results.append({
                "t_planet": tplanet, "n_planet": nplanet, "aspect": aspect,
                "icon": best_row['الرمز'], "time_str": time_str,
                "t_sign": t_sign, "t_deg": int(get_sign_degree(t_deg)), 
                "t_status": get_planet_status(tplanet, t_sign),
                "n_sign": get_sign_name(best_row['درجة المولد']), "n_deg": int(get_sign_degree(best_row['درجة المولد'])),
                "timeframe": TRANSIT_TIMEFRAMES.get(tplanet, "")
            })
            
    return render_template('stock_detail.html', stock_name=real_name or stock_name, date=date_str, rating=ai_rating, rating_color=ai_color, results=processed_results)

if __name__ == '__main__':
    load_data()
    app.run(debug=True, port=5000)