# Gerekli Kütüphaneleri İçe Aktarıyoruz
import streamlit as st
import sqlite3
import pandas as pd
import datetime
from dateutil.relativedelta import relativedelta
import copy
import os
from werkzeug.security import generate_password_hash, check_password_hash
import io
import numpy as np

# --- VERİTABANI TANIMI ---
DB_FILE = "finans_veritabani.db"

# --- VERİTABANI İŞLEMLERİ (Sadece Üye Modu için) ---

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, is_admin INTEGER DEFAULT 0)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT, amount REAL, type TEXT,
            raises_per_year INTEGER, raise_percentage REAL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT, balance REAL,
            interest_rate REAL, min_payment REAL, type TEXT,
            card_limit REAL DEFAULT 0, remaining_installments INTEGER DEFAULT 0, first_payment_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS fixed_expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT, amount REAL, FOREIGN KEY (user_id) REFERENCES users (id))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS savings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT, monthly_amount REAL, 
            strategy TEXT, percentage REAL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()

def load_data(user_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    st.session_state.incomes = [dict(row) for row in cur.execute("SELECT * FROM incomes WHERE user_id = ?", (user_id,)).fetchall()]
    st.session_state.debts = [dict(row) for row in cur.execute("SELECT * FROM debts WHERE user_id = ?", (user_id,)).fetchall()]
    st.session_state.fixed_expenses = [dict(row) for row in cur.execute("SELECT * FROM fixed_expenses WHERE user_id = ?", (user_id,)).fetchall()]
    st.session_state.savings = [dict(row) for row in cur.execute("SELECT * FROM savings WHERE user_id = ?", (user_id,)).fetchall()]
    conn.close()

def save_record(table, data_dict):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    columns = ', '.join(data_dict.keys())
    placeholders = ', '.join(['?'] * len(data_dict))
    cur.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(data_dict.values()))
    conn.commit()
    conn.close()

def delete_record(table, record_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    user_id_to_check = st.session_state.get('viewing_user_id', st.session_state.user_id)
    cur.execute(f"DELETE FROM {table} WHERE id = ? AND user_id = ?", (record_id, user_id_to_check))
    conn.commit()
    conn.close()

def add_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)", (username, generate_password_hash(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError: return False
    finally: conn.close()

def check_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    user = cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password): return user['id'], bool(user['is_admin'])
    return None, False

def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    users = cur.execute("SELECT id, username FROM users").fetchall()
    conn.close()
    return users

# --- MİSAFİR MODU FONKSİYONLARI ---
def guest_save_record(category, data_dict):
    """Misafir modunda verileri session_state'e kaydeder."""
    st.session_state.guest_id_counter += 1
    data_dict['id'] = st.session_state.guest_id_counter
    st.session_state[category].append(data_dict)

def guest_delete_record(category, record_id):
    """Misafir modunda verileri session_state'ten siler."""
    st.session_state[category] = [item for item in st.session_state[category] if item['id'] != record_id]


# --- HESAPLAMA VE GÖRSELLEŞTİRME FONKSİYONLARI ---

def format_df_for_display(df):
    """Görüntüleme için DataFrame'i formatlar."""
    display_df = df.copy()
    for col in display_df.columns:
        if '(Kalan)' in col:
            display_df[col] = display_df[col].apply(lambda x: "🟢 TAMAMLANDI" if x == "✅ BİTTİ" else (f"{x:,.0f} TL" if isinstance(x, (int, float, np.number)) and x > 0 else ("-" if x == 0 else x)))
        elif any(keyword in col for keyword in ['(Gelir)', '(Gider)', 'Ek Ödeme Gücü', 'Toplam Birikim']):
            display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f} TL" if isinstance(x, (int, float, np.number)) and x > 0 else "-")
    return display_df


def calculate_payoff_plan_detailed(borclar_listesi, ekstra_odeme_gucu, gelirler_listesi, sabit_giderler_listesi, aylik_birikim_payi, toplam_kredi_limiti, birikim_faiz_orani):
    sim_borclar = copy.deepcopy(borclar_listesi)
    sim_gelirler = copy.deepcopy(gelirler_listesi)
    ay_sayaci, toplam_odenen_faiz, toplam_birikim = 0, 0.0, 0.0
    
    tablo_verisi = []
    
    while any(b['balance'] > 0 for b in sim_borclar) and ay_sayaci < 600:
        ay_sayaci += 1
        current_date = datetime.date.today() + relativedelta(months=ay_sayaci)
        
        # 1. Gelirlerin Hesaplanması
        aylik_gelir_artis, toplam_aylik_gelir = 0, 0
        aylik_gelir_kalemleri = {}
        for gelir in sim_gelirler:
            gelir_tutari = gelir['amount']
            if gelir['type'] == 'Maaş (Düzenli Ve Zamlı)':
                if (gelir['raises_per_year'] == 1 and (ay_sayaci - 1) % 12 == 0 and ay_sayaci > 1) or \
                   (gelir['raises_per_year'] == 2 and (ay_sayaci - 1) % 6 == 0 and ay_sayaci > 1):
                    artis = gelir['amount'] * (gelir['raise_percentage'] / 100)
                    gelir['amount'] += artis
                    aylik_gelir_artis += artis
                    gelir_tutari = gelir['amount']
            
            aylik_gelir_kalemleri[f"{gelir['name']} (Gelir)"] = gelir_tutari
            toplam_aylik_gelir += gelir_tutari

        ekstra_odeme_gucu += aylik_gelir_artis
        
        # 2. Faizlerin Hesaplanması ve Kümülatif Borçların Güncellenmesi
        kartopu_etkisi = 0
        for borc in sim_borclar:
            if borc['balance'] > 0:
                if borc['type'] in ['KMH / Ek Hesap', 'Diğer']:
                    aylik_faiz = borc['balance'] * (borc['interest_rate'] / 100)
                    borc['balance'] += aylik_faiz
                    toplam_odenen_faiz += aylik_faiz
                if borc['type'] == 'Kredi Kartı': 
                    borc['min_payment'] = borc['balance'] * (0.40 if toplam_kredi_limiti > 50000 else 0.20)
        
        # 3. Ödemelerin Yapılması
        odeme_gucu = ekstra_odeme_gucu
        kalan_borclar_sirali = [b for b in borclar_listesi if dict(next((sim_b for sim_b in sim_borclar if sim_b['id'] == b['id']), None))['balance'] > 0]
        hedef_borc = kalan_borclar_sirali[0] if kalan_borclar_sirali else None

        for borc in sim_borclar:
            if borc['balance'] > 0:
                odenecek_asgari_orjinal = borc['min_payment']
                if hedef_borc and borc['id'] == hedef_borc['id']:
                    odeme = min(borc['balance'], borc['min_payment'] + odeme_gucu)
                else:
                    odeme = min(borc['balance'], borc['min_payment'])
                
                borc['balance'] -= odeme
                
                if borc['type'] == 'Sabit Taksitli Borç (Okul, Senet Vb.)' and borc['balance'] > 0: 
                    borc['remaining_installments'] -= 1
                if borc['balance'] <= 0: 
                    kartopu_etkisi += odenecek_asgari_orjinal

        ekstra_odeme_gucu += kartopu_etkisi
        
        # 4. Birikimin Hesaplanması (Bileşik Faizli)
        toplam_birikim = (toplam_birikim + aylik_birikim_payi) * (1 + (birikim_faiz_orani / 100))

        # 5. Aylık Rapor Satırının Oluşturulması
        aylik_veri_satiri = {'Ay': ay_sayaci, 'Tarih': current_date.strftime("%B %Y")}
        aylik_veri_satiri.update(aylik_gelir_kalemleri)
        
        for gider in sabit_giderler_listesi:
            aylik_veri_satiri[f"{gider['name']} (Gider)"] = gider['amount']

        for b_orj in borclar_listesi:
            ilgili_borc = next((sim_b for sim_b in sim_borclar if sim_b['id'] == b_orj['id']), None)
            if ilgili_borc and ilgili_borc['balance'] > 0:
                aylik_veri_satiri[f"{b_orj['name']} (Kalan)"] = ilgili_borc['balance']
            else:
                aylik_veri_satiri[f"{b_orj['name']} (Kalan)"] = "✅ BİTTİ"
        
        aylik_veri_satiri['Ek Ödeme Gücü'] = ekstra_odeme_gucu
        aylik_veri_satiri['Toplam Birikim'] = toplam_birikim
        
        tablo_verisi.append(aylik_veri_satiri)

    if ay_sayaci >= 600: return None
    
    tablo_df = pd.DataFrame(tablo_verisi).fillna(0)
    return ay_sayaci, toplam_odenen_faiz, tablo_df

# --- ANA UYGULAMA ---
st.set_page_config(page_title="Finans Yönetim Paneli", layout="wide")
st.markdown("""<style> h1, h2, h3 { text-transform: capitalize; } </style>""", unsafe_allow_html=True)

# --- MOD KONTROLÜ ---
if 'mode' not in st.session_state:
    st.session_state.mode = None

# 1. Başlangıç Ekranı
if st.session_state.mode is None:
    st.title("Finansal Özgürlük Planlayıcısına Hoş Geldiniz")
    st.markdown("### Lütfen bir başlangıç ​​seçeneği seçin:")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Misafir Olarak Hızlı Planlama Yap", use_container_width=True, type="primary"):
            st.session_state.mode = 'guest'
            st.session_state.incomes = []
            st.session_state.debts = []
            st.session_state.fixed_expenses = []
            st.session_state.savings = []
            st.session_state.guest_id_counter = 0
            st.rerun()
    with col2:
        if st.button("🔐 Giriş Yap / Kayıt Ol (Verileri Kaydet)", use_container_width=True):
            st.session_state.mode = 'user'
            st.rerun()

# 2. Ana Uygulama Mantığı (Misafir ve Üye Modları)
else:
    is_guest = st.session_state.mode == 'guest'
    
    if is_guest:
        st.warning("Şu anda Misafir Modundasınız. Girdiğiniz veriler bu oturum kapatıldığında silinecektir.")
        if st.button("↩️ Ana Menüye Dön"):
            del st.session_state['mode']
            st.rerun()
        st.title("💸 Misafir Finans Planlama Paneli")
        
        tab_list = ["📊 Genel Durum", "➕ Yeni Kayıt Ekle", "🚀 Strateji Ve Ödeme Planı"]
    else: # Üye Modu
        if 'logged_in' not in st.session_state:
            st.session_state.logged_in = False
            if not os.path.exists(DB_FILE): init_db()

        if not st.session_state.logged_in:
            st.title("Giriş Yap Veya Kayıt Ol")
            if st.button("↩️ Ana Menüye Dön"):
                del st.session_state['mode']
                st.rerun()
            login_tab, register_tab = st.tabs(["Giriş Yap", "Kayıt Ol"])
            with login_tab:
                with st.form("login_form"):
                    username = st.text_input("Kullanıcı Adı")
                    password = st.text_input("Şifre", type="password")
                    if st.form_submit_button("Giriş Yap"):
                        if not username or not password: st.error("Lütfen Tüm Alanları Doldurun.")
                        else:
                            user_id, is_admin = check_user(username, password)
                            if user_id:
                                st.session_state.logged_in, st.session_state.username, st.session_state.user_id, st.session_state.is_admin = True, username, user_id, is_admin
                                load_data(user_id)
                                st.success("Giriş Başarılı!"); st.rerun()
                            else: st.error("Kullanıcı Adı Veya Şifre Hatalı.")
            with register_tab:
                with st.form("register_form"):
                    new_username = st.text_input("Yeni Kullanıcı Adı")
                    new_password = st.text_input("Yeni Şifre", type="password")
                    if st.form_submit_button("Kayıt Ol"):
                        if not new_username or not new_password: st.error("Lütfen Tüm Alanları Doldurun.")
                        elif add_user(new_username, new_password): st.success("Hesap Başarıyla Oluşturuldu! Şimdi 'Giriş Yap' Sekmesinden Giriş Yapabilirsiniz.")
                        else: st.error("Bu Kullanıcı Adı Zaten Alınmış.")
            st.stop() # Giriş yapılmadıysa devam etme
        
        user_id_to_view = st.session_state.get('viewing_user_id', st.session_state.user_id)
        if 'data_loaded_for' not in st.session_state or st.session_state.data_loaded_for != user_id_to_view:
            load_data(user_id_to_view)
            st.session_state.data_loaded_for = user_id_to_view
        
        viewing_username = st.session_state.username
        if st.session_state.get('viewing_user_id'):
            all_users_dict = {u['id']: u['username'] for u in get_all_users()}
            viewing_username = all_users_dict.get(st.session_state.viewing_user_id, "Bilinmeyen")

        st.sidebar.header(f"Hoş Geldin, {st.session_state.username.capitalize()}!")
        if st.session_state.get('viewing_user_id'):
            st.sidebar.warning(f"Şu An '{viewing_username.capitalize()}' Adlı Kullanıcının Hesabını Görüntülüyorsunuz.")
            if st.sidebar.button("Kendi Hesabıma Dön"):
                del st.session_state['viewing_user_id']
                st.rerun()
        if st.sidebar.button("Çıkış Yap"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()

        st.title(f"💸 {viewing_username.capitalize()}'in Finans Ve Borç Yönetim Asistanı")
        
        tab_list = ["ℹ️ Başlarken & Yardım", "📊 Genel Durum", "➕ Yeni Kayıt Ekle", "🚀 Strateji Ve Ödeme Planı"]
        if st.session_state.is_admin: tab_list.append("👑 Admin Paneli")
    
    # --- ORTAK ARAYÜZ (Tüm modlar için) ---
    tabs = st.tabs(tab_list)

    with tabs[0]:
        st.header("Programa Hoş Geldiniz!")
        # ... (Yardım metni)
        
    with tabs[1]:
        st.header("Finansal Gösterge Paneli")
        # ... (Genel Durum - Üye ve Misafir için uyarlanmış)
        
    with tabs[2]:
        st.header("Veri Giriş Formları")
        # ... (Yeni Kayıt Ekle - Üye ve Misafir için uyarlanmış)
        
    with tabs[3]:
        st.header("Strateji Geliştirme Ve Ödeme Planı")
        # ... (Strateji ve Ödeme Planı - Üye ve Misafir için uyarlanmış)
    
    if not is_guest and st.session_state.is_admin and len(tabs) > 4:
        with tabs[4]:
            st.header("Admin Kontrol Paneli")
            # ... (Admin Paneli)

    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; font-size: small; color: gray;'>
        Bu gelişmiş finansal planlama aracı, **Turan Emekli** tarafından bireysel finansal stratejileri güçlendirmek amacıyla titizlikle hazırlanmıştır.
    </div>
    """, unsafe_allow_html=True)
