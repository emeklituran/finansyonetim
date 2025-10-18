import sqlite3

# BURAYA ADMİN YAPMAK İSTEDİĞİNİZ KULLANICI ADINI YAZIN
ADMIN_USERNAME = "turanrona"

conn = sqlite3.connect("finans_veritabani.db")
cur = conn.cursor()
try:
    cur.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (ADMIN_USERNAME,))
    conn.commit()
    if cur.rowcount > 0:
        print(f"Başarılı: '{ADMIN_USERNAME}' Adlı Kullanıcı Artık Bir Admin.")
    else:
        print(f"Hata: '{ADMIN_USERNAME}' Adlı Kullanıcı Bulunamadı. Lütfen Önce Kayıt Olduğunuzdan Emin Olun.")
except Exception as e:
    print(f"Bir Hata Oluştu: {e}")
finally:
    conn.close()
