# Gerekli Kütüphaneleri İçe Aktarıyoruz
import streamlit as st
import sqlite3
import pandas as pd
import datetime
from dateutil.relativedelta import relativedelta
import copy
import os
from werkzeug.security import generate_password_hash, check_password_hash

# --- VERİTABANI İŞLEMLERİ ---
DB_FILE = "finans_veritabani.db"

def init_db():
    """Veritabanını Ve Tabloları Oluşturur."""
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
    """Veritabanından Sadece Belirtilen Kullanıcının Verilerini Yükler."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    st.session_state.incomes = cur.execute("SELECT * FROM incomes WHERE user_id = ?", (user_id,)).fetchall()
    st.session_state.debts = cur.execute("SELECT * FROM debts WHERE user_id = ?", (user_id,)).fetchall()
    st.session_state.fixed_expenses = cur.execute("SELECT * FROM fixed_expenses WHERE user_id = ?", (user_id,)).fetchall()
    st.session_state.savings = cur.execute("SELECT * FROM savings WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()

def save_record(table, data_dict):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    columns = ', '.join(data_dict.keys())
    placeholders = ', '.join(['?'] * len(data_dict))
    cur.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(data_dict.values()))
    conn.commit()
    conn.close()
    load_data(st.session_state.get('viewing_user_id', st.session_state.user_id))

def delete_record(table, record_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    user_id_to_check = st.session_state.get('viewing_user_id', st.session_state.user_id)
    cur.execute(f"DELETE FROM {table} WHERE id = ? AND user_id = ?", (record_id, user_id_to_check))
    conn.commit()
    conn.close()
    load_data(user_id_to_check)

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

def calculate_payoff_plan_detailed(borclar_listesi, ekstra_odeme_gucu, gelirler_listesi, toplam_kredi_limiti):
    sim_borclar = [dict(b) for b in copy.deepcopy(borclar_listesi)]
    sim_gelirler = [dict(g) for g in copy.deepcopy(gelirler_listesi)]
    ay_sayaci, toplam_odenen_faiz = 0, 0.0
    grafik_verisi = {"Ay": [0], "Toplam Borç": [sum(b['balance'] for b in sim_borclar)]}
    tablo_sutunlari = ['Ay', 'Tarih'] + [b['name'] for b in borclar_listesi] + ['Toplam Kalan Borç']
    tablo_verisi = []
    
    while any(b['balance'] > 0 for b in sim_borclar) and ay_sayaci < 600:
        ay_sayaci += 1
        current_date = datetime.date.today() + relativedelta(months=ay_sayaci)
        aylik_gelir_artis = 0
        for gelir in sim_gelirler:
            if gelir['type'] == 'Maaş (Düzenli Ve Zamlı)':
                if (gelir['raises_per_year'] == 1 and (ay_sayaci - 1) % 12 == 0 and ay_sayaci > 1) or \
                   (gelir['raises_per_year'] == 2 and (ay_sayaci - 1) % 6 == 0 and ay_sayaci > 1):
                    artis = gelir['amount'] * (gelir['raise_percentage'] / 100)
                    gelir['amount'] += artis
                    aylik_gelir_artis += artis
        ekstra_odeme_gucu += aylik_gelir_artis
        
        kartopu_etkisi = 0
        for borc in sim_borclar:
            if borc['balance'] > 0:
                is_active_installment = borc['type'] == 'Sabit Taksitli Borç (Okul, Senet Vb.)' and borc['first_payment_date'] and current_date >= datetime.datetime.strptime(borc['first_payment_date'], '%Y-%m-%d').date()
                if borc['type'] != 'Sabit Taksitli Borç (Okul, Senet Vb.)' or is_active_installment:
                    if borc['type'] != 'Sabit Taksitli Borç (Okul, Senet Vb.)':
                        aylik_faiz = borc['balance'] * (borc['interest_rate'] / 100 / 12)
                        borc['balance'] += aylik_faiz
                        toplam_odenen_faiz += aylik_faiz
                        if borc['type'] == 'KMH / Ek Hesap': borc['min_payment'] = aylik_faiz
                        elif borc['type'] == 'Kredi Kartı': borc['min_payment'] = borc['balance'] * (0.40 if toplam_kredi_limiti > 50000 else 0.20)

        odeme_gucu = ekstra_odeme_gucu
        kalan_borclar_sirali = [b for b in borclar_listesi if dict(next((sim_b for sim_b in sim_borclar if sim_b['id'] == b['id']), None))['balance'] > 0]
        hedef_borc = kalan_borclar_sirali[0] if kalan_borclar_sirali else None

        for borc in sim_borclar:
            if borc['balance'] > 0:
                is_active_installment_payment = borc['type'] == 'Sabit Taksitli Borç (Okul, Senet Vb.)' and borc['first_payment_date'] and current_date >= datetime.datetime.strptime(borc['first_payment_date'], '%Y-%m-%d').date() and borc['remaining_installments'] > 0
                if borc['type'] != 'Sabit Taksitli Borç (Okul, Senet Vb.)' or is_active_installment_payment:
                    odenecek_asgari_orjinal = borc['min_payment']
                    if hedef_borc and borc['id'] == hedef_borc['id']:
                        odeme = min(borc['balance'], borc['min_payment'] + odeme_gucu)
                    else:
                        odeme = min(borc['balance'], borc['min_payment'])
                    borc['balance'] -= odeme
                    if borc['type'] == 'Sabit Taksitli Borç (Okul, Senet Vb.)' and borc['balance'] > 0: borc['remaining_installments'] -= 1
                    if borc['balance'] <= 0: kartopu_etkisi += odenecek_asgari_orjinal

        ekstra_odeme_gucu += kartopu_etkisi
        
        toplam_kalan_borc = sum(b['balance'] for b in sim_borclar if b['balance'] > 0)
        grafik_verisi["Ay"].append(ay_sayaci); grafik_verisi["Toplam Borç"].append(toplam_kalan_borc)
        aylik_veri_satiri = [ay_sayaci, current_date.strftime("%B %Y")]
        for b_orj in borclar_listesi:
            ilgili_borc = next((sim_b for sim_b in sim_borclar if sim_b['id'] == b_orj['id']), None)
            if ilgili_borc and ilgili_borc['balance'] > 0: aylik_veri_satiri.append(f"{ilgili_borc['balance']:,.2f} TL")
            else: aylik_veri_satiri.append("✅ BİTTİ")
        aylik_veri_satiri.append(f"{toplam_kalan_borc:,.2f} TL")
        tablo_verisi.append(aylik_veri_satiri)

    if ay_sayaci >= 600: return None
    grafik_df = pd.DataFrame(grafik_verisi).set_index("Ay")
    tablo_df = pd.DataFrame(tablo_verisi, columns=tablo_sutunlari)
    return ay_sayaci, toplam_odenen_faiz, grafik_df, tablo_df

# --- ANA UYGULAMA MANTARI ---
st.set_page_config(page_title="Finans Yönetim Paneli", layout="wide")
st.markdown("""<style> h1, h2, h3 { text-transform: capitalize; } </style>""", unsafe_allow_html=True)

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    if not os.path.exists(DB_FILE): init_db()

if not st.session_state.logged_in:
    st.title("Giriş Yap Veya Kayıt Ol")
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
else:
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
    
    tab_list = ["ℹ️ Başlarken & Yardım", "📊 Genel Durum", "➕ Yeni Kayıt Ekle", "🚀 Strateji Ve Simülasyon"]
    if st.session_state.is_admin: tab_list.append("👑 Admin Paneli")
    tabs = st.tabs(tab_list)

    with tabs[0]:
        st.header("Programa Hoş Geldiniz!")
        st.markdown("""
            Bu Uygulama, Finansal Durumunuzu Kontrol Altına Almanıza, Borçlarınızı Stratejik Olarak Daha Hızlı Bitirmenize Ve Birikim Hedeflerinize Ulaşmanıza Yardımcı Olmak İçin Tasarlanmıştır.
            
            ### Programın Amacı Nedir?
            - **Netlik Kazanmak:** Tüm Gelir, Gider Ve Borçlarınızı Tek Bir Yerde Görerek Finansal Fotoğrafınızı Netleştirin.
            - **Strateji Oluşturmak:** 'Çığ' Ve 'Kartopu' Gibi Kanıtlanmış Yöntemlerle, Borçlarınızı En Verimli Şekilde Nasıl Kapatacağınızı Keşfedin.
            - **Geleceği Planlamak:** Simülasyon Motoru Sayesinde, Seçtiğiniz Planla Borçlarınızın Ne Zaman Biteceğini, Ne Kadar Faizden Tasarruf Edeceğinizi Görün Ve Motive Olun.

            ### Adım Adım Kullanım Kılavuzu
            1.  **Adım: Finansal Verilerinizi Girin (Önemli!)**
                - **`Yeni Kayıt Ekle`** Sekmesine Gidin.
                - **Tüm Gelirlerinizi** Ekleyin. Eğer Maaş Gibi Düzenli Bir Geliriniz Varsa, "Maaş" Seçeneğini İşaretleyip Olası Yıllık Zam Oranlarınızı Girerek Simülasyonu Çok Daha Gerçekçi Hale Getirebilirsiniz.
                - **Tüm Borçlarınızı** Ekleyin. "Kredi Kartı" Eklerken Kart Limitinizi Girmeniz Yeterlidir. "KMH" Veya "Sabit Taksitli Borç" Eklerken İlgili Alanları Doldurun. Program Gerekli Hesaplamaları Otomatik Yapar.
                - **Sabit Giderlerinizi** (Kira, Abonelikler Vb.) Ve Aylık **Birikim Hedeflerinizi** Ekleyin. Birikim İçin Sabit Bir Tutar Veya Kalan Paranın Yüzdesi Şeklinde İki Farklı Strateji Seçebilirsiniz.

            2.  **Adım: Genel Durumunuzu Gözden Geçirin**
                - **`Genel Durum`** Sekmesine Tıklayın. Eklediğiniz Her Kaydın Yanında Bir "Sil" Butonu Bulunur.
                - Eklediğiniz Tüm Bilgilerin Modern Bir Kart Tasarımıyla Özetlendiğini Göreceksiniz. Bu Sizin Mevcut Finansal Fotoğrafınızdır.

            3.  **Adım: Stratejinizi Oluşturun Ve Geleceği Görün**
                - **`Strateji Ve Simülasyon`** Sekmesine Gidin.
                - Program, Girdiğiniz Verilere Göre Elinizde Kalan "Net Fazlayı" Ve Bu Fazlanın Birikim/Borç Ödemesi Arasında Nasıl Dağıtıldığını Gösterir.
                - "Çığ" Veya "Kartopu" Yöntemlerinden Birini Seçin Ve **"Simülasyonu Çalıştır"** Butonuna Basın.
                - **Sonuçları İnceleyin:** Borçlarınızın Ne Zaman Biteceğini, Toplam Ne Kadar Faiz Ödeyeceğinizi, Borcunuzun Zamanla Azalışını Gösteren Grafiği Ve Ay Ay Tüm Detayları İçeren Tabloyu Görerek Geleceğinizi Planlayın!
        """)

    with tabs[1]:
        st.header("Finansal Gösterge Paneli")
        col1, col2 = st.columns(2)
        with col1:
            with st.container(border=True):
                st.subheader("💰 Gelirler")
                if not st.session_state.incomes: st.info("Gelir Eklenmemiş.")
                for income in st.session_state.incomes:
                    st.markdown(f"**{income['name']}:** `{income['amount']:,.2f} TL`")
                    if st.button(f"Sil##gelir{income['id']}", key=f"del_gelir_{income['id']}"): delete_record("incomes", income['id']); st.rerun()
        with col2:
            with st.container(border=True):
                st.subheader("🎯 Birikim Hedefleri")
                if not st.session_state.savings: st.info("Birikim Hedefi Eklenmemiş.")
                for saving in st.session_state.savings:
                    strategy_text = f"Sabit: {saving['monthly_amount']:,.2f} TL" if saving['strategy'] == 'Sabit Tutar' else f"Yüzdesel: %{saving['percentage']}"
                    st.markdown(f"**{saving['name']}:** `{strategy_text}`")
                    if st.button(f"Sil##birikim{saving['id']}", key=f"del_birikim_{saving['id']}"): delete_record("savings", saving['id']); st.rerun()
        
        st.subheader("💳 Toplam Borç Durumu")
        if not st.session_state.debts: st.info("Borç Eklenmemiş.")
        else:
            toplam_borc = sum(d['balance'] for d in st.session_state.debts)
            toplam_kredi_karti_limiti = sum(d['card_limit'] for d in st.session_state.debts if d['type'] == 'Kredi Kartı')
            c1, c2 = st.columns(2)
            c1.metric("Toplam Borç Bakiyesi", f"{toplam_borc:,.2f} TL")
            c2.metric("Hesaplanan Toplam Kredi Kartı Limiti", f"{toplam_kredi_karti_limiti:,.2f} TL")

        st.subheader("Borç Detayları")
        for debt in st.session_state.debts:
            with st.container(border=True):
                col_b1, col_b2 = st.columns([4, 1])
                with col_b1:
                    if debt['type'] == 'Sabit Taksitli Borç (Okul, Senet Vb.)':
                        st.markdown(f"**{debt['name']} ({debt['type']}):** `{debt['balance']:,.2f} TL` (Kalan Taksit: *{debt['remaining_installments']}*)")
                    else:
                        st.markdown(f"**{debt['name']} ({debt['type']}):** `{debt['balance']:,.2f} TL` (Faiz: *%{debt['interest_rate']}*)")
                with col_b2:
                    if st.button(f"Sil##borc{debt['id']}", key=f"del_borc_{debt['id']}"): delete_record("debts", debt['id']); st.rerun()
        
        with st.container(border=True):
            st.subheader("🏠 Sabit Giderler")
            if not st.session_state.fixed_expenses: st.info("Sabit Gider Eklenmemiş.")
            for expense in st.session_state.fixed_expenses:
                st.markdown(f"**{expense['name']}:** `{expense['amount']:,.2f} TL`")
                if st.button(f"Sil##gider{expense['id']}", key=f"del_gider_{expense['id']}"): delete_record("fixed_expenses", expense['id']); st.rerun()

    with tabs[2]:
        st.header("Veri Giriş Formları")
        with st.expander("Yeni Gelir Ekle", expanded=True):
            gelir_tipi_secim = st.selectbox("Eklenecek Gelirin Türünü Seçin", ["Maaş (Düzenli Ve Zamlı)", "Diğer Düzenli Gelir (Zamsız)", "Tek Seferlik Gelir"], key="gelir_tur_secimi")
            with st.form(f"gelir_form_{gelir_tipi_secim}", clear_on_submit=True):
                st.write(f"**{gelir_tipi_secim} Bilgilerini Girin**")
                gelir_ad = st.text_input("Gelir Kaynağının Adı (Örn: Maaş)")
                gelir_tutar = st.number_input("Tutar", min_value=0.01, format="%.2f")
                zam_sayisi, zam_orani = 0, 0.0
                if gelir_tipi_secim == "Maaş (Düzenli Ve Zamlı)":
                    zam_sayisi = st.selectbox("Yılda Kaç Kez Zam Bekleniyor?", [0, 1, 2], index=1)
                    zam_orani = st.number_input("Tahmini Yıllık Zam Oranı (%)", min_value=0.0, max_value=200.0, value=40.0, format="%.1f")
                if st.form_submit_button("Geliri Kaydet"):
                    if not gelir_ad or gelir_tutar <= 0: st.warning("Lütfen Tüm Alanları Doldurun.")
                    else:
                        save_record("incomes", {"user_id": user_id_to_view, "name": gelir_ad, "amount": gelir_tutar, "type": gelir_tipi_secim, "raises_per_year": zam_sayisi, "raise_percentage": zam_orani}); st.success(f"'{gelir_ad}' Eklendi!")
        with st.expander("Yeni Borç Ekle"):
            borc_tur_secim = st.selectbox("Eklenecek Borcun Türünü Seçin", ["Kredi Kartı", "Tüketici Kredisi", "Konut Kredisi", "KMH / Ek Hesap", "Sabit Taksitli Borç (Okul, Senet Vb.)", "Diğer"], key="borc_tur_secimi")
            with st.form(f"borc_form_{borc_tur_secim}", clear_on_submit=True):
                st.write(f"**{borc_tur_secim} Bilgilerini Girin**")
                borc_ad = st.text_input("Borcun Adı")
                borc_bakiye, borc_faiz, asgari_odeme, kart_limiti, taksit_sayisi, ilk_odeme, valid = 0.0, 0.0, 0.0, 0.0, 0, None, True
                if borc_tur_secim == "Sabit Taksitli Borç (Okul, Senet Vb.)":
                    asgari_odeme = st.number_input("Aylık Taksit Tutarı", min_value=0.01, format="%.2f"); taksit_sayisi = st.number_input("Kalan Taksit Sayısı", min_value=1, step=1)
                    ilk_odeme = st.date_input("İlk Ödeme Tarihi", value=datetime.date.today() + relativedelta(months=1)); borc_faiz = 0.0
                    if asgari_odeme <= 0 or taksit_sayisi <= 0: valid = False
                else:
                    borc_bakiye = st.number_input("Güncel Bakiye", min_value=0.01, format="%.2f"); borc_faiz = st.number_input("Yıllık Faiz Oranı (%)", min_value=0.01, format="%.2f")
                    if borc_bakiye <= 0 or borc_faiz <= 0: valid = False
                    if borc_tur_secim == "Kredi Kartı": kart_limiti = st.number_input("Kart Limiti", min_value=0.01, help="Bu karta ait bireysel limiti giriniz.")
                    elif borc_tur_secim not in ["KMH / Ek Hesap"]: asgari_odeme = st.number_input("Aylık Asgari Ödeme", min_value=0.01, format="%.2f")
                if st.form_submit_button("Borcu Kaydet"):
                    if not borc_ad or not valid: st.warning("Lütfen Tüm Gerekli Alanları Doldurun.")
                    else:
                        kaydedilecek_bakiye = asgari_odeme * taksit_sayisi if borc_tur_secim == "Sabit Taksitli Borç (Okul, Senet Vb.)" else borc_bakiye
                        save_record("debts", {"user_id": user_id_to_view, "name": borc_ad, "balance": kaydedilecek_bakiye, "interest_rate": borc_faiz, "min_payment": asgari_odeme, "type": borc_tur_secim, "card_limit": kart_limiti, "remaining_installments": taksit_sayisi, "first_payment_date": str(ilk_odeme)}); st.success(f"'{borc_ad}' Eklendi!")
        with st.expander("Yeni Sabit Gider Ekle"):
            with st.form("sabit_gider_formu", clear_on_submit=True):
                gider_ad = st.text_input("Giderin Adı"); gider_tutar = st.number_input("Aylık Tutar", min_value=0.01, format="%.2f")
                if st.form_submit_button("Sabit Gideri Kaydet"):
                    if not gider_ad or gider_tutar <= 0: st.warning("Lütfen Tüm Alanları Doldurun.")
                    else: save_record("fixed_expenses", {"user_id": user_id_to_view, "name": gider_ad, "amount": gider_tutar}); st.success(f"'{gider_ad}' Eklendi!")
        with st.expander("Yeni Birikim Hedefi Ekle"):
            with st.form("birikim_formu", clear_on_submit=True):
                birikim_ad = st.text_input("Birikim Hedefinin Adı")
                birikim_stratejisi = st.selectbox("Birikim Stratejisi", ["Sabit Tutar", "Yüzdesel Paylaşım"])
                birikim_tutar, birikim_yuzde = 0.0, 0.0
                if birikim_stratejisi == "Sabit Tutar": birikim_tutar = st.number_input("Aylık Ayrılacak Sabit Tutar", min_value=0.01, format="%.2f")
                else: birikim_yuzde = st.slider("Kalan Paranın Yüzde Kaçı Birikime Aktarılsın?", 0, 100, 90)
                if st.form_submit_button("Birikim Hedefini Kaydet"):
                    if not birikim_ad: st.warning("Lütfen Birikim Hedefine Bir Ad Verin.")
                    else: save_record("savings", {"user_id": user_id_to_view, "name": birikim_ad, "monthly_amount": birikim_tutar, "strategy": birikim_stratejisi, "percentage": birikim_yuzde}); st.success(f"'{birikim_ad}' Hedefi Eklendi!")

    with tabs[3]:
        st.header("Strateji Geliştirme Ve Simülasyon")
        if not st.session_state.incomes or not st.session_state.debts: st.warning("Simülasyonu Çalıştırmak İçin En Az Bir Gelir Ve Bir Borç Eklemelisiniz.")
        else:
            toplam_kredi_limiti = sum(b['card_limit'] for b in st.session_state.debts if b['type'] == 'Kredi Kartı')
            toplam_gelir = sum(g['amount'] for g in st.session_state.incomes if g['type'] != 'Tek Seferlik Gelir') + sum(g['amount'] for g in st.session_state.incomes if g['type'] == 'Tek Seferlik Gelir')
            toplam_sabit_giderler = sum(g['amount'] for g in st.session_state.fixed_expenses)
            borc_asgari_odemeleri = 0
            for borc in st.session_state.debts:
                if borc['type'] == 'Kredi Kartı': borc_asgari_odemeleri += borc['balance'] * (0.40 if toplam_kredi_limiti > 50000 else 0.20)
                elif borc['type'] == 'KMH / Ek Hesap': borc_asgari_odemeleri += borc['balance'] * (borc['interest_rate'] / 100 / 12)
                else: borc_asgari_odemeleri += borc['min_payment']
            toplam_zorunlu_cikis = borc_asgari_odemeleri + toplam_sabit_giderler
            net_kullanilabilir_fazla = toplam_gelir - toplam_zorunlu_cikis
            aylik_birikim_payi, borclar_icin_ekstra_guc = 0, 0
            saving_goal = st.session_state.savings[0] if st.session_state.savings else None
            if saving_goal:
                if saving_goal['strategy'] == 'Sabit Tutar': aylik_birikim_payi = saving_goal['monthly_amount']
                else:
                    if net_kullanilabilir_fazla > 0: aylik_birikim_payi = net_kullanilabilir_fazla * (saving_goal['percentage'] / 100)
            borclar_icin_ekstra_guc = net_kullanilabilir_fazla - aylik_birikim_payi
            
            st.subheader("Nakit Akışı Analizi")
            col1, col2, col3 = st.columns(3); col1.metric("✅ Toplam Aylık Gelir", f"{toplam_gelir:,.2f} TL"); col2.metric("❌ Zorunlu Giderler", f"{toplam_zorunlu_cikis:,.2f} TL"); col3.metric("💰 Net Kullanılabilir Fazla", f"{net_kullanilabilir_fazla:,.2f} TL")
            if saving_goal:
                st.success(f"Bu Fazla Tutarın Dağılımı ({saving_goal['strategy']}):")
                col_s1, col_s2 = st.columns(2); col_s1.metric("🎯 Birikime Aktarılacak", f"{aylik_birikim_payi:,.2f} TL"); col_s2.metric("⚡️ Borç Ödemesine Aktarılacak (Ekstra Güç)", f"{borclar_icin_ekstra_guc:,.2f} TL")
            st.divider()
            if borclar_icin_ekstra_guc > 0:
                st.subheader("Borç Ödeme Stratejisi Ve Simülasyon")
                secilen_strateji = st.radio("Stratejinizi Seçin:", ("Çığ Yöntemi (En Hızlı Ve En Tasarruflu)", "Kartopu Yöntemi (En Motive Edici)"))
                if st.button("📈 Simülasyonu Çalıştır Ve Ödeme Planını Gör"):
                    if secilen_strateji.startswith("Çığ"): sirali_borclar = sorted(st.session_state.debts, key=lambda b: b['interest_rate'], reverse=True)
                    else: sirali_borclar = sorted(st.session_state.debts, key=lambda b: b['balance'])
                    sonuc = calculate_payoff_plan_detailed(sirali_borclar, borclar_icin_ekstra_guc, st.session_state.incomes, toplam_kredi_limiti)
                    if sonuc is None: st.error("Plan 50 Yıldan Uzun Sürüyor. Lütfen Verilerinizi Gözden Geçirin.")
                    else:
                        ay_sayaci, toplam_faiz, grafik_df, tablo_df = sonuc
                        toplam_yil, kalan_ay = divmod(ay_sayaci, 12)
                        st.success(f"Tebrikler! Bu Plana Sadık Kalırsanız, Tüm Borçlarınız **{toplam_yil} Yıl {kalan_ay} Ay** Sonra Bitecek.")
                        st.metric("Bu Süreçte Ödeyeceğiniz Toplam Faiz", f"{toplam_faiz:,.2f} TL")
                        st.subheader("Toplam Borcun Zamanla Azalması"); st.line_chart(grafik_df)
                        st.subheader("Ay Ay Detaylı Ödeme Tablosu"); st.dataframe(tablo_df, use_container_width=True, hide_index=True)
            else:
                st.error(f"Bütçenizde **{borclar_icin_ekstra_guc:,.2f} TL** Açık Var Veya Borçları Hızlandırmak İçin Ekstra Gücünüz Kalmadı. Simülasyon Çalıştırılamıyor.")

    if st.session_state.is_admin and len(tabs) > 4:
        with tabs[4]:
            st.header("Admin Kontrol Paneli")
            all_users = get_all_users()
            st.subheader("Tüm Kullanıcılar")
            for user in all_users:
                col1, col2 = st.columns([3,1])
                col1.write(f"Kullanıcı: **{user['username']}** (ID: {user['id']})")
                if col2.button("Verileri Görüntüle", key=f"view_user_{user['id']}"):
                    st.session_state.viewing_user_id = user['id']
                    st.rerun()
