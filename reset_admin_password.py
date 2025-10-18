import sqlite3
from werkzeug.security import generate_password_hash
import getpass

# --- DEĞİŞTİRİLECEK BİLGİLER ---
# Lütfen Sadece Bu İki Satırı Güncelleyin
ADMIN_USERNAME = "turanrona"
NEW_PASSWORD = "3383299Qqw" # Buraya Yeni Ve Unutmayacağınız Bir Şifre Yazın

# --- KODUN GERİ KALANINA DOKUNMAYIN ---
DB_FILE = "finans_veritabani.db"

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

try:
    # Yeni şifreyi güvenli bir şekilde hash'liyoruz
    new_password_hash = generate_password_hash(NEW_PASSWORD)

    # Kullanıcının şifresini veritabanında güncelliyoruz
    cur.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_password_hash, ADMIN_USERNAME))
    conn.commit()

    if cur.rowcount > 0:
        print(f"\nBaşarılı: '{ADMIN_USERNAME}' Adlı Kullanıcının Şifresi Başarıyla Güncellendi.")
        print("Artık Yeni Şifrenizle Giriş Yapabilirsiniz.")
    else:
        print(f"\nHata: '{ADMIN_USERNAME}' Adlı Kullanıcı Veritabanında Bulunamadı.")

except Exception as e:
    print(f"\nBir Hata Oluştu: {e}")
finally:
    conn.close()