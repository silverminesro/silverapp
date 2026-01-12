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
import os, re
import random
import string

app = Flask(__name__)
app.secret_key = 'tajny_klic'

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
    
    # Ak user_id == 1, presmeruje na admin
    if user_id == 1:
        return redirect(url_for('admin'))
    
    # Overenie, či prihlásený používateľ je rovnaký ako user_id v URL
    if session['user_id'] != user_id:
        return "Pristup zakázaný"
    
    # 1. Načítanie user_info z tabuľky users
    user_info = get_user_info_by_id(user_id)
    
    # 2. Načítanie záznamov z archívu (archiv.db), ktoré patria danému používateľovi
    conn = sqlite3.connect('archiv.db')
    c = conn.cursor()
    c.execute("SELECT * FROM archive WHERE delivering = ?", (user_info[3],))  # user_info[3] = firma
    archive_records = c.fetchall()
    conn.close()

    # 3. Skontrolujeme businesses.db -> rocne_suhrny pre firmu používateľa
    #    aby sme vedeli, či sa má zobraziť tlačidlo "Zobraziť potvrdenie 2024"
    import os
    db_path = os.path.join(os.path.dirname(__file__), 'businesses.db')
    has_data = False  # prednastavíme na False

    # Firma používateľa
    firma = user_info[3]  # to isté, čo sme použili vyššie (delivering)

    # Skúsime vyhľadať riadok v rocne_suhrny, kde stĺpec name = firma
    if os.path.exists(db_path):
        conn_b = sqlite3.connect(db_path)
        c_b = conn_b.cursor()
        c_b.execute("SELECT * FROM rocne_suhrny WHERE name = ?", (firma,))
        row = c_b.fetchone()
        conn_b.close()

        if row:
            # row = (id, name, rok2024_200108, rok2024_200125, ...)
            # Overíme, či aspoň jeden stĺpec (od indexu 2 vyššie) nie je None
            # t.j. aby neboli všetky stĺpce v ročnom súhrne prázdne
            if any(field is not None for field in row[2:]):
                has_data = True

    # 4. Vrátime šablónu personal_page.html so všetkými premennými
    return render_template(
        'personal_page.html',
        user_info=user_info,
        archive_records=archive_records,
        has_data=has_data
    )



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
# Pôvodná funkcia show_report_template pre zobrazenie všetkých záznamov
# Funkcia show_report_template pre zobrazenie konkrétneho záznamu pre všetkých
# Funkcia show_user_report_template pre zobrazenie konkrétneho záznamu pre užívateľa
@app.route('/user/<int:user_id>/report_template/<int:record_id>')
def show_user_report_template(user_id, record_id):
    try:
        # Skontrolovať, či session obsahuje user_id
        if 'user_id' not in session:
            return redirect(url_for('login'))  # Predpokladám, že máte login stránku

        # Skontrolovať, či sa user_id v session zhoduje s user_id z URL
        if session['user_id'] != user_id:
            return "Prístup zakázaný: Nesprávne ID používateľa"

        # Pripojenie k databáze users.db a overenie user_id a firma
        conn_users = sqlite3.connect('users.db')
        c_users = conn_users.cursor()
        c_users.execute("SELECT id, firma FROM users WHERE id = ?", (user_id,))
        user_row = c_users.fetchone()
        conn_users.close()

        if not user_row:
            return "Prístup zakázaný: Nesprávne ID používateľa"

        user_id_db, firma = user_row

        # Pripojenie k databáze v režime iba na čítanie
        conn = sqlite3.connect('file:archiv.db?mode=ro', uri=True)
        c = conn.cursor()

        # Vykonanie SQL dotazu na vybratie údajov pre dané ID a overenie zhodnosti hodnoty firma a delivering
        c.execute("SELECT * FROM archive WHERE id = ? AND delivering = ?", (record_id, firma))
        row = c.fetchone()

        # Zatvorenie spojenia s databázou
        conn.close()

        if row:
            # Ak sa nájde záznam, preniesť údaje do šablóny
            return render_template('report_template.html', archive_records=row)
        else:
            # Ak sa záznam nenájde, vrátiť chybovú správu
            return render_template('error.html', message="Záznam nebol nájdený alebo nemáte prístup k tomuto záznamu.")

    except Exception as e:
        # Spracovanie chyby
        return render_template('error.html', message=str(e))

@app.route('/report_template/<int:record_id>')
def show_report_template(record_id):
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
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



@app.route('/user/<int:user_id>/report_template_2024/<int:record_id>')
def show_user_report_template_2024(user_id, record_id):
    """
    Len používateľ so session['user_id'] == user_id
    môže zobraziť záznam, kde v stĺpci 'delivering'
    je firma toho istého používateľa.
    """
    import os
    import sqlite3

    # 1) Overenie session
    if 'user_id' not in session:
        return "Prístup zakázaný: Nie ste prihlásený."
    if session['user_id'] != user_id:
        return "Prístup zakázaný: Nesprávne ID používateľa."

    # 2) Z users.db vytiahneme 'firma' (predpokladáme, že tam má používateľ uložený nejaký identifikátor)
    conn_users = sqlite3.connect('users.db')
    c_users = conn_users.cursor()
    c_users.execute("SELECT firma FROM users WHERE id = ?", (user_id,))
    user_row = c_users.fetchone()
    conn_users.close()

    if not user_row:
        return "Používateľ so zadaným ID neexistuje."
    
    # firma = napr. "Obec Horovce, IČO: ...."
    firma = user_row[0]

    # 3) Pripojenie k zberne_listy_2025.db a SELECT s filtrom na ID a delivering
    db_path = os.path.join(os.path.dirname(__file__), 'archivy', 'zberne_listy_2025.db')
    conn_archive = sqlite3.connect(db_path)
    c_archive = conn_archive.cursor()

    # Filtrujeme, aby sedelo ID aj delivering
    c_archive.execute("""
        SELECT * FROM archive
        WHERE id = ?
          AND delivering = ?
    """, (record_id, firma))
    
    row = c_archive.fetchone()
    conn_archive.close()

    # 4) Vyhodnotenie výsledku
    if row:
        # Záznam patrí tomuto používateľovi (podľa delivering = jeho firma)
        return render_template('report_template.html', archive_records=row)
    else:
        return render_template('error.html', message="Záznam nebol nájdený alebo nepatrí tomuto používateľovi.")





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



from collections import defaultdict

#@app.route('/user/<user_id>/statistika2024.html')
#def statistika_2024(user_id):
    #if session['user_id'] != user_id:
        #return "Pristup zakázaný"
    #if 'user_id' not in session:
        #return redirect(url_for('login'))

@app.route('/user/<user_id>/statistika2024.html')
def statistika_2024(user_id):
    # Skontrolovať, či session obsahuje user_id
    if 'user_id' not in session:
        return "Prístup zakázaný: Používateľ nie je prihlásený"

    # Skontrolovať, či sa user_id v session zhoduje s user_id z URL
    if str(session['user_id']) != str(user_id):
        return "Prístup zakázaný: Nesprávne ID používateľa"
    
    # Načítanie firmy používateľa z databázy users.db
    conn_users = sqlite3.connect('users.db')
    c_users = conn_users.cursor()
    c_users.execute("SELECT firma FROM users WHERE id = ?", (user_id,))
    user_company = c_users.fetchone()
    conn_users.close()

    if user_company:
        # Načítanie záznamov z archívu, ktoré majú hodnotu "delivering" rovnakú ako firma používateľa
        conn_archive = sqlite3.connect('archiv.db')
        c_archive = conn_archive.cursor()
        c_archive.execute("SELECT * FROM archive WHERE delivering = ?", (user_company[0],))
        archive_records = c_archive.fetchall()
        conn_archive.close()

        # Spočítajte a súčet množstva položiek pre každého prepravcu a odpad
        carriers_data = defaultdict(lambda: defaultdict(float))
        for record in archive_records:
            carriers_data[record[4]][record[7]] += float(record[10])

        return render_template('statistika2024.html', user_id=user_id, carriers_data=carriers_data)
    else:
        # Ak nebola firma nájdená, vykonajte príslušnú obsluhu chyby
        return render_template('error.html', message="Firma používateľa nebola nájdená.")

@app.route('/user/<user_id>/potvrdenie2024.html')
def potvrdenie_2024(user_id):
    # Skontrolovať, či session obsahuje user_id
    if 'user_id' not in session:
        return "Prístup zakázaný: Používateľ nie je prihlásený"

    # Skontrolovať, či sa user_id v session zhoduje s user_id z URL
    if str(session['user_id']) != str(user_id):
        return "Prístup zakázaný: Nesprávne ID používateľa"
    
    odovzdavajuci = "Názov odovzdávajúcej spoločnosti"
    prepravca = "Názov prepravcu"
    preberajuci = "Názov preberajúcej spoločnosti"
    registracne_cislo = "123456"
    total_quantity = "5000"

    return render_template('potvrdenie2024.html', odovzdavajuci=odovzdavajuci, prepravca=prepravca, preberajuci=preberajuci, registracne_cislo=registracne_cislo, total_quantity=total_quantity)



# Funkcia pre načítanie názvov prevádzok z databázy do /admin/invoice_management
@app.route('/admin/invoice_management')
def invoice_management():
    if 'user_id' not in session or session['user_id'] != 1:
        return "Pristup zakázaný"  # Pokud uživatel není administrátor, zakáže se přístup
    
    # Získanie všech dat z tabulky "uhrady"
    conn = sqlite3.connect(UHRADY_DB)
    c = conn.cursor()
    c.execute("SELECT * FROM uhrady")
    all_data = c.fetchall()
    conn.close()
    
    return render_template('invoice_management.html', all_data=all_data)





# KOD DATABAZY PRE ÚHRADY

USERS_DB = 'users.db'
UHRADY_DB = 'uhrady.db'

def create_uhrady_table():
    # Pripojenie k databáze "users.db"
    conn_existing = sqlite3.connect(USERS_DB)
    c_existing = conn_existing.cursor()

    # Získanie informácií zo stĺpcov "ID" a "firma" z databázy "users.db"
    c_existing.execute('SELECT ID, firma FROM users')
    data = c_existing.fetchall()

    # Odpojenie od databáze "users.db"
    conn_existing.close()

    # Pripojenie k databáze "uhrady.db"
    conn_new = sqlite3.connect(UHRADY_DB)
    c_new = conn_new.cursor()

    # Vytvorenie tabuľky "uhrady" s potrebnými stĺpcami
    c_new.execute('''
        CREATE TABLE IF NOT EXISTS uhrady (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            firma TEXT
        )
    ''')

    # Získanie názvov existujúcich stĺpcov
    c_new.execute('PRAGMA table_info(uhrady)')
    existing_columns = [info[1] for info in c_new.fetchall()]

    # Pridanie stĺpcov pre jednotlivé mesiace, ak neexistujú
    for month in range(1, 13):
        column_name = f'mesiac_{month}'
        if column_name not in existing_columns:
            c_new.execute(f'ALTER TABLE uhrady ADD COLUMN {column_name} REAL DEFAULT NULL')

    # Vloženie údajov z "users.db" do "uhrady.db"
    for row in data:
        user_id, firma = row
        # Skontrolujeme, či záznam už existuje
        c_new.execute('SELECT * FROM uhrady WHERE user_id = ?', (user_id,))
        existing_record = c_new.fetchone()
        if not existing_record:
            c_new.execute('INSERT INTO uhrady (user_id, firma) VALUES (?, ?)', (user_id, firma))

    # Uloženie zmien a uzavretie pripojenia k databáze
    conn_new.commit()
    conn_new.close()

    # Získanie mesiacov s hodnotami z databázy
    conn_new = sqlite3.connect(UHRADY_DB)
    c_new = conn_new.cursor()
    c_new.execute("PRAGMA table_info(uhrady)")
    columns = c_new.fetchall()
    column_names = [column[1] for column in columns]
    existing_months = [column for column in column_names if column.startswith('mesiac_') and column != 'mesiac_' and column != 'NULL']
    conn_new.close()

    # Preposlať zoznam existujúcich mesiacov do šablóny
    return existing_months

existing_months = create_uhrady_table()
#print(existing_months)  # Pre kontrolu, či sú správne načítané mesiace

###

#KOD PRE UHRADY UžIVATELOV
@app.route('/user/<int:user_id>/payments.html')
def payments(user_id):
    # Skontrolovať, či session obsahuje user_id
    if 'user_id' not in session:
        return "Prístup zakázaný: Používateľ nie je prihlásený"

    # Skontrolovať, či sa user_id v session zhoduje s user_id z URL
    if session['user_id'] != user_id:
        return "Prístup zakázaný: Nesprávne ID používateľa"

    # Pripojenie k databáze 'uhrady.db' a získanie údajov pre daného používateľa podľa user_id
    conn = sqlite3.connect(UHRADY_DB)
    c = conn.cursor()
    c.execute('SELECT firma, mesiac_1, mesiac_2, mesiac_3, mesiac_4, mesiac_5, mesiac_6, mesiac_7, mesiac_8, mesiac_9, mesiac_10, mesiac_11, mesiac_12 FROM uhrady WHERE user_id = ?', (user_id,))
    payments_info = c.fetchone()
    conn.close()

    if not payments_info:
        return "Žiadne informácie o úhradách pre tohto používateľa"

    # Vytvorenie slovníka z výsledkov dotazu
    payments_data = {
        "firma": payments_info[0],
        "mesiac_1": payments_info[1],
        "mesiac_2": payments_info[2],
        "mesiac_3": payments_info[3],
        "mesiac_4": payments_info[4],
        "mesiac_5": payments_info[5],
        "mesiac_6": payments_info[6],
        "mesiac_7": payments_info[7],
        "mesiac_8": payments_info[8],
        "mesiac_9": payments_info[9],
        "mesiac_10": payments_info[10],
        "mesiac_11": payments_info[11],
        "mesiac_12": payments_info[12]
    }

    # Renderovanie šablóny 'payments.html' s údajmi o úhradách
    return render_template('payments.html', payments_info=payments_data)



@app.route('/user/<int:user_id>/potvrdenia')
def potvrdenia(user_id):
    # Skontrolovať, či session obsahuje user_id
    if 'user_id' not in session:
        return "Prístup zakázaný: Používateľ nie je prihlásený"
    
    # Skontrolovať, či sa user_id v session zhoduje s user_id z URL
    if session['user_id'] != user_id:
        return "Prístup zakázaný: Nesprávne ID používateľa"
    
    """
    Jednoduchá stránka s prehľadom potvrdení,
    kde môžeš postupne pridávať odkazy na jednotlivé potvrdenia.
    """
    return render_template('potvrdenia.html')



@app.route('/user/<int:user_id>/potvrdenie_rok_2024')
def show_potvrdenie_rok_2024(user_id):
    if 'user_id' not in session:
        return "Prístup zakázaný: Používateľ nie je prihlásený"
    if session['user_id'] != user_id:
        return "Prístup zakázaný: Nesprávne ID používateľa"

    import sqlite3, os

    # 1) Z users.db vytiahni firmu (alebo name) pre tohto user_id
    users_db_path = os.path.join(os.path.dirname(__file__), 'users.db')
    conn_users = sqlite3.connect(users_db_path)
    c_users = conn_users.cursor()
    c_users.execute("SELECT firma FROM users WHERE id = ?", (user_id,))
    row_user = c_users.fetchone()
    conn_users.close()

    if not row_user:
        return "Používateľ neexistuje v tabuľke 'users'."

    firma = row_user[0]  # Napríklad "Obec Horovce" alebo "ABC s.r.o."

    # 2) V businesses.db -> rocne_suhrny -> stĺpec 'name'  
    #    musí obsahovať rovnakú hodnotu ako firma
    db_path = os.path.join(os.path.dirname(__file__), 'businesses.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Vyber záznam, kde name = firma
    c.execute("SELECT * FROM rocne_suhrny WHERE name = ?", (firma,))
    row = c.fetchone()
    conn.close()

    if not row:
        return f"V tabuľke 'rocne_suhrny' nie je záznam s name = '{firma}'"

    # row = (id, name, rok2024_200108, rok2024_200125, ...)  - len príklad
    # Ulož si to do nejakej štruktúry, aby sa ti dobre prenášalo do šablóny
    data = {
        "name": row[1],
        "rok2024_200108": row[2],
        "rok2024_200125": row[3],
        "rok2024_190819": row[4],
        # Zvyšné stĺpce podľa skutočnej štruktúry (index 2, 3, 4,...)
        # napr. "rk_2024_200108": row[2],
        # ...
    }

    # Vráť šablónu, napr. potvrdenie_rok_2024.html
    return render_template('potvrdenie_rok_2024.html', data=data)





@app.route('/archiv-zbernych-dokladov/<int:user_id>')
def archiv_zbernych_dokladov(user_id):
    # Kontrola session
    if 'user_id' not in session:
        return "Prístup zakázaný: Používateľ nie je prihlásený"
    if session['user_id'] != user_id:
        return "Prístup zakázaný: Nesprávne ID používateľa"

 # 1. Zisti firmu používateľa (user_id) z tabuľky users
    conn_users = sqlite3.connect('users.db')
    c_users = conn_users.cursor()
    c_users.execute("SELECT firma FROM users WHERE id = ?", (user_id,))
    user_row = c_users.fetchone()
    conn_users.close()

    if not user_row:
        return "Používateľ s týmto ID neexistuje."

    # firma = napr. "Obec Horovce, IČO: 0017306"
    firma = user_row[0]

    # 2. Pripojenie k DB zberne_listy_2025.db
    db_path = os.path.join(os.path.dirname(__file__), 'archivy', 'zberne_listy_2025.db')
    conn_archive = sqlite3.connect(db_path)
    c_archive = conn_archive.cursor()

    # 3. SELECT len tie záznamy, kde delivering je rovnaké ako firma užívateľa
    c_archive.execute("SELECT * FROM archive WHERE delivering = ?", (firma,))
    archive_records = c_archive.fetchall()
    conn_archive.close()

    # 4. Šablóna
    return render_template('archiv_zbernych_dokladov.html', archive_records=archive_records)



def get_available_years():
    """
    Prejde priečinok 'archivy/' a vráti zoznam rokov,
    pre ktoré existuje 'zberne_listy_YYYY.db'.
    """
    folder = os.path.join(os.path.dirname(__file__), 'archivy')
    pattern = r"^zberne_listy_(\d{4})\.db$"
    years = []
    
    for filename in os.listdir(folder):
        match = re.match(pattern, filename)
        if match:
            year = int(match.group(1))
            years.append(year)
    
    years.sort()
    return years




if __name__ == "__main__":
    app.run(debug=True)


   