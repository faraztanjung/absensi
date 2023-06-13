from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
import requests
import calendar
from datetime import datetime, time

app = Flask(__name__)

# Konfigurasi koneksi database
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'database_absensi'
app.config['MYSQL_PORT'] = 3306

mysql = MySQL(app)


@app.route('/absensi/check_in/<int:id_karyawan>', methods=['POST'])
def check_in(id_karyawan):
    # Mengambil data karyawan dari JSON API external
    response = requests.get(f'https://karyawan-app.000webhostapp.com/api/karyawan/{id_karyawan}')
    karyawan_data = response.json()

    # Memeriksa apakah pengambilan data karyawan berhasil
    if response.status_code != 200 or not karyawan_data.get('success', False):
        return jsonify({'message': 'Gagal mengambil data karyawan dari JSON API.'}), 500

    karyawan = karyawan_data['data']
    nama = karyawan['nama_lengkap']

    # Mendapatkan tanggal saat ini
    tanggal = datetime.now().date()

    # Mendapatkan jam saat ini
    current_time = datetime.now().time()
    closing_time = datetime.strptime('17:00:00', '%H:%M:%S').time()

    # Pengecekan jam
    if current_time > closing_time:
        return jsonify({'message': 'Anda tidak dapat melakukan check-in setelah pukul 17:00:00.'})

    # Mendapatkan jam saat ini
    check_in = current_time.strftime('%H:%M:%S')

    # Menyiapkan data absensi
    status = 'hadir'
    check_out = '17:00:00'
    check_out_datetime = datetime.strptime(check_out, '%H:%M:%S')
    check_in_datetime = datetime.strptime(check_in, '%H:%M:%S')
    durasi = check_out_datetime - check_in_datetime

    # Memeriksa apakah karyawan telah melakukan absensi pada tanggal yang sama sebelumnya
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM absensi WHERE id_karyawan = %s AND tanggal = %s", (id_karyawan, tanggal))
    result = cur.fetchone()
    absensi_count = result[0]
    cur.close()

    # Jika karyawan telah melakukan absensi pada tanggal yang sama, kirimkan respons bahwa tidak bisa absen lagi
    if absensi_count > 0:
        return jsonify({'message': 'Anda telah melakukan absensi hari ini.'})

    # Jika karyawan belum melakukan absensi pada tanggal yang sama, tambahkan data absensi ke database
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO absensi (id_karyawan, nama, tanggal, status, check_in, check_out, durasi) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (id_karyawan, nama, tanggal, status, check_in, check_out, durasi))
    mysql.connection.commit()
    cur.close()

    return jsonify({'message': 'Absensi ditambahkan'})


@app.route('/absensi/check_out/<int:id_karyawan>', methods=['PUT'])
def check_out(id_karyawan):
    cur = mysql.connection.cursor()

    # Mendapatkan data check_in dan check_out dari database
    cur.execute("SELECT check_in FROM absensi WHERE id_karyawan = %s", (id_karyawan,))
    result = cur.fetchone()
    check_in_old = result[0]

    # Mendapatkan jam check_out maksimal (17:00:00) di hari yang sama dengan check_in
    check_in = datetime.strptime(str(check_in_old), '%H:%M:%S')
    check_out_max = datetime.combine(check_in.date(), time(hour=17))
    
    # Mendapatkan datetime objek dari check_out yang diberikan
    # Mendapatkan jam saat ini
    check_out = datetime.now().time().strftime('%H:%M:%S')
    check_out_datetime = datetime.strptime(check_out, '%H:%M:%S')

    # Memeriksa apakah check_out melebihi batas maksimal
    if check_out_datetime > check_out_max:
        check_out = check_out_max
        cur.execute("UPDATE absensi SET check_out = %s WHERE id_karyawan = %s", (check_out, id_karyawan))
        mysql.connection.commit()

        # Menghitung durasi
        duration = check_out_max - check_in
        cur.execute("UPDATE absensi SET durasi = %s WHERE id_karyawan = %s", (duration, id_karyawan))
        mysql.connection.commit()

        cur.close()
        return jsonify({'message': 'Check-out melebihi batas waktu maksimal (17:00:00)'})

    # Memeriksa apakah check_out lebih awal dari check_in
    if check_out_datetime < check_in:
        return jsonify({'message': 'Check-out tidak dapat lebih awal dari check-in'})

    # Memperbarui data check_out dan durasi di database
    cur.execute("UPDATE absensi SET check_out = %s WHERE id_karyawan = %s", (check_out, id_karyawan))
    mysql.connection.commit()

    # Menghitung durasi
    duration = check_out_datetime - check_in
    cur.execute("UPDATE absensi SET durasi = %s WHERE id_karyawan = %s", (duration, id_karyawan))
    mysql.connection.commit()

    cur.close()

    return jsonify({'message': 'Absensi diperbarui'})


@app.route('/absensi/delete/<int:id_karyawan>/<string:tanggal>', methods=['DELETE'])
def delete_attendance(id_karyawan, tanggal):
    cur = mysql.connection.cursor()

    # Memeriksa apakah absensi sudah dihapus sebelumnya pada tanggal yang sama
    cur.execute("SELECT check_in, check_out FROM absensi WHERE id_karyawan = %s AND DATE(check_in) = %s", (id_karyawan, tanggal))
    result = cur.fetchone()
    if result is None:
        return jsonify({'message': 'Absensi tidak ditemukan untuk tanggal yang diberikan'})

    # Menghapus absensi pada tanggal yang diberikan
    cur.execute("DELETE FROM absensi WHERE id_karyawan = %s AND DATE(check_in) = %s", (id_karyawan, tanggal))
    mysql.connection.commit()

    cur.close()

    return jsonify({'message': 'Absensi dihapus'})


@app.route('/calculate_rating/all', methods=['GET'])
def calculate_rating_all():
    cur = mysql.connection.cursor()

    # Mendapatkan daftar karyawan dari tabel karyawan
    cur.execute("SELECT id_karyawan FROM absensi")
    id_karyawan = cur.fetchall()

    rating_data = []  # Menyimpan data id_karyawan dan rating

    for employee_id in id_karyawan:
        # Mendapatkan total jam kerja per bulan untuk karyawan tertentu
        cur.execute(
            "SELECT SUM(TIME_TO_SEC(TIMEDIFF(check_out, check_in))) AS total_seconds FROM absensi WHERE id_karyawan = %s AND YEAR(check_in) = YEAR(CURDATE()) AND MONTH(check_in) = MONTH(CURDATE())",
            (employee_id,))
        result = cur.fetchone()
        total_seconds = result[0]
        total_hours = total_seconds // 3600

        # Menghitung rating berdasarkan total jam kerja
        rating = calculate_rating(total_hours)

        # Menyimpan id_karyawan dan rating ke dalam rating_data
        rating_data.append({'id_karyawan': employee_id[0], 'durasi':total_hours, 'rating': rating})

    cur.close()

    return jsonify({'message': 'Rating calculated successfully', 'rating_data': rating_data})


@app.route('/calculate_rating/id/<int:id_karyawan>', methods=['GET'])
def calculate_rating_by_id(id_karyawan):
    cur = mysql.connection.cursor()

    rating_data = []  # Menyimpan data id_karyawan dan rating

    # Mendapatkan total jam kerja per bulan untuk karyawan tertentu
    cur.execute(
        "SELECT SUM(TIME_TO_SEC(TIMEDIFF(check_out, check_in))) AS total_seconds FROM absensi WHERE id_karyawan = %s AND YEAR(check_in) = YEAR(CURDATE()) AND MONTH(check_in) = MONTH(CURDATE())",
        (id_karyawan,))
    result = cur.fetchone()

    if result is None or result[0] is None:
        cur.close()
        return jsonify({'message': 'Employee not found'})

    total_seconds = result[0]
    total_hours = total_seconds // 3600

    # Menghitung rating berdasarkan total jam kerja
    rating = calculate_rating(total_hours)

    # Menyimpan id_karyawan dan rating ke dalam rating_data
    rating_data.append({'id_karyawan': id_karyawan, 'durasi': total_hours, 'rating': rating})

    cur.close()

    return jsonify({'message': 'Rating calculated successfully', 'rating_data': rating_data})


@app.route('/calculate_rating/bulan/<int:month>', methods=['GET'])
def calculate_rating_monthly(month):
    cur = mysql.connection.cursor()

    # Mendapatkan daftar karyawan dari tabel absensi berdasarkan bulan tertentu
    cur.execute("SELECT id_karyawan FROM absensi WHERE MONTH(check_in) = %s", (month,))
    id_karyawan = cur.fetchall()

    rating_data = []  # Menyimpan data id_karyawan dan rating

    for employee_id in id_karyawan:
        # Mendapatkan total jam kerja per bulan untuk karyawan tertentu
        cur.execute(
            "SELECT SUM(TIME_TO_SEC(TIMEDIFF(check_out, check_in))) AS total_seconds FROM absensi WHERE id_karyawan = %s AND YEAR(check_in) = YEAR(CURDATE()) AND MONTH(check_in) = %s",
            (employee_id[0], month))
        result = cur.fetchone()
        total_seconds = result[0]
        total_hours = total_seconds // 3600

        # Menghitung rating berdasarkan total jam kerja
        rating = calculate_rating(total_hours)

        # Menyimpan id_karyawan dan rating ke dalam rating_data
        rating_data.append({'id_karyawan': employee_id[0], 'durasi': total_hours, 'rating': rating})

    cur.close()

    month_name = calendar.month_name[month]  # Mendapatkan nama bulan

    return jsonify({'message': f'Rating calculated successfully for {month_name}', 'rating_data': rating_data})


@app.route('/calculate_rating/id/<int:id_karyawan>/bulan/<int:month>', methods=['GET'])
def calculate_rating_by_id_and_month(id_karyawan, month):
    cur = mysql.connection.cursor()

    # Mendapatkan total jam kerja per bulan untuk karyawan tertentu
    cur.execute(
        "SELECT SUM(TIME_TO_SEC(TIMEDIFF(check_out, check_in))) AS total_seconds FROM absensi WHERE id_karyawan = %s AND YEAR(check_in) = YEAR(CURDATE()) AND MONTH(check_in) = %s",
        (id_karyawan, month))
    result = cur.fetchone()

    if result is None or result[0] is None:
        cur.close()
        return jsonify({'message': 'Employee not found'})

    total_seconds = result[0]
    total_hours = total_seconds // 3600

    # Menghitung rating berdasarkan total jam kerja
    rating = calculate_rating(total_hours)

    cur.close()

    return jsonify({'message': f'Rating calculated successfully for employee ID {id_karyawan} and month {calendar.month_name[month]}', 'id_karyawan': id_karyawan, 'bulan': month, 'durasi': total_hours, 'rating': rating})


def calculate_rating(total_hours):
    # Menghitung rating berdasarkan total jam kerja
    if total_hours >= 160:
        return 'Very Good'
    elif total_hours >= 120:
        return 'Good'
    else:
        return 'Bad'


@app.route('/absensi/all', methods=['GET'])
def get_all_absensi():
    cur = mysql.connection.cursor()

    # Mendapatkan semua data absensi
    cur.execute("SELECT * FROM absensi")
    absensi_data = cur.fetchall()

    absensi_list = []
    for absensi in absensi_data:
        durasi_hours = absensi[7].total_seconds() / 3600
        formatted_durasi_hours = "{:.3f}".format(round(durasi_hours, 3))

        absensi_dict = {
            'id_absensi': absensi[0],
            'id_karyawan': absensi[1],
            'nama': absensi[2],
            'tanggal': absensi[3].strftime('%Y-%m-%d'),
            'status': absensi[4],
            'check_in': str(absensi[5]),
            'check_out': str(absensi[6]),
            'durasi': str(absensi[7]),
            'format_jam': formatted_durasi_hours + " hours"
        }
        absensi_list.append(absensi_dict)

    cur.close()

    return jsonify({'absensi': absensi_list})


@app.route('/absensi/id/<int:id_karyawan>', methods=['GET'])
def get_absensi(id_karyawan):
    cur = mysql.connection.cursor()

    # Mendapatkan data absensi berdasarkan id_karyawan
    cur.execute("SELECT * FROM absensi WHERE id_karyawan = %s", (id_karyawan,))
    absensi_data = cur.fetchall()

    absensi_list = []
    for absensi in absensi_data:
        durasi_hours = absensi[7].total_seconds() / 3600
        formatted_durasi_hours = "{:.3f}".format(round(durasi_hours, 3))

        absensi_dict = {
            'id_absensi': absensi[0],
            'id_karyawan': absensi[1],
            'nama': absensi[2],
            'tanggal': absensi[3].strftime('%Y-%m-%d'),
            'status': absensi[4],
            'check_in': str(absensi[5]),
            'check_out': str(absensi[6]),
            'durasi': str(absensi[7]),
            'format_jam': formatted_durasi_hours + " hours"
        }
        absensi_list.append(absensi_dict)

    cur.close()

    return jsonify({'absensi': absensi_list})


@app.route('/absensi/tanggal/<string:tanggal>', methods=['GET'])
def get_absensi_by_tanggal(tanggal):
    try:
        # Mengubah string tanggal menjadi objek datetime
        tanggal_obj = datetime.strptime(tanggal, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'Format tanggal tidak valid. Gunakan format YYYY-MM-DD.'}), 400

    cur = mysql.connection.cursor()

    # Mendapatkan data absensi berdasarkan tanggal
    cur.execute("SELECT * FROM absensi WHERE tanggal = %s", (tanggal_obj,))
    absensi_data = cur.fetchall()

    absensi_list = []
    for absensi in absensi_data:
        durasi_hours = absensi[7].total_seconds() / 3600
        formatted_durasi_hours = "{:.3f}".format(round(durasi_hours, 3))

        absensi_dict = {
            'id_absensi': absensi[0],
            'id_karyawan': absensi[1],
            'nama': absensi[2],
            'tanggal': absensi[3].strftime('%Y-%m-%d'),
            'status': absensi[4],
            'check_in': str(absensi[5]),
            'check_out': str(absensi[6]),
            'durasi': str(absensi[7]),
            'format_jam': formatted_durasi_hours + " hours"
        }
        absensi_list.append(absensi_dict)

    cur.close()

    return jsonify({'absensi': absensi_list})

@app.route('/absensi/id/<int:id_karyawan>/tanggal/<string:tanggal>', methods=['GET'])
def get_absensi_by_id_and_tanggal(id_karyawan, tanggal):
    try:
        # Mengubah string tanggal menjadi objek datetime
        tanggal_obj = datetime.strptime(tanggal, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'Format tanggal tidak valid. Gunakan format YYYY-MM-DD.'}), 400

    cur = mysql.connection.cursor()

    # Mendapatkan data absensi berdasarkan id_karyawan dan tanggal
    cur.execute("SELECT * FROM absensi WHERE id_karyawan = %s AND tanggal = %s", (id_karyawan, tanggal_obj))
    absensi_data = cur.fetchall()

    absensi_list = []
    for absensi in absensi_data:
        durasi_hours = absensi[7].total_seconds() / 3600
        formatted_durasi_hours = "{:.3f}".format(round(durasi_hours, 3))

        absensi_dict = {
            'id_absensi': absensi[0],
            'id_karyawan': absensi[1],
            'nama': absensi[2],
            'tanggal': absensi[3].strftime('%Y-%m-%d'),
            'status': absensi[4],
            'check_in': str(absensi[5]),
            'check_out': str(absensi[6]),
            'durasi': str(absensi[7]),
            'format_jam': formatted_durasi_hours + " hours"
        }
        absensi_list.append(absensi_dict)

    cur.close()

    return jsonify({'absensi': absensi_list})


@app.route('/absensi/close', methods=['POST'])
def tambah_absensi():
    # Mendapatkan waktu saat ini
    waktu_sekarang = datetime.now().time()

    # Memeriksa apakah waktu lebih dari pukul 17:00:00
    if waktu_sekarang < time(17, 0, 0):
        return jsonify({'message': 'Endpoint hanya dapat diakses setelah pukul 17:00:00.'}), 400

    # Mendapatkan data dari external API
    response = requests.get('https://karyawan-app.000webhostapp.com/api/karyawan/getAll')
    data_api = response.json()

    # Mendapatkan tanggal saat ini
    tanggal_sekarang = datetime.now().date()

    # Mengambil data karyawan yang belum melakukan presensi pada tanggal sekarang
    cur = mysql.connection.cursor()
    cur.execute("SELECT id_karyawan FROM absensi WHERE tanggal = %s", (tanggal_sekarang,))
    absensi_hari_ini = cur.fetchall()
    id_karyawan_absen_hari_ini = [row[0] for row in absensi_hari_ini]

    # Memasukkan data karyawan yang belum melakukan presensi ke dalam tabel absensi
    for karyawan in data_api['data']:
        id_karyawan = karyawan['id']
        if id_karyawan not in id_karyawan_absen_hari_ini:
            cur.execute("INSERT INTO absensi (id_karyawan, nama, tanggal, status, check_in, check_out, durasi) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (id_karyawan, karyawan['nama_lengkap'], tanggal_sekarang, 'alfa',
                         '00:00:00', '00:00:00', '00:00:00'))

    # Melakukan commit ke database
    mysql.connection.commit()
    cur.close()

    return jsonify({'message': 'Data absensi berhasil ditambahkan.'})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
