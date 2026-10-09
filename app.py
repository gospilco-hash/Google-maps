import io
import urllib.parse
import folium
from folium.features import DivIcon
import googlemaps
import googlemaps.exceptions
import pandas as pd
import polyline
import streamlit as st
from streamlit_folium import st_folium

# ==============================================================================
# 🔑 ЗЧИТУВАННЯ API KEY
# ==============================================================================
if "GOOGLE_MAPS_API_KEY" in st.secrets:
    DEFAULT_API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
else:
    DEFAULT_API_KEY = ""


# ------------------------------------------------------------------------------
# 🛠 ДОПОМІЖНІ ФУНКЦІЇ
# ------------------------------------------------------------------------------
def format_time(seconds: int) -> str:
    """Форматує секунди у зрозумілий текст 'X год Y хв'."""
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    if hrs > 0:
        return f"{hrs} год {mins} хв"
    return f"{mins} хв"


def create_numbered_icon(number_str: str, bg_color: str = "#2563eb") -> DivIcon:
    """Створює круговий нумерований маркер для карти Folium."""
    html = f"""
    <div style="
        background-color: {bg_color};
        color: white;
        border-radius: 50%;
        width: 30px;
        height: 30px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        font-size: 13px;
        border: 2px solid white;
        box-shadow: 0 2px 6px rgba(0,0,0,0.4);
        font-family: Arial, sans-serif;
    ">{number_str}</div>
    """
    return DivIcon(html=html, icon_size=(30, 30), icon_anchor=(15, 15))


def generate_gpx(route_points: list, waypoints_info: list) -> str:
    """Генерує файл GPX з повним GPS-треком та точками для навігаторів."""
    gpx_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Streamlit Route Optimizer">',
        '  <trk>',
        '    <name>Оптимізований маршрут</name>',
        '    <trkseg>',
    ]
    for lat, lng in route_points:
        gpx_lines.append(f'      <trkpt lat="{lat}" lon="{lng}" />')
    gpx_lines.extend(['    </trkseg>', '  </trk>'])

    for wp in waypoints_info:
        lat_val = wp.get("lat")
        lon_val = wp.get("lng", wp.get("lon"))
        name_val = wp.get("name", "Зупинка")
        if lat_val is not None and lon_val is not None:
            gpx_lines.append(f'  <wpt lat="{lat_val}" lon="{lon_val}"><name>{name_val}</name></wpt>')

    gpx_lines.append("</gpx>")
    return "\n".join(gpx_lines)


def build_gmaps_coords_url(start_loc: tuple, end_loc: tuple, waypoints_locs: list) -> str:
    """Формує пряме посилання на Google Maps за точними GPS-координатами."""
    base_url = "https://www.google.com/maps/dir/?api=1"
    orig_q = f"{start_loc[0]},{start_loc[1]}"
    dest_q = f"{end_loc[0]},{end_loc[1]}"
    if waypoints_locs:
        wp_q = "|".join([f"{lat},{lng}" for lat, lng in waypoints_locs])
        return f"{base_url}&origin={orig_q}&destination={dest_q}&waypoints={wp_q}&travelmode=driving"
    return f"{base_url}&origin={orig_q}&destination={dest_q}&travelmode=driving"


def build_waze_url(lat: float, lng: float) -> str:
    """Формує посилання на Waze за точними GPS-координатами."""
    return f"https://www.waze.com/ul?ll={lat},{lng}&navigate=yes"


# ------------------------------------------------------------------------------
# 🎨 НАЛАШТУВАННЯ СТОРІНКИ ТА CSS ДЛЯ ДРУКУ
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Оптимізатор маршрутів",
    page_icon="🗺",
    layout="wide",
)

# Ініціалізація Session State для точок
if "origin_val" not in st.session_state:
    st.session_state["origin_val"] = ""
if "destination_val" not in st.session_state:
    st.session_state["destination_val"] = ""
if "waypoints_list" not in st.session_state:
    st.session_state["waypoints_list"] = []

# Стилі для друку
st.markdown(
    """
<style>
@media print {
    header, footer, [data-testid="stHeader"], [data-testid="stSidebar"],
    .stButton, .stDownloadButton, [data-testid="stFileUploader"],
    [data-testid="stTextInput"], [data-testid="stTextArea"], .stAlert {
        display: none !important;
    }
    
    html, body, .main, .block-container {
        visibility: visible !important;
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
        background-color: white !important;
        color: black !important;
    }

    iframe {
        display: block !important;
        visibility: visible !important;
        width: 100% !important;
        height: 550px !important;
        page-break-inside: avoid !important;
    }

    .block-container {
        max-width: 100% !important;
    }
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🗺️ Планувальник та оптимізатор маршрутів")
st.caption("Розрахунок порядку зупинок, інтерактивна карта з нумерацією, навігація Waze та експорт треку")

# Авторизація API Key
if not DEFAULT_API_KEY:
    api_key_input = st.text_input(
        "🔑 Введіть ваш Google Maps API Key:",
        type="password",
        help="Отримайте ключ у Google Cloud Console або додайте його в Secrets",
    )
else:
    api_key_input = DEFAULT_API_KEY
    st.success("🔒 Google Maps API Key підключено з безпечних налаштувань (Secrets).")

st.divider()

# ------------------------------------------------------------------------------
# 📝 ВВЕДЕННЯ ТА КЕРУВАННЯ МАРШРУТОМ
# ------------------------------------------------------------------------------
st.subheader("📝 Параметри маршруту")

col1, col_swap, col2 = st.columns([5, 2, 5])

with col1:
    origin_input = st.text_input(
        "🚀 Початкова точка (Старт):",
        value=st.session_state["origin_val"],
        key="origin_key",
        placeholder="Наприклад: м. Дніпро, вул. Робоча, 15",
    )
    st.session_state["origin_val"] = origin_input

with col_swap:
    st.write(" ")
    st.write(" ")
    if st.button("🔄 Swap Старт/Фініш", help="Поміняти місцями Старт і Фініш", use_container_width=True):
        st.session_state["origin_val"], st.session_state["destination_val"] = (
            st.session_state["destination_val"],
            st.session_state["origin_val"],
        )
        if "calculated_data" in st.session_state:
            del st.session_state["calculated_data"]
        st.rerun()

with col2:
    destination_input = st.text_input(
        "🏁 Кінцева точка (Фініш):",
        value=st.session_state["destination_val"],
        key="destination_key",
        placeholder="Наприклад: м. Одеса, вул. Дерибасівська, 1",
    )
    st.session_state["destination_val"] = destination_input

# 📂 Завантаження файлу з адресами
st.subheader("🛑 Проміжні адреси")

uploaded_file = st.file_uploader("📂 Завантажити файл з адресами (Excel або CSV):", type=["xlsx", "xls", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        col_name = st.selectbox("Оберіть колонку з адресами:", options=df.columns.tolist())

        if st.button("📥 Завантажити адреси з файлу"):
            extracted = df[col_name].dropna().astype(str).tolist()
            st.session_state["waypoints_list"] = [a.strip() for a in extracted if a.strip()]
            if "calculated_data" in st.session_state:
                del st.session_state["calculated_data"]
            st.success(f"Завантажено {len(st.session_state['waypoints_list'])} адрес!")
            st.rerun()

    except Exception as e:
        st.error(f"❌ Помилка читання файлу: {e}")

# Додавання точки вручну або розбиття по рядках
stops_raw = st.text_area(
    "Швидке вставляння кількох адрес (кожна з нового рядка):",
    height=100,
    placeholder="м. Дніпро, вул. Робоча, 25\nм. Кривий Ріг, пр. Поштовий, 10",
)

if st.button("➕ Додати ці адреси до списку"):
    new_stops = [line.strip() for line in stops_raw.split("\n") if line.strip()]
    if new_stops:
        st.session_state["waypoints_list"].extend(new_stops)
        if "calculated_data" in st.session_state:
            del st.session_state["calculated_data"]
        st.rerun()

# ------------------------------------------------------------------------------
# 🔀 ІНТЕРАКТИВНЕ РЕДАГУВАННЯ ТА ВПОРЯДКУВАННЯ ТОЧОК
# ------------------------------------------------------------------------------
if st.session_state["waypoints_list"]:
    st.write("---")
    st.markdown("### ⚙️ Керування послідовністю проміжних точок:")

    c_rev, c_clr = st.columns([1, 1])
    with c_rev:
        if st.button("🔄 Розвернути всі зупинки у зворотному порядку (Реверс)", use_container_width=True):
            st.session_state["waypoints_list"].reverse()
            if "calculated_data" in st.session_state:
                del st.session_state["calculated_data"]
            st.rerun()
    with c_clr:
        if st.button("🗑️ Очистити всі проміжні точки", use_container_width=True):
            st.session_state["waypoints_list"] = []
            if "calculated_data" in st.session_state:
                del st.session_state["calculated_data"]
            st.rerun()

    st.write("")

    wp_list = st.session_state["waypoints_list"]
    action_type = None
    action_index = None

    for i in range(len(wp_list)):
        c_num, c_text, c_up, c_down, c_del = st.columns([0.5, 6, 1, 1, 1])

        with c_num:
            st.markdown(f"**{i+1}.**")

        with c_text:
            val = st.text_input(
                f"Точка {i+1}",
                value=wp_list[i],
                key=f"wp_txt_{i}_{wp_list[i]}",
                label_visibility="collapsed"
            )
            st.session_state["waypoints_list"][i] = val

        with c_up:
            if i > 0:
                if st.button("⬆", key=f"btn_up_{i}"):
                    action_type = "up"
                    action_index = i

        with c_down:
            if i < len(wp_list) - 1:
                if st.button("⬇", key=f"btn_down_{i}"):
                    action_type = "down"
                    action_index = i

        with c_del:
            if st.button("❌", key=f"btn_del_{i}"):
                action_type = "del"
                action_index = i

    # Виконання дій переміщення/видалення
    if action_type == "up" and action_index is not None:
        idx = action_index
        st.session_state["waypoints_list"][idx], st.session_state["waypoints_list"][idx - 1] = (
            st.session_state["waypoints_list"][idx - 1],
            st.session_state["waypoints_list"][idx],
        )
        if "calculated_data" in st.session_state:
            del st.session_state["calculated_data"]
        st.rerun()

    elif action_type == "down" and action_index is not None:
        idx = action_index
        st.session_state["waypoints_list"][idx], st.session_state["waypoints_list"][idx + 1] = (
            st.session_state["waypoints_list"][idx + 1],
            st.session_state["waypoints_list"][idx],
        )
        if "calculated_data" in st.session_state:
            del st.session_state["calculated_data"]
        st.rerun()

    elif action_type == "del" and action_index is not None:
        st.session_state["waypoints_list"].pop(action_index)
        if "calculated_data" in st.session_state:
            del st.session_state["calculated_data"]
        st.rerun()

# ------------------------------------------------------------------------------
# 🧩 НАЛАШТУВАННЯ ОПТИМІЗАЦІЇ ТА РОЗРАХУНОК
# ------------------------------------------------------------------------------
st.write("---")

# Чекбокс фіксації порядку
fix_order = st.checkbox(
    "🔒 Фіксований порядок зупинок (їхати чітко за вказаним списком без автоперестановки Google)",
    value=True,
    help="Якщо увімкнено, Google зафіксує вашу послідовність (корисно для реверсу або точного маршруту). Якщо вимкнено, Google сама підбере найкоротший порядок точок."
)

btn_col1, btn_col2 = st.columns([4, 1])
with btn_col1:
    calc_button = st.button("🧩 Розрахувати маршрут", type="primary", use_container_width=True)
with btn_col2:
    if "calculated_data" in st.session_state:
        if st.button("🔄 Скинути розрахунок", use_container_width=True):
            del st.session_state["calculated_data"]
            st.rerun()

if calc_button:
    origin = st.session_state["origin_val"].strip()
    destination = st.session_state["destination_val"].strip()
    waypoints = [w.strip() for w in st.session_state["waypoints_list"] if w.strip()]

    if not api_key_input:
        st.error("❌ Вкажіть Google Maps API Key!")
    elif not origin or not destination:
        st.warning("⚠ Будь ласка, вкажіть початкову та кінцеву точки.")
    elif not waypoints:
        st.warning("⚠ Додайте хоча б одну проміжну зупинку.")
    else:
        with st.spinner("Розрахунок маршруту та побудова карти..."):
            try:
                gmaps = googlemaps.Client(key=api_key_input)
                
                # Якщо увімкнено фіксований порядок, optimize_waypoints = False
                should_optimize = not fix_order

                directions = gmaps.directions(
                    origin=origin,
                    destination=destination,
                    waypoints=waypoints,
                    optimize_waypoints=should_optimize,
                    mode="driving",
                    language="uk",
                    region="ua",
                )

                if not directions:
                    st.error("❌ Не вдалося розрахувати маршрут. Перевірте правильність написання адрес.")
                else:
                    route = directions[0]
                    
                    if should_optimize:
                        order = route.get("waypoint_order", [])
                        opt_wp = [waypoints[i] for i in order]
                    else:
                        opt_wp = waypoints  # Послідовність залишається суворо такою, як ввів користувач

                    legs = route.get("legs", [])

                    total_m = sum(l["distance"]["value"] for l in legs)
                    total_s = sum(l["duration"]["value"] for l in legs)

                    start_address = legs[0].get("start_address", origin)
                    start_coords = (legs[0]["start_location"]["lat"], legs[0]["start_location"]["lng"])

                    end_address = legs[-1].get("end_address", destination)
                    end_coords = (legs[-1]["end_location"]["lat"], legs[-1]["end_location"]["lng"])

                    wp_coords = []
                    wp_addresses = []
                    for idx, wp_name in enumerate(opt_wp):
                        stop_lat = legs[idx]["end_location"]["lat"]
                        stop_lng = legs[idx]["end_location"]["lng"]
                        confirmed_addr = legs[idx].get("end_address", wp_name)
                        wp_coords.append((stop_lat, stop_lng))
                        wp_addresses.append(confirmed_addr)

                    encoded_polyline = route["overview_polyline"]["points"]
                    route_points = polyline.decode(encoded_polyline)

                    st.session_state["calculated_data"] = {
                        "km": round(total_m / 1000, 1),
                        "total_s": total_s,
                        "opt_wp": opt_wp,
                        "legs": legs,
                        "start_address": start_address,
                        "start_coords": start_coords,
                        "end_address": end_address,
                        "end_coords": end_coords,
                        "wp_coords": wp_coords,
                        "wp_addresses": wp_addresses,
                        "route_points": route_points,
                        "origin_user": origin,
                        "destination_user": destination,
                    }

            except googlemaps.exceptions.ApiError as e:
                st.error(f"❌ Помилка Google Maps API ({e.status}): {e}")
            except Exception as e:
                st.error(f"❌ Несподівана помилка: {e}")

# ------------------------------------------------------------------------------
# 📊 ВІДОБРАЖЕННЯ РЕЗУЛЬТАТІВ
# ------------------------------------------------------------------------------
if "calculated_data" in st.session_state:
    data = st.session_state["calculated_data"]

    st.success("✅ Маршрут побудовано!")

    # Статистика
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Загальна відстань", f"{data['km']} км")
    c2.metric("Час у дорозі", format_time(data["total_s"]))
    c3.metric("Кількість зупинок", len(data["opt_wp"]))

    st.divider()

    # Інтерактивна карта Folium
    st.subheader("🗺️ Карта маршруту з нумерацією зупинок:")

    m = folium.Map(location=data["route_points"][0], zoom_start=7)

    # Лінія маршруту
    folium.PolyLine(data["route_points"], color="#2563eb", weight=5, opacity=0.8).add_to(m)

    # 1. СТАРТ
    folium.Marker(
        location=data["start_coords"],
        popup=f"1. Старт: {data['start_address']}",
        tooltip=f"🚀 1. СТАРТ: {data['start_address']}",
        icon=create_numbered_icon("1", bg_color="#16a34a"),
    ).add_to(m)

    # 2. Проміжні зупинки
    wpt_for_gpx = [{"lat": data["start_coords"][0], "lng": data["start_coords"][1], "name": f"1. СТАРТ: {data['start_address']}"}]

    for idx, (coords, addr) in enumerate(zip(data["wp_coords"], data["wp_addresses"])):
        num_str = str(idx + 2)
        folium.Marker(
            location=coords,
            popup=f"Зупинка {num_str}: {addr}",
            tooltip=f"{num_str}. {addr}",
            icon=create_numbered_icon(num_str, bg_color="#2563eb"),
        ).add_to(m)

        wpt_for_gpx.append({"lat": coords[0], "lng": coords[1], "name": f"{num_str}. {addr}"})

    # 3. ФІНІШ
    finish_num_str = str(len(data["wp_coords"]) + 2)
    folium.Marker(
        location=data["end_coords"],
        popup=f"Фініш ({finish_num_str}): {data['end_address']}",
        tooltip=f"🏁 {finish_num_str}. ФІНІШ: {data['end_address']}",
        icon=create_numbered_icon(finish_num_str, bg_color="#dc2626"),
    ).add_to(m)

    wpt_for_gpx.append({"lat": data["end_coords"][0], "lng": data["end_coords"][1], "name": f"{finish_num_str}. ФІНІШ: {data['end_address']}"})

    st_folium(m, use_container_width=True, height=550)

    # 📍 Покроковий перелік
    st.divider()
    st.subheader("📍 Порядок відвідування точка за точкою:")

    st.markdown(f"**1. 🚀 СТАРТ:** {data['start_address']}")

    for idx, (wp_user, addr, (stop_lat, stop_lng)) in enumerate(zip(data["opt_wp"], data["wp_addresses"], data["wp_coords"])):
        d = data["legs"][idx]["distance"]["text"]
        t = format_time(data["legs"][idx]["duration"]["value"])

        col_info, col_waze = st.columns([3, 1])
        with col_info:
            st.markdown(f"**{idx + 2}. 🛑 {addr}**\n*(введено: `{wp_user}` | відрізок: {d} | час: {t})*")
        with col_waze:
            st.link_button(f"🚘 Waze (Точка {idx + 2})", build_waze_url(stop_lat, stop_lng), use_container_width=True)

    fin_d = data["legs"][-1]["distance"]["text"]
    fin_t = format_time(data["legs"][-1]["duration"]["value"])
    total_stops_count = len(data["opt_wp"]) + 2

    col_info, col_waze = st.columns([3, 1])
    with col_info:
        st.markdown(f"**{total_stops_count}. 🏁 ФІНІШ:** {data['end_address']}\n*(введено: `{data['destination_user']}` | відрізок: {fin_d} | час: {fin_t})*")
    with col_waze:
        st.link_button("🏁 Waze (Фініш)", build_waze_url(data["end_coords"][0], data["end_coords"][1]), use_container_width=True)

    # Експорт
    export_rows = [
        {
            "№": 1,
            "Тип": "🚀 СТАРТ",
            "Введена адреса": data["origin_user"],
            "Точна адреса": data["start_address"],
            "Широта (Lat)": data["start_coords"][0],
            "Довгота (Lng)": data["start_coords"][1],
            "Відстань": "-",
            "Час": "-",
        }
    ]

    for idx, (wp_user, addr, coords) in enumerate(zip(data["opt_wp"], data["wp_addresses"], data["wp_coords"])):
        export_rows.append(
            {
                "№": idx + 2,
                "Тип": f"🛑 Зупинка {idx + 1}",
                "Введена адреса": wp_user,
                "Точна адреса": addr,
                "Широта (Lat)": coords[0],
                "Довгота (Lng)": coords[1],
                "Відстань": data["legs"][idx]["distance"]["text"],
                "Час": format_time(data["legs"][idx]["duration"]["value"]),
            }
        )

    export_rows.append(
        {
            "№": total_stops_count,
            "Тип": "🏁 ФІНІШ",
            "Введена адреса": data["destination_user"],
            "Точна адреса": data["end_address"],
            "Широта (Lat)": data["end_coords"][0],
            "Довгота (Lng)": data["end_coords"][1],
            "Відстань": fin_d,
            "Час": fin_t,
        }
    )

    df_export = pd.DataFrame(export_rows)

    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="Маршрут")
    excel_bytes = excel_buffer.getvalue()

    csv_data = df_export.to_csv(index=False, encoding="utf-8-sig")
    map_html_str = m.get_root().render()
    gpx_str = generate_gpx(data["route_points"], wpt_for_gpx)

    st.divider()
    st.subheader("📥 Завантаження готового маршруту:")

    exp_col1, exp_col2, exp_col3, exp_col4 = st.columns(4)

    with exp_col1:
        st.download_button(
            label="📊 Excel (.xlsx)",
            data=excel_bytes,
            file_name="optimal_route.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with exp_col2:
        st.download_button(
            label="📄 CSV (.csv)",
            data=csv_data,
            file_name="optimal_route.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with exp_col3:
        st.download_button(
            label="🗺️ HTML Карта (.html)",
            data=map_html_str,
            file_name="route_map.html",
            mime="text/plain",
            use_container_width=True,
        )

    with exp_col4:
        st.download_button(
            label="🛰️ GPS Трек (.gpx)",
            data=gpx_str,
            file_name="optimal_route.gpx",
            mime="text/plain",
            use_container_width=True,
        )

    # Google Maps посилання
    st.divider()
    st.subheader("🔗 Відкрити маршрут у застосунку Google Maps:")

    all_coords = [data["start_coords"]] + data["wp_coords"] + [data["end_coords"]]
    all_labels = [data["start_address"]] + data["wp_addresses"] + [data["end_address"]]

    if len(data["wp_coords"]) <= 8:
        st.link_button(
            "👉 Відкрити весь маршрут у Google Maps",
            build_gmaps_coords_url(data["start_coords"], data["end_coords"], data["wp_coords"]),
            use_container_width=True,
        )
    else:
        for i in range(0, len(all_coords) - 1, 8):
            chunk_coords = all_coords[i : i + 9]
            chunk_labels = all_labels[i : i + 9]
            url = build_gmaps_coords_url(chunk_coords[0], chunk_coords[-1], chunk_coords[1:-1])
            part_num = (i // 8) + 1
            st.link_button(
                f"🧭 Відкрити Частину {part_num} ({chunk_labels[0][:20]}... ➔ {chunk_labels[-1][:20]}...)",
                url,
                use_container_width=True,
            )