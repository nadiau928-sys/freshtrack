
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

DB_PATH = Path(os.environ.get("FRESHTRACK_DB", "freshtrack.db"))
TZ = ZoneInfo(os.environ.get("FRESHTRACK_TZ", "Asia/Jakarta"))
SOON_DAYS = 3

UNITS = ["buah", "butir", "pcs", "gram", "kg", "ml", "liter", "papan", "ikat", "kemasan"]
CATEGORIES = [
    "Sayur", "Buah", "Daging/Protein", "Susu dan olahan",
    "Bahan pokok", "Makanan siap saji", "Lainnya",
]
SORT_OPTIONS = {
    "Tanggal terdekat": ("expiry_date", True),
    "Tanggal terjauh": ("expiry_date", False),
    "Nama A-Z": ("name", True),
    "Terbaru ditambahkan": ("added_at", False),
}

st.set_page_config(
    page_title="FreshTrack | Pemantau Persediaan Makanan",
    page_icon="🥬",
    layout="wide",
)


def today() -> date:
    """Tanggal hari ini menurut zona waktu pengguna (bukan UTC server Colab)."""
    return datetime.now(TZ).date()



@st.cache_resource
def get_connection():
    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            quantity REAL NOT NULL,
            unit TEXT NOT NULL,
            category TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            added_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn




def add_food(name, quantity, unit, category, expiry):
    connection = get_connection()
    connection.execute(
        """
        INSERT INTO foods (
            name, quantity, unit, category, expiry_date, added_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            quantity,
            unit,
            category,
            expiry.isoformat(),
            datetime.now(TZ).isoformat(timespec="seconds"),
        ),
    )
    connection.commit()



def update_quantity(selected_id, new_qty):
    connection = get_connection()
    connection.execute(
        "UPDATE foods SET quantity = ? WHERE id = ?",
        (new_qty, selected_id),
    )
    connection.commit()



def delete_food(food_id):
    conn.execute("DELETE FROM foods WHERE id = ?", (int(food_id),))
    conn.commit()


def get_status(days: int) -> str:
    if days < 0:
        return "Lewat tanggal"
    if days == 0:
        return "Batas hari ini"
    if days <= SOON_DAYS:
        return "Segera gunakan"
    return "Masih beberapa hari"



def load_foods():
    connection = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM foods",
        connection
    )

    if df.empty:
        df["sisa_hari"] = pd.Series(dtype="int64")
        return df

    df["expiry_date"] = pd.to_datetime(
        df["expiry_date"], errors="coerce"
    ).dt.date

    current_date = today()

    df["sisa_hari"] = df["expiry_date"].apply(
        lambda expiry: (expiry - current_date).days
        if pd.notna(expiry) else None
    )

    return df


def flash(message: str):
    st.session_state["flash"] = message


def style_row(row):
    colors = {
        "Lewat tanggal": "background-color: #fde2e2; color: #7a1010",
        "Batas hari ini": "background-color: #ffe8cc; color: #7a3d00",
        "Segera gunakan": "background-color: #fff6cc; color: #5c4a00",
        "Masih beberapa hari": "background-color: #e3f6e3; color: #14501a",
    }
    return [colors.get(row["Status"], "")] * len(row)


# ----------------------------------------------------------------- Header
st.title("🥬 FreshTrack")
st.subheader("Pantau Persediaan, Hindari Pemborosan")
st.write(
    "Catat bahan makanan, periksa tanggal yang dimasukkan, dan prioritaskan "
    "bahan yang perlu segera digunakan."
)
st.warning(
    "Status dihitung hanya dari tanggal yang Anda masukkan. Ini bukan jaminan "
    "keamanan pangan; perhatikan petunjuk penyimpanan, kondisi kemasan, dan "
    "kondisi bahan makanan."
)

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon="✅")

# ---------------------------------------------------------------- Sidebar
with st.sidebar:
    st.header("Tambah persediaan")
    with st.form("food_form", clear_on_submit=True):
        name = st.text_input("Nama bahan", placeholder="Contoh: susu UHT")
        quantity = st.number_input("Jumlah", min_value=0.01, value=1.0, step=1.0)
        unit = st.selectbox("Satuan", UNITS)
        category = st.selectbox("Kategori", CATEGORIES)
        expiry = st.date_input(
            "Tanggal kedaluwarsa / batas penggunaan", value=today()
        )
        submitted = st.form_submit_button("Simpan bahan")
        if submitted:
            if not name.strip():
                st.error("Nama bahan harus diisi.")
            else:
                add_food(name, quantity, unit, category, expiry)
                flash(f"{name.strip()} berhasil ditambahkan.")
                st.rerun()
    st.caption(f"Tanggal hari ini: {today().strftime('%d-%m-%Y')}")

# ------------------------------------------------------------------- Main
df = load_foods()

if df.empty:
    st.info("Belum ada data persediaan. Tambahkan bahan melalui formulir di sidebar.")
else:
    total = len(df)
    soon = int(df["sisa_hari"].between(0, SOON_DAYS).sum())
    overdue = int((df["sisa_hari"] < 0).sum())
    later = int((df["sisa_hari"] > SOON_DAYS).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Jenis bahan", total)
    c2.metric(f"Segera digunakan (0-{SOON_DAYS} hari)", soon)
    c3.metric("Lewat tanggal", overdue)
    c4.metric(f"Lebih dari {SOON_DAYS} hari", later)

    if overdue:
        names = ", ".join(df.loc[df["sisa_hari"] < 0, "name"].tolist())
        st.error(f"Sudah lewat tanggal yang dicatat: {names}. Periksa kondisinya.")

   
    # ---- Daftar persediaan
    st.markdown("### Daftar persediaan")

    # Pastikan kolom perhitungan tersedia
    df = df.copy()

    if "sisa_hari" not in df.columns:
        df["expiry_date"] = pd.to_datetime(
            df["expiry_date"], errors="coerce"
        ).dt.date

        tanggal_hari_ini = today()

        df["sisa_hari"] = df["expiry_date"].apply(
            lambda tanggal: (tanggal - tanggal_hari_ini).days
            if pd.notna(tanggal) else None
        )

    # Buat status berdasarkan sisa hari
    if "status" not in df.columns:
        def tentukan_status(hari):
            if pd.isna(hari):
                return "Tanggal tidak valid"
            elif hari < 0:
                return "Lewat tanggal"
            elif hari == 0:
                return "Batas hari ini"
            elif hari <= SOON_DAYS:
                return "Segera gunakan"
            else:
                return "Masih beberapa hari"

        df["status"] = df["sisa_hari"].apply(tentukan_status)

    # Filter dan pencarian
    f1, f2, f3 = st.columns([2, 1, 2])

    query = f1.text_input("Cari berdasarkan nama atau kategori")
    sort_label = f2.selectbox("Urutkan", list(SORT_OPTIONS))
    status_filter = f3.multiselect(
        "Filter status",
        [
            "Lewat tanggal",
            "Batas hari ini",
            "Segera gunakan",
            "Masih beberapa hari",
        ],
    )

    filtered = df.copy()

    if query.strip():
        q = query.strip()
        mask = (
            filtered["name"].str.contains(
                q, case=False, na=False, regex=False
            )
            | filtered["category"].str.contains(
                q, case=False, na=False, regex=False
            )
        )
        filtered = filtered[mask]

    if status_filter:
        filtered = filtered[filtered["status"].isin(status_filter)]

    sort_col, ascending = SORT_OPTIONS[sort_label]
    filtered = filtered.sort_values(
        sort_col, ascending=ascending, kind="stable"
    )

    if filtered.empty:
        st.info("Tidak ada data yang cocok dengan pencarian/filter.")
    else:
        view = filtered[
            [
                "id", "name", "quantity", "unit", "category",
                "expiry_date", "sisa_hari", "status",
            ]
        ].copy()

        view.columns = [
            "ID", "Nama bahan", "Jumlah", "Satuan", "Kategori",
            "Tanggal", "Sisa hari", "Status",
        ]

        st.dataframe(
            view.style.apply(style_row, axis=1).format({"Jumlah": "{:g}"}),
            hide_index=True,
        )

    # ---- Prioritas
    st.markdown("### Prioritas penggunaan")
    priorities = df[df["sisa_hari"] >= 0].sort_values(["sisa_hari", "name"])
    if priorities.empty:
        st.write("Tidak ada bahan dengan tanggal hari ini atau setelahnya.")
    else:
        for _, row in priorities.head(5).iterrows():
            days = int(row["sisa_hari"])
            if days == 0:
                note = "Tanggal yang dicatat adalah hari ini; periksa kondisi bahan."
            elif days <= SOON_DAYS:
                note = f"Prioritas diperiksa/digunakan dalam {days} hari."
            else:
                note = f"Sisa {days} hari menurut tanggal yang dicatat."
            st.write(f"**{row['name']}**: {row['quantity']:g} {row['unit']} · {note}")

    # ---- Grafik
    st.markdown("### Jumlah jenis bahan per kategori")
    chart = df.groupby("category").size().sort_values(ascending=False)
    st.bar_chart(chart)
    st.caption(
        "Grafik menghitung banyaknya jenis bahan per kategori, karena satuan "
        "yang berbeda (kg, butir, liter) tidak bisa dijumlahkan."
    )

    # ---- Kelola data
    st.markdown("### Kelola data")
    id_to_label = {
        int(r["id"]): f"{int(r['id'])} - {r['name']} ({r['quantity']:g} {r['unit']})"
        for _, r in df.iterrows()
    }
    ids = list(id_to_label)
    selected_id = st.selectbox(
        "Pilih bahan", ids, format_func=lambda x: id_to_label[x]
    )
    current_qty = float(df.loc[df["id"] == selected_id, "quantity"].iloc[0])

    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Perbarui jumlah** (misalnya setelah sebagian dipakai)")
        new_qty = st.number_input(
            "Jumlah baru", min_value=0.01, value=current_qty, step=1.0,
            key=f"qty_{selected_id}",
        )
        if st.button("Simpan jumlah"):
            update_quantity(selected_id, new_qty)
            flash("Jumlah diperbarui.")
            st.rerun()
    with e2:
        st.markdown("**Hapus bahan** (habis dipakai atau salah input)")
        confirm = st.checkbox("Saya yakin ingin menghapus bahan ini")
        if st.button("Hapus bahan terpilih", disabled=not confirm):
            delete_food(selected_id)
            flash("Data dihapus.")
            st.rerun()

st.caption(
    "FreshTrack adalah prototipe edukasi. Jika tidak memakai Google Drive, data "
    "tersimpan di runtime Colab dan hilang ketika runtime direset."
)
