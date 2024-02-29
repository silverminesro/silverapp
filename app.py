from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
import sqlite3
from refresh_data import refresh_data  # Importujeme funkciu refresh_data z refresh_data.py
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, SelectField
from wtforms.validators import DataRequired
from zipfile import ZipFile
from datetime import datetime
import psycopg2
import atexit
import shutil
import os
import random
import string
import hashlib

app = Flask(__name__)
app.secret_key = 'tajny_klic'

# Funkcia pre hashovanie čísla v URL
def hash_record_id(value):
    if isinstance(value, int):
        # Hashovanie čísla
        hashed_value = hashlib.sha256(str(value).encode()).hexdigest()
        return hashed_value
    else:
        return value

# URL value preprocessor
@app.url_value_preprocessor
def preprocess_record_id(endpoint, values):
    if 'record_id' in values:
        values['record_id'] = hash_record_id(values['record_id'])

# Funkcia pre generovanie náhodného čísla čísla dokladu
def generate_document_number():
    min_length = 10
    digits = ''.join(random.choices(string.digits, k=min_length))
    return digits

class ArchiveForm(FlaskForm):
    date = DateField('Dátum', format='%Y-%m-%d', validators=[DataRequired()])
    document_number = StringField('Číslo dokladu', validators=[DataRequired()])
    delivering = SelectField('Odovzdávajúci', validators=[DataRequired()], choices=[])
    carrier = StringField('Prepravca', validators=[DataRequired()])
    receiver = StringField('Preberajúci', validators=[DataRequired()])
    material = StringField('Materiál', validators=[DataRequired()])
    waste_name = StringField('Názov odpadu', validators=[DataRequired()])
    carrier_name = StringField('Meno prepravcu', validators=[DataRequired()])
    ecv = StringField('ECV', validators=[DataRequired()])
    quantity = StringField('Množstvo v KG', validators=[DataRequired()])
    poznamka = StringField('Poznamka', validators=[DataRequired()])  # Opravená syntax



# Funkce pro vytvoření tabulky users
def create_table():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, firma TEXT, personal_page TEXT)''')
    conn.commit()
    conn.close()

# Funkce pro vytvoření tabulky businesses
def create_business_table():
    conn = sqlite3.connect('businesses.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS businesses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, address TEXT, ico TEXT)''')
    conn.commit()
    conn.close()

# Funkce pro vytvoření tabulky archive
def create_archive_table():
    conn = sqlite3.connect('archiv.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS archive
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, document_number TEXT, delivering TEXT, carrier TEXT, receiver TEXT, material TEXT, waste_name TEXT, carrier_name TEXT, ecv TEXT, quantity REAL, poznamka TEXT)''')  # Pridaný stĺpec pre množstvo v KG a stĺpec Poznamka
    conn.commit()
    conn.close()

# Funkcia pre vytvorenie tabuľky logs
def create_logs_table():
    conn = sqlite3.connect('logs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, timestamp TEXT, FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    conn.close()

create_table()
create_business_table()
create_archive_table()
create_logs_table()

# Presmerovanie na login.html po spustení aplikácie
@app.route('/')
def index():
    return redirect(url_for('login'))

# Ruta pre registráciu užívateľov
@app.route('/register', methods=['POST', 'GET'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        firma = request.form['firma']  # Získání hodnoty firmy z formuláře

        if not username or not password or not firma:
            return "Vyplňte prosím uživatelské jméno, heslo a firmu."

        conn = sqlite3.connect('users.db')
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        if c.fetchone():
            return "Uživatelské jméno již existuje. Vyberte prosím jiné."

        c.execute("INSERT INTO users (username, password, firma) VALUES (?, ?, ?)", (username, password, firma))  # Přidání firmy do databáze
        conn.commit()
        
        # Přidání osobní cesty pro každého uživatele
        personal_page = f"/user/{c.lastrowid}"
        c.execute("UPDATE users SET personal_page = ? WHERE id = ?", (personal_page, c.lastrowid))
        conn.commit()
        
        conn.close()

        return redirect(url_for('login'))
    else:
        if 'user_id' not in session or session['user_id'] != 1:
            return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
        else:
            return render_template('register.html')



@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if spravne_prihlaseni(username, password):
            # Získanie informácií o používateľovi
            user_info = get_user_info(username)
            user_id = user_info[0]
            # Uloženie ID užívateľa do relácie
            session['user_id'] = user_id  
            
            # Zaznamenanie prihlásenia do databázy logs.db
            conn = sqlite3.connect('logs.db')
            c = conn.cursor()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO logs (user_id, action, timestamp) VALUES (?, ?, ?)", (user_id, 'login', timestamp))
            conn.commit()
            conn.close()
            
            # Presmerovanie na osobnú hlavnú stránku po úspešnom prihlásení
            return redirect(url_for('personal_page', user_id=user_id))
        else:
            return "Nesprávne prihlasovacie údaje. Skúste to znova."
    else:
        return render_template('login.html')

# Ruta pre hlavnú stránku
@app.route('/home')
def home():
    return render_template('home.html')

# Ruta pre osobnú stránku užívateľa
@app.route('/user/<int:user_id>')
def personal_page(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if user_id == 1:
        return redirect(url_for('admin'))
    
    if session['user_id'] != user_id:
        return "Pristup zakázaný"
    
    user_info = get_user_info_by_id(user_id)
    
    # Načítanie záznamov z archívu, ktoré patria danému používateľovi
    conn = sqlite3.connect('archiv.db')
    c = conn.cursor()
    c.execute("SELECT * FROM archive WHERE delivering = ?", (user_info[3],))  # Index 3 odkazuje na stĺpec "firma" v tabuľke users
    archive_records = c.fetchall()
    conn.close()

    return render_template('personal_page.html', user_info=user_info, archive_records=archive_records)


# Ruta pre odhlásenie užívateľa
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Ruta pre admina
@app.route('/admin')
def admin():
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
    # Sem můžete přidat logiku pro stránku admina
    return render_template('admin.html')

# Ruta pre pridanie záznamu do archívu
@app.route('/add_to_archive', methods=['GET', 'POST'])
def add_to_archive():
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
    form = ArchiveForm()
    form.document_number.data = generate_document_number()  # Nastavenie náhodného čísla
    form.delivering.choices = get_delivering_options()
    if form.validate_on_submit():
        conn = sqlite3.connect('archiv.db')
        c = conn.cursor()
        c.execute("INSERT INTO archive (date, document_number, delivering, carrier, receiver, material, waste_name, carrier_name, ecv, quantity, poznamka) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (form.date.data, form.document_number.data, form.delivering.data, form.carrier.data, form.receiver.data, form.material.data, form.waste_name.data, form.carrier_name.data, form.ecv.data, form.quantity.data, form.poznamka.data))
        conn.commit()
        conn.close()
        flash('Dáta boli úspešne uložené do archívu.')
        return redirect(url_for('add_to_archive'))
    return render_template('add_to_archive.html', form=form)

# Ruta pre stránku archív zberných listov
@app.route('/archive')
def archive():
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
    
    # Načítanie údajov priamo po načítaní stránky pomocou AJAX
    data = refresh_data()
    return render_template('archive.html', archive_records=data)

# Ruta pre vytvorenie noveho záznamu pre podnik
@app.route('/create_business', methods=['POST'])
def create_business():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    name = request.form['name']
    address = request.form['address']
    ico = request.form['ico']

    if not name or not address or not ico:
        flash("Vyplňte prosím všechny informace.")
        return redirect(url_for('admin'))

    conn = sqlite3.connect('businesses.db')
    c = conn.cursor()
    c.execute("INSERT INTO businesses (name, address, ico) VALUES (?, ?, ?)", (name, address, ico))
    conn.commit()
    conn.close()

    flash("Nová prevádzka byla úspěšně vytvořena.")
    return redirect(url_for('admin'))

# Funkce pro získání informací o uživateli podle jeho ID
def get_user_info_by_id(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_info = c.fetchone()
    conn.close()
    return user_info

# Funkce pro získání ID uživatele podle jeho uživatelského jména
def get_user_info(username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user_id = c.fetchone()
    conn.close()
    return user_id

# Funkce pro ověření správného přihlášení
def spravne_prihlaseni(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
    user_info = c.fetchone()
    conn.close()
    if user_info and user_info[1] == password:
        return True
    return False

# Ruta pro zobrazení seznamu podniků
@app.route('/list_of_businesses')
def list_of_businesses():
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
    conn = sqlite3.connect('businesses.db')
    c = conn.cursor()
    c.execute("SELECT * FROM businesses")
    businesses = c.fetchall()
    conn.close()
    return render_template('list_of_businesses.html', businesses=businesses)

# Funkce pro získání možností pro rozbalovací menu
def get_delivering_options():
    conn = sqlite3.connect('businesses.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT name FROM businesses")
    delivering_options = c.fetchall()
    conn.close()
    return [option[0] for option in delivering_options]  # Vrátí seznam hodnot ze sloupce "name"

# Ruta pre obnovenie údajov s refresh_data.py
@app.route('/refresh_data', methods=['GET'])
def refresh_archive_data():
    data = refresh_data()  # Voláme funkciu refresh_data na obnovenie údajov z databázy
    return render_template('archive.html', archive_records=data)  # Renderujeme šablonu archive.html s aktualizovanými údajmi

# Cesta pre archív2
@app.route('/archive2')
def show_archive2():
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
    # Pripojenie k databáze
    conn = sqlite3.connect('archiv.db')
    c = conn.cursor()

    # Vykonanie SQL dotazu na vybratie všetkých záznamov
    c.execute("SELECT * FROM archive")
    rows = c.fetchall()

    # Zatvorenie spojenia s databázou
    conn.close()

    # Vrátenie údajov a ich zobrazenie v HTML šablóne
    return render_template('archive2.html', archive_records=rows)

###
# Ruta pre zobrazenie šablóny reportu <--- táto cesta určuje generovanie reportu, ale len s ID 1, takže všetky reporty sú rovnaké!!!
#@app.route('/report_template')
def show_report_template():
    
    # Pripojenie k databáze
    conn = sqlite3.connect('archiv.db')
    c = conn.cursor()
    
    # Vykonanie SQL dotazu na vybratie všetkých záznamov
    c.execute("SELECT * FROM archive")
    rows = c.fetchone()

    # Zatvorenie spojenia s databázou
    conn.close()
    
    return render_template('report_template.html', archive_records=rows)

@app.route('/report_template/<int:record_id>')
def show_report_template(record_id):
    try:
        # Pripojenie k databáze
        conn = sqlite3.connect('archiv.db')
        c = conn.cursor()

        # Vykonanie SQL dotazu na vybratie údajov pre dané ID
        c.execute("SELECT * FROM archive WHERE id = ?", (record_id,))
        row = c.fetchone()

        # Zatvorenie spojenia s databázou
        conn.close()

        if row:
            # Ak sa nájde záznam, preniesť údaje do šablóny
            return render_template('report_template.html', archive_records=row)
        else:
            # Ak sa záznam nenájde, vrátiť chybovú správu
            return render_template('error.html', message="Záznam nebol nájdený.")

    except Exception as e:
        # Spracovanie chyby
        return render_template('error.html', message=str(e))

# Druhá definícia show_statistika pre načítanie iba stĺpcov delivering a quantity
# Cesta pre štatistika.html


# Cesta pre štatistika.html
@app.route('/statistika')
def show_statistika_data():
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
    # Pripojenie k databáze
    conn = sqlite3.connect('archiv.db')
    c = conn.cursor()

    # SQL dotaz na načítanie iba unikátnych hodnôt z stĺpca "delivering" pre Silver Mine
    c.execute("SELECT DISTINCT delivering FROM archive WHERE carrier = 'Silver Mine, s.r.o, Kvašov 43, 020 62 Kvašov, IČO: 47 204 788'")
    silver_mine_deliveries = c.fetchall()

    # Vytvorenie prázdneho slovníka pre ukladanie súčtu hodnôt quantity pre každé "delivering" pre Silver Mine
    silver_mine_quantities = {}

    # Pre každú unikátnu položku "delivering" pre Silver Mine
    for delivery in silver_mine_deliveries:
        # SQL dotaz na sčítanie hodnôt "quantity" pre dané "delivering" pre Silver Mine
        c.execute("SELECT SUM(quantity) FROM archive WHERE delivering=? AND carrier='Silver Mine, s.r.o, Kvašov 43, 020 62 Kvašov, IČO: 47 204 788' AND waste_name='20 01 08 biologicky rozložiteľný kuchynský a reštauračný odpad'", (delivery[0],))
        total_quantity = c.fetchone()[0]
        # SQL dotaz na počet výskytov daného "delivering" pre Silver Mine
        c.execute("SELECT COUNT(delivering) FROM archive WHERE delivering=? AND carrier='Silver Mine, s.r.o, Kvašov 43, 020 62 Kvašov, IČO: 47 204 788' AND waste_name='20 01 08 biologicky rozložiteľný kuchynský a reštauračný odpad'", (delivery[0],))
        total_deliveries = c.fetchone()[0]
        # Uloženie súčtu a počtu vývozov do slovníka s kľúčom "delivering" pre Silver Mine
        silver_mine_quantities[delivery[0]] = (total_quantity, total_deliveries)

    # SQL dotaz na načítanie iba unikátnych hodnôt z stĺpca "delivering" pre Silver Mine PLUS
    c.execute("SELECT DISTINCT delivering FROM archive WHERE carrier = 'Silver Mine PLUS, s.r.o., Kvašov 43, 020 62 Kvašov, IČO: 55598439'")
    silver_mine_plus_deliveries = c.fetchall()

    # Vytvorenie prázdneho slovníka pre ukladanie súčtu hodnôt quantity pre každé "delivering" pre Silver Mine PLUS
    silver_mine_plus_quantities = {}

    # Pre každú unikátnu položku "delivering" pre Silver Mine PLUS
    for delivery in silver_mine_plus_deliveries:
        # SQL dotaz na sčítanie hodnôt "quantity" pre dané "delivering" pre Silver Mine PLUS
        c.execute("SELECT SUM(quantity) FROM archive WHERE delivering=? AND carrier='Silver Mine PLUS, s.r.o., Kvašov 43, 020 62 Kvašov, IČO: 55598439' AND waste_name='20 01 08 biologicky rozložiteľný kuchynský a reštauračný odpad'", (delivery[0],))
        total_quantity = c.fetchone()[0]
        # SQL dotaz na počet výskytov daného "delivering" pre Silver Mine PLUS
        c.execute("SELECT COUNT(delivering) FROM archive WHERE delivering=? AND carrier='Silver Mine PLUS, s.r.o., Kvašov 43, 020 62 Kvašov, IČO: 55598439' AND waste_name='20 01 08 biologicky rozložiteľný kuchynský a reštauračný odpad'", (delivery[0],))
        total_deliveries = c.fetchone()[0]
        # Uloženie súčtu a počtu vývozov do slovníka s kľúčom "delivering" pre Silver Mine PLUS
        silver_mine_plus_quantities[delivery[0]] = (total_quantity, total_deliveries)

    # Zatvorenie spojenia s databázou
    conn.close()

    # Vrátenie údajov a ich zobrazenie v HTML šablóne
    return render_template('statistika.html', silver_mine_quantities=silver_mine_quantities, silver_mine_plus_quantities=silver_mine_plus_quantities)

#Stiahnutie databáz cez tlačidlo "stiahnuť databazy" v admin.html
@app.route('/download_databases', methods=['POST'])
def download_databases():
    # Zoznam názvov databáz
    database_names = ['users.db', 'businesses.db', 'archiv.db']
    # Cesta k adresáru s databázami
    database_dir = os.path.dirname(__file__)

    # Vytvorenie zip archívu
    zip_path = 'databases.zip'
    with ZipFile(zip_path, 'w') as zipf:
        for db_name in database_names:
            db_path = os.path.join(database_dir, db_name)
            zipf.write(db_path, arcname=db_name)

    # Odoslanie zip archívu ako súboru na sťahovanie
    return send_file(zip_path, as_attachment=True)

###externa databaza heroku
def connect_to_postgres():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def migrate_data():
    # Pripojenie k SQLite databáze
    sqlite_connection = sqlite3.connect('archiv.db')
    sqlite_cursor = sqlite_connection.cursor()

    # Pripojenie k PostgreSQL databáze na Heroku
    postgres_connection = connect_to_postgres()
    postgres_cursor = postgres_connection.cursor()

    # Selektovanie dát z SQLite tabuľky
    sqlite_cursor.execute("SELECT * FROM archive;")
    data = sqlite_cursor.fetchall()

    # Vloženie dát do PostgreSQL tabuľky
    for row in data:
        postgres_cursor.execute("INSERT INTO archive (date, document_number, delivering, carrier, receiver, material, waste_name, carrier_name, ecv, quantity, poznamka) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);", row)
    
    # Potvrdenie transakcie
    postgres_connection.commit()

    # Zatvorenie pripojení
    sqlite_connection.close()
    postgres_connection.close()




if __name__ == "__main__":
    app.run(debug=True)