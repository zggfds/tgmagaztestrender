from flask import Flask, request, redirect, render_template, url_for, session
from firebase_admin import credentials, initialize_app, db
import os
from werkzeug.utils import secure_filename
from yoomoney import Quickpay

app = Flask(__name__)
app.secret_key = 'your_secret_key'
key_yoo = "3E2CD83996ACCE4FAF001A0B782309DA831FA0C8B6B16C0EE67B903F71644242"

# Firebase конфигурация
cred = credentials.Certificate("key.json")
initialize_app(cred, {'databaseURL': 'https://market-solobob-default-rtdb.firebaseio.com/'})

# Папка для загрузки фото
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def allowed_file(filename):
    """Проверяем, разрешён ли формат файла."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/red', methods=['GET', 'POST'])
def redirect():
    pass


@app.route('/not', methods=['GET', 'POST'])
def notifi():
    pass



@app.route('/<username>', methods=['GET', 'POST'])
def username_route(username):
    """
    Страница для обработки пользователя по `username`.
    Если пользователь существует, перенаправляем в профиль.
    Если нет, предлагаем зарегистрироваться.
    """
    ref = db.reference("users")
    users = ref.get() or {}

    # Проверяем, есть ли пользователь в базе
    for user_id, user_data in users.items():
        if user_data.get('username') == username:
            session['user_key'] = user_id
            session['username'] = username
            return redirect(url_for('profile'))

    # Если пользователь не найден, просим ввести логин
    if request.method == 'POST':
        nickname = request.form['nickname']
        #tg=request.form['nicknametg']

        # Сохраняем нового пользователя
        user_ref = ref.push()
        user_ref.set({
            'username': username,
            'nickname': nickname,
            'telegram': tg,
            'photo': None  # Можно загрузить позже
        })

        # Сохраняем сессию
        session['user_key'] = user_ref.key
        session['username'] = username
        return redirect(url_for('profile'))

    return render_template('register.html', username=username)


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    """
    Профиль пользователя с возможностью загрузки изображения.
    """
    user_key = session.get('user_key')
    if not user_key:
        return redirect(url_for('home'))

    ref = db.reference(f"users/{user_key}")
    user = ref.get()

    if request.method == 'POST':
        if 'photo' in request.files:
            photo = request.files['photo']
            if photo and allowed_file(photo.filename):
                # Сохраняем фото в папке static/uploads
                filename = secure_filename(f"{user['username']}_{photo.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(filepath)

                # Обновляем ссылку на фото в базе данных
                ref.update({'photo': f'uploads/{filename}'})
                return redirect(url_for('profile'))

    # Ссылка на фото, если оно есть
    photo_url = url_for('static', filename=user.get('photo')) if user.get('photo') else None
    return render_template('profile.html', user=user, photo_url=photo_url)



@app.route('/<username>/add_item', methods=['GET', 'POST'])
def add_item(username):
    """
    Страница добавления нового товара.
    """
    try:
        # Попытка найти пользователя по username
        users_ref = db.reference("users")
        user = None

        # Поиск пользователя по username
        all_users = users_ref.get()
        if all_users:
            for user_id, user_data in all_users.items():
                if user_data.get("username") == username:
                    user = user_data
                    break

        if not user:
            return "Пользователь не найден", 404

        # Если метод GET — возвращаем страницу добавления товара
        if request.method == 'GET':
            return render_template('add_item.html', username=username, nickname=user.get("nickname", username))

        # Если метод POST — обрабатываем добавление товара
        if request.method == 'POST':
            title = request.form.get('title')
            cover = request.files.get('cover')

            if not title or not cover:
                return "Все поля обязательны для заполнения", 400

            # Сохраняем обложку
            filename = secure_filename(f"{username}_{cover.filename}")
            cover_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            cover.save(cover_path)

            # Сохраняем данные товара в "pending_items"
            pending_items_ref = db.reference("pending_items")
            item_id = pending_items_ref.push({
                "title": title,
                "cover": filename,
                "username": username,
                "nickname": user.get("nickname", username)  # Используем никнейм, если он есть
            }).key

            return f"Товар отправлен на модерацию! ID: {item_id}"

    except Exception as e:
        print(f"Ошибка: {e}")
        return "Произошла ошибка при добавлении товара", 500




@app.route('/moderate_items')
def moderate_items():
    """
    Страница модерации товаров.
    """
    pending_items_ref = db.reference("pending_items")
    pending_items = pending_items_ref.get()

    if not pending_items:
        return "Нет товаров для модерации"

    return render_template('moderate_items.html', items=pending_items)




@app.route('/approve_item/<item_id>', methods=['POST'])
def approve_item(item_id):
    try:
        pending_items_ref = db.reference("pending_items")
        item = pending_items_ref.child(item_id).get()

        if not item:
            return "Товар не найден в базе данных", 404

        # Перенос товара
        items_ref = db.reference("items")
        items_ref.push(item)

        # Удаление из pending_items
        pending_items_ref.child(item_id).delete()

        return redirect('/moderate_items')  # Возврат на страницу модерации
    except Exception as e:
        logging.error(f"Ошибка при одобрении товара: {e}")
        return f"Произошла ошибка: {e}", 500



@app.route('/reject_item/<item_id>', methods=['POST'])
def reject_item(item_id):
    """
    Отклонение товара (удаление из "pending_items").
    """
    pending_items_ref = db.reference(f"pending_items/{item_id}")
    item = pending_items_ref.get()

    if not item:
        return "Товар не найден", 404

    # Удаляем товар
    pending_items_ref.delete()

    return f"Товар {item['title']} отклонен!"


@app.route('/items')
def view_items():
    """
    Страница для отображения всех товаров.
    """
    try:
        # Получаем список товаров из Firebase
        items_ref = db.reference("items")
        items = items_ref.get()

        # Если товаров нет, возвращаем пустую страницу
        if not items:
            items = {}

        # Преобразуем товары в список для удобной работы
        items_list = []
        for item_id, item_data in items.items():
            items_list.append({
                "id": item_id,
                "title": item_data.get("title"),
                "nickname": item_data.get("nickname"),
                "cover": item_data.get("cover")
            })

        return render_template('view_items.html', items=items_list)

    except Exception as e:
        print(f"Ошибка: {e}")
        return "Произошла ошибка при загрузке товаров", 500


@app.route('/item/<item_id>')
def item_detail(item_id):
    """
    Страница с подробной информацией о товаре.
    """
    try:
        # Получаем данные товара из Firebase
        item_ref = db.reference(f"items/{item_id}")
        item = item_ref.get()

        if not item:
            return "Товар не найден", 404

        # Добавляем ID товара в данные (если он отсутствует)
        item['id'] = item_id

        # Рендерим шаблон
        return render_template('item_detail.html', item=item)

    except Exception as e:
        print(f"Ошибка: {e}")
        return "Произошла ошибка при загрузке страницы", 500



@app.route('/pay/<item_id>')
def pay_item(item_id):
    YOOMONEY_TOKEN = "4100118365940760.B77CE578ADF382C40E41F9E9D902D726A867F7DDCCD0015FA093FA2E535A651A8DCD1C2359A36867D2C2EB8FD2A22789F9A844D10E49384068AA2B9346B63D9DC903B87A8C4D5C33436672BF7F3F494896E92640DA25248372976CA59BE0174BD76C64E998A4CD79AE47A9271D08E78FC96BA05F43C744D70FEB1927F8EA104E"
    RECEIVER_WALLET = "4100118365940760"
    """
    Обработчик оплаты товара и удаления из базы данных.
    """
     """
    Создание ссылки для оплаты товара через YooMoney.
    """
    if "user_key" not in session:
        return redirect(url_for("login"))  # Если пользователь не залогинен, отправляем на авторизацию

    # Уникальный идентификатор платежа
    payment_label = str(uuid.uuid4())

    quickpay = Quickpay(
        receiver=RECEIVER_WALLET,
        quickpay_form="shop",
        targets=f"Оплата товара {item_id}",
        paymentType="SB",
        sum=2,  # Укажите цену товара
        label=payment_label
    )

    # Сохраняем информацию о платеже в сессии
    session['payment_label'] = payment_label
    session['item_id'] = item_id

    return redirect(quickpay.base_url)




@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Сервис для отображения загруженных файлов. Используется для загрузки фото."""
    return send_from_directory(os.path.join(app.root_path, 'static/uploads'), filename)


@app.route('/')
def home():
    return render_template('home.html')


if __name__ == '__main__':
    app.run(debug=True)