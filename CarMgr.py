import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import re
import time
import calendar
import os
import shutil
import io
from datetime import datetime, date, timedelta

# --- 页面配置和自定义样式 ---
st.set_page_config(
    page_title="Yoyo派车车v1.0",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义TAB样式
tab_style = """
<style>
    /* TAB按钮容器 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #f8f9fa;
        padding: 10px 10px 0 10px;
        border-radius: 12px 12px 0 0;
        border-bottom: 2px solid #e9ecef;
    }
    
    /* 单个TAB按钮 */
    .stTabs [data-baseweb="tab"] {
        height: 42px;
        white-space: pre-wrap;
        background-color: #ffffff;
        border-radius: 8px 8px 0 0;
        gap: 4px;
        padding: 10px 20px;
        font-weight: 500;
        color: #6c757d;
        border: 1px solid #dee2e6;
        border-bottom: none;
        transition: all 0.3s ease;
    }
    
    /* TAB悬停效果 */
    .stTabs [data-baseweb="tab"]:hover {
        background-color: #e3f2fd;
        color: #1976d2;
        border-color: #1976d2;
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(25, 118, 210, 0.15);
    }
    
    /* 选中状态的TAB */
    .stTabs [aria-selected="true"] {
        background-color: #1976d2 !important;
        color: #ffffff !important;
        border-color: #1976d2 !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 12px rgba(25, 118, 210, 0.3);
    }
    
    /* TAB内容区域 */
    .stTabs [data-baseweb="tab-panel"] {
        background-color: #ffffff;
        border-radius: 0 0 12px 12px;
        padding: 20px;
        border: 1px solid #e9ecef;
        border-top: none;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
    }
</style>
"""
st.markdown(tab_style, unsafe_allow_html=True)

# --- 1. 核心数据库逻辑 ---
DB_FILE = "Carmgr.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, car_name TEXT, start_time TIMESTAMP, 
                 end_time TIMESTAMP, user_name TEXT, passenger_count INTEGER, 
                 reason TEXT, status TEXT, is_deleted INTEGER DEFAULT 0, mileage REAL DEFAULT NULL)''')
    # 迁移：为旧表添加mileage字段
    try:
        c.execute("ALTER TABLE bookings ADD COLUMN mileage REAL DEFAULT NULL")
    except:
        pass  # 字段已存在
    c.execute('''CREATE TABLE IF NOT EXISTS cars (plate_num TEXT PRIMARY KEY, car_type TEXT, capacity INTEGER, driver_name TEXT, driver_phone TEXT, available INTEGER DEFAULT 1, is_deleted INTEGER DEFAULT 0)''')
    # 迁移：为旧表添加available字段
    try:
        c.execute("ALTER TABLE cars ADD COLUMN available INTEGER DEFAULT 1")
    except:
        pass  # 字段已存在
    # 迁移：为旧表添加is_deleted字段（软删除）
    try:
        c.execute("ALTER TABLE cars ADD COLUMN is_deleted INTEGER DEFAULT 0")
    except:
        pass  # 字段已存在
    # 迁移：为旧表添加display_order字段（显示排序）
    try:
        c.execute("ALTER TABLE cars ADD COLUMN display_order INTEGER DEFAULT 999")
    except:
        pass  # 字段已存在
    if not c.execute("SELECT * FROM users WHERE username='admin'").fetchone():
        c.execute("INSERT INTO users VALUES (?,?,?)", ("admin", hashlib.sha256("123".encode()).hexdigest(), "admin"))
    conn.commit()
    return conn

# 冲突判定逻辑：支持获取冲突任务详情
def check_conflict(conn, car, start, end, curr_id):
    q = """SELECT user_name as '使用人', start_time as '开始时间', end_time as '结束时间', reason as '事由' FROM bookings 
           WHERE car_name=? AND status='已指派' AND id!=? AND is_deleted=0
           AND (datetime(?) < datetime(end_time) AND datetime(?) > datetime(start_time))"""
    return pd.read_sql_query(q, conn, params=(car, curr_id, start, end))

# 渲染已指派任务项（用于双列布局）
def render_assigned_task(conn, car_list, r):
    # 处理时间显示：如果日期相同，省略结束时间的日期
    start_str = r['start_time'] if isinstance(r['start_time'], str) else str(r['start_time'])
    end_str = r['end_time'] if isinstance(r['end_time'], str) else str(r['end_time'])
    
    # 提取日期和时间部分
    start_date = start_str[:10] if len(start_str) >= 10 else start_str
    start_time = start_str[11:16] if len(start_str) >= 16 else start_str
    end_date = end_str[:10] if len(end_str) >= 10 else end_str
    end_time = end_str[11:16] if len(end_str) >= 16 else end_str
    
    # 如果日期相同，只显示一次日期
    if start_date == end_date:
        time_display = f"{start_date} {start_time} - {end_time}"
    else:
        time_display = f"{start_str} - {end_str}"
    
    with st.expander(f"🚗 {r['car_name']} | {r['user_name']} | {time_display}"):
        # 检查是否需要重置表单
        form_key_suffix = ""
        if st.session_state.get(f"reset_{r['id']}", False):
            st.session_state[f"reset_{r['id']}"] = False
            form_key_suffix = f"_{datetime.now().timestamp()}"
        
        with st.form(f"a_{r['id']}{form_key_suffix}"):
            # 始终使用从数据库中获取的原始值作为默认值
            dt_def = pd.to_datetime(r['start_time']).date() if isinstance(r['start_time'], str) else date.today()
            st_def = r['start_time'][11:16] if isinstance(r['start_time'], str) and len(r['start_time']) >= 16 else "09:00"
            et_def = r['end_time'][11:16] if isinstance(r['end_time'], str) and len(r['end_time']) >= 16 else "11:00"
            e1, e2, e3 = st.columns([2,1,1])
            un_edit = e1.text_input("人员", r['user_name'] or "", key=f"un_a_{r['id']}{form_key_suffix}")
            pn_edit = e2.number_input("人数", 1, 50, int(r['passenger_count'] or 1), key=f"pn_a_{r['id']}{form_key_suffix}")
            ud_edit = e3.date_input("日期", dt_def, key=f"ud_a_{r['id']}{form_key_suffix}")
            e4, e5 = st.columns(2)
            st_edit = e4.text_input("开始时间", st_def, placeholder="HH:MM", key=f"st_a_{r['id']}{form_key_suffix}")
            et_edit = e5.text_input("结束时间", et_def, placeholder="HH:MM", key=f"et_a_{r['id']}{form_key_suffix}")
            rs_edit = st.text_area("事由", r['reason'] or "", height=80, key=f"rs_a_{r['id']}{form_key_suffix}")
            
            # 判断任务状态：待执行的任务禁用完成按钮
            now = datetime.now()
            start_time = pd.to_datetime(r['start_time']) if isinstance(r['start_time'], str) else now
            is_pending_execution = now < start_time  # 当前时间 < 开始时间 = 待执行
            
            # 已执行的任务显示里程输入框
            mileage_edit = None
            if not is_pending_execution:
                current_mileage = r.get('mileage', None)
                # 如果没有里程数据，默认为None（显示为空）
                if current_mileage is None or current_mileage == '':
                    mileage_value = None
                else:
                    try:
                        mileage_value = int(current_mileage)
                    except:
                        mileage_value = None
                mileage_edit = st.number_input("里程(公里)", min_value=0, value=mileage_value, step=1, placeholder="输入实际行驶里程", key=f"mileage_a_{r['id']}{form_key_suffix}")
            
            b1, b2, b3, b4, b5 = st.columns([1,1,1,1,1])
            with b1:
                save_btn = st.form_submit_button("💾 保存", use_container_width=True)
            with b2:
                reset_btn = st.form_submit_button("↻ 重置", use_container_width=True)
            with b3:
                back_btn = st.form_submit_button("↩️ 退回", use_container_width=True)
            with b4:
                if is_pending_execution:
                    st.form_submit_button("🏁 完成", use_container_width=True, disabled=True, help="任务尚未开始，无法完成")
                    done_btn = False
                else:
                    done_btn = st.form_submit_button("🏁 完成", use_container_width=True)
            with b5:
                del_btn_a = st.form_submit_button("🗑️ 删除", use_container_width=True)
            if save_btn:
                st_n = (st_edit or "").replace('：', ':').strip()
                et_n = (et_edit or "").replace('：', ':').strip()
                if not re.match(r'^\d{1,2}:\d{2}$', st_n) or not re.match(r'^\d{1,2}:\d{2}$', et_n):
                    st.error("时间格式应为 HH:MM")
                else:
                    car_curr = r['car_name'] or ""
                    if car_curr:
                        cf = check_conflict(conn, car_curr, f"{ud_edit} {st_n}", f"{ud_edit} {et_n}", r['id'])
                        if not cf.empty:
                            st.error("❌ 冲突！占用任务如下：")
                            st.dataframe(cf, use_container_width=True, hide_index=True)
                        else:
                            # 检查人数是否超过已指派车辆的乘客数限制
                            car_capacity = pd.read_sql_query(
                                "SELECT capacity FROM cars WHERE plate_num=? AND (is_deleted=0 OR is_deleted IS NULL)",
                                conn, params=(car_curr,)
                            ).iloc[0]['capacity'] or 0
                            if int(pn_edit) > car_capacity:
                                st.error(f"❌ 人数超过限制！车辆 {car_curr} 最大乘客数为 {car_capacity} 人，当前任务人数为 {int(pn_edit)} 人，请退回任务")
                            else:
                                conn.execute("UPDATE bookings SET start_time=?, end_time=?, user_name=?, passenger_count=?, reason=? WHERE id=?", (f"{ud_edit} {st_n}", f"{ud_edit} {et_n}", un_edit, int(pn_edit), rs_edit, r['id']))
                                conn.commit(); st.toast("✅ 已保存"); time.sleep(0.3); st.rerun()
                    else:
                        conn.execute("UPDATE bookings SET start_time=?, end_time=?, user_name=?, passenger_count=?, reason=? WHERE id=?", (f"{ud_edit} {st_n}", f"{ud_edit} {et_n}", un_edit, int(pn_edit), rs_edit, r['id']))
                        conn.commit(); st.toast("✅ 已保存"); time.sleep(0.3); st.rerun()
            if reset_btn:
                # 设置重置标志，下次渲染时使用新的key
                st.session_state[f"reset_{r['id']}"] = True
                st.rerun()
            if back_btn:
                conn.execute("UPDATE bookings SET status='待指派', car_name=NULL WHERE id=?", (r['id'],)); conn.commit(); st.rerun()
            if done_btn:
                # 完成任务时保存里程
                if mileage_edit is not None:
                    conn.execute("UPDATE bookings SET status='已完成', mileage=? WHERE id=?", (int(mileage_edit), r['id']))
                else:
                    conn.execute("UPDATE bookings SET status='已完成' WHERE id=?", (r['id'],))
                conn.commit(); st.rerun()
            if del_btn_a:
                conn.execute("UPDATE bookings SET is_deleted=1 WHERE id=?", (r['id'],))
                conn.commit(); st.toast("🗑️ 已删除"); time.sleep(0.3); st.rerun()

def regex_parser(text):
    if not text.strip(): return None
    today = date.today()
    parsed = {"u": "", "p": 1, "d": today, "s": "09:00", "e": "11:00", "r": text}
    
    # 1. 日期识别 - 支持多种格式
    # 标准格式：2024-01-15、2024/01/15、2024.01.15
    d_m = re.search(r'(\d{2,4})?[./\-](\d{1,2})[./\-](\d{1,2})|(\d{1,2})[./\-](\d{1,2})', text)
    if d_m:
        g = d_m.groups()
        try:
            if g[3]: parsed["d"] = date(today.year, int(g[3]), int(g[4]))
            elif g[1]: parsed["d"] = date(int(g[0]) if g[0] else today.year, int(g[1]), int(g[2]))
        except: pass
    
    # 中文日期格式：1月15日、1月15号、2024年1月15日
    if parsed["d"] == today:
        cn_date_m = re.search(r'(\d{4})?年?(\d{1,2})月(\d{1,2})[日号]', text)
        if cn_date_m:
            try:
                year = int(cn_date_m.group(1)) if cn_date_m.group(1) else today.year
                month = int(cn_date_m.group(2))
                day = int(cn_date_m.group(3))
                parsed["d"] = date(year, month, day)
            except: pass
    
    # 相对日期：明天、后天、大后天、下周X
    if parsed["d"] == today:
        if '明天' in text or '明日' in text:
            parsed["d"] = today + timedelta(days=1)
        elif '后天' in text:
            parsed["d"] = today + timedelta(days=2)
        elif '大后天' in text:
            parsed["d"] = today + timedelta(days=3)
        elif '下周' in text:
            weekday_map = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
            for cn_day, target_weekday in weekday_map.items():
                if f'下周{cn_day}' in text:
                    days_ahead = target_weekday - today.weekday() + 7
                    parsed["d"] = today + timedelta(days=days_ahead)
                    break
    
    # 2. 人数识别 - 支持多种写法
    # 标准格式：5人、3名
    p_m = re.search(r'(\d+)\s*[人|名|位]', text)
    if p_m: parsed["p"] = int(p_m.group(1))
    # 键值对格式：人数：5、人员数量5
    if parsed["p"] == 1:
        p_m2 = re.search(r'(?:人数|人员数量|人数数量)[：:]\s*(\d+)', text)
        if p_m2: parsed["p"] = int(p_m2.group(1))
    
    # 3. 时间识别 - 支持多种格式
    # 标准格式：09:00、14:30
    t_m = re.findall(r'(\d{1,2})[:：](\d{2})', text)
    if len(t_m) >= 1: 
        parsed["s"] = f"{int(t_m[0][0]):02d}:{t_m[0][1]}"
    if len(t_m) >= 2: 
        parsed["e"] = f"{int(t_m[1][0]):02d}:{t_m[1][1]}"
    
    # 中文时间：上午9点、下午2点半、晚上7点
    if parsed["s"] == "09:00":
        # 上午X点
        am_m = re.search(r'上午(\d{1,2})点(?:半)?', text)
        if am_m:
            hour = int(am_m.group(1))
            minute = 30 if '半' in text[am_m.start():am_m.end()] else 0
            parsed["s"] = f"{hour:02d}:{minute:02d}"
        # 下午X点
        pm_m = re.search(r'下午(\d{1,2})点(?:半)?', text)
        if pm_m:
            hour = int(pm_m.group(1)) + 12
            minute = 30 if '半' in text[pm_m.start():pm_m.end()] else 0
            parsed["s"] = f"{hour:02d}:{minute:02d}"
        # 晚上X点
        night_m = re.search(r'晚上(\d{1,2})点(?:半)?', text)
        if night_m:
            hour = int(night_m.group(1)) + 12
            minute = 30 if '半' in text[night_m.start():night_m.end()] else 0
            parsed["s"] = f"{hour:02d}:{minute:02d}"
    
    # 时间范围：9:00-11:00、9点至11点、9点到11点
    if parsed["e"] == "11:00":
        range_m = re.search(r'(\d{1,2})[:：]?(\d{2})?\s*(?:-|—|至|到|~)\s*(\d{1,2})[:：]?(\d{2})?', text)
        if range_m:
            try:
                start_hour = int(range_m.group(1))
                start_min = int(range_m.group(2)) if range_m.group(2) else 0
                end_hour = int(range_m.group(3))
                end_min = int(range_m.group(4)) if range_m.group(4) else 0
                parsed["s"] = f"{start_hour:02d}:{start_min:02d}"
                parsed["e"] = f"{end_hour:02d}:{end_min:02d}"
            except: pass
    
    # 4. 人员识别 - 支持多种格式
    # 键值对格式：人员：张三、姓名：李四
    u_m = re.search(r'(?:人员|姓名|名字|申请人)[：:]\s*([^\s\d，。；]+)', text)
    if u_m:
        parsed["u"] = u_m.group(1)
    else:
        # 默认：第一个不含数字且长度>1的词
        for w in text.replace('，', ' ').replace('。', ' ').replace('；', ' ').split():
            if not re.search(r'\d', w) and len(w) > 1 and w not in ['明天', '后天', '大后天', '上午', '下午', '晚上']:
                parsed["u"] = w
                break
    
    # 5. 事由提取 - 支持键值对格式
    r_m = re.search(r'(?:事由|原因|目的|任务)[：:]\s*(.+?)(?:\n|$)', text)
    if r_m:
        parsed["r"] = r_m.group(1).strip()
    
    return parsed

# --- 2. 界面美化 CSS ---
def inject_custom_css():
    st.markdown("""
    <style>
    /* 基础样式优化 */
    .main .block-container { padding-top: 6px !important; }
    
    /* TAB样式 - 保持简洁 */
    [data-baseweb="tab-list"] {
        position: sticky; top: 0; z-index: 40;
        padding: 4px 0; gap: 8px;
        flex-wrap: nowrap; overflow-x: auto;
    }
    [data-baseweb="tab"] {
        border-radius: 8px; padding: 6px 12px;
    }
    
    /* 任务申请TAB (第5个TAB，索引4) - 未选中时橙色背景 */
    [data-baseweb="tab-list"] button:nth-child(5) {
        background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%) !important;
        border: 2px solid #ff9800 !important;
        color: #e65100 !important;
        font-weight: 600 !important;
    }
    [data-baseweb="tab-list"] button:nth-child(5):hover {
        background: linear-gradient(135deg, #ffe0b2 0%, #ffcc80 100%) !important;
    }
    /* 任务申请TAB选中状态 - 沿用蓝色选中样式 */
    [data-baseweb="tab-list"] button:nth-child(5)[aria-selected="true"] {
        background: #1976d2 !important;
        border-color: #1976d2 !important;
        color: #ffffff !important;
        box-shadow: 0 4px 12px rgba(25, 118, 210, 0.3);
    }
    
    /* 车辆指派TAB (第6个TAB，索引5) - 未选中时绿色背景 */
    [data-baseweb="tab-list"] button:nth-child(6) {
        background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%) !important;
        border: 2px solid #4caf50 !important;
        color: #1b5e20 !important;
        font-weight: 600 !important;
    }
    [data-baseweb="tab-list"] button:nth-child(6):hover {
        background: linear-gradient(135deg, #c8e6c9 0%, #a5d6a7 100%) !important;
    }
    /* 车辆指派TAB选中状态 - 沿用蓝色选中样式 */
    [data-baseweb="tab-list"] button:nth-child(6)[aria-selected="true"] {
        background: #1976d2 !important;
        border-color: #1976d2 !important;
        color: #ffffff !important;
        box-shadow: 0 4px 12px rgba(25, 118, 210, 0.3);
    }
    
    /* 任务标签样式 */
    .task-tag { 
        font-size: 12px; 
        display: inline-block; 
        padding: 4px 10px; 
        margin: 6px 0 2px; 
        border-radius: 999px; 
    }
    .task-tag .t-car { font-weight: 600; margin-right: 6px; }
    .task-tag .t-time { margin-right: 6px; }
    
    /* 打印样式 */
    @media print {
        header, [data-testid="stSidebar"], .stButton, .no-print { display: none !important; }
        .main { padding: 0 !important; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #333; padding: 10px; text-align: left; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心功能函数 ---
def render_calendar(conn, year, month, label):
    with st.container(border=True):
        st.markdown(f"<h4 style='text-align:center;'>{label} ({year}-{month:02d})</h4>", unsafe_allow_html=True)
        df = pd.read_sql_query("SELECT * FROM bookings WHERE status='已指派' AND is_deleted=0 AND start_time LIKE ? ORDER BY start_time ASC", conn, params=(f"{year}-{month:02d}%",))
        cal = calendar.monthcalendar(year, month)
        cols = st.columns(7)
        for i, dname in enumerate(["一","二","三","四","五","六","日"]): cols[i].caption(f"<p style='text-align:center'>{dname}</p >", unsafe_allow_html=True)
        for week in cal:
            w_cols = st.columns(7)
            for i, day in enumerate(week):
                if day == 0: continue
                with w_cols[i].container(border=True):
                    if date(year, month, day) == date.today(): st.markdown(f"<b style='color:red;'>{day}</b>", unsafe_allow_html=True)
                    else: st.write(day)
                    d_tasks = df[df['start_time'].str.startswith(f"{year}-{month:02d}-{day:02d}")]
                    for _, t in d_tasks.iterrows():
                        palette = ["#eef2ff|#6366f1", "#fee2e2|#ef4444", "#dcfce7|#22c55e", "#fde68a|#f59e0b", "#e0f2fe|#0284c7", "#f3e8ff|#7c3aed"]
                        key = (t['car_name'] or "") if isinstance(t['car_name'], str) else ""
                        idx = (sum(ord(ch) for ch in key) % len(palette)) if key else 0
                        bg, accent = palette[idx].split("|")
                        s = t['start_time']; e = t['end_time']
                        st_t = s[11:16] if isinstance(s, str) and len(s) >= 16 else ""
                        et_t = e[11:16] if isinstance(e, str) and len(e) >= 16 else ""
                        car_short = key[-5:] if key else ""
                        user_short = (t['user_name'] or "")[:2] if isinstance(t['user_name'], str) else ""
                        st.markdown(f"<div class='task-tag' style='background:{bg}; border-left:3px solid {accent};'><span class='t-car'>{car_short}</span><span class='t-time'>{st_t}-{et_t}</span><span class='t-user'>{user_short}</span></div>", unsafe_allow_html=True)

# --- 4. 主程序 ---
def main_app():
    conn = init_db()
    inject_custom_css()
    
    with st.sidebar:
        st.components.v1.html("""
        <div style='width:100%; text-align:center; margin-bottom: 8px;'>
          <div id='sc-date' style='font-weight:700; font-size:26px;'></div>
          <div id='sc-time' style='font-weight:700; font-size:26px;'></div>
        </div>
        <script>
          function pad(n){return n<10?'0'+n:n;}
          function updateClock(){
            var now = new Date();
            var y = now.getFullYear();
            var m = pad(now.getMonth()+1);
            var d = pad(now.getDate());
            var hh = pad(now.getHours());
            var mm = pad(now.getMinutes());
            var dEl = document.getElementById('sc-date');
            var tEl = document.getElementById('sc-time');
            if(dEl){ dEl.textContent = y + '-' + m + '-' + d; }
            if(tEl){ tEl.textContent = hh + ':' + mm; }
          }
          updateClock();
          setInterval(updateClock, 10000);
        </script>
        """, height=90, scrolling=False)
        st.title("🚐 Yoyo派车车")
        st.info(f"👤 {st.session_state.username} ({st.session_state.role})")
        if st.button("🚪 退出", use_container_width=True):
            st.session_state.clear(); st.rerun()
        df_un_top = pd.read_sql_query("SELECT id FROM bookings WHERE status='待指派' AND is_deleted=0", conn)
        if not df_un_top.empty:
            st.warning(f"🔔 当前有 {len(df_un_top)} 项未指派申请，请到【车辆指派】中操作")
        else:
            st.success("所有申请均已指派")
        today = date.today()
        df_today_assigned = pd.read_sql_query(
            "SELECT id FROM bookings WHERE status='已指派' AND is_deleted=0 AND date(start_time)=?",
            conn, params=(today,)
        )
        st.info(f"本日尚有 {len(df_today_assigned)} 项任务")
        now = datetime.now()
        df_overdue = pd.read_sql_query(
            "SELECT id, end_time FROM bookings WHERE status='已指派' AND is_deleted=0",
            conn
        )
        overdue_count = 0
        for _, row in df_overdue.iterrows():
            end_time = pd.to_datetime(row['end_time'])
            if now > end_time:
                overdue_count += 1
        if overdue_count > 0:
            st.error(f"当前已发生 {overdue_count} 项任务逾期")
        else:
            st.success("当前无任务逾期")

    menu = ["车辆卡片", "间隙警示", "双月全景", "已派打印", "任务申请", "车辆指派", "任务列表", "车辆报表", "车辆管理", "用户管理", "流程说明", "高级设置"]
    if st.session_state.role != 'admin': menu = ["车辆卡片", "间隙警示", "双月全景", "已派打印", "任务申请", "流程说明"]
    tabs = st.tabs(menu)

    # --- TAB 0: 车辆卡片 ---
    with tabs[0]:
        now = datetime.now()
        
        cars = pd.read_sql_query("SELECT * FROM cars WHERE is_deleted=0 OR is_deleted IS NULL ORDER BY display_order ASC, plate_num ASC", conn)
        tasks = pd.read_sql_query("SELECT * FROM bookings WHERE status='已指派' AND is_deleted=0 ORDER BY start_time", conn)
        
        # 检查是否有车辆
        if cars.empty:
            st.warning("⚠️ 请先在【车辆管理】中维护车辆信息")
        else:
            cols = st.columns(3)
            for i, car in cars.iterrows():
                with cols[i % 3]:
                    c_tasks = tasks[tasks['car_name'] == car['plate_num']]
                    curr = c_tasks[(pd.to_datetime(c_tasks['start_time']) <= now) & (pd.to_datetime(c_tasks['end_time']) >= now)]
                    overdue = c_tasks[pd.to_datetime(c_tasks['end_time']) < now]
                    available = bool(car.get('available', 1))
                    with st.container(border=True):
                        st.markdown(f"### {car['plate_num']}")
                        st.caption(f"司机: {car['driver_name']} | 📞 {car['driver_phone']}")
                        if not available:
                            st.info("⛔ 不可用")
                        elif not curr.empty:
                            st.warning(f"🔴 运行中: {curr.iloc[0]['user_name']}")
                        elif not overdue.empty:
                            st.error(f"⛔ 逾期: {overdue.iloc[0]['user_name']} (已超 {overdue.iloc[0]['end_time']})")
                        else:
                            st.success("🟢 待命")
                        st_dt = pd.to_datetime(c_tasks['start_time'], errors='coerce')
                        today = date.today()
                        tomorrow = today + timedelta(days=1)
                        today_count = int(((st_dt.dt.date == today) & (st_dt > now)).sum())
                        tomorrow_count = int((st_dt.dt.date == tomorrow).sum())
                        st.write(f"今日任务：{today_count}")
                        st.write(f"明日任务：{tomorrow_count}")
                        with st.expander("查看后续安排"):
                            for _, ft in c_tasks[pd.to_datetime(c_tasks['start_time']) > now].iterrows():
                                st.write(f"🕒 {ft['start_time'][5:16]} - {ft['user_name']}")

    # --- TAB 1: 间隙警示 ---
    if st.session_state.role == 'admin':
        with tabs[1]:
            st.markdown("### ⚠️ 间隙警示")
            st.caption("显示同一天内任务间隔小于60分钟的车辆")
            
            # 获取所有车辆和已指派任务
            cars = pd.read_sql_query("SELECT * FROM cars WHERE is_deleted=0 OR is_deleted IS NULL ORDER BY display_order ASC, plate_num ASC", conn)
            tasks = pd.read_sql_query("SELECT * FROM bookings WHERE status='已指派' AND is_deleted=0 ORDER BY car_name, start_time", conn)
            
            # 处理任务时间
            tasks['start_dt'] = pd.to_datetime(tasks['start_time'])
            tasks['end_dt'] = pd.to_datetime(tasks['end_time'])
            tasks['date'] = tasks['start_dt'].dt.date
            
            # 创建车辆卡片布局
            cols = st.columns(3)
            has_warning = False
            
            for i, car in cars.iterrows():
                car_tasks = tasks[tasks['car_name'] == car['plate_num']].copy()
                
                # 检查该车辆是否有间隔小于60分钟的任务
                warning_tasks = []
                
                # 按日期分组检查
                for task_date, day_tasks in car_tasks.groupby('date'):
                    day_tasks = day_tasks.sort_values('start_dt')
                    
                    # 检查相邻任务的间隔
                    for j in range(len(day_tasks) - 1):
                        current_task = day_tasks.iloc[j]
                        next_task = day_tasks.iloc[j + 1]
                        
                        gap_minutes = (next_task['start_dt'] - current_task['end_dt']).total_seconds() / 60
                        
                        if 0 <= gap_minutes < 60:  # 间隔小于60分钟
                            warning_tasks.append({
                                'date': task_date,
                                'current_task': current_task,
                                'next_task': next_task,
                                'gap_minutes': int(gap_minutes)
                            })
                
                # 只显示有警示的车辆
                if warning_tasks:
                    has_warning = True
                    with cols[i % 3]:
                        with st.container(border=True):
                            st.markdown(f"### 🚗 {car['plate_num']}")
                            st.caption(f"司机: {car['driver_name'] or '未设置'}")
                            
                            # 显示警示数量
                            st.warning(f"⚠️ 发现 {len(warning_tasks)} 个短间隔任务")
                            
                            # 直接显示详细信息
                            st.markdown("---")
                            for wt in warning_tasks:
                                st.markdown(f"**📅 {wt['date']}**")
                                
                                # 当前任务
                                ct = wt['current_task']
                                st.markdown(f"🔴 前任务: {ct['start_time'][11:16]} - {ct['end_time'][11:16]} | {ct['user_name']}")
                                
                                # 间隔提示
                                gap = wt['gap_minutes']
                                st.markdown(f"<div style='color:#ff6b6b;font-weight:bold;margin-left:20px;'>⏱️ 间隔: {gap} 分钟</div>", unsafe_allow_html=True)
                                
                                # 下一任务
                                nt = wt['next_task']
                                st.markdown(f"🟢 后任务: {nt['start_time'][11:16]} - {nt['end_time'][11:16]} | {nt['user_name']}")
                                
                                st.divider()
            
            if not has_warning:
                st.success("✅ 所有车辆的任务安排均无短间隔问题")

    # --- TAB 2: 双月全景 ---
    with tabs[2]:
        t = date.today()
        nxt = (t.replace(day=28) + timedelta(days=4)).replace(day=1)
        c1, c2 = st.columns(2)
        with c1: render_calendar(conn, t.year, t.month, "📅 本月")
        with c2: render_calendar(conn, nxt.year, nxt.month, "🗓️ 次月")

    # --- TAB 3: 已派打印 ---
    with tabs[3]:
        car_list = pd.read_sql_query("SELECT plate_num FROM cars WHERE (is_deleted=0 OR is_deleted IS NULL) AND available=1", conn)['plate_num'].tolist()
        df_un = pd.read_sql_query("SELECT * FROM bookings WHERE status='待指派' AND is_deleted=0", conn)
        if not df_un.empty:
            st.warning("当前有未指派申请，请谨慎打印")
        else:
            st.success("所有申请均已指派，请放心打印")
        # 选择车辆靠左放置
        p_car = st.selectbox("选择车辆", ["请选择"] + car_list)
        if p_car != "请选择":
            # 获取车辆信息
            car_info = pd.read_sql_query("SELECT * FROM cars WHERE plate_num=?", conn, params=(p_car,)).iloc[0]
            # 获取任务数据
            p_df = pd.read_sql_query("SELECT start_time, end_time, user_name, passenger_count, reason FROM bookings WHERE car_name=? AND status='已指派' AND is_deleted=0 ORDER BY start_time ASC", conn, params=(p_car,))
            
            # 统计信息
            total_tasks = len(p_df)
            total_passengers = p_df['passenger_count'].sum() if not p_df.empty else 0
            
            # 打印预览区域
            st.markdown("---")
            
            # 预览卡片
            with st.container(border=True):
                # 标题区域
                st.markdown(f"""
                <div style="text-align: center; padding: 20px; border-bottom: 2px solid #e0e0e0; margin-bottom: 20px;">
                    <h1 style="margin: 0; color: #1a1a1a;"> {p_car} 任务清单</h1>
                    <p style="color: #666; margin: 10px 0 0 0;">生成时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # 车辆信息
                info_cols = st.columns(4)
                with info_cols[0]:
                    st.metric("司机", car_info['driver_name'] or "未设置")
                with info_cols[1]:
                    st.metric("电话", car_info['driver_phone'] or "未设置")
                with info_cols[2]:
                    st.metric("车型", car_info['car_type'] or "未知")
                with info_cols[3]:
                    st.metric("任务总数", total_tasks)
                
                st.markdown("---")
                
                # 任务表格
                if not p_df.empty:
                    display_df = p_df.copy()
                    display_df.columns = ['开始时间', '结束时间', '使用人', '人数', '事由']
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
                else:
                    st.info("暂无已指派任务")
            
            # 操作按钮 - 下载PDF按钮全宽
            st.markdown("---")
            
            # PDF生成和下载
            if not p_df.empty:
                try:
                    from reportlab.lib.pagesizes import A4
                    from reportlab.pdfbase import pdfmetrics
                    from reportlab.pdfbase.ttfonts import TTFont
                    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
                    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                    from reportlab.lib import colors
                    from reportlab.lib.units import cm
                    
                    # 注册中文字体
                    try:
                        pdfmetrics.registerFont(TTFont('SimSun', 'simsun.ttc'))
                        chinese_font = 'SimSun'
                    except:
                        try:
                            pdfmetrics.registerFont(TTFont('SimSun', 'C:/Windows/Fonts/simsun.ttc'))
                            chinese_font = 'SimSun'
                        except:
                            chinese_font = 'Helvetica'
                    
                    # 创建PDF
                    buffer = io.BytesIO()
                    doc = SimpleDocTemplate(buffer, pagesize=A4,
                                          rightMargin=2*cm, leftMargin=2*cm,
                                          topMargin=2*cm, bottomMargin=2*cm)
                    
                    styles = getSampleStyleSheet()
                    title_style = ParagraphStyle(
                        'CustomTitle',
                        parent=styles['Heading1'],
                        fontName=chinese_font,
                        fontSize=20,
                        spaceAfter=10,
                        alignment=1
                    )
                    normal_style = ParagraphStyle(
                        'CustomNormal',
                        parent=styles['Normal'],
                        fontName=chinese_font,
                        fontSize=10,
                        spaceAfter=6
                    )
                    header_style = ParagraphStyle(
                        'CustomHeader',
                        parent=styles['Normal'],
                        fontName=chinese_font,
                        fontSize=10,
                        textColor=colors.black,
                        alignment=1
                    )
                    
                    story = []
                    
                    # 标题
                    story.append(Paragraph(f"{p_car} 任务清单", title_style))
                    story.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}", normal_style))
                    story.append(Spacer(1, 0.5*cm))
                    
                    # 车辆信息
                    story.append(Paragraph(f"<b>车型：</b>{car_info['car_type'] or '未知'}", normal_style))
                    story.append(Paragraph(f"<b>司机：</b>{car_info['driver_name'] or '未设置'} | <b>电话：</b>{car_info['driver_phone'] or '无'}", normal_style))
                    story.append(Paragraph(f"<b>任务总数：</b>{total_tasks} 项", normal_style))
                    story.append(Spacer(1, 0.5*cm))
                    
                    # 表格数据
                    if not p_df.empty:
                        table_data = [['开始时间', '结束时间', '使用人', '人数', '事由']]
                        for _, row in p_df.iterrows():
                            table_data.append([
                                row['start_time'][:16] if row['start_time'] else '',
                                row['end_time'][:16] if row['end_time'] else '',
                                row['user_name'] or '',
                                str(row['passenger_count'] or ''),
                                row['reason'] or ''
                            ])
                        
                        table = Table(table_data, colWidths=[4*cm, 4*cm, 3*cm, 1.5*cm, 5*cm])
                        table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                            ('FONTNAME', (0, 0), (-1, 0), chinese_font),
                            ('FONTSIZE', (0, 0), (-1, 0), 10),
                            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                            ('GRID', (0, 0), (-1, -1), 1, colors.black),
                            ('FONTNAME', (0, 1), (-1, -1), chinese_font),
                            ('FONTSIZE', (0, 1), (-1, -1), 9),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ]))
                        story.append(table)
                    
                    doc.build(story)
                    pdf_data = buffer.getvalue()
                    buffer.close()
                    
                    st.download_button(
                        label="📄 下载PDF",
                        data=pdf_data,
                        file_name=f"{p_car}_任务清单_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary"
                    )
                except Exception as e:
                    st.error(f"PDF生成失败：{str(e)}")
            else:
                st.button("📄 下载PDF", disabled=True, use_container_width=True)
    
    # --- TAB 4: 任务申请 (带智能识别) ---
    with tabs[4]:
        # 检查是否需要清空表单（提交成功后）
        if st.session_state.get('clear_form', False):
            st.session_state['clear_form'] = False
            d = {"u":"","p":1,"d":date.today(),"s":"09:00","e":"11:00","r":""}
            # 使用新的form key来强制重新渲染表单
            st.session_state['form_key'] = st.session_state.get('form_key', 0) + 1
        else:
            d = st.session_state.get('parsed', {"u":"","p":1,"d":date.today(),"s":"09:00","e":"11:00","r":""})
        
        # 左右布局：左边3份任务输入，右边1份智能识别
        left_col, right_col = st.columns([3, 1])
        
        with left_col:
            # 使用动态key来强制重新渲染表单
            form_key = f"req_{st.session_state.get('form_key', 0)}"
            with st.form(form_key, border=True):
                st.markdown("#### 📝 任务信息（默认只支持当日24：00结束）")
                st.caption("💡 任务来源包括但不限于用车申请")
                c1, c2, c3 = st.columns([2,1,1])
                un = c1.text_input("人员", d['u'], key=f"un_{form_key}")
                pn = c2.number_input("人数", 1, 50, d['p'], key=f"pn_{form_key}")
                ud = c3.date_input("日期", d['d'], key=f"ud_{form_key}")
                c4, c5 = st.columns(2)
                st_t = c4.text_input("开始时间", d['s'], placeholder="HH:MM", key=f"st_{form_key}")
                et_t = c5.text_input("结束时间", d['e'], placeholder="HH:MM", key=f"et_{form_key}")
                rs = st.text_area("事由", d['r'], height=145, key=f"rs_{form_key}")
                if st.form_submit_button("🚀 提交申请", use_container_width=True, type="primary"):
                    st_t_n = (st_t or "").replace('：', ':').strip()
                    et_t_n = (et_t or "").replace('：', ':').strip()
                    if not re.match(r'^\d{1,2}:\d{2}$', st_t_n) or not re.match(r'^\d{1,2}:\d{2}$', et_t_n):
                        st.error("时间格式应为 HH:MM")
                    else:
                        # 检查人数是否超过最大车辆座位数
                        max_capacity = pd.read_sql_query(
                            "SELECT MAX(capacity) as max_cap FROM cars WHERE is_deleted=0 OR is_deleted IS NULL", conn
                        ).iloc[0]['max_cap'] or 0
                        
                        if pn > max_capacity:
                            st.warning(f"⚠️ 该任务需要安排多辆车共同完成，请将人员分组安排（当前最大车辆乘客数为 {max_capacity} 人）")
                        
                        conn.execute("INSERT INTO bookings (start_time, end_time, user_name, passenger_count, reason, status) VALUES (?,?,?,?,?,?)", (f"{ud} {st_t_n}", f"{ud} {et_t_n}", un, pn, rs, "待指派"))
                        conn.commit()
                        # 设置清空表单标志
                        st.session_state['clear_form'] = True
                        st.toast("✅ 已提交"); time.sleep(0.5); st.rerun()
            
            # 批量常规任务
            with st.container(border=True):
                st.markdown("#### 📅 批量常规任务")
                st.caption("用于批量选择多个日期，固定时段、相同人员和事由的常规性任务（限制在1个月内）")
                
                batch_form_key = f"batch_{st.session_state.get('form_key', 0)}"
                with st.form(batch_form_key, border=False):
                    # 人员、人数、事由
                    bc1, bc2 = st.columns([2, 1])
                    batch_un = bc1.text_input("人员", key=f"batch_un_{batch_form_key}")
                    batch_pn = bc2.number_input("人数", 1, 50, 1, key=f"batch_pn_{batch_form_key}")
                    
                    # 固定时段
                    bc3, bc4 = st.columns(2)
                    batch_st = bc3.text_input("开始时间", placeholder="HH:MM", key=f"batch_st_{batch_form_key}")
                    batch_et = bc4.text_input("结束时间", placeholder="HH:MM", key=f"batch_et_{batch_form_key}")
                    
                    # 事由
                    batch_rs = st.text_area("事由", key=f"batch_rs_{batch_form_key}", height=80)
                    
                    # 车辆选择（可选）
                    st.markdown("**车辆选择（可选）**")
                    st.caption("选择车辆后，系统会尝试为每个日期自动指派，如遇冲突则该日期进入待指派")
                    
                    # 获取可用车辆列表
                    df_cars = pd.read_sql_query(
                        "SELECT plate_num, capacity FROM cars WHERE available=1 AND (is_deleted=0 OR is_deleted IS NULL) ORDER BY plate_num",
                        conn
                    )
                    car_options = ["不选择车辆（全部进入待指派）"] + df_cars['plate_num'].tolist()
                    selected_car = st.selectbox("选择车辆", car_options, key=f"batch_car_{batch_form_key}")
                    
                    # 日期范围选择
                    st.markdown("**选择日期范围（最多31天）**")
                    bc5, bc6 = st.columns(2)
                    batch_start_date = bc5.date_input("开始日期", key=f"batch_sd_{batch_form_key}")
                    batch_end_date = bc6.date_input("结束日期", key=f"batch_ed_{batch_form_key}")
                    
                    # 星期选择
                    st.markdown("**选择每周的哪几天**")
                    week_days = st.columns(7)
                    selected_days = []
                    day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                    for i, (col, day_name) in enumerate(zip(week_days, day_names)):
                        with col:
                            if st.checkbox(day_name, value=(i < 5), key=f"batch_day_{i}_{batch_form_key}"):
                                selected_days.append(i)  # 0=周一, 6=周日
                    
                    if st.form_submit_button("📦 批量创建任务", use_container_width=True, type="primary"):
                        # 验证输入
                        batch_st_n = (batch_st or "").replace('：', ':').strip()
                        batch_et_n = (batch_et or "").replace('：', ':').strip()
                        
                        if not batch_un or not batch_rs:
                            st.error("请填写人员和事由")
                        elif not re.match(r'^\d{1,2}:\d{2}$', batch_st_n) or not re.match(r'^\d{1,2}:\d{2}$', batch_et_n):
                            st.error("时间格式应为 HH:MM")
                        elif not selected_days:
                            st.error("请至少选择一天")
                        else:
                            # 计算日期范围内的所有选中星期几的日期
                            dates_to_create = []
                            current_date = batch_start_date
                            
                            while current_date <= batch_end_date:
                                # weekday(): 0=周一, 6=周日
                                if current_date.weekday() in selected_days:
                                    dates_to_create.append(current_date)
                                current_date += timedelta(days=1)
                            
                            # 检查是否超过31天
                            if len(dates_to_create) > 31:
                                st.error(f"选择的日期范围超过31天限制（当前选择了 {len(dates_to_create)} 天）")
                            elif len(dates_to_create) == 0:
                                st.error("在选择的日期范围内没有符合条件的日期")
                            else:
                                # 批量创建任务
                                assigned_count = 0
                                pending_count = 0
                                conflict_dates = []
                                
                                # 获取选择的车辆信息
                                car_to_assign = None
                                car_capacity = 0
                                if selected_car != "不选择车辆（全部进入待指派）":
                                    car_to_assign = selected_car
                                    car_capacity = df_cars[df_cars['plate_num'] == selected_car]['capacity'].iloc[0] or 0
                                
                                for task_date in dates_to_create:
                                    start_time_str = f"{task_date} {batch_st_n}"
                                    end_time_str = f"{task_date} {batch_et_n}"
                                    
                                    # 判断是否可以直接指派车辆
                                    can_assign = False
                                    if car_to_assign:
                                        # 检查冲突
                                        cf = check_conflict(conn, car_to_assign, start_time_str, end_time_str, 0)
                                        
                                        # 检查车辆是否有逾期任务
                                        now = datetime.now()
                                        df_car_overdue = pd.read_sql_query(
                                            "SELECT * FROM bookings WHERE car_name=? AND status='已指派' AND is_deleted=0",
                                            conn, params=(car_to_assign,)
                                        )
                                        has_overdue = False
                                        for _, row in df_car_overdue.iterrows():
                                            if now > pd.to_datetime(row['end_time']):
                                                has_overdue = True
                                                break
                                        
                                        # 检查人数限制
                                        exceeds_capacity = batch_pn > car_capacity
                                        
                                        # 只有无冲突、无逾期、不超载才能指派
                                        if cf.empty and not has_overdue and not exceeds_capacity:
                                            can_assign = True
                                    
                                    if can_assign:
                                        # 直接指派车辆
                                        conn.execute(
                                            "INSERT INTO bookings (start_time, end_time, user_name, passenger_count, reason, status, car_name) VALUES (?,?,?,?,?,?,?)",
                                            (start_time_str, end_time_str, batch_un, batch_pn, batch_rs, "已指派", car_to_assign)
                                        )
                                        assigned_count += 1
                                    else:
                                        # 进入待指派状态
                                        conn.execute(
                                            "INSERT INTO bookings (start_time, end_time, user_name, passenger_count, reason, status) VALUES (?,?,?,?,?,?)",
                                            (start_time_str, end_time_str, batch_un, batch_pn, batch_rs, "待指派")
                                        )
                                        pending_count += 1
                                        if car_to_assign:
                                            conflict_dates.append(str(task_date))
                                
                                conn.commit()
                                
                                # 显示结果
                                if assigned_count > 0 and pending_count > 0:
                                    st.success(f"✅ 成功创建 {assigned_count + pending_count} 个任务")
                                    st.info(f"🚗 已指派：{assigned_count} 个 | 📋 待指派：{pending_count} 个")
                                    if conflict_dates:
                                        st.warning(f"⚠️ 以下日期因冲突进入待指派：{', '.join(conflict_dates[:5])}{'...' if len(conflict_dates) > 5 else ''}")
                                elif assigned_count > 0:
                                    st.success(f"✅ 成功创建 {assigned_count} 个任务，全部已指派车辆 {car_to_assign}")
                                else:
                                    st.success(f"✅ 成功创建 {pending_count} 个任务，全部进入待指派状态")
                                
                                time.sleep(1.5)
                                st.rerun()
        
        with right_col:
            with st.container(border=True):
                st.markdown("#### 🤖 智能识别")
                st.caption("粘贴含时间、人员等信息的文本，自动填充表单")
                p_txt = st.text_area("粘贴申请内容...", height=280)
                if st.button("🔍 一键识别", use_container_width=True):
                    st.session_state.parsed = regex_parser(p_txt)
                    st.rerun()

    # --- TAB 5: 车辆指派 ---
    if st.session_state.role == 'admin':
        with tabs[5]:
            s1, s2, s3 = st.tabs(["待指派", "已指派（待执行）", "已指派（已执行）"])
            with s1:
                now = datetime.now()
                df_overdue = pd.read_sql_query(
                    "SELECT * FROM bookings WHERE status='已指派' AND is_deleted=0",
                    conn
                )
                overdue_tasks = []
                for _, row in df_overdue.iterrows():
                    end_time = pd.to_datetime(row['end_time'])
                    if now > end_time:
                        overdue_tasks.append(row)
                if overdue_tasks:
                    st.error(f"⚠️ 当前有 {len(overdue_tasks)} 项任务已逾期，为保证派车有效，请先确认逾期任务是否已经完成")
                    with st.expander("🔍 查看/处理逾期任务，需前往【已指派（已执行）】", expanded=True):
                        for i in range(0, len(overdue_tasks), 2):
                            cols = st.columns(2)
                            for j in range(2):
                                if i + j < len(overdue_tasks):
                                    task = overdue_tasks[i + j]
                                    with cols[j]:
                                        with st.container(border=True):
                                            st.markdown(f"**🚗 {task['car_name']}** | {task['user_name']}")
                                            st.caption(f"{task['start_time']} - {task['end_time']}")
                                            st.caption(f"事由: {task['reason'] or '无'}")
                else:
                    st.success("✅ 当前无逾期任务，可以正常派车")
                df_p = pd.read_sql_query("SELECT * FROM bookings WHERE status='待指派' AND is_deleted=0 ORDER BY start_time ASC", conn)
                # 获取最大车辆乘客数
                max_capacity = pd.read_sql_query(
                    "SELECT MAX(capacity) as max_cap FROM cars WHERE is_deleted=0 OR is_deleted IS NULL", conn
                ).iloc[0]['max_cap'] or 0
                
                # 按日期分组显示待指派任务
                from itertools import groupby
                p_items = list(df_p.iterrows())
                
                if p_items:
                    # 按日期排序
                    p_items_sorted = sorted(p_items, key=lambda x: str(x[1]['start_time'])[:10] if x[1]['start_time'] else '')
                    
                    for date_str, tasks_group in groupby(p_items_sorted, key=lambda x: str(x[1]['start_time'])[:10] if x[1]['start_time'] else ''):
                        # 显示日期分隔
                        st.markdown(f"#### 📅 {date_str}")
                        
                        # 将该日期的任务转换为列表并显示
                        date_tasks = list(tasks_group)
                        for i in range(0, len(date_tasks), 2):
                            cols = st.columns(2)
                            for j in range(2):
                                if i + j < len(date_tasks):
                                    _, r = date_tasks[i + j]
                                    # 检查是否需要多辆车
                                    need_multi_cars = (r['passenger_count'] or 0) > max_capacity
                                    
                                    with cols[j]:
                                        # 处理时间显示：如果日期相同，省略结束时间的日期
                                        start_str = r['start_time'] if isinstance(r['start_time'], str) else str(r['start_time'])
                                        end_str = r['end_time'] if isinstance(r['end_time'], str) else str(r['end_time'])
                                        
                                        # 提取日期和时间部分
                                        start_date = start_str[:10] if len(start_str) >= 10 else start_str
                                        start_time = start_str[11:16] if len(start_str) >= 16 else start_str
                                        end_date = end_str[:10] if len(end_str) >= 10 else end_str
                                        end_time = end_str[11:16] if len(end_str) >= 16 else end_str
                                        
                                        # 如果日期相同，只显示一次日期
                                        if start_date == end_date:
                                            time_display = f"{start_date} {start_time} - {end_time}"
                                        else:
                                            time_display = f"{start_str} - {end_str}"
                                        
                                        expander_title = f"📌 {time_display} | {r['user_name']}"
                                        if need_multi_cars:
                                            expander_title += " 🔴需多车"
                                        
                                        with st.expander(expander_title):
                                            # 如果需要多辆车，显示提示和快速复制按钮
                                            if need_multi_cars:
                                                st.warning(f"⚠️ 该任务有 {r['passenger_count']} 人，超过单辆车最大乘客数 {max_capacity} 人，需要安排多辆车")
                                                
                                                # 快速复制按钮
                                                if st.button("📋 复制任务", key=f"copy_{r['id']}", use_container_width=True):
                                                    conn.execute(
                                                        "INSERT INTO bookings (start_time, end_time, user_name, passenger_count, reason, status) VALUES (?,?,?,?,?,?)",
                                                        (r['start_time'], r['end_time'], r['user_name'], r['passenger_count'], r['reason'], '待指派')
                                                    )
                                                    conn.commit()
                                                    st.success("✅ 已复制任务，请分别修改人数后指派车辆")
                                                    time.sleep(0.5)
                                                    st.rerun()
                                                st.divider()
                                            
                                            # 检查是否需要重置表单
                                            form_key_suffix = ""
                                            if st.session_state.get(f"reset_p_{r['id']}", False):
                                                st.session_state[f"reset_p_{r['id']}"] = False
                                                form_key_suffix = f"_{datetime.now().timestamp()}"
                                            
                                            with st.form(f"p_{r['id']}{form_key_suffix}"):
                                                # 指派车辆部分 - 全宽靠左对齐
                                                st.markdown("**📋 指派车辆**")
                                                sc = st.selectbox("选择车辆", ["请选择"] + car_list, key=f"sc_{r['id']}{form_key_suffix}", label_visibility="collapsed")
                                                st.caption("选好车辆后点击下方按钮派车")
                                                submit_assign = st.form_submit_button("🟣 确认派车", use_container_width=True)
                                                # 冲突提示显示在确认派车按钮下方
                                                if submit_assign and sc != "请选择":
                                                    # 检查时间冲突
                                                    cf = check_conflict(conn, sc, r['start_time'], r['end_time'], r['id'])
                                                    # 检查该车辆是否有逾期任务
                                                    now = datetime.now()
                                                    df_car_overdue = pd.read_sql_query(
                                                        "SELECT * FROM bookings WHERE car_name=? AND status='已指派' AND is_deleted=0",
                                                        conn, params=(sc,)
                                                    )
                                                    has_overdue = False
                                                    for _, row in df_car_overdue.iterrows():
                                                        if now > pd.to_datetime(row['end_time']):
                                                            has_overdue = True
                                                            break
                                                    # 检查车辆乘客数是否满足任务人数
                                                    car_capacity_df = pd.read_sql_query(
                                                        "SELECT capacity FROM cars WHERE plate_num=? AND (is_deleted=0 OR is_deleted IS NULL)",
                                                        conn, params=(sc,)
                                                    )
                                                    car_capacity = car_capacity_df.iloc[0]['capacity'] if not car_capacity_df.empty else 0
                                                    task_passengers = r['passenger_count'] or 0
                                                    if not cf.empty:
                                                        st.error("❌ 冲突！占用任务如下：")
                                                        st.dataframe(cf, use_container_width=True, hide_index=True)
                                                    elif has_overdue:
                                                        st.error("❌ 该车辆存在逾期任务，请先处理逾期任务后再派车！")
                                                    elif task_passengers > car_capacity:
                                                        st.error(f"❌ 人数超过限制！该任务有 {task_passengers} 人，车辆 {sc} 最大乘客数为 {car_capacity} 人")
                                                    else:
                                                        conn.execute("UPDATE bookings SET car_name=?, status='已指派' WHERE id=?", (sc, r['id']))
                                                        conn.commit(); st.rerun()
                                                dt_def = pd.to_datetime(r['start_time']).date() if isinstance(r['start_time'], str) else date.today()
                                                st_def = r['start_time'][11:16] if isinstance(r['start_time'], str) and len(r['start_time']) >= 16 else "09:00"
                                                et_def = r['end_time'][11:16] if isinstance(r['end_time'], str) and len(r['end_time']) >= 16 else "11:00"
                                                e1, e2, e3 = st.columns([2,1,1])
                                                un_edit = e1.text_input("人员", r['user_name'] or "", key=f"un_p_{r['id']}{form_key_suffix}")
                                                pn_edit = e2.number_input("人数", 1, 50, int(r['passenger_count'] or 1), key=f"pn_p_{r['id']}{form_key_suffix}")
                                                ud_edit = e3.date_input("日期", dt_def, key=f"ud_p_{r['id']}{form_key_suffix}")
                                                e4, e5 = st.columns(2)
                                                st_edit = e4.text_input("开始时间", st_def, placeholder="HH:MM", key=f"st_p_{r['id']}{form_key_suffix}")
                                                et_edit = e5.text_input("结束时间", et_def, placeholder="HH:MM", key=f"et_p_{r['id']}{form_key_suffix}")
                                                rs_edit = st.text_area("事由", r['reason'] or "", height=80, key=f"rs_p_{r['id']}{form_key_suffix}")
                                                # 保存、重置和删除按钮
                                                btn_cols = st.columns(3)
                                                with btn_cols[0]:
                                                    save_edit = st.form_submit_button("💾 保存", use_container_width=True)
                                                with btn_cols[1]:
                                                    reset_btn = st.form_submit_button("↻ 重置", use_container_width=True)
                                                with btn_cols[2]:
                                                    del_btn_p = st.form_submit_button("🗑️ 删除", use_container_width=True)
                                                if save_edit:
                                                    st_n = (st_edit or "").replace('：', ':').strip()
                                                    et_n = (et_edit or "").replace('：', ':').strip()
                                                    if not re.match(r'^\d{1,2}:\d{2}$', st_n) or not re.match(r'^\d{1,2}:\d{2}$', et_n):
                                                        st.error("时间格式应为 HH:MM")
                                                    else:
                                                        conn.execute("UPDATE bookings SET start_time=?, end_time=?, user_name=?, passenger_count=?, reason=? WHERE id=?", (f"{ud_edit} {st_n}", f"{ud_edit} {et_n}", un_edit, int(pn_edit), rs_edit, r['id']))
                                                        conn.commit(); st.toast("✅ 已保存"); time.sleep(0.3); st.rerun()
                                                if reset_btn:
                                                    st.session_state[f"reset_p_{r['id']}"] = True
                                                    st.rerun()
                                                if del_btn_p:
                                                    conn.execute("UPDATE bookings SET is_deleted=1 WHERE id=?", (r['id'],))
                                                    conn.commit(); st.toast("🗑️ 已删除"); time.sleep(0.3); st.rerun()
                        
                        # 日期之间添加分隔线
                        st.divider()
            with s2:
                # 已指派（待执行）：任务已指派，但还未开始（当前时间 < 开始时间）
                df_a = pd.read_sql_query("SELECT * FROM bookings WHERE status='已指派' AND is_deleted=0 ORDER BY start_time ASC", conn)
                now = datetime.now()
                pending_tasks = []
                for _, r in df_a.iterrows():
                    start_time = pd.to_datetime(r['start_time'])
                    if now < start_time:
                        pending_tasks.append(r)
                if pending_tasks:
                    st.markdown(f"### 🟢 待执行任务（共 {len(pending_tasks)} 项）")
                    
                    # 按日期分组显示
                    from itertools import groupby
                    # 提取日期字符串作为分组键
                    pending_tasks_sorted = sorted(pending_tasks, key=lambda x: str(x['start_time'])[:10] if x['start_time'] else '')
                    
                    for date_str, tasks_group in groupby(pending_tasks_sorted, key=lambda x: str(x['start_time'])[:10] if x['start_time'] else ''):
                        # 显示日期分隔
                        st.markdown(f"#### 📅 {date_str}")
                        
                        # 将该日期的任务转换为列表并显示
                        date_tasks = list(tasks_group)
                        for i in range(0, len(date_tasks), 2):
                            cols = st.columns(2)
                            for j in range(2):
                                if i + j < len(date_tasks):
                                    with cols[j]:
                                        render_assigned_task(conn, car_list, date_tasks[i + j])
                        
                        # 日期之间添加分隔线
                        st.divider()
                else:
                    st.success("✅ 当前没有待执行的任务")
            
            with s3:
                # 已指派（已执行）：任务已开始或已逾期（当前时间 >= 开始时间）
                df_a = pd.read_sql_query("SELECT * FROM bookings WHERE status='已指派' AND is_deleted=0 ORDER BY start_time ASC", conn)
                now = datetime.now()
                today = now.date()
                
                overdue_tasks_today = []
                overdue_tasks_future = []
                executed_tasks_today = []
                executed_tasks_future = []
                
                for _, r in df_a.iterrows():
                    start_time = pd.to_datetime(r['start_time'])
                    end_time = pd.to_datetime(r['end_time'])
                    task_date = start_time.date()
                    
                    if now > end_time:
                        # 已逾期
                        if task_date == today:
                            overdue_tasks_today.append(r)
                        else:
                            overdue_tasks_future.append(r)
                    elif now >= start_time:
                        # 已执行（进行中）
                        if task_date == today:
                            executed_tasks_today.append(r)
                        else:
                            executed_tasks_future.append(r)
                
                # 显示当日任务
                if overdue_tasks_today:
                    st.markdown(f"### ⛔ 今日已逾期任务（共 {len(overdue_tasks_today)} 项）")
                    for i in range(0, len(overdue_tasks_today), 2):
                        cols = st.columns(2)
                        for j in range(2):
                            if i + j < len(overdue_tasks_today):
                                with cols[j]:
                                    task = overdue_tasks_today[i + j]
                                    # 检查该车辆当日是否有后续任务
                                    task_date = pd.to_datetime(task['start_time']).date()
                                    car_name = task['car_name']
                                    has_later_task = False
                                    for _, r in df_a.iterrows():
                                        if r['car_name'] == car_name:
                                            other_start = pd.to_datetime(r['start_time'])
                                            if other_start.date() == task_date and other_start > pd.to_datetime(task['start_time']):
                                                has_later_task = True
                                                break
                                    if has_later_task:
                                        st.error("⚠️ 该任务已逾期，将可能影响后续任务安排，请确认！！")
                                    render_assigned_task(conn, car_list, task)
                    st.divider()
                
                if executed_tasks_today:
                    st.markdown(f"### 🔴 今日已执行任务（共 {len(executed_tasks_today)} 项）")
                    for i in range(0, len(executed_tasks_today), 2):
                        cols = st.columns(2)
                        for j in range(2):
                            if i + j < len(executed_tasks_today):
                                with cols[j]:
                                    render_assigned_task(conn, car_list, executed_tasks_today[i + j])
                    st.divider()
                
                # 显示今后任务（非今日）
                if overdue_tasks_future:
                    st.markdown(f"### 📅 今后已逾期任务（共 {len(overdue_tasks_future)} 项）")
                    for i in range(0, len(overdue_tasks_future), 2):
                        cols = st.columns(2)
                        for j in range(2):
                            if i + j < len(overdue_tasks_future):
                                with cols[j]:
                                    render_assigned_task(conn, car_list, overdue_tasks_future[i + j])
                    st.divider()
                
                if executed_tasks_future:
                    st.markdown(f"### 📅 今后已执行任务（共 {len(executed_tasks_future)} 项）")
                    for i in range(0, len(executed_tasks_future), 2):
                        cols = st.columns(2)
                        for j in range(2):
                            if i + j < len(executed_tasks_future):
                                with cols[j]:
                                    render_assigned_task(conn, car_list, executed_tasks_future[i + j])
                    st.divider()
                
                if not overdue_tasks_today and not executed_tasks_today and not overdue_tasks_future and not executed_tasks_future:
                    st.success("✅ 当前没有已执行的任务")

    # --- TAB 6: 任务列表 ---
    if st.session_state.role == 'admin':
        with tabs[6]:
            st.markdown("### 🔍 筛选条件")
            
            # 获取筛选条件数据
            cars_list = pd.read_sql_query("SELECT plate_num FROM cars WHERE is_deleted=0 OR is_deleted IS NULL ORDER BY plate_num", conn)
            car_options = ["全部车辆"] + cars_list['plate_num'].tolist() if not cars_list.empty else ["全部车辆"]
            
            # 筛选条件行
            filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 1])
            
            with filter_col1:
                # 时间范围选择
                date_col1, date_col2 = st.columns(2)
                with date_col1:
                    start_date = st.date_input("开始日期", value=None, key="audit_start_date")
                with date_col2:
                    end_date = st.date_input("结束日期", value=None, key="audit_end_date")
            
            with filter_col2:
                # 车号选择
                selected_car = st.selectbox("选择车辆", car_options, key="audit_car_select")
            
            with filter_col3:
                st.write("")
                st.write("")
                if st.button("🔄 重置筛选", use_container_width=True, type="secondary"):
                    st.session_state.audit_start_date = None
                    st.session_state.audit_end_date = None
                    st.session_state.audit_car_select = "全部车辆"
                    st.rerun()
            
            
            # 构建查询条件
            query = "SELECT id, car_name, start_time, end_time, user_name, passenger_count, reason, status, is_deleted FROM bookings WHERE 1=1"
            params = []
            
            # 时间范围筛选
            if start_date:
                query += " AND datetime(start_time) >= datetime(?)"
                params.append(f"{start_date} 00:00:00")
            if end_date:
                query += " AND datetime(start_time) <= datetime(?)"
                params.append(f"{end_date} 23:59:59")
            
            # 车号筛选
            if selected_car and selected_car != "全部车辆":
                query += " AND car_name = ?"
                params.append(selected_car)
            
            query += " ORDER BY id DESC"
            
            df_all = pd.read_sql_query(query, conn, params=params)
            
            # 显示统计信息
            if not df_all.empty:
                stat_cols = st.columns(4)
                with stat_cols[0]:
                    st.metric("📊 总记录数", len(df_all))
                with stat_cols[1]:
                    st.metric("🔵 未完成", len(df_all[(df_all['status'] == '已指派') & (df_all['is_deleted'] == 0)]))
                with stat_cols[2]:
                    st.metric("🟢 已完成", len(df_all[df_all['status'] == '已完成']))
                with stat_cols[3]:
                    st.metric("🔴 已删除", len(df_all[df_all['is_deleted'] == 1]))
                
                st.markdown("---")
                
                st_df = df_all.copy()
                st_df['任务状态'] = st_df.apply(lambda x: "已删除" if int(x['is_deleted'] or 0) == 1 else (x['status'] or ""), axis=1)
                # 重命名列为中文
                st_df = st_df.rename(columns={
                    'id': 'ID',
                    'car_name': '车号',
                    'start_time': '任务开始时间',
                    'end_time': '任务结束时间',
                    'user_name': '使用人',
                    'passenger_count': '人数',
                    'reason': '事由'
                })
                show_cols = ['ID', '车号', '任务开始时间', '任务结束时间', '使用人', '人数', '事由', '任务状态']
                st.dataframe(st_df[show_cols], use_container_width=True, hide_index=True)
            else:
                st.info("📝 暂无符合条件的任务记录")
    
    # --- TAB 7: 车辆报表 ---
    if st.session_state.role == 'admin':
        with tabs[7]:
            st.markdown("### 📊 车辆使用报表")
            
            # 月份选择 - 使用月份列表简化选择
            current_year = datetime.now().year
            current_month = datetime.now().month
            
            # 生成月份选项列表（近24个月）
            month_options = []
            month_values = []
            for i in range(24):
                # 从当前月份往前推24个月
                year = current_year
                month = current_month - i
                while month <= 0:
                    month += 12
                    year -= 1
                month_str = f"{year}年{month}月"
                month_options.append(month_str)
                month_values.append((year, month))
            
            # 使用单一下拉框选择年月
            col1, col2 = st.columns([1, 3])
            with col1:
                selected_idx = st.selectbox("📅 选择月份", range(len(month_options)), 
                                           format_func=lambda x: month_options[x], index=0)
                selected_year, selected_month = month_values[selected_idx]
            
            # 构建查询条件
            month_start = f"{selected_year}-{selected_month:02d}-01 00:00:00"
            if selected_month == 12:
                month_end = f"{selected_year + 1}-01-01 00:00:00"
            else:
                month_end = f"{selected_year}-{selected_month + 1:02d}-01 00:00:00"
            
            # 先查询当月总任务数
            total_tasks = pd.read_sql_query(
                """SELECT COUNT(*) as count FROM bookings 
                   WHERE is_deleted = 0
                   AND datetime(start_time) >= datetime(?)
                   AND datetime(start_time) < datetime(?)""",
                conn, params=(month_start, month_end)
            ).iloc[0]['count']
            
            with col2:
                # 使用更紧凑的显示方式
                st.markdown(f"""
                <div style="
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 10px 20px;
                    border-radius: 10px;
                    color: white;
                    text-align: center;
                    margin-top: 5px;
                ">
                    <div style="font-size: 14px; opacity: 0.9;">📊 当月任务总数</div>
                    <div style="font-size: 32px; font-weight: bold;">{int(total_tasks)}</div>
                </div>
                """, unsafe_allow_html=True)
            
            
            # 获取所有车辆
            cars_df = pd.read_sql_query("SELECT plate_num FROM cars WHERE is_deleted=0 OR is_deleted IS NULL ORDER BY plate_num", conn)
            
            if cars_df.empty:
                st.warning("🚗 暂无车辆信息")
            else:
                # 统计每辆车的数据
                report_data = []
                for _, car in cars_df.iterrows():
                    car_name = car['plate_num']
                    
                    # 查询该月份的任务数
                    task_count = pd.read_sql_query(
                        """SELECT COUNT(*) as count FROM bookings 
                           WHERE car_name = ? 
                           AND is_deleted = 0
                           AND datetime(start_time) >= datetime(?)
                           AND datetime(start_time) < datetime(?)""",
                        conn, params=(car_name, month_start, month_end)
                    ).iloc[0]['count']
                    
                    # 查询该月份的里程合计（当前为空）
                    mileage_result = pd.read_sql_query(
                        """SELECT SUM(mileage) as total_mileage FROM bookings 
                           WHERE car_name = ? 
                           AND is_deleted = 0
                           AND datetime(start_time) >= datetime(?)
                           AND datetime(start_time) < datetime(?)""",
                        conn, params=(car_name, month_start, month_end)
                    ).iloc[0]['total_mileage']
                    
                    total_mileage = mileage_result if mileage_result is not None else 0
                    
                    report_data.append({
                        '车牌号': car_name,
                        '任务次数': task_count,
                        '公里数合计': f"{total_mileage:.1f}" if total_mileage > 0 else "-"
                    })
                
                # 显示报表
                report_df = pd.DataFrame(report_data)
                
                st.markdown("---")
                st.markdown("#### 任务完成数")
                
                # 使用表格显示
                st.dataframe(report_df, use_container_width=True, hide_index=True)
                
                # 导出功能
                st.markdown("---")
                col_export1, col_export2 = st.columns([1, 4])
                with col_export1:
                    @st.cache_data
                    def convert_report_to_excel(df):
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name=f'{selected_year}年{selected_month}月车辆报表')
                        return output.getvalue()
                    
                    excel_data = convert_report_to_excel(report_df)
                    st.download_button(
                        label="📥 导出报表",
                        data=excel_data,
                        file_name=f"车辆报表_{selected_year}年{selected_month}月.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
    
    # --- TAB 8: 车辆管理 ---
    if st.session_state.role == 'admin':
        with tabs[8]:
            # 左右分栏布局
            left_col, right_col = st.columns([2, 1])
            
            # ========== 左侧：车辆列表和统计 ==========
            with left_col:
                st.markdown("### 🚗 车辆列表")
                
                cars_list = pd.read_sql_query("SELECT * FROM cars WHERE is_deleted=0 OR is_deleted IS NULL ORDER BY display_order ASC, plate_num ASC", conn)
                
                if cars_list.empty:
                    st.info("📝 暂无车辆信息，请在右侧添加车辆或导入Excel")
                else:
                    # 统计信息
                    total_cars = len(cars_list)
                    available_cars = len(cars_list[cars_list['available'] == 1])
                    unavailable_cars = total_cars - available_cars
                    
                    # 统计卡片
                    stat_cols = st.columns(3)
                    with stat_cols[0]:
                        st.metric("🚗 车辆总数", total_cars)
                    with stat_cols[1]:
                        st.metric("✅ 可用", available_cars)
                    with stat_cols[2]:
                        st.metric("❌ 不可用", unavailable_cars)
                    
                    st.markdown("---")
                    
                    # 车辆卡片 - 每行2个
                    car_cols = st.columns(2)
                    for idx, (_, c) in enumerate(cars_list.iterrows()):
                        with car_cols[idx % 2]:
                            available = bool(c.get('available', 1))
                            status_text = "可用" if available else "不可用"
                            status_bg = "#e8f5e9" if available else "#ffebee"
                            status_text_color = "#2e7d32" if available else "#c62828"
                            
                            with st.container(border=True):
                                # 头部：车牌 + 状态 + 排序
                                header_col, status_col, order_col = st.columns([2, 1, 1])
                                display_order = int(c.get('display_order', 999))
                                with header_col:
                                    st.markdown(f"**{c['plate_num']}**")
                                with status_col:
                                    st.markdown(f"<span style='background-color:{status_bg};color:{status_text_color};padding:3px 8px;border-radius:8px;font-size:12px;font-weight:600;'>{status_text}</span>", 
                                              unsafe_allow_html=True)
                                with order_col:
                                    st.markdown(f"<span style='background-color:#e3f2fd;color:#1565c0;padding:3px 8px;border-radius:8px;font-size:12px;font-weight:600;'>📋{display_order}</span>", 
                                              unsafe_allow_html=True)
                                
                                st.caption(f"{c['car_type']} | 乘客{c['capacity']}人")
                                st.caption(f"👤 {c['driver_name'] or '无'} | 📞 {c['driver_phone'] or '无'}")
                                
                                # 操作按钮
                                btn_cols = st.columns([1, 1, 1, 1])
                                
                                btn_key = f"btn_toggle_{c['plate_num']}"
                                state_key = f"state_toggle_{c['plate_num']}"
                                confirm_key = f"confirm_toggle_{c['plate_num']}"
                                cancel_key = f"cancel_toggle_{c['plate_num']}"
                                
                                with btn_cols[0]:
                                    if available:
                                        if st.button("⏸️", key=btn_key, help="设为不可用"):
                                            st.session_state[state_key] = True
                                            st.rerun()
                                    else:
                                        if st.button("▶️", key=btn_key, help="设为可用"):
                                            conn.execute("UPDATE cars SET available=1 WHERE plate_num=?", (c['plate_num'],))
                                            conn.commit()
                                            st.rerun()
                                
                                with btn_cols[1]:
                                    if st.button("✏️", key=f"edit_{c['plate_num']}", help="编辑信息"):
                                        st.session_state[f'show_edit_{c["plate_num"]}'] = True
                                        st.rerun()
                                
                                with btn_cols[2]:
                                    if st.button("📋", key=f"order_{c['plate_num']}", help="修改排序"):
                                        st.session_state[f'show_order_{c["plate_num"]}'] = True
                                        st.rerun()
                                
                                with btn_cols[3]:
                                    if st.button("🗑️", key=f"dc_{c['plate_num']}", help="删除车辆"):
                                        st.session_state[f'confirm_delete_{c["plate_num"]}'] = True
                                        st.rerun()
                                
                                # 编辑车辆信息表单
                                if st.session_state.get(f'show_edit_{c["plate_num"]}', False):
                                    with st.form(f"edit_form_{c['plate_num']}", border=True):
                                        st.markdown(f"**✏️ 编辑 {c['plate_num']} 信息**")
                                        
                                        edit_col1, edit_col2 = st.columns(2)
                                        with edit_col1:
                                            new_car_type = st.text_input("车型", c['car_type'] or "")
                                            new_capacity = st.number_input("乘客人数", 1, 60, int(c['capacity'] or 5))
                                        with edit_col2:
                                            new_driver_name = st.text_input("司机姓名", c['driver_name'] or "")
                                            new_driver_phone = st.text_input("司机电话", c['driver_phone'] or "")
                                        
                                        edit_btn_cols = st.columns([1, 1])
                                        with edit_btn_cols[0]:
                                            if st.form_submit_button("✅ 保存", use_container_width=True):
                                                conn.execute(
                                                    "UPDATE cars SET car_type=?, capacity=?, driver_name=?, driver_phone=? WHERE plate_num=?",
                                                    (new_car_type, new_capacity, new_driver_name, new_driver_phone, c['plate_num'])
                                                )
                                                conn.commit()
                                                st.session_state[f'show_edit_{c["plate_num"]}'] = False
                                                st.success("✅ 车辆信息已更新")
                                                time.sleep(0.3)
                                                st.rerun()
                                        with edit_btn_cols[1]:
                                            if st.form_submit_button("❌ 取消", use_container_width=True):
                                                st.session_state[f'show_edit_{c["plate_num"]}'] = False
                                                st.rerun()
                                
                                # 修改排序表单
                                if st.session_state.get(f'show_order_{c["plate_num"]}', False):
                                    with st.form(f"order_form_{c['plate_num']}", border=True):
                                        st.markdown(f"**📋 修改 {c['plate_num']} 的显示顺序**")
                                        new_order = st.number_input("显示顺序", 1, 999, display_order, 
                                                                    help="数字越小越靠前，1为最先显示")
                                        order_cols = st.columns([1, 1])
                                        with order_cols[0]:
                                            if st.form_submit_button("✅ 保存", use_container_width=True):
                                                conn.execute("UPDATE cars SET display_order=? WHERE plate_num=?", (new_order, c['plate_num']))
                                                conn.commit()
                                                st.session_state[f'show_order_{c["plate_num"]}'] = False
                                                st.success("✅ 排序已更新")
                                                time.sleep(0.3)
                                                st.rerun()
                                        with order_cols[1]:
                                            if st.form_submit_button("❌ 取消", use_container_width=True):
                                                st.session_state[f'show_order_{c["plate_num"]}'] = False
                                                st.rerun()
                                
                                # 删除确认（软删除）
                                if st.session_state.get(f'confirm_delete_{c["plate_num"]}', False):
                                    # 检查该车辆是否有已指派任务
                                    assigned_tasks = pd.read_sql_query(
                                        "SELECT COUNT(*) as count FROM bookings WHERE car_name=? AND status='已指派' AND is_deleted=0",
                                        conn, params=(c['plate_num'],)
                                    ).iloc[0]['count']
                                    
                                    if assigned_tasks > 0:
                                        st.error(f"❌ 无法删除！该车辆有 {assigned_tasks} 个已指派任务，请先处理这些任务后再删除车辆。")
                                        if st.button("❌ 关闭", key=f"del_close_{c['plate_num']}"):
                                            st.session_state[f'confirm_delete_{c["plate_num"]}'] = False
                                            st.rerun()
                                    else:
                                        st.warning(f"⚠️ 确认删除 **{c['plate_num']}**？\n\n软删除后车辆将不在列表中显示，但历史任务记录将保留。")
                                        del_cols = st.columns([1, 1])
                                        with del_cols[0]:
                                            if st.button("✅ 确认", key=f"del_confirm_{c['plate_num']}", help="确认软删除"):
                                                conn.execute("UPDATE cars SET is_deleted=1 WHERE plate_num=?", (c['plate_num'],))
                                                conn.commit()
                                                st.session_state[f'confirm_delete_{c["plate_num"]}'] = False
                                                st.success("✅ 车辆已删除")
                                                time.sleep(0.3)
                                                st.rerun()
                                        with del_cols[1]:
                                            if st.button("❌ 取消", key=f"del_cancel_{c['plate_num']}", help="取消删除"):
                                                st.session_state[f'confirm_delete_{c["plate_num"]}'] = False
                                                st.rerun()
                                
                                # 设为不可用确认
                                if st.session_state.get(state_key, False):
                                    # 检查该车辆是否有已指派任务
                                    assigned_tasks_df = pd.read_sql_query(
                                        "SELECT id, start_time, end_time, user_name, passenger_count, reason FROM bookings WHERE car_name=? AND status='已指派' AND is_deleted=0 ORDER BY start_time ASC",
                                        conn, params=(c['plate_num'],)
                                    )
                                    
                                    if not assigned_tasks_df.empty:
                                        st.warning(f"⚠️ **{c['plate_num']}** 有 {len(assigned_tasks_df)} 个已指派任务")
                                        st.markdown("**以下任务将被退回至待指派状态：**")
                                        
                                        # 显示任务列表
                                        display_df = assigned_tasks_df.copy()
                                        display_df.columns = ['ID', '开始时间', '结束时间', '人员', '人数', '事由']
                                        st.dataframe(display_df, use_container_width=True, hide_index=True)
                                        
                                        st.markdown("---")
                                        st.markdown("**请选择操作：**")
                                        toggle_cols = st.columns([1, 1])
                                        with toggle_cols[0]:
                                            if st.button("✅ 确认更改", key=confirm_key, help="将车辆设为不可用，并退回所有已指派任务"):
                                                # 将所有已指派任务退回待指派状态
                                                for _, task in assigned_tasks_df.iterrows():
                                                    conn.execute(
                                                        "UPDATE bookings SET car_name=NULL, status='待指派' WHERE id=?",
                                                        (task['id'],)
                                                    )
                                                # 将车辆设为不可用
                                                conn.execute("UPDATE cars SET available=0 WHERE plate_num=?", (c['plate_num'],))
                                                conn.commit()
                                                st.session_state[state_key] = False
                                                st.success(f"✅ 车辆已设为不可用，{len(assigned_tasks_df)} 个任务已退回待指派状态")
                                                time.sleep(0.3)
                                                st.rerun()
                                        with toggle_cols[1]:
                                            if st.button("❌ 取消", key=cancel_key, help="取消操作"):
                                                st.session_state[state_key] = False
                                                st.rerun()
                                    else:
                                        st.warning(f"⚠️ 确认将 **{c['plate_num']}** 设为不可用？")
                                        toggle_cols = st.columns([1, 1])
                                        with toggle_cols[0]:
                                            if st.button("✅ 确认", key=confirm_key, help="确认设为不可用"):
                                                conn.execute("UPDATE cars SET available=0 WHERE plate_num=?", (c['plate_num'],))
                                                conn.commit()
                                                st.session_state[state_key] = False
                                                st.success("✅ 车辆已设为不可用")
                                                time.sleep(0.3)
                                                st.rerun()
                                        with toggle_cols[1]:
                                            if st.button("❌ 取消", key=cancel_key, help="取消操作"):
                                                st.session_state[state_key] = False
                                                st.rerun()
            
            # ========== 右侧：添加新车辆 ==========
            with right_col:
                st.markdown("### ➕ 添加新车辆")
                with st.form("cadd", border=True):
                    pn = st.text_input("🚗 车牌号", placeholder="如：苏D12345")
                    ct = st.text_input("🚙 车型", placeholder="如：轿车、商务车")
                    cap = st.number_input("👥 乘客人数", 1, 60, 4, help="不含驾驶员的乘客座位数")
                    dn = st.text_input("👤 司机姓名", placeholder="司机姓名")
                    dp = st.text_input("📞 司机电话", placeholder="联系电话")
                    disp_order = st.number_input("📋 显示顺序", 1, 999, 999, help="数字越小越靠前显示，1为最先显示")
                    
                    submitted = st.form_submit_button("✨ 添加车辆", use_container_width=True, type="primary")
                    
                    if submitted:
                        if not pn or not ct:
                            st.error("❌ 车牌号和车型不能为空")
                        else:
                            try:
                                conn.execute("INSERT OR REPLACE INTO cars VALUES (?,?,?,?,?,?,0,?)", (pn, ct, cap, dn, dp, 1, disp_order))
                                conn.commit()
                                st.success(f"✅ 车辆 {pn} 添加成功！")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"添加失败：{str(e)}")
                
                
                # 导入/导出功能（折叠）
                with st.expander("📥📤 导入/导出车辆数据"):
                    # 导出功能
                    cars_df = pd.read_sql_query("SELECT plate_num as '车牌号', car_type as '车型', capacity as '乘客人数', driver_name as '司机姓名', driver_phone as '司机电话', available as '可用状态' FROM cars WHERE is_deleted=0 OR is_deleted IS NULL", conn)
                    if not cars_df.empty:
                        cars_df['可用状态'] = cars_df['可用状态'].apply(lambda x: '可用' if x == 1 else '不可用')
                    
                    @st.cache_data
                    def convert_df_to_excel(df):
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name='车辆信息')
                        return output.getvalue()
                    
                    if not cars_df.empty:
                        excel_data = convert_df_to_excel(cars_df)
                        st.download_button(
                            label="📥 导出车辆信息",
                            data=excel_data,
                            file_name=f"车辆信息_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            type="secondary"
                        )
                    else:
                        st.button("📥 导出车辆信息", use_container_width=True, disabled=True)                    
                    
                    # 导入功能
                    uploaded_file = st.file_uploader("📤 导入Excel", type=['xlsx', 'xls'], key="car_import")
                    if uploaded_file is not None:
                        try:
                            import_df = pd.read_excel(uploaded_file)
                            column_mapping = {
                                '车牌号': 'plate_num', 'plate_num': 'plate_num',
                                '车型': 'car_type', 'car_type': 'car_type',
                                '乘客人数': 'capacity', 'capacity': 'capacity',
                                '司机姓名': 'driver_name', 'driver_name': 'driver_name',
                                '司机电话': 'driver_phone', 'driver_phone': 'driver_phone',
                                '可用状态': 'available', 'available': 'available'
                            }
                            import_df = import_df.rename(columns=column_mapping)
                            required_cols = ['plate_num', 'car_type', 'capacity']
                            missing_cols = [col for col in required_cols if col not in import_df.columns]
                            
                            if missing_cols:
                                st.error(f"缺少必要列: {', '.join(missing_cols)}")
                            else:
                                if 'driver_name' not in import_df.columns:
                                    import_df['driver_name'] = ''
                                if 'driver_phone' not in import_df.columns:
                                    import_df['driver_phone'] = ''
                                if 'available' not in import_df.columns:
                                    import_df['available'] = 1
                                else:
                                    import_df['available'] = import_df['available'].apply(
                                        lambda x: 1 if str(x).lower() in ['可用', 'true', '1', '是', 'yes'] else 0
                                    )
                                
                                st.success(f"✅ 成功读取 {len(import_df)} 条车辆记录")
                                
                                if st.button("✨ 确认导入", use_container_width=True, type="primary"):
                                    success_count = 0
                                    for _, row in import_df.iterrows():
                                        try:
                                            conn.execute(
                                                "INSERT OR REPLACE INTO cars VALUES (?,?,?,?,?,?)",
                                                (row['plate_num'], row['car_type'], int(row['capacity']), 
                                                 row['driver_name'], row['driver_phone'], int(row['available']))
                                            )
                                            success_count += 1
                                        except Exception as e:
                                            st.warning(f"导入 {row['plate_num']} 失败: {str(e)}")
                                    conn.commit()
                                    st.success(f"✅ 成功导入 {success_count} 条记录")
                                    time.sleep(1)
                                    st.rerun()
                        except Exception as e:
                            st.error(f"读取Excel失败: {str(e)}")
                    
                    # 下载模板
                    template_df = pd.DataFrame({
                        '车牌号': ['苏D12345', '苏D67890'],
                        '车型': ['轿车', '商务车'],
                        '乘客人数': [4, 6],
                        '司机姓名': ['张师傅', '李师傅'],
                        '司机电话': ['13800138000', '13900139000'],
                        '可用状态': ['可用', '可用']
                    })
                    template_excel = convert_df_to_excel(template_df)
                    st.download_button(
                        label="📄 下载导入模板",
                        data=template_excel,
                        file_name="车辆导入模板.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
    
    # --- TAB 9: 用户管理 ---
    if st.session_state.role == 'admin':
        with tabs[9]:
            # 左右分栏布局 - 与车辆管理统一
            left_col, right_col = st.columns([2, 1])
            
            # ========== 左侧：用户列表和统计 ==========
            with left_col:
                st.markdown("### 👥 用户列表")
                
                # 获取用户数据
                users_df = pd.read_sql_query("SELECT * FROM users ORDER BY username", conn)
                
                if users_df.empty:
                    st.info("📝 暂无用户数据，请在右侧添加用户")
                else:
                    # 统计信息 - 与车辆管理风格统一
                    total_users = len(users_df)
                    admin_count = len(users_df[users_df['role'] == 'admin'])
                    user_count = len(users_df[users_df['role'] == 'user'])
                    
                    # 统计卡片 - 与车辆管理风格统一
                    stat_cols = st.columns(3)
                    with stat_cols[0]:
                        st.metric("👥 用户总数", total_users)
                    with stat_cols[1]:
                        st.metric("🔴 管理员", admin_count)
                    with stat_cols[2]:
                        st.metric("🟢 普通用户", user_count)
                    
                    st.markdown("---")
                    
                    # 用户卡片 - 每行2个（与车辆管理每行3个区分，因用户信息较少）
                    user_cols = st.columns(2)
                    for idx, (_, u) in enumerate(users_df.iterrows()):
                        with user_cols[idx % 2]:
                            # 根据角色设置不同的颜色
                            is_admin = u['role'] == 'admin'
                            role_text = "管理员" if is_admin else "普通用户"
                            role_bg = "#ffebee" if is_admin else "#e8f5e9"
                            role_text_color = "#c62828" if is_admin else "#2e7d32"
                            
                            with st.container(border=True):
                                # 头部：用户名 + 角色标签（与车辆管理风格统一）
                                header_col, role_col = st.columns([2, 1])
                                with header_col:
                                    st.markdown(f"**{u['username']}**")
                                with role_col:
                                    st.markdown(f"<span style='background-color:{role_bg};color:{role_text_color};padding:3px 8px;border-radius:8px;font-size:12px;font-weight:600;'>{role_text}</span>", 
                                              unsafe_allow_html=True)
                                
                                st.caption(f"🛡️ 角色: {u['role']}")
                                
                                # 操作按钮 - 与车辆管理风格统一（使用图标按钮）
                                btn_cols = st.columns([1, 1, 1])
                                
                                with btn_cols[0]:
                                    if st.button("🔑", key=f"cp_{u['username']}", help="修改密码"):
                                        st.session_state[f'show_cp_{u["username"]}'] = True
                                        st.rerun()
                                
                                with btn_cols[1]:
                                    if u['username'] == 'admin':
                                        st.button("🚫", key=f"du_{u['username']}", disabled=True, help="admin账户不能删除")
                                    else:
                                        if st.button("🗑️", key=f"du_{u['username']}", help="删除用户"):
                                            st.session_state[f'confirm_del_{u["username"]}'] = True
                                            st.rerun()
                                
                                with btn_cols[2]:
                                    pass
                                
                                # 删除确认对话框（与车辆管理风格统一）
                                if st.session_state.get(f'confirm_del_{u["username"]}', False):
                                    st.warning(f"⚠️ 确认删除 **{u['username']}**？")
                                    del_cols = st.columns([1, 1])
                                    with del_cols[0]:
                                        if st.button("✅ 确认", key=f"confirm_del_btn_{u['username']}", use_container_width=True):
                                            conn.execute("DELETE FROM users WHERE username=?", (u['username'],))
                                            conn.commit()
                                            st.session_state[f'confirm_del_{u["username"]}'] = False
                                            st.success(f"✅ 用户 {u['username']} 已删除")
                                            time.sleep(0.3)
                                            st.rerun()
                                    with del_cols[1]:
                                        if st.button("❌ 取消", key=f"cancel_del_{u['username']}", use_container_width=True):
                                            st.session_state[f'confirm_del_{u["username"]}'] = False
                                            st.rerun()
                                
                                # 修改密码表单（与车辆管理风格统一）
                                if st.session_state.get(f'show_cp_{u["username"]}', False):
                                    with st.form(f"cp_form_{u['username']}", border=True):
                                        st.markdown(f"**🔐 修改 {u['username']} 的密码**")
                                        
                                        new_pw = st.text_input("新密码", type="password", key=f"new_pw_{u['username']}", placeholder="输入新密码")
                                        confirm_pw = st.text_input("确认密码", type="password", key=f"confirm_pw_{u['username']}", placeholder="再次输入")
                                        
                                        btn_cols = st.columns([1, 1])
                                        with btn_cols[0]:
                                            if st.form_submit_button("✅ 保存", use_container_width=True):
                                                if not new_pw:
                                                    st.error("请输入新密码")
                                                elif new_pw != confirm_pw:
                                                    st.error("两次输入的密码不一致")
                                                else:
                                                    conn.execute("UPDATE users SET password=? WHERE username=?", 
                                                               (hashlib.sha256(new_pw.encode()).hexdigest(), u['username']))
                                                    conn.commit()
                                                    st.session_state[f'show_cp_{u["username"]}'] = False
                                                    st.success(f"✅ {u['username']} 的密码已修改")
                                                    time.sleep(0.3)
                                                    st.rerun()
                                        with btn_cols[1]:
                                            if st.form_submit_button("❌ 取消", use_container_width=True):
                                                st.session_state[f'show_cp_{u["username"]}'] = False
                                                st.rerun()
            
            # ========== 右侧：添加新用户 ==========
            with right_col:
                st.markdown("### ➕ 添加新用户")
                with st.form("uadd", border=True):
                    un_u = st.text_input("👤 账号", placeholder="输入用户名")
                    pw_u = st.text_input("🔒 密码", type="password", placeholder="输入密码")
                    rl_u = st.selectbox("🛡️ 角色", ["user", "admin"])
                    
                    submitted = st.form_submit_button("✨ 创建账号", use_container_width=True, type="primary")
                    
                    if submitted:
                        if not un_u or not pw_u:
                            st.error("❌ 账号和密码不能为空")
                        else:
                            try:
                                conn.execute("INSERT INTO users VALUES (?,?,?)", 
                                           (un_u, hashlib.sha256(pw_u.encode()).hexdigest(), rl_u))
                                conn.commit()
                                st.success(f"✅ 用户 {un_u} 创建成功！")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 创建失败：{str(e)}")

    # --- TAB 10: 流程说明 ---
        with tabs[10]:
            # 标题和导出按钮
            title_col, export_col = st.columns([4, 1])
            with title_col:
                st.markdown("## 📋 派车系统流程说明")
            with export_col:
                st.write("")
                st.write("")
                
                # 生成PDF的函数
                def generate_pdf():
                    try:
                        from reportlab.lib.pagesizes import A4
                        from reportlab.pdfbase import pdfmetrics
                        from reportlab.pdfbase.ttfonts import TTFont
                        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
                        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                        from reportlab.lib import colors
                        from reportlab.lib.units import cm
                        
                        # 注册中文字体
                        try:
                            pdfmetrics.registerFont(TTFont('SimSun', 'simsun.ttc'))
                            chinese_font = 'SimSun'
                        except:
                            try:
                                pdfmetrics.registerFont(TTFont('SimSun', 'C:/Windows/Fonts/simsun.ttc'))
                                chinese_font = 'SimSun'
                            except:
                                chinese_font = 'Helvetica'
                        
                        # 创建PDF缓冲区
                        buffer = io.BytesIO()
                        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                                              rightMargin=2*cm, leftMargin=2*cm,
                                              topMargin=2*cm, bottomMargin=2*cm)
                        
                        # 创建样式
                        styles = getSampleStyleSheet()
                        title_style = ParagraphStyle(
                            'CustomTitle',
                            parent=styles['Heading1'],
                            fontName=chinese_font,
                            fontSize=20,
                            spaceAfter=20,
                            alignment=1
                        )
                        heading2_style = ParagraphStyle(
                            'CustomHeading2',
                            parent=styles['Heading2'],
                            fontName=chinese_font,
                            fontSize=14,
                            spaceAfter=10,
                            spaceBefore=15,
                            textColor=colors.black
                        )
                        normal_style = ParagraphStyle(
                            'CustomNormal',
                            parent=styles['Normal'],
                            fontName=chinese_font,
                            fontSize=10,
                            spaceAfter=6,
                            leading=14
                        )
                        
                        story = []
                        
                        # 标题
                        story.append(Paragraph("派车系统流程说明", title_style))
                        story.append(Spacer(1, 0.3*cm))
                        story.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal_style))
                        story.append(Spacer(1, 0.5*cm))
                        
                        # 0. 系统设计理念
                        story.append(Paragraph("零、系统设计理念", heading2_style))
                        story.append(Paragraph("本系统围绕<strong>任务全生命周期管理</strong>和<strong>车辆资源冲突避免</strong>两个核心目标设计：", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("<strong>任务流转逻辑</strong>：", normal_style))
                        story.append(Paragraph('从收到用车申请开始，任务经历"申请→指派→执行→完成"的完整流程。每个阶段的状态变化都由系统自动控制或用户操作触发，确保任务状态实时反映实际情况。特别设计了"已逾期"状态，强制要求人工确认逾期任务的处置，防止车辆资源被无效占用。', normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("<strong>车辆冲突避免机制</strong>：", normal_style))
                        story.append(Paragraph('车辆被占用的时间段从任务指派开始，到任务手动完成为止（而非仅按预定结束时间）。这种设计确保：1) 逾期任务必须被确认后才能释放车辆；2) 新任务指派时会检查时间重叠、车辆逾期状态、车辆可用性三重条件；3) 避免同一辆车在同一时段被重复指派。', normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 1. 操作流程
                        story.append(Paragraph("一、操作流程", heading2_style))
                        story.append(Paragraph("1. 任务申请", normal_style))
                        story.append(Paragraph("• 在【任务申请】TAB填写信息", normal_style))
                        story.append(Paragraph("• 提交后任务为<strong>待指派</strong>状态", normal_style))
                        story.append(Paragraph("• 此时不占用任何车辆", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        story.append(Paragraph("2. 车辆指派", normal_style))
                        story.append(Paragraph("• 在【车辆指派】→【待指派】选择车辆", normal_style))
                        story.append(Paragraph("• 系统检查：时间冲突、车辆是否有逾期任务、车辆是否可用、人数是否超过限制", normal_style))
                        story.append(Paragraph("• 指派后任务为<strong>已指派</strong>状态", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        story.append(Paragraph("3. 任务执行与完成", normal_style))
                        story.append(Paragraph("• 到达开始时间自动变为<strong>已执行</strong>", normal_style))
                        story.append(Paragraph("• 超过结束时间变为<strong>已逾期</strong>", normal_style))
                        story.append(Paragraph('• 必须手动点击"完成"按钮', normal_style))
                        story.append(Paragraph("• 完成后车辆释放", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 2. 任务状态流转
                        story.append(Paragraph("二、任务状态流转（5个状态）", heading2_style))
                        story.append(Paragraph("新建任务 → 待指派 → 已指派 → 已执行 → 已逾期 → 已完成", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        # 状态表格
                        task_data = [
                            ['状态', '说明', '车辆占用', '转换条件'],
                            ['待指派', '任务已创建，未分配车辆', '否', '新建默认'],
                            ['待执行', '已分配车辆，尚未开始', '是', '指派后，当前时间<开始时间'],
                            ['已执行', '任务进行中', '是', '开始时间≤当前≤结束时间'],
                            ['已逾期', '超过结束时间，需手动完成', '是', '当前时间>结束时间'],
                            ['已完成', '任务已结束，车辆释放', '否', '手动点击完成']
                        ]
                        task_table = Table(task_data, colWidths=[3*cm, 5*cm, 2.5*cm, 5*cm])
                        task_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                            ('FONTNAME', (0, 0), (-1, 0), chinese_font),
                            ('FONTSIZE', (0, 0), (-1, 0), 10),
                            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                            ('GRID', (0, 0), (-1, -1), 1, colors.black),
                            ('FONTNAME', (0, 1), (-1, -1), chinese_font),
                            ('FONTSIZE', (0, 1), (-1, -1), 9),
                            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ]))
                        story.append(task_table)
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 3. 状态自动转换规则
                        story.append(Paragraph("三、状态自动转换规则", heading2_style))
                        story.append(Paragraph("系统根据<strong>当前时间</strong>与任务的<strong>开始/结束时间</strong>自动判断状态：", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("• 当前时间 &lt; 开始时间 → <strong>待执行</strong>", normal_style))
                        story.append(Paragraph("• 开始时间 ≤ 当前时间 ≤ 结束时间 → <strong>已执行</strong>", normal_style))
                        story.append(Paragraph("• 当前时间 &gt; 结束时间 → <strong>已逾期</strong>（需手动完成）", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 4. 车辆状态管理
                        story.append(Paragraph("四、车辆状态管理（2个状态）", heading2_style))
                        story.append(Paragraph("<strong>可用</strong>：可接受新任务指派，卡片正常显示，默认状态", normal_style))
                        story.append(Paragraph("<strong>不可用</strong>：无法接受新任务，卡片红色警示，用于临时停运、维修", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("设为不可用的限制：", normal_style))
                        story.append(Paragraph("• 无法设为不可用：车辆有执行中的任务（已开始但未结束）", normal_style))
                        story.append(Paragraph("• 需要确认：车辆有待执行的任务（未开始），确认后退回待指派", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 5. 车辆占用时间段定义
                        story.append(Paragraph("五、车辆占用时间段定义", heading2_style))
                        story.append(Paragraph("车辆被任务占用的时间段为：<strong>从开始时间起，到任务被手动完成为止</strong>", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("占用期间：", normal_style))
                        story.append(Paragraph("• 待执行：任务已指派，等待开始", normal_style))
                        story.append(Paragraph("• 已执行：任务进行中", normal_style))
                        story.append(Paragraph("• 已逾期：超过结束时间但未完成", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("释放条件：", normal_style))
                        story.append(Paragraph('• 任务被手动标记为"已完成"', normal_style))
                        story.append(Paragraph('• 任务被"退回"到待指派状态', normal_style))
                        story.append(Paragraph("• 任务被删除", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("<strong>重要说明</strong>：即使任务已经超过结束时间（已逾期），只要未手动完成，车辆仍然处于被占用状态，不能指派给其他任务。这是为了确保逾期任务得到确认和处理。", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 6. 车辆指派冲突检查逻辑
                        story.append(Paragraph("六、车辆指派冲突检查逻辑", heading2_style))
                        story.append(Paragraph("当为待指派任务安排车辆时，系统会进行以下检查：", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("冲突判定条件：", normal_style))
                        story.append(Paragraph("1. 时间重叠冲突：新任务与已指派任务的时间段重叠", normal_style))
                        story.append(Paragraph("   新任务开始时间 &lt; 占用任务结束时间 <strong>且</strong> 新任务结束时间 &gt; 占用任务开始时间", normal_style))
                        story.append(Paragraph("2. 车辆逾期任务：车辆存在已逾期（未完成）的任务", normal_style))
                        story.append(Paragraph('3. 车辆不可用：车辆被标记为"不可用"状态', normal_style))
                        story.append(Paragraph('4. 人数超过限制：任务人数 &gt; 车辆最大乘客数', normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("通过条件（同时满足）：", normal_style))
                        story.append(Paragraph("• 时间段无重叠", normal_style))
                        story.append(Paragraph("• 车辆无逾期任务", normal_style))
                        story.append(Paragraph('• 车辆状态为"可用"', normal_style))
                        story.append(Paragraph('• 任务人数 ≤ 车辆乘客数', normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("检查范围：只检查 status='已指派' 的任务（包括：待执行、已执行、已逾期）", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 7. 其他功能说明
                        story.append(Paragraph("七、其他功能说明", heading2_style))
                        story.append(Paragraph("<strong>已派打印</strong>：选择车辆生成任务清单PDF，包含车辆信息、司机、任务列表，用于出车前的任务确认", normal_style))
                        story.append(Paragraph("<strong>任务列表</strong>：查看所有任务记录，支持按时间、车号筛选，显示任务状态统计，按ID倒序排列", normal_style))
                        story.append(Paragraph("<strong>车辆报表</strong>：按月统计车辆使用情况，显示每辆车的任务次数，便于车辆使用分析", normal_style))
                        story.append(Paragraph("<strong>车辆卡片</strong>：直观展示所有车辆状态，支持快速查看车辆任务详情", normal_style))
                        story.append(Paragraph("<strong>双月全景</strong>：双月日历视图，按开始时间排序展示任务", normal_style))
                        story.append(Paragraph("<strong>间隙警示</strong>：显示车辆任务间隔小于60分钟的警示信息", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 8. 车辆软删除与回收站
                        story.append(Paragraph("八、车辆软删除与回收站", heading2_style))
                        story.append(Paragraph("车辆删除采用<strong>软删除</strong>机制，删除的车辆可在【高级设置】中恢复", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("<strong>软删除</strong>：删除车辆时标记为已删除，历史任务记录保留，车辆不再显示在车辆卡片中", normal_style))
                        story.append(Paragraph("<strong>回收站恢复</strong>：在【高级设置】→【回收站】中查看，可恢复误删的车辆或永久删除", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 9. 多车辆任务处理
                        story.append(Paragraph("九、多车辆任务处理", heading2_style))
                        story.append(Paragraph("当任务人数超过单辆车最大乘客数时，支持快速复制任务", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("触发条件：任务人数 > 所有车辆中最大乘客数", normal_style))
                        story.append(Paragraph("处理方式：系统提示需要多辆车共同完成，在【车辆指派】中显示快速复制按钮，点击可复制任务", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 10. 高级设置
                        story.append(Paragraph("十、高级设置", heading2_style))
                        story.append(Paragraph("<strong>数据库备份</strong>：一键备份当前数据库，生成带时间戳的备份文件，用于数据迁移和灾难恢复", normal_style))
                        story.append(Paragraph("<strong>数据库恢复</strong>：从备份文件恢复数据，恢复前自动备份当前数据，防止误操作", normal_style))
                        story.append(Paragraph("<strong>数据库初始化</strong>：清空所有任务记录，保留车辆和用户信息，需要多次确认", normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 11. 特殊情况处理
                        story.append(Paragraph("十一、特殊情况处理", heading2_style))
                        story.append(Paragraph("<strong>任务退回</strong>：", normal_style))
                        story.append(Paragraph('• 在【已指派】中点击"退回"按钮', normal_style))
                        story.append(Paragraph('• 任务回到"待指派"状态，车辆立即释放', normal_style))
                        story.append(Paragraph("• 需重新指派车辆", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        story.append(Paragraph("<strong>逾期任务处理</strong>：", normal_style))
                        story.append(Paragraph("• 逾期任务会显示红色警示", normal_style))
                        story.append(Paragraph("• 车辆仍被占用，不能指派新任务", normal_style))
                        story.append(Paragraph("• 需在【已指派】→【已逾期】中处理", normal_style))
                        story.append(Paragraph('• 点击"完成"后车辆才释放', normal_style))
                        story.append(Spacer(1, 0.3*cm))
                        
                        # 12. 未来改进方向
                        story.append(Paragraph("十二、未来改进方向（企业微信/钉钉集成）", heading2_style))
                        story.append(Paragraph("为解决单机操作无法实时通知司机的问题，可集成企业微信或钉钉实现以下功能：", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        story.append(Paragraph("<strong>1. 架构设计</strong>", normal_style))
                        story.append(Paragraph("派车系统 → 消息推送服务（企业微信/钉钉API） → 司机手机（企业应用）", normal_style))
                        story.append(Paragraph("• 任务指派时自动推送消息给司机", normal_style))
                        story.append(Paragraph("• 司机通过企业应用确认接收和完成任务", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        story.append(Paragraph("<strong>2. 企业微信集成方案</strong>", normal_style))
                        story.append(Paragraph("前期准备：", normal_style))
                        story.append(Paragraph("• 注册企业微信并创建内部应用", normal_style))
                        story.append(Paragraph("• 获取企业ID、应用ID、应用密钥", normal_style))
                        story.append(Paragraph("• 添加司机为成员并获取UserID", normal_style))
                        story.append(Spacer(1, 0.1*cm))
                        story.append(Paragraph("核心功能：", normal_style))
                        story.append(Paragraph("• 消息推送：任务指派时发送卡片消息给司机", normal_style))
                        story.append(Paragraph("• 回调接口：接收司机的确认和完成操作", normal_style))
                        story.append(Paragraph("• 状态同步：司机操作后自动更新任务状态", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        story.append(Paragraph("<strong>3. 钉钉集成方案</strong>", normal_style))
                        story.append(Paragraph("前期准备：", normal_style))
                        story.append(Paragraph("• 注册钉钉开发者账号并创建企业内部应用", normal_style))
                        story.append(Paragraph("• 获取AppKey、AppSecret、AgentId", normal_style))
                        story.append(Paragraph("• 添加司机为员工并获取UserID", normal_style))
                        story.append(Spacer(1, 0.1*cm))
                        story.append(Paragraph("核心功能：", normal_style))
                        story.append(Paragraph("• 发送任务卡片：包含任务详情和确认按钮", normal_style))
                        story.append(Paragraph("• 工作通知：通过钉钉工作通知推送任务", normal_style))
                        story.append(Paragraph("• 回调处理：处理司机的确认和完成回调", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        story.append(Paragraph("<strong>4. 实现步骤</strong>", normal_style))
                        story.append(Paragraph("① 注册并配置企业微信/钉钉", normal_style))
                        story.append(Paragraph("② 扩展数据库添加司机通知ID字段", normal_style))
                        story.append(Paragraph("③ 开发消息推送模块封装API", normal_style))
                        story.append(Paragraph("④ 开发回调接口接收司机操作", normal_style))
                        story.append(Paragraph("⑤ 集成到现有系统指派任务时发送通知", normal_style))
                        story.append(Spacer(1, 0.2*cm))
                        
                        story.append(Paragraph("<strong>5. 优缺点对比</strong>", normal_style))
                        story.append(Paragraph("企业微信：需要企业资质，适合已有企业微信的组织", normal_style))
                        story.append(Paragraph("钉钉：个人/企业均可注册，开发文档完善", normal_style))
                        story.append(Paragraph("两者均免费（有额度限制），消息到达率高", normal_style))
                        
                        # 生成PDF
                        doc.build(story)
                        pdf_data = buffer.getvalue()
                        buffer.close()
                        return pdf_data
                    except Exception as e:
                        st.error(f"PDF生成失败：{str(e)}")
                        return None
                
                # 预生成PDF数据
                pdf_data = generate_pdf()
                
                # 直接提供下载按钮（如果PDF生成成功）
                if pdf_data:
                    st.download_button(
                        label="📄 导出PDF",
                        data=pdf_data,
                        file_name=f"派车系统流程说明_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
            
            st.markdown("### 💡 系统设计理念")
            st.info("""
            本系统围绕**任务全生命周期管理**和**车辆资源冲突避免**两个核心目标设计：
            
            **任务流转逻辑**：
            从收到用车申请开始，任务经历"申请→指派→执行→完成"的完整流程。每个阶段的状态变化都由系统自动控制或用户操作触发，
            确保任务状态实时反映实际情况。特别设计了"已逾期"状态，强制要求人工确认逾期任务的处置，防止车辆资源被无效占用。
            
            **车辆冲突避免机制**：
            车辆被占用的时间段从任务指派开始，到任务手动完成为止（而非仅按预定结束时间）。这种设计确保：
            1) 逾期任务必须被确认后才能释放车辆；2) 新任务指派时会检查时间重叠、车辆逾期状态、车辆可用性三重条件；
            3) 避免同一辆车在同一时段被重复指派。
            """)
            
            st.divider()

            st.markdown("### 👤 用户权限说明")
            st.info("系统根据用户角色控制功能访问权限，分为管理员和普通用户两种角色")

            col_role1, col_role2 = st.columns(2)

            with col_role1:
                st.markdown("#### 🛡️ 管理员 (admin)")
                st.markdown("""
                **完整权限，可访问所有功能：**
                - ✅ 车辆卡片 - 查看车辆状态
                - ✅ 间隙警示 - 查看任务间隔警示
                - ✅ 双月全景 - 查看双月日历
                - ✅ 已派打印 - 打印任务清单
                - ✅ 任务申请 - 提交用车申请
                - ✅ **车辆指派** - 分配车辆给任务
                - ✅ **任务列表** - 查看所有任务记录
                - ✅ **车辆报表** - 车辆使用统计
                - ✅ **车辆管理** - 添加/编辑/删除车辆
                - ✅ **用户管理** - 添加/编辑/删除用户
                - ✅ 流程说明 - 查看使用说明
                - ✅ **高级设置** - 数据库备份/恢复/回收站
                """)

            with col_role2:
                st.markdown("#### 👤 普通用户 (user)")
                st.markdown("""
                **受限权限，仅可查看和申请：**
                - ✅ 车辆卡片 - 查看车辆状态
                - ✅ 间隙警示 - 查看任务间隔警示
                - ✅ 双月全景 - 查看双月日历
                - ✅ 已派打印 - 打印任务清单
                - ✅ 任务申请 - 提交用车申请
                - ❌ 车辆指派 - 不可访问
                - ❌ 任务列表 - 不可访问
                - ❌ 车辆报表 - 不可访问
                - ❌ 车辆管理 - 不可访问
                - ❌ 用户管理 - 不可访问
                - ✅ 流程说明 - 查看使用说明
                - ❌ 高级设置 - 不可访问
                """)

            st.warning("""
            **⚠️ 权限说明：**
            - 新创建的用户默认为普通用户(user)角色
            - 只有管理员可以创建新用户和修改用户权限
            - admin账户为系统默认管理员，不可删除
            - 普通用户只能提交任务申请，无法指派车辆
            """)

            st.divider()

            st.markdown("### 📖 操作流程")
            
            col3, col4, col5 = st.columns(3)
            
            with col3:
                st.markdown("#### 1️⃣ 任务申请")
                st.markdown("""
                - 在【任务申请】TAB填写信息
                - 提交后任务为**待指派**状态
                - 此时不占用任何车辆
                """)
                
            with col4:
                st.markdown("#### 2️⃣ 车辆指派")
                st.markdown("""
                - 在【车辆指派】→【待指派】选择车辆
                - 系统检查：
                  - 时间冲突
                  - 车辆是否有逾期任务
                  - 车辆是否可用
                - 指派后任务为**已指派**状态
                """)
                
            with col5:
                st.markdown("#### 3️⃣ 任务执行与完成")
                st.markdown("""
                - 到达开始时间自动变为**已执行**
                - 超过结束时间变为**已逾期**
                - 必须手动点击"完成"按钮
                - 完成后车辆释放
                """)
            
            st.divider()
            
            st.markdown("### 🔄 任务状态流转（5个状态）")
            st.info("""
            **新建任务** → **待指派** → **已指派** → **已执行** → **已逾期** → **已完成**
            """)
            
            st.markdown("#### 📌 任务状态说明")
            st.markdown("""
            | 状态 | 说明 | 车辆占用 | 转换条件 |
            |------|------|----------|----------|
            | 🟡 **待指派** | 任务已创建，未分配车辆 | ❌ 否 | 新建任务默认状态 |
            | 🟢 **待执行** | 已分配车辆，尚未开始 | ✅ 是 | 指派车辆后，当前时间 < 开始时间 |
            | 🔴 **已执行** | 任务进行中，时间已开始 | ✅ 是 | 开始时间 ≤ 当前时间 ≤ 结束时间 |
            | ⛔ **已逾期** | 超过结束时间，需手动完成 | ✅ 是 | 当前时间 > 结束时间 |
            | ✅ **已完成** | 任务已结束，车辆释放 | ❌ 否 | 手动点击"完成"按钮 |
            """)
            
            st.divider()
            
            st.markdown("### 📝 状态自动转换规则")
            st.markdown("""
            系统根据**当前时间**与任务的**开始/结束时间**自动判断状态：
            
            ```
            当前时间 < 开始时间  →  待执行
            开始时间 ≤ 当前时间 ≤ 结束时间  →  已执行
            当前时间 > 结束时间  →  已逾期（需手动完成）
            ```
            """)
            
            st.divider()
            
            st.markdown("### 🚗 车辆状态管理（2个状态）")
            
            col_v1, col_v2 = st.columns(2)
            
            with col_v1:
                st.markdown("#### ✅ 可用")
                st.markdown("""
                - 可接受新任务指派
                - 卡片正常显示
                - 默认状态
                """)
                
            with col_v2:
                st.markdown("#### ❌ 不可用")
                st.markdown("""
                - 无法接受新任务
                - 卡片红色背景警示
                - 用于临时停运、维修
                """)
            
            st.info("💡 **任务状态 vs 车辆状态**：任务有5个流转状态，车辆只有2个管理状态（可用/不可用）")
            
            st.markdown("#### ⚠️ 设为不可用的限制")
            st.warning("""
            **无法设为不可用：**
            - 车辆有**执行中的任务**（已开始但未结束）
            
            **需要确认：**
            - 车辆有**待执行的任务**（未开始）
            - 确认后所有待执行任务将**退回到待指派状态**
            """)
            
            st.divider()
            
            st.markdown("### ⏰ 车辆占用时间段定义")
            st.info("""
            车辆被任务占用的时间段为：**从开始时间起，到任务被手动完成为止**
            """)
            
            col_time1, col_time2 = st.columns(2)
            
            with col_time1:
                st.markdown("#### 📌 占用期间")
                st.markdown("""
                以下情况车辆处于**被占用**状态：
                - 🟢 **待执行**：任务已指派，等待开始
                - 🔴 **已执行**：任务进行中
                - ⛔ **已逾期**：超过结束时间但未完成
                
                **占用特点：**
                - 从任务指派后开始占用
                - 不随结束时间自动释放
                - 必须手动点击"完成"才释放
                """)
                
            with col_time2:
                st.markdown("#### 📌 释放条件")
                st.markdown("""
                车辆**释放**的条件：
                - ✅ 任务被手动标记为"已完成"
                - 🔄 任务被"退回"到待指派状态
                - 🗑️ 任务被删除
                
                **冲突判定：**
                新任务与占用任务的时间段重叠时：
                ```
                新任务开始时间 < 占用任务结束时间
                且
                新任务结束时间 > 占用任务开始时间
                ```
                即视为冲突，无法指派
                """)
            
            st.warning("""
            **⚠️ 重要说明：**
            即使任务已经超过结束时间（已逾期），只要未手动完成，车辆仍然处于被占用状态，
            不能指派给其他任务。这是为了确保逾期任务得到确认和处理。
            """)
            
            st.divider()
            
            st.markdown("### 🔍 车辆指派冲突检查逻辑")
            st.info("当为待指派任务安排车辆时，系统会进行以下检查：")
            
            col_chk1, col_chk2 = st.columns(2)
            
            with col_chk1:
                st.markdown("#### ❌ 冲突判定条件")
                st.markdown("""
                **1. 时间重叠冲突**
                新任务与已指派任务的时间段重叠：
                ```
                新任务开始时间 < 占用任务结束时间
                且
                新任务结束时间 > 占用任务开始时间
                ```
                
                **2. 车辆逾期任务**
                车辆存在已逾期（未完成）的任务
                
                **3. 车辆不可用**
                车辆被标记为"不可用"状态
                
                **4. 人数超过限制**
                任务人数 > 车辆最大乘客数
                """)
                
            with col_chk2:
                st.markdown("#### ✅ 通过条件")
                st.markdown("""
                **同时满足以下条件才能指派：**
                - ✅ 时间段无重叠
                - ✅ 车辆无逾期任务
                - ✅ 车辆状态为"可用"
                - ✅ 任务人数 ≤ 车辆乘客数
                
                **检查范围：**
                只检查 `status='已指派'` 的任务
                - 包括：待执行、已执行、已逾期
                - 不包括：待指派、已完成
                """)
            
            st.warning("""
            **⚠️ 注意**：
            - 冲突检查只针对**已指派**状态的任务
            - **待指派**任务（无车号）不参与冲突判定
            - **已完成**任务已释放车辆，不参与冲突判定
            - 修改已指派任务时也会检查人数限制
            """)
            
            st.divider()
            
            st.markdown("### 🤖 智能识别功能")
            st.info("在【任务申请】TAB中，支持粘贴文本自动识别任务信息")
            
            st.markdown("#### 📋 支持的识别格式")
            
            col_ir1, col_ir2 = st.columns(2)
            
            with col_ir1:
                st.markdown("**日期格式**")
                st.markdown("""
                - 标准格式：`2024-01-15`、`2024/01/15`、`01-15`
                - 中文日期：`1月15日`、`1月15号`、`2024年1月15日`
                - 相对日期：`明天`、`后天`、`大后天`
                - 下周：`下周一`、`下周三`、`下周日`
                """)
                
                st.markdown("**时间格式**")
                st.markdown("""
                - 标准格式：`09:00`、`14:30`
                - 中文时间：`上午9点`、`下午2点半`、`晚上7点`
                - 时间范围：`9:00-11:00`、`9点至11点`、`9点到11点`
                """)
            
            with col_ir2:
                st.markdown("**人员与人数**")
                st.markdown("""
                - 人数：`5人`、`3名`、`2位`
                - 键值对：`人数：5`、`人员数量：3`
                - 人员：`人员：张三`、`姓名：李四`
                """)
                
                st.markdown("**事由提取**")
                st.markdown("""
                - 键值对：`事由：去南京出差`
                - 键值对：`任务：参加会议`
                """)
            
            st.markdown("#### 💡 识别示例")
            
            col_ex1, col_ex2 = st.columns(2)
            
            with col_ex1:
                st.markdown("**示例1：简洁格式**")
                st.code("""张三 5人 明天 上午9点-下午5点 去南京出差""", language="text")
                st.markdown("""
                识别结果：
                - 人员：张三
                - 人数：5
                - 日期：明天
                - 时间：09:00 - 17:00
                - 事由：去南京出差
                """)
            
            with col_ex2:
                st.markdown("**示例2：键值对格式**")
                st.code("""人员：李四
人数：3人
日期：2024年1月20日
时间：14:00-16:00
事由：参加会议""", language="text")
                st.markdown("""
                识别结果：
                - 人员：李四
                - 人数：3
                - 日期：2024-01-20
                - 时间：14:00 - 16:00
                - 事由：参加会议
                """)
            
            st.divider()
            
            st.markdown("### 📊 其他功能说明")
            
            col8, col9, col10, col10a = st.columns(4)
            
            with col8:
                st.markdown("#### 📄 已派打印")
                st.markdown("""
                - 选择车辆生成任务清单
                - 支持下载格式化PDF文件
                - 包含车辆信息、司机、任务列表
                - 用于出车前的任务确认
                """)
                
            with col9:
                st.markdown("#### 📋 任务列表")
                st.markdown("""
                - 查看所有任务记录
                - 支持按时间、车号筛选
                - 显示任务状态统计
                - 可查看已删除任务
                - 按ID倒序排列
                """)
                
            with col10:
                st.markdown("#### 📈 车辆报表")
                st.markdown("""
                - 按月统计车辆使用情况
                - 显示每辆车的任务次数
                - 汇总当月任务总数
                - 便于车辆使用分析
                """)
                
            with col10a:
                st.markdown("#### ⚠️ 间隙警示")
                st.markdown("""
                - 显示车辆任务间隔警示
                - 间隔小于60分钟的任务
                - 便于合理安排车辆调度
                - 避免车辆连续高强度使用
                """)
                
            st.divider()
            
            st.markdown("### 🎴 车辆卡片")
            st.info("直观展示所有车辆状态，支持快速查看车辆任务")
            st.markdown("""
            - 以卡片形式展示所有车辆
            - 显示车辆状态：待命/运行中/逾期/不可用
            - 点击卡片查看车辆任务详情
            - 支持快速编辑车辆信息
            """)
            
            st.divider()
            
            st.markdown("### 📅 双月全景")
            st.info("双月日历视图，按开始时间排序展示任务")
            st.markdown("""
            - 同时显示本月和下月日历
            - 任务按开始时间升序排列
            - 彩色任务标签区分不同车辆
            - 直观查看每日任务分布
            """)
            
            st.divider()
            
            st.markdown("### 🗑️ 车辆软删除与回收站")
            st.info("车辆删除采用**软删除**机制，删除的车辆可在【高级设置】中恢复")
            
            col_del1, col_del2 = st.columns(2)
            
            with col_del1:
                st.markdown("#### 🗑️ 软删除")
                st.markdown("""
                - 删除车辆时标记为已删除
                - 历史任务记录保留
                - 车辆不再显示在车辆卡片中
                - 不可用于新任务指派
                """)
                
            with col_del2:
                st.markdown("#### ♻️ 回收站恢复")
                st.markdown("""
                - 在【高级设置】→【回收站】中查看
                - 可恢复误删的车辆
                - 可永久删除车辆
                - 恢复后车辆可正常使用
                """)
            
            st.divider()
            
            st.markdown("### 👥 多车辆任务处理")
            st.info("当任务人数超过单辆车最大乘客数时，支持快速复制任务")
            
            st.markdown("""
            **触发条件：**
            - 任务人数 > 所有车辆中最大乘客数
            
            **处理方式：**
            - 系统提示需要多辆车共同完成
            - 在【车辆指派】中显示"快速复制"按钮
            - 点击可复制任务（保留人数等信息）
            - 将人员分组后分别指派不同车辆
            """)
            
            st.divider()
            
            st.markdown("### ⚙️ 高级设置")
            st.info("管理员功能：数据库管理和系统维护")
            
            col_adv1, col_adv2, col_adv3 = st.columns(3)
            
            with col_adv1:
                st.markdown("#### 💾 数据库备份")
                st.markdown("""
                - 一键备份当前数据库
                - 生成带时间戳的备份文件
                - 用于数据迁移和灾难恢复
                """)
                
            with col_adv2:
                st.markdown("#### 📥 数据库恢复")
                st.markdown("""
                - 从备份文件恢复数据
                - 恢复前自动备份当前数据
                - 防止误操作导致数据丢失
                """)
                
            with col_adv3:
                st.markdown("#### 🔄 数据库初始化")
                st.markdown("""
                - 清空所有任务记录
                - 保留车辆和用户信息
                - 需要多次确认，谨慎使用
                """)
            
            st.divider()
            
            st.markdown("### ⚠️ 特殊情况处理")
            
            col6, col7 = st.columns(2)
            
            with col6:
                st.markdown("#### 🔄 任务退回")
                st.markdown("""
                - 在【已指派】中点击"退回"按钮
                - 任务回到**待指派**状态
                - **车辆立即释放**，可被其他任务使用
                - 需重新指派车辆
                """)
                
            with col7:
                st.markdown("#### ⛔ 逾期任务处理")
                st.markdown("""
                - 逾期任务会显示红色警示
                - **车辆仍被占用**，不能指派新任务
                - 需在【已指派】→【已逾期】中处理
                - 点击"完成"后车辆才释放
                """)
            
            st.info("💡 **提示**：车辆卡片会实时显示每辆车的当前状态（待命/运行中/逾期/不可用）")
            
            st.divider()
            
            st.markdown("### 🚀 未来改进方向")
            st.info("为解决单机操作无法实时通知司机的问题，可集成企业微信或钉钉实现消息推送功能")
            
            st.markdown("""
            **1. 架构设计**
            ```
            派车系统 → 消息推送服务（企业微信/钉钉API） → 司机手机（企业应用）
            ```
            - 任务指派时自动推送消息给司机
            - 司机通过企业应用确认接收和完成任务
            
            **2. 企业微信集成方案**
            
            *前期准备：*
            - 注册企业微信并创建内部应用
            - 获取企业ID、应用ID、应用密钥
            - 添加司机为成员并获取UserID
            
            *核心功能：*
            - 消息推送：任务指派时发送卡片消息给司机
            - 回调接口：接收司机的确认和完成操作
            - 状态同步：司机操作后自动更新任务状态
            
            **3. 钉钉集成方案**
            
            *前期准备：*
            - 注册钉钉开发者账号并创建企业内部应用
            - 获取AppKey、AppSecret、AgentId
            - 添加司机为员工并获取UserID
            
            *核心功能：*
            - 发送任务卡片：包含任务详情和确认按钮
            - 工作通知：通过钉钉工作通知推送任务
            - 回调处理：处理司机的确认和完成回调
            
            **4. 实现步骤**
            1. 注册并配置企业微信/钉钉
            2. 扩展数据库添加司机通知ID字段
            3. 开发消息推送模块封装API
            4. 开发回调接口接收司机操作
            5. 集成到现有系统指派任务时发送通知
            
            **5. 优缺点对比**
            | 平台 | 注册要求 | 适用场景 |
            |------|----------|----------|
            | 企业微信 | 需要企业资质 | 已有企业微信的组织 |
            | 钉钉 | 个人/企业均可 | 开发文档完善，易上手 |
            
            *两者均免费（有额度限制），消息到达率高*
            """)
    
    # --- TAB 11: 高级设置 ---
    if st.session_state.role == 'admin':
        with tabs[11]:
            st.markdown("## ⚙️ 高级设置")
            
            # ========== 数据库备份与恢复 ==========
            st.markdown("### 💾 数据库备份与恢复")
            
            col_backup, col_restore = st.columns(2)
            
            with col_backup:
                st.markdown("#### 📥 备份数据库")
                st.info("将当前数据库备份为文件，可用于数据迁移或灾难恢复。")
                
                if st.button("💾 创建备份", use_container_width=True, type="primary"):
                    backup_path = None
                    try:
                        # 生成备份文件名
                        backup_filename = f"Carmgr_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                        backup_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), backup_filename)
                        
                        # 关闭当前连接后复制文件
                        conn.close()
                        shutil.copy2(DB_FILE, backup_path)
                        
                        # 重新建立连接
                        conn = sqlite3.connect(DB_FILE)
                        
                        # 提供下载
                        with open(backup_path, 'rb') as f:
                            backup_data = f.read()
                        
                        st.download_button(
                            label="📥 下载备份文件",
                            data=backup_data,
                            file_name=backup_filename,
                            mime="application/octet-stream",
                            use_container_width=True
                        )
                        
                        st.success(f"✅ 备份成功！文件大小: {os.path.getsize(backup_path) / 1024:.1f} KB")
                        
                    except Exception as e:
                        st.error(f"❌ 备份失败: {str(e)}")
                        # 确保连接恢复
                        try:
                            conn = sqlite3.connect(DB_FILE)
                        except:
                            pass
                    finally:
                        # 清理临时备份文件
                        if backup_path and os.path.exists(backup_path):
                            try:
                                os.remove(backup_path)
                            except:
                                pass
            
            with col_restore:
                st.markdown("#### 📤 恢复数据库")
                st.warning("⚠️ 恢复数据库将覆盖当前所有数据，请谨慎操作！")
                
                uploaded_file = st.file_uploader("选择备份文件 (.db)", type=['db'])
                
                if uploaded_file is not None:
                    st.info(f"已选择文件: {uploaded_file.name}")
                    
                    if st.button("⚠️ 确认恢复", use_container_width=True, type="secondary"):
                        temp_backup = None
                        try:
                            # 先创建当前数据库的临时备份
                            temp_backup = f"Carmgr_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                            shutil.copy2(DB_FILE, temp_backup)
                            
                            # 关闭连接
                            conn.close()
                            
                            # 写入新数据库文件
                            with open(DB_FILE, 'wb') as f:
                                f.write(uploaded_file.getvalue())
                            
                            # 重新连接
                            conn = sqlite3.connect(DB_FILE)
                            
                            st.success("✅ 数据库恢复成功！请刷新页面。")
                            st.balloons()
                            
                        except Exception as e:
                            st.error(f"❌ 恢复失败: {str(e)}")
                            # 尝试恢复临时备份
                            if temp_backup and os.path.exists(temp_backup):
                                try:
                                    shutil.copy2(temp_backup, DB_FILE)
                                    st.info("已自动回滚到恢复前的状态")
                                except Exception as rollback_error:
                                    st.error(f"回滚失败: {str(rollback_error)}")
                        finally:
                            # 确保连接恢复
                            try:
                                conn = sqlite3.connect(DB_FILE)
                            except:
                                pass
                            # 清理临时备份文件
                            if temp_backup and os.path.exists(temp_backup):
                                try:
                                    os.remove(temp_backup)
                                except:
                                    pass
            
            st.markdown("---")
            
            # ========== 回收站功能 ==========
            st.markdown("### 🗑️ 回收站")
            st.markdown("#### 已删除的车辆")
            
            # 获取已软删除的车辆
            deleted_cars = pd.read_sql_query(
                "SELECT * FROM cars WHERE is_deleted=1 ORDER BY plate_num", 
                conn
            )
            
            if deleted_cars.empty:
                st.info("📝 回收站为空，没有已删除的车辆")
            else:
                st.warning(f"⚠️ 共有 {len(deleted_cars)} 辆已删除的车辆")
                
                # 显示已删除车辆列表
                for _, car in deleted_cars.iterrows():
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([3, 2, 1])
                        
                        with col1:
                            st.markdown(f"**🚗 {car['plate_num']}**")
                            st.caption(f"车型: {car['car_type']} | 乘客{car['capacity']}人")
                            st.caption(f"司机: {car['driver_name'] or '无'} | 电话: {car['driver_phone'] or '无'}")
                        
                        with col2:
                            # 查询该车辆的历史任务数
                            task_count = pd.read_sql_query(
                                "SELECT COUNT(*) as count FROM bookings WHERE car_name=? AND is_deleted=0",
                                conn, params=(car['plate_num'],)
                            ).iloc[0]['count']
                            st.caption(f"📊 历史任务数: {task_count}")
                        
                        with col3:
                            if st.button("🔄 恢复", key=f"restore_{car['plate_num']}", use_container_width=True):
                                conn.execute("UPDATE cars SET is_deleted=0 WHERE plate_num=?", (car['plate_num'],))
                                conn.commit()
                                st.success(f"✅ 车辆 {car['plate_num']} 已恢复！")
                                time.sleep(0.5)
                                st.rerun()
                            
                            if st.button("❌ 彻底删除", key=f"hard_del_{car['plate_num']}", use_container_width=True, type="secondary"):
                                st.session_state[f'confirm_hard_delete_{car["plate_num"]}'] = True
                                st.rerun()
                        
                        # 彻底删除确认
                        if st.session_state.get(f'confirm_hard_delete_{car["plate_num"]}', False):
                            st.error(f"⚠️ 确认彻底删除 **{car['plate_num']}**？\n\n此操作不可恢复，相关历史任务将保留但车辆信息将永久丢失。")
                            confirm_cols = st.columns([1, 1, 2])
                            with confirm_cols[0]:
                                if st.button("✅ 确认删除", key=f"confirm_hd_{car['plate_num']}", type="primary"):
                                    conn.execute("DELETE FROM cars WHERE plate_num=?", (car['plate_num'],))
                                    conn.commit()
                                    st.session_state[f'confirm_hard_delete_{car["plate_num"]}'] = False
                                    st.success(f"🗑️ 车辆 {car['plate_num']} 已彻底删除")
                                    time.sleep(0.5)
                                    st.rerun()
                            with confirm_cols[1]:
                                if st.button("❌ 取消", key=f"cancel_hd_{car['plate_num']}"):
                                    st.session_state[f'confirm_hard_delete_{car["plate_num"]}'] = False
                                    st.rerun()
            
            st.info("""
            **软删除 vs 彻底删除：**
            - 🔄 **恢复**：将车辆重新变为正常状态，可继续使用
            - ❌ **彻底删除**：从数据库中永久删除车辆记录（不可恢复）
            
            **注意：**
            - 软删除的车辆不会出现在车辆列表中
            - 历史任务记录会保留，但车辆信息可能显示为已删除状态
            """)
            
            st.markdown("---")
            
            # ========== 数据库初始化 ==========
            st.markdown("### ⚠️ 数据库初始化")
            st.error("🚨 **危险操作**：此功能将清空数据库中的所有记录（保留admin账户）！")
            
            init_col1, init_col2, init_col3 = st.columns([1, 1, 2])
            
            with init_col1:
                if st.button("🔴 数据库初始化", use_container_width=True, type="secondary"):
                    st.session_state['show_init_confirm'] = True
                    st.rerun()
            
            if st.session_state.get('show_init_confirm', False):
                st.warning("""
                **⚠️ 再次确认：数据库初始化**
                
                此操作将删除以下内容（不可恢复）：
                - 所有任务记录（bookings表）
                - 所有车辆信息（cars表）
                - 所有普通用户账户（保留admin）
                
                **建议操作前先创建备份！**
                """)
                
                confirm_col1, confirm_col2, confirm_col3 = st.columns([1, 1, 2])
                
                with confirm_col1:
                    if st.button("✅ 确认初始化", use_container_width=True, type="primary"):
                        try:
                            # 清空bookings表
                            conn.execute("DELETE FROM bookings")
                            # 清空cars表
                            conn.execute("DELETE FROM cars")
                            # 删除除admin外的所有用户
                            conn.execute("DELETE FROM users WHERE username != 'admin'")
                            conn.commit()
                            
                            st.session_state['show_init_confirm'] = False
                            st.success("✅ 数据库初始化完成！所有记录已清空（admin账户保留）")
                            st.balloons()
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ 初始化失败: {str(e)}")
                
                with confirm_col2:
                    if st.button("❌ 取消", use_container_width=True):
                        st.session_state['show_init_confirm'] = False
                        st.rerun()

# --- 登录入口 by Jiayi Gu with TRAE---
def login():
    # 登录页面使用居中对齐，通过列布局实现
    inject_custom_css()
    left, center, right = st.columns([2,1,2])
    with center:
        st.title("🚗 派车车")
        with st.container(border=True):
            u = st.text_input("工号")
            p = st.text_input("密码", type="password")
            if st.button("登录系统", use_container_width=True):
                conn = init_db()
                res = conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
                if res and res[1] == hashlib.sha256(p.encode()).hexdigest():
                    st.session_state.update({"logged_in": True, "username": u, "role": res[2]}); st.rerun()
                else: st.error("登录失败")

if __name__ == '__main__':
    if 'logged_in' not in st.session_state: st.session_state.logged_in = False
    if not st.session_state.logged_in: login()
    else: main_app()
