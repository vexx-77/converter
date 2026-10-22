import sys
import subprocess
import importlib.util

# ==================================================
# АВТОУСТАНОВКА БИБЛИОТЕК И FFMPEG
# ==================================================
def _ensure_package(pip_name, import_name):
    if importlib.util.find_spec(import_name) is None:
        print(f"⏳ Устанавливаю {pip_name}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
            print(f"✅ {pip_name} установлен.")
        except subprocess.CalledProcessError:
            print(f"❌ Не удалось установить {pip_name}")
            sys.exit(1)

_ensure_package("pyTelegramBotAPI", "telebot")
_ensure_package("Pillow", "PIL")
_ensure_package("static-ffmpeg", "static_ffmpeg")

# Скачиваем и подключаем ffmpeg
import static_ffmpeg
static_ffmpeg.add_paths()

# ==================================================
# ОСНОВНОЙ КОД
# ==================================================
import os
import re
# ... дальше идет твой обычный код (import random, string и т.д.)
# ==================================================
# ОСНОВНОЙ КОД
# ==================================================
import os
import re
import random
import string
import time
import threading
import signal
import zipfile
import logging
import shutil

import telebot
from telebot import types
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

def signal_handler(sig, frame):
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")

# Токен берется напрямую из окружения
bot = telebot.TeleBot(os.getenv("TOKEN"))

pending_renames = {}
v2a_sessions = {}
user_pack_sessions = {}
audio_conv_sessions = {}

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

def log_action(user, action):
    username = f" (@{user.username})" if user.username else ""
    first_name = user.first_name or "Пользователь"
    logging.info(f"{first_name}{username} [{user.id}]: {action}")

def remove_path(path):
    if not path or not os.path.exists(path):
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    except Exception:
        pass

def clear_entire_temp():
    if os.path.exists(TEMP_DIR):
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            remove_path(file_path)

clear_entire_temp()

def auto_cleanup_files():
    while True:
        try:
            current_time = time.time()
            if os.path.exists(TEMP_DIR):
                for root, dirs, files in os.walk(TEMP_DIR, topdown=False):
                    for filename in files:
                        file_path = os.path.join(root, filename)
                        try:
                            if current_time - os.path.getmtime(file_path) > 900:
                                os.remove(file_path)
                        except Exception:
                            pass
                    for d in dirs:
                        dir_path = os.path.join(root, d)
                        try:
                            if os.path.isdir(dir_path) and not os.listdir(dir_path):
                                os.rmdir(dir_path)
                        except Exception:
                            pass

            for uid, session in list(user_pack_sessions.items()):
                try:
                    if "pack_dir" in session and os.path.exists(session["pack_dir"]) and current_time - os.path.getmtime(session["pack_dir"]) > 900:
                        remove_path(session["pack_dir"])
                        del user_pack_sessions[uid]
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"Ошибка в auto_cleanup_files: {e}")
        time.sleep(10)

threading.Thread(target=auto_cleanup_files, daemon=True).start()

def get_folder_stats():
    files_count = 0
    total_size = 0.0
    if os.path.exists(TEMP_DIR):
        for root, dirs, files in os.walk(TEMP_DIR):
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    files_count += 1
                    total_size += os.path.getsize(file_path)
                except Exception:
                    pass
    return files_count, total_size / (1024 * 1024)

def get_rename_keyboard(file_type, is_cropped=False, has_changes=False):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Изменить название", callback_data=f"rename_{file_type}_{1 if is_cropped else 0}_{int(time.time())}"))
    
    if file_type in ['ogg', 'mp3', 'm4a', 'wav']:
        markup.add(types.InlineKeyboardButton("Изменить автора", callback_data=f"edit_author_{file_type}_{int(time.time())}"))
        markup.add(types.InlineKeyboardButton("Удалить автора", callback_data=f"del_author_{file_type}_{int(time.time())}"))
        markup.add(types.InlineKeyboardButton("Изменить обложку", callback_data=f"edit_cover_{file_type}_{int(time.time())}"))
        markup.add(types.InlineKeyboardButton("Удалить обложку", callback_data=f"del_cover_{file_type}_{int(time.time())}"))
        if has_changes:
            markup.add(types.InlineKeyboardButton("Подтвердить ✅", callback_data=f"confirm_audio_{file_type}_{int(time.time())}"))
        
    return markup

def get_audio_conv_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("MP3", callback_data="audconv_mp3"),
        types.InlineKeyboardButton("M4A", callback_data="audconv_m4a"),
        types.InlineKeyboardButton("WAV", callback_data="audconv_wav"),
        types.InlineKeyboardButton("Голосовое (OGG)", callback_data="audconv_voice")
    )
    return markup

def check_button_expiry(call):
    parts = call.data.split("_")
    idx = 3 if len(parts) >= 4 else (2 if len(parts) >= 3 else -1)
    if idx != -1:
        try:
            btn_time = int(parts[idx])
            if int(time.time()) - btn_time > 900:
                bot.answer_callback_query(call.id, "Устаревшее сообщение", show_alert=True)
                return True
        except ValueError:
            pass
    return False

def generate_random_name(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_zip_password():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(10))

def clear_temp_files(*files):
    for file in files:
        remove_path(file)

def draw_progress_bar(pct, length=20):
    filled = int(round((pct / 100.0) * length))
    return "█" * filled + "░" * (length - filled)

def process_audio_conversion(chat_id, file_id, target_fmt):
    status_msg = bot.send_message(chat_id, "Конвертация...")
    rand_suffix = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
    input_audio = os.path.join(TEMP_DIR, f"conv_in_{rand_suffix}")
    
    try:
        file_info = bot.get_file(file_id)
        ext = file_info.file_path.split('.')[-1].lower()
        input_audio += f".{ext}"
        
        downloaded = bot.download_file(file_info.file_path)
        with open(input_audio, 'wb') as f:
            f.write(downloaded)
            
        out_audio = os.path.join(TEMP_DIR, f"conv_out_{rand_suffix}.{target_fmt if target_fmt != 'voice' else 'ogg'}")
        
        ff_cmd = ["ffmpeg", "-y", "-i", input_audio, "-vn"]
        
        if target_fmt == 'mp3':
            ff_cmd.extend(["-ar", "44100", "-ac", "2", "-b:a", "192k"])
        elif target_fmt == 'm4a':
            ff_cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        elif target_fmt == 'wav':
            ff_cmd.extend(["-c:a", "pcm_s16le"])
        elif target_fmt == 'voice':
            ff_cmd.extend(["-c:a", "libopus", "-b:a", "32k", "-vbr", "on"])
            
        ff_cmd.append(out_audio)
        subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(out_audio):
            if target_fmt == 'voice':
                with open(out_audio, 'rb') as f:
                    bot.send_voice(chat_id, f)
            else:
                with open(out_audio, 'rb') as f:
                    bot.send_audio(
                        chat_id, 
                        f, 
                        title="Converted_Audio", 
                        caption=f"`Converted.{target_fmt}`", 
                        parse_mode="Markdown",
                        reply_markup=get_rename_keyboard(target_fmt, False)
                    )
        else:
            bot.send_message(chat_id, "Ошибка конвертации.")
            
    except Exception as e:
        logging.error(f"Audio conversion error: {e}")
        bot.send_message(chat_id, "Системная ошибка при конвертации.")
    finally:
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass
        clear_temp_files(input_audio)
        if 'out_audio' in locals() and os.path.exists(out_audio):
            clear_temp_files(out_audio)

def process_standard_emoji(message, target_stk):
    log_action(message.from_user, f"Отправил стандартный эмодзи: {target_stk.emoji}")
    status_msg = bot.reply_to(message, "Обработка..")
    try:
        user_id = message.from_user.id
        rand_suffix = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
        base_name = f"{user_id}_std_emj_{rand_suffix}"
        
        f_info = bot.get_file(target_stk.file_id)
        d_file = bot.download_file(f_info.file_path)
        ext = f_info.file_path.split('.')[-1].lower()
        
        input_path = os.path.join(TEMP_DIR, f"{base_name}_in.{ext}")
        out_mp4 = os.path.join(TEMP_DIR, f"{base_name}_out.mp4")
        out_png = os.path.join(TEMP_DIR, f"{base_name}_frame.png")
        
        with open(input_path, 'wb') as f:
            f.write(d_file)
            
        if target_stk.is_animated:
            lottie_script = os.path.join(BASE_DIR, "lottie_convert.py")
            subprocess.run(["python", lottie_script, input_path, out_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif target_stk.is_video:
            subprocess.run(["ffmpeg", "-y", "-i", input_path, "-pix_fmt", "yuv420p", "-c:v", "libx264", out_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            bot.send_photo(message.chat.id, input_path)
            clear_temp_files(input_path)
            try:
                bot.delete_message(message.chat.id, status_msg.message_id)
            except Exception:
                pass
            return
            
        if os.path.exists(out_mp4):
            subprocess.run(["ffmpeg", "-y", "-i", out_mp4, "-vframes", "1", out_png], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(out_png):
                with open(out_png, 'rb') as f:
                    bot.send_photo(message.chat.id, f)
                    
            with open(out_mp4, 'rb') as f:
                bot.send_animation(message.chat.id, f)
                
            clear_temp_files(out_png, out_mp4)
            try:
                bot.delete_message(message.chat.id, status_msg.message_id)
            except Exception:
                pass
        else:
            bot.edit_message_text("Ошибка конвертации. (Проверьте работу скрипта lottie_convert.py и наличие ffmpeg)", message.chat.id, status_msg.message_id)
            
        clear_temp_files(input_path)
    except Exception as e:
        logging.error(f"Ошибка process_standard_emoji: {e}")
        try:
            bot.edit_message_text("Системная ошибка обработки.", message.chat.id, status_msg.message_id)
        except Exception:
            pass

def process_sticker_data(message, sticker, is_emoji=False):
    log_action(message.from_user, "Отправил стикер/эмодзи на конвертацию")
    status_msg = bot.reply_to(message, "Обработка..")
    
    user_id = message.from_user.id
    suffix = "emj" if is_emoji else "st"
    base_name = f"{user_id}_{suffix}"
    
    file_info = bot.get_file(sticker.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    ext = file_info.file_path.split('.')[-1].lower()
    
    rand_suffix = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
    input_path = os.path.join(TEMP_DIR, f"{base_name}_{rand_suffix}_in.{ext}")
    
    with open(input_path, 'wb') as new_file:
        new_file.write(downloaded_file)

    try:
        if not sticker.is_animated and not sticker.is_video:
            out_png = os.path.join(TEMP_DIR, f"{base_name}_out_{rand_suffix}.png")
            out_jpg = os.path.join(TEMP_DIR, f"{base_name}_out_{rand_suffix}.jpg")
            
            final_path = None
            final_ext = "png"
            
            try:
                im = Image.open(input_path).convert("RGBA")
                bbox = im.getbbox()
                if bbox:
                    im = im.crop(bbox)
                im.save(out_png, 'PNG')
                final_path = out_png
                final_ext = "png"
            except Exception:
                try:
                    im = Image.open(input_path).convert("RGB")
                    im.save(out_jpg, 'JPEG')
                    final_path = out_jpg
                    final_ext = "jpg"
                except Exception:
                    final_path = input_path
                    final_ext = ext

            with open(final_path, 'rb') as photo:
                bot.send_document(
                    message.chat.id, 
                    photo, 
                    visible_file_name=f"{base_name}.{final_ext}", 
                    caption=f"`{base_name}.{final_ext}`", 
                    parse_mode="Markdown", 
                    reply_markup=get_rename_keyboard(final_ext, True)
                )
            clear_temp_files(input_path, out_png, out_jpg)

        elif sticker.is_animated:
            orig_mp4 = os.path.join(TEMP_DIR, f"{base_name}_orig_{rand_suffix}.mp4")
            
            lottie_script = os.path.join(BASE_DIR, "lottie_convert.py")
            subprocess.run(["python", lottie_script, input_path, orig_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(orig_mp4):
                crop_mp4 = os.path.join(TEMP_DIR, f"{base_name}_crop_{rand_suffix}.mp4")
                
                detect_cmd = f"ffmpeg -i {orig_mp4} -vf cropdetect=limit=24:round=2 -vframes 5 -f null -"
                res = subprocess.run(detect_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                crop_param = ""
                for line in res.stderr.split('\n'):
                    if "crop=" in line:
                        crop_param = line.split("crop=")[-1].strip()
                        break
                
                if crop_param:
                    subprocess.run([
                        "ffmpeg", "-y", "-i", orig_mp4,
                        "-vf", f"crop={crop_param}",
                        "-pix_fmt", "yuv420p", "-c:v", "libx264", crop_mp4
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    final_video = crop_mp4 if os.path.exists(crop_mp4) else orig_mp4
                else:
                    final_video = orig_mp4

                with open(final_video, 'rb') as video:
                    bot.send_video(
                        message.chat.id, 
                        video, 
                        caption=f"`{base_name}.mp4`", 
                        parse_mode="Markdown", 
                        reply_markup=get_rename_keyboard("mp4", True)
                    )
                clear_temp_files(orig_mp4, crop_mp4)
            clear_temp_files(input_path)

        elif sticker.is_video:
            out_mp4 = os.path.join(TEMP_DIR, f"{base_name}_out_{rand_suffix}.mp4")
            
            detect_cmd = f"ffmpeg -i {input_path} -vf cropdetect=limit=24:round=2 -vframes 5 -f null -"
            res = subprocess.run(detect_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            crop_param = ""
            for line in res.stderr.split('\n'):
                if "crop=" in line:
                    crop_param = line.split("crop=")[-1].strip()
                    break
            
            ff_cmd = ["ffmpeg", "-y", "-i", input_path]
            if crop_param:
                ff_cmd.extend(["-vf", f"crop={crop_param}"])
            ff_cmd.extend(["-pix_fmt", "yuv420p", "-c:v", "libx264", out_mp4])
            
            subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(out_mp4):
                with open(out_mp4, 'rb') as video:
                    bot.send_video(
                        message.chat.id, 
                        video, 
                        caption=f"`{base_name}.mp4`", 
                        parse_mode="Markdown", 
                        reply_markup=get_rename_keyboard("mp4", True)
                    )
                clear_temp_files(out_mp4)
            clear_temp_files(input_path)

    except Exception as e:
        logging.error(f"Ошибка при обработке стикера: {e}")
        clear_temp_files(input_path)
    finally:
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass

def process_stickerpack_download(message, pack_name, is_emoji=False):
    item_type_ru = "эмодзи" if is_emoji else "стикеров"
    log_action(message.from_user, f"Запросил скачивание пака: {pack_name}")
    status_msg = bot.reply_to(message, f"Обработка: 0,0%\n{draw_progress_bar(0, 20)}")
    
    try:
        sticker_set = bot.get_sticker_set(pack_name)
    except Exception as e:
        logging.error(f"Ошибка получения пака {pack_name}: {e}")
        bot.edit_message_text(f"Не удалось найти пак {item_type_ru}.", message.chat.id, status_msg.message_id)
        return

    pack_title = sticker_set.title or pack_name
    safe_title = "".join(c for c in pack_title if c.isalnum() or c in (' ', '_', '-')).strip() or "pack"
    
    rand_id = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    pack_dir = os.path.join(TEMP_DIR, f"pack_{rand_id}")
    os.makedirs(pack_dir, exist_ok=True)
    
    total_items = len(sticker_set.stickers)
    file_paths = []
    
    last_update_time = 0

    for idx, stk in enumerate(sticker_set.stickers, start=1):
        f_info = bot.get_file(stk.file_id)
        d_file = bot.download_file(f_info.file_path)
        
        ext = f_info.file_path.split('.')[-1].lower()
        
        if not stk.is_animated and not stk.is_video:
            temp_in = os.path.join(pack_dir, f"temp_{idx}.{ext}")
            with open(temp_in, 'wb') as f:
                f.write(d_file)
            
            out_file = os.path.join(pack_dir, f"{idx:03d}.png")
            try:
                im = Image.open(temp_in).convert("RGBA")
                bbox = im.getbbox()
                if bbox:
                    im = im.crop(bbox)
                im.save(out_file, 'PNG')
                arc_name = f"{idx:03d}.png"
            except Exception:
                out_file = os.path.join(pack_dir, f"{idx:03d}.jpg")
                try:
                    im = Image.open(temp_in).convert("RGB")
                    im.save(out_file, 'JPEG')
                    arc_name = f"{idx:03d}.jpg"
                except Exception:
                    out_file = temp_in
                    arc_name = f"{idx:03d}.{ext}"
            
            if out_file != temp_in:
                clear_temp_files(temp_in)
            file_paths.append((out_file, arc_name))

        elif stk.is_animated or stk.is_video:
            temp_in = os.path.join(pack_dir, f"temp_{idx}.{ext}")
            with open(temp_in, 'wb') as f:
                f.write(d_file)
            
            out_mp4 = os.path.join(pack_dir, f"{idx:03d}.mp4")
            
            if stk.is_animated:
                lottie_script = os.path.join(BASE_DIR, "lottie_convert.py")
                subprocess.run(["python", lottie_script, temp_in, out_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["ffmpeg", "-y", "-i", temp_in, "-pix_fmt", "yuv420p", "-c:v", "libx264", out_mp4], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
            if os.path.exists(out_mp4):
                clear_temp_files(temp_in)
                file_paths.append((out_mp4, f"{idx:03d}.mp4"))
            else:
                file_paths.append((temp_in, f"{idx:03d}.{ext}"))

        curr_pct = (idx / total_items) * 100.0
        now = time.time()
        if now - last_update_time > 1.2 or idx == total_items:
            last_update_time = now
            p_bar = draw_progress_bar(curr_pct, 20)
            pct_str = f"{curr_pct:.1f}".replace(".", ",")
            try:
                bot.edit_message_text(
                    f"Обработка: {pct_str}%\n{p_bar}",
                    message.chat.id,
                    status_msg.message_id
                )
            except Exception:
                pass

    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception:
        pass

    user_pack_sessions[message.from_user.id] = {
        "pack_dir": pack_dir,
        "safe_title": safe_title,
        "file_paths": file_paths,
        "is_emoji": is_emoji
    }

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Отправить без пароля.", callback_data="pack_pass_none"))
    markup.add(types.InlineKeyboardButton("Задать пароль...", callback_data="pack_pass_set"))

    bot.send_message(
        message.chat.id,
        "Архив готов\nЗащитить паролем?",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data in ["pack_pass_none", "pack_pass_set"])
def handle_pass_option(call):
    user_id = call.from_user.id
    if user_id not in user_pack_sessions:
        bot.answer_callback_query(call.id, "Сессия истекла", show_alert=True)
        return

    if call.data == "pack_pass_none":
        finalize_archive_and_generate_key(call.message, user_id, password=None)
    elif call.data == "pack_pass_set":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Выбрать случайный пароль", callback_data="pack_pass_rand"))
        markup.add(types.InlineKeyboardButton("Отправить без пароля", callback_data="pack_pass_none"))
        
        user_pack_sessions[user_id]["waiting_custom_pass"] = True
        try:
            bot.edit_message_text(
                "Введите пароль или нажмите кнопки ниже:",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: call.data == "pack_pass_rand")
def handle_pass_rand(call):
    user_id = call.from_user.id
    if user_id not in user_pack_sessions:
        bot.answer_callback_query(call.id, "Сессия истекла", show_alert=True)
        return
    
    rnd_pass = generate_zip_password()
    finalize_archive_and_generate_key(call.message, user_id, password=rnd_pass)

def finalize_archive_and_generate_key(message, user_id, password=None):
    session = user_pack_sessions.get(user_id)
    if not session:
        return

    pack_dir = session["pack_dir"]
    safe_title = session["safe_title"]
    file_paths = session["file_paths"]

    rand_id = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    zip_name = f"{safe_title}_{rand_id}.zip"
    zip_path = os.path.join(TEMP_DIR, zip_name)

    if password:
        cmd_zip = f"7z a -tzip -p'{password}' -mx0 '{zip_path}' '{pack_dir}/*'"
        res = subprocess.run(cmd_zip, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            cmd_zip = f"zip -0 -P '{password}' -j '{zip_path}' '{pack_dir}'/*"
            subprocess.run(cmd_zip, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
            for f_path, arc_name in file_paths:
                zf.write(f_path, arc_name)

    del user_pack_sessions[user_id]

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    pass_text = f"\nПароль: `{password}`" if password else ""

    try:
        with open(zip_path, 'rb') as f:
            bot.send_document(
                message.chat.id,
                f,
                visible_file_name=zip_name,
                caption=f"Ваш архив: `{zip_name}`{pass_text}",
                parse_mode="Markdown"
            )
        remove_path(zip_path)
        remove_path(pack_dir)
        return
    except Exception as e:
        logging.error(f"Ошибка отправки архива: {e}")
        bot.send_message(
            message.chat.id,
            "Файл превышает лимит API, к сожалению выхода нет, воспользуйтесь другим ботом или сайтом."
        )
        remove_path(zip_path)
        remove_path(pack_dir)
        return

def process_video_to_stickers(chat_id, file_id):
    status_msg = bot.send_message(chat_id, "Обработка..")
    rand_suffix = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
    input_video = os.path.join(TEMP_DIR, f"v_stk_in_{rand_suffix}.mp4")
    out_anim = os.path.join(TEMP_DIR, f"stk_anim_{rand_suffix}.webm")
    out_static = os.path.join(TEMP_DIR, f"stk_static_{rand_suffix}.webp")

    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        with open(input_video, 'wb') as new_file:
            new_file.write(downloaded_file)

        ff_anim = [
            "ffmpeg", "-y", "-i", input_video,
            "-vf", "scale=512:512:force_original_aspect_ratio=decrease",
            "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-an", "-t", "3",
            out_anim
        ]
        subprocess.run(ff_anim, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        ff_static = [
            "ffmpeg", "-y", "-i", input_video,
            "-vframes", "1",
            "-vf", "scale=512:512:force_original_aspect_ratio=decrease",
            out_static
        ]
        subprocess.run(ff_static, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.path.exists(out_anim):
            with open(out_anim, 'rb') as stk:
                bot.send_sticker(chat_id, stk)

        if os.path.exists(out_static):
            with open(out_static, 'rb') as stk:
                bot.send_sticker(chat_id, stk)

    except Exception as e:
        logging.error(f"Ошибка конвертации видео в стикеры: {e}")
    finally:
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass
        clear_temp_files(input_video, out_anim, out_static)

@bot.message_handler(commands=['start'])
def send_start(message):
    log_action(message.from_user, "Запустил бота (/start)")
    text = (
        "Отправь стикер или премиум эмодзи, переделаю в png или video.\n"
        "Или отправь ссылку на стикерпак/эмодзипак, чтобы скачать его архивом.\n"
        "Или отправь мне видео/аудио/голосовое, и я помогу изменить его данные или конвертировать."
    )
    bot.reply_to(message, text)

@bot.message_handler(content_types=['sticker'])
def handle_sticker(message):
    process_sticker_data(message, message.sticker, is_emoji=False)

@bot.message_handler(content_types=['video', 'document', 'animation'])
def handle_video(message):
    file_id = None
    is_gif = False

    if message.animation:
        is_gif = True
        file_id = message.animation.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.document:
        mime = message.document.mime_type or ''
        fname = message.document.file_name or ''
        if mime == 'image/gif' or fname.lower().endswith('.gif'):
            is_gif = True
            file_id = message.document.file_id
        elif mime.startswith('video/'):
            file_id = message.document.file_id
    
    if not file_id:
        return

    if is_gif:
        log_action(message.from_user, "Отправил GIF на конвертацию в стикер")
        process_video_to_stickers(message.chat.id, file_id)
        return

    log_action(message.from_user, "Отправил видео/документ")
    user_id = message.from_user.id
    
    v2a_sessions[user_id] = {
        "file_id": file_id,
        "step": "waiting_action"
    }

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Аудио / гс", callback_data="v2a_act_audio"))
    markup.add(types.InlineKeyboardButton("Стикер", callback_data="v2a_act_sticker"))
    
    bot.reply_to(message, "Что сделать?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["v2a_act_audio", "v2a_act_sticker"])
def handle_v2a_action_choice(call):
    user_id = call.from_user.id
    if user_id not in v2a_sessions:
        bot.answer_callback_query(call.id, "Сессия истекла", show_alert=True)
        return

    file_id = v2a_sessions[user_id]["file_id"]

    if call.data == "v2a_act_audio":
        log_action(call.from_user, "Выбрал конвертацию видео в 'Аудио / гс'")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Пропустить", callback_data="v2aname_skip"))
        
        try:
            bot.edit_message_text(
                "Отправьте название файла или нажмите кнопку ниже...",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
        except Exception:
            pass
            
        v2a_sessions[user_id]["prompt_msg_id"] = call.message.message_id
        v2a_sessions[user_id]["step"] = "waiting_name"
        v2a_sessions[user_id]["custom_title"] = None
        bot.answer_callback_query(call.id)

    elif call.data == "v2a_act_sticker":
        log_action(call.from_user, "Выбрал конвертацию видео в 'Стикер'")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        del v2a_sessions[user_id]
        bot.answer_callback_query(call.id)
        process_video_to_stickers(call.message.chat.id, file_id)

@bot.callback_query_handler(func=lambda call: call.data == "v2aname_skip")
def handle_v2a_skip_name(call):
    user_id = call.from_user.id
    if user_id not in v2a_sessions:
        bot.answer_callback_query(call.id, "Сессия истекла", show_alert=True)
        return
        
    v2a_sessions[user_id]["custom_title"] = generate_random_name(10)
    v2a_sessions[user_id]["step"] = "waiting_format"
    
    send_v2a_format_keyboard(call.message.chat.id, user_id, call.message.message_id)
    bot.answer_callback_query(call.id)

def send_v2a_format_keyboard(chat_id, user_id, message_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("MP3", callback_data="v2afmt_mp3"),
        types.InlineKeyboardButton("M4A", callback_data="v2afmt_m4a"),
        types.InlineKeyboardButton("WAV", callback_data="v2afmt_wav")
    )
    markup.add(types.InlineKeyboardButton("Отправить как голосовое сообщение", callback_data="v2afmt_voice"))
    
    try:
        bot.edit_message_text("Выберите формат:", chat_id=chat_id, message_id=message_id, reply_markup=markup)
    except Exception:
        bot.send_message(chat_id, "Выберите формат:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("v2afmt_"))
def handle_v2a_format_choice(call):
    user_id = call.from_user.id
    if user_id not in v2a_sessions:
        bot.answer_callback_query(call.id, "Сессия истекла", show_alert=True)
        return

    fmt = call.data.split("_")[1]
    session = v2a_sessions[user_id]
    file_id = session["file_id"]
    title = session.get("custom_title") or generate_random_name(10)

    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass

    del v2a_sessions[user_id]
    bot.answer_callback_query(call.id)
    
    process_video_to_audio(call.message.chat.id, user_id, file_id, fmt, title)

def process_video_to_audio(chat_id, user_id, file_id, fmt, title):
    status_msg = bot.send_message(chat_id, "Обработка, подождите..")
    rand_suffix = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
    input_video = os.path.join(TEMP_DIR, f"v_in_{rand_suffix}.mp4")

    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        with open(input_video, 'wb') as new_file:
            new_file.write(downloaded_file)

        if fmt == "voice":
            out_audio = os.path.join(TEMP_DIR, f"v_out_{rand_suffix}.ogg")
            ff_cmd = [
                "ffmpeg", "-y", "-i", input_video,
                "-vn", "-c:a", "libopus", "-b:a", "32k", "-vbr", "on",
                out_audio
            ]
            subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(out_audio):
                with open(out_audio, 'rb') as voice:
                    bot.send_voice(chat_id, voice)
        else:
            out_audio = os.path.join(TEMP_DIR, f"{title}.{fmt}")
            ff_cmd = ["ffmpeg", "-y", "-i", input_video, "-vn"]
            
            if fmt == 'mp3':
                ff_cmd.extend(["-ar", "44100", "-ac", "2", "-b:a", "192k"])
            elif fmt == 'm4a':
                ff_cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            elif fmt == 'wav':
                ff_cmd.extend(["-c:a", "pcm_s16le"])

            ff_cmd.append(out_audio)
            subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(out_audio):
                with open(out_audio, 'rb') as audio:
                    bot.send_audio(
                        chat_id,
                        audio,
                        title=title,
                        performer=" ",
                        caption=f"`{title}.{fmt}`",
                        parse_mode="Markdown",
                        reply_markup=get_rename_keyboard(fmt, False)
                    )
    except Exception as e:
        logging.error(f"Ошибка конвертации видео в аудио: {e}")
    finally:
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    log_action(message.from_user, "Отправил голосовое сообщение")
    user_id = message.from_user.id
    audio_conv_sessions[user_id] = {"file_id": message.voice.file_id}
    
    bot.reply_to(
        message, 
        "Выберите формат для конвертации:", 
        reply_markup=get_audio_conv_keyboard()
    )

@bot.message_handler(content_types=['audio'])
def handle_audio(message):
    log_action(message.from_user, "Отправил аудиофайл")
    user_id = message.from_user.id
    audio_obj = message.audio
    
    orig_title = audio_obj.title if audio_obj.title else f"{user_id}_aud"
    orig_performer = audio_obj.performer if audio_obj.performer else " "
    
    file_info = bot.get_file(audio_obj.file_id)
    ext = file_info.file_path.split('.')[-1].lower()
    if ext not in ['ogg', 'mp3', 'm4a', 'wav']:
        ext = 'mp3'
        
    bot.send_audio(
        message.chat.id,
        audio_obj.file_id,
        title=orig_title,
        performer=orig_performer,
        caption=f"`{orig_title}.{ext}`",
        parse_mode="Markdown",
        reply_markup=get_rename_keyboard(ext, False)
    )
    
    audio_conv_sessions[user_id] = {"file_id": message.audio.file_id}
    bot.send_message(message.chat.id, "Хотите конвертировать в другой формат?", reply_markup=get_audio_conv_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("audconv_"))
def handle_audconv(call):
    user_id = call.from_user.id
    if user_id not in audio_conv_sessions:
        bot.answer_callback_query(call.id, "Сессия истекла", show_alert=True)
        return
    
    target_fmt = call.data.split("_")[1]
    file_id = audio_conv_sessions[user_id]["file_id"]
    
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
        
    process_audio_conversion(call.message.chat.id, file_id, target_fmt)

def process_cover_image(message, user_id, file_id, file_type, prompt_msg_id):
    if message.content_type == 'photo':
        photo_file = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(photo_file.file_path)
        rand_str = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
        img_path = os.path.join(TEMP_DIR, f"cover_{rand_str}.jpg")
        with open(img_path, 'wb') as f:
            f.write(downloaded)
            
        if user_id in pending_renames and pending_renames[user_id].get("state_file_id") == file_id:
            pending_renames[user_id]["cover_path"] = img_path
            pending_renames[user_id]["remove_cover"] = False
            current_title = pending_renames[user_id]["title"]
            current_performer = pending_renames[user_id]["performer"]
        else:
            current_title = f"{user_id}_aud"
            current_performer = " "
            pending_renames[user_id] = {
                "state_file_id": file_id,
                "title": current_title,
                "performer": current_performer,
                "cover_path": img_path,
                "remove_cover": False
            }
            
        try:
            bot.delete_message(message.chat.id, prompt_msg_id)
        except Exception:
            pass
            
        try:
            bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=pending_renames[user_id]["origin_msg_id"],
                caption=f"Название: `{current_title}`\nАвтор: `{current_performer}`\nОбложка: `Добавлена 🖼`",
                parse_mode="Markdown",
                reply_markup=get_rename_keyboard(file_type, False, has_changes=True)
            )
        except Exception:
            pass
    else:
        bot.reply_to(message, "Это не фото. Операция отменена.")
        if user_id in pending_renames and "action" in pending_renames[user_id]:
            del pending_renames[user_id]["action"]

@bot.message_handler(content_types=['text', 'photo', 'sticker'])
def handle_text_and_media(message):
    user_id = message.from_user.id
    
    if user_id in user_pack_sessions and user_pack_sessions[user_id].get("waiting_custom_pass"):
        if message.content_type == 'text':
            custom_pass = message.text.strip()
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except Exception:
                pass
            finalize_archive_and_generate_key(message, user_id, password=custom_pass)
            return

    if user_id in v2a_sessions and v2a_sessions[user_id]["step"] == "waiting_name":
        if message.content_type == 'text':
            custom_name = message.text.strip().replace("/", "_").replace("\\", "_")
            session = v2a_sessions[user_id]
            session["custom_title"] = custom_name
            session["step"] = "waiting_format"
            
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except Exception:
                pass

            send_v2a_format_keyboard(message.chat.id, user_id, session["prompt_msg_id"])
            return

    if user_id in pending_renames and "action" in pending_renames[user_id]:
        file_info = pending_renames[user_id]
        action = file_info["action"]
        file_id = file_info["file_id"]
        file_type = file_info["file_type"]
        prompt_msg_id = file_info["prompt_msg_id"]
        
        del pending_renames[user_id]["action"]
        
        if action == "cover":
            process_cover_image(message, user_id, file_id, file_type, prompt_msg_id)
            return
            
        if message.content_type != 'text':
            return
            
        input_text = message.text.strip()
        
        try:
            bot.delete_message(message.chat.id, prompt_msg_id)
        except Exception:
            pass
            
        if user_id not in pending_renames or pending_renames[user_id].get("state_file_id") != file_id:
            pending_renames[user_id] = {
                "state_file_id": file_id,
                "title": f"{user_id}_aud",
                "performer": " ",
                "cover_path": None,
                "remove_cover": False,
                "origin_msg_id": file_info["origin_msg_id"]
            }
            
        if action == "rename":
            new_name = input_text.replace("/", "_").replace("\\", "_")
            pending_renames[user_id]["title"] = new_name
        elif action == "author":
            pending_renames[user_id]["performer"] = input_text
            
        current_title = pending_renames[user_id]["title"]
        current_performer = pending_renames[user_id]["performer"]
        if pending_renames[user_id].get("remove_cover"):
            has_cover = "Удалена ❌"
        elif pending_renames[user_id]["cover_path"]:
            has_cover = "Добавлена 🖼"
        else:
            has_cover = "Оригинальная"
        
        if file_type in ['ogg', 'mp3', 'm4a', 'wav']:
            try:
                bot.edit_message_caption(
                    chat_id=message.chat.id,
                    message_id=file_info["origin_msg_id"],
                    caption=f"Название: `{current_title}`\nАвтор: `{current_performer}`\nОбложка: `{has_cover}`",
                    parse_mode="Markdown",
                    reply_markup=get_rename_keyboard(file_type, False, has_changes=True)
                )
            except Exception:
                pass
        else:
            new_name = current_title
            if not new_name.endswith(f".{file_type}"):
                new_name += f".{file_type}"
            status_msg = bot.reply_to(message, "Обработка..")
            try:
                info = bot.get_file(file_id)
                downloaded = bot.download_file(info.file_path)
                rand_str = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
                temp_path = os.path.join(TEMP_DIR, f"proc_{rand_str}_{new_name}")
                with open(temp_path, 'wb') as f:
                    f.write(downloaded)
                with open(temp_path, 'rb') as f:
                    bot.send_document(
                        message.chat.id, 
                        f, 
                        visible_file_name=new_name, 
                        caption=f"`{new_name}`", 
                        parse_mode="Markdown"
                    )
                clear_temp_files(temp_path)
            except Exception as e:
                logging.error(f"Ошибка сохранения документа: {e}")
            finally:
                try:
                    bot.delete_message(message.chat.id, status_msg.message_id)
                except Exception:
                    pass
            if user_id in pending_renames:
                del pending_renames[user_id]
        return

    if message.content_type == 'text':
        pack_match = re.search(r'(?:addstickers|addemoji)/([a-zA-Z0-9_]+)', message.text)
        if pack_match:
            pack_name = pack_match.group(1)
            is_emoji = "addemoji" in message.text
            process_stickerpack_download(message, pack_name, is_emoji=is_emoji)
            return

        # Прямой запрос ADMIN_ID из окружения без объявления глобальной переменной
        if user_id == int(os.getenv("ADMIN_ID", 0)) and message.text.lower() == 'кэш':
            files_count, size_mb = get_folder_stats()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Отчистить", callback_data="clear_cache"))
            bot.reply_to(message, f"Файлов: {files_count}\nВес: {size_mb:.2f} mb", reply_markup=markup)
            return

        if message.entities:
            for entity in message.entities:
                if entity.type == 'custom_emoji':
                    try:
                        stickers = bot.get_custom_emoji_stickers([entity.custom_emoji_id])
                        if stickers:
                            process_sticker_data(message, stickers[0], is_emoji=True)
                            return
                    except Exception as e:
                        logging.error(f"Ошибка с кастомным эмодзи: {e}")

        if not message.entities and len(message.text.strip()) <= 10:
            try:
                pack = bot.get_sticker_set("AnimatedEmojies")
                for stk in pack.stickers:
                    if stk.emoji == message.text.strip():
                        process_standard_emoji(message, stk)
                        return
            except Exception as e:
                logging.error(f"Ошибка проверки AnimatedEmojies: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("rename_") or call.data.startswith("edit_author_") or call.data.startswith("del_author_") or call.data.startswith("edit_cover_") or call.data.startswith("del_cover_"))
def handle_modification_clicks(call):
    if check_button_expiry(call):
        return

    parts = call.data.split("_")
    
    if parts[0] == "rename":
        action = "rename"
        file_type = parts[1]
        prompt_text = "Введите новое название файла:"
    elif parts[0] == "edit" and parts[1] == "author":
        action = "author"
        file_type = parts[2]
        prompt_text = "Введите имя автора (исполнителя):"
    elif parts[0] == "del" and parts[1] == "author":
        user_id = call.from_user.id
        msg = call.message
        file_id = msg.document.file_id if msg.document else (msg.video.file_id if msg.video else (msg.audio.file_id if msg.audio else None))
        if not file_id:
            bot.answer_callback_query(call.id, "Файл не найден", show_alert=True)
            return
        file_type = parts[2]
        
        if user_id not in pending_renames or pending_renames[user_id].get("state_file_id") != file_id:
            orig_title = msg.audio.title if (msg.audio and msg.audio.title) else f"{user_id}_aud"
            orig_performer = msg.audio.performer if (msg.audio and msg.audio.performer) else " "
            pending_renames[user_id] = {
                "state_file_id": file_id,
                "title": orig_title,
                "performer": orig_performer,
                "cover_path": None,
                "remove_cover": False,
                "origin_msg_id": msg.message_id
            }
        
        pending_renames[user_id]["performer"] = " "
        current_title = pending_renames[user_id]["title"]
        if pending_renames[user_id].get("remove_cover"):
            has_cover = "Удалена ❌"
        elif pending_renames[user_id]["cover_path"]:
            has_cover = "Добавлена 🖼"
        else:
            has_cover = "Оригинальная"
            
        try:
            bot.edit_message_caption(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                caption=f"Название: `{current_title}`\nАвтор: ` `\nОбложка: `{has_cover}`",
                parse_mode="Markdown",
                reply_markup=get_rename_keyboard(file_type, False, has_changes=True)
            )
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Автор удален")
        return
    elif parts[0] == "edit" and parts[1] == "cover":
        action = "cover"
        file_type = parts[2]
        prompt_text = "Отправьте фото."
    elif parts[0] == "del" and parts[1] == "cover":
        user_id = call.from_user.id
        msg = call.message
        file_id = msg.document.file_id if msg.document else (msg.video.file_id if msg.video else (msg.audio.file_id if msg.audio else None))
        if not file_id:
            bot.answer_callback_query(call.id, "Файл не найден", show_alert=True)
            return
        file_type = parts[2]
        
        if user_id not in pending_renames or pending_renames[user_id].get("state_file_id") != file_id:
            orig_title = msg.audio.title if (msg.audio and msg.audio.title) else f"{user_id}_aud"
            orig_performer = msg.audio.performer if (msg.audio and msg.audio.performer) else " "
            pending_renames[user_id] = {
                "state_file_id": file_id,
                "title": orig_title,
                "performer": orig_performer,
                "cover_path": None,
                "remove_cover": False,
                "origin_msg_id": msg.message_id
            }
        
        if pending_renames[user_id].get("cover_path"):
            clear_temp_files(pending_renames[user_id]["cover_path"])
            pending_renames[user_id]["cover_path"] = None
        pending_renames[user_id]["remove_cover"] = True
        
        current_title = pending_renames[user_id]["title"]
        current_performer = pending_renames[user_id]["performer"]
        
        try:
            bot.edit_message_caption(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                caption=f"Название: `{current_title}`\nАвтор: `{current_performer}`\nОбложка: `Удалена ❌`",
                parse_mode="Markdown",
                reply_markup=get_rename_keyboard(file_type, False, has_changes=True)
            )
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Обложка удалена")
        return
    else:
        return
    
    msg = call.message
    file_id = None
    
    if msg.document:
        file_id = msg.document.file_id
    elif msg.video:
        file_id = msg.video.file_id
    elif msg.audio:
        file_id = msg.audio.file_id
        
    if not file_id:
        return
        
    user_id = call.from_user.id
    
    cancel_markup = types.InlineKeyboardMarkup()
    cancel_markup.add(types.InlineKeyboardButton("Отмена", callback_data="cancel_rename"))
    
    prompt_msg = bot.send_message(
        chat_id=msg.chat.id,
        text=prompt_text,
        reply_to_message_id=msg.message_id,
        reply_markup=cancel_markup
    )
    
    if user_id not in pending_renames or pending_renames[user_id].get("state_file_id") != file_id:
        orig_title = msg.audio.title if (msg.audio and msg.audio.title) else f"{user_id}_aud"
        orig_performer = msg.audio.performer if (msg.audio and msg.audio.performer) else " "
        pending_renames[user_id] = {
            "state_file_id": file_id,
            "title": orig_title,
            "performer": orig_performer,
            "cover_path": None,
            "remove_cover": False,
            "origin_msg_id": msg.message_id
        }
    
    pending_renames[user_id]["action"] = action
    pending_renames[user_id]["file_id"] = file_id
    pending_renames[user_id]["file_type"] = file_type
    pending_renames[user_id]["prompt_msg_id"] = prompt_msg.message_id
    pending_renames[user_id]["origin_msg_id"] = msg.message_id
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_audio_"))
def handle_confirm_audio(call):
    if check_button_expiry(call):
        return
        
    user_id = call.from_user.id
    if user_id not in pending_renames:
        bot.answer_callback_query(call.id, "Данные не найдены", show_alert=True)
        return
        
    file_info = pending_renames[user_id]
    file_id = file_info["state_file_id"]
    file_type = call.data.split("_")[2]
    
    status_msg = bot.send_message(call.message.chat.id, "Применение изменений..", reply_to_message_id=file_info["origin_msg_id"])
    bot.answer_callback_query(call.id)
    
    try:
        info = bot.get_file(file_id)
        downloaded = bot.download_file(info.file_path)
        rand_str = ''.join(random.choice(string.ascii_lowercase) for _ in range(5))
        
        orig_filename = info.file_path.split('/')[-1]
        if not orig_filename.endswith(f".{file_type}"):
            orig_filename += f".{file_type}"
            
        temp_path = os.path.join(TEMP_DIR, f"proc_{rand_str}_{orig_filename}")
        with open(temp_path, 'wb') as f:
            f.write(downloaded)
            
        new_name = file_info["title"]
        if not new_name.endswith(f".{file_type}"):
            new_name += f".{file_type}"
            
        out_path = os.path.join(TEMP_DIR, f"final_{rand_str}_{orig_filename}")
        
        ff_cmd = ["ffmpeg", "-y", "-i", temp_path]
        if file_info.get("cover_path"):
            ff_cmd.extend(["-i", file_info["cover_path"]])
            
        ff_cmd.extend([
            "-metadata", f"title={file_info['title']}",
            "-metadata", f"artist={file_info['performer']}",
            "-metadata", f"performer={file_info['performer']}"
        ])
        
        if file_info.get("cover_path"):
            ff_cmd.extend([
                "-map", "0:0", "-map", "1:0", "-c", "copy", "-id3v2_version", "3",
                "-metadata:s:v", "title=\"Album cover\"", "-metadata:s:v", "comment=\"Cover (Front)\""
            ])
        elif file_info.get("remove_cover"):
            ff_cmd.extend([
                "-map", "0:a", "-c:a", "copy", "-map_metadata", "-1",
                "-metadata", f"title={file_info['title']}",
                "-metadata", f"artist={file_info['performer']}",
                "-metadata", f"performer={file_info['performer']}"
            ])
        else:
            ff_cmd.extend(["-c", "copy"])
            
        ff_cmd.append(out_path)
        
        subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        final_send = out_path if os.path.exists(out_path) else temp_path
        
        with open(final_send, 'rb') as f:
            bot.send_audio(
                call.message.chat.id,
                f,
                title=file_info['title'],
                performer=file_info['performer'],
                caption=f"`{new_name}`",
                parse_mode="Markdown",
                reply_markup=get_rename_keyboard(file_type, False)
            )
            
        clear_temp_files(temp_path, out_path, file_info.get("cover_path"))
        del pending_renames[user_id]
        
        try:
            bot.delete_message(call.message.chat.id, file_info["origin_msg_id"])
        except Exception:
            pass
    except Exception as e:
        logging.error(f"Ошибка сохранения изменений аудио: {e}")
    finally:
        try:
            bot.delete_message(call.message.chat.id, status_msg.message_id)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: call.data == "cancel_rename")
def handle_cancel_rename(call):
    user_id = call.from_user.id
    if user_id in pending_renames and "action" in pending_renames[user_id]:
        del pending_renames[user_id]["action"]
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "clear_cache")
def handle_clear_cache(call):
    if call.from_user.id != int(os.getenv("ADMIN_ID", 0)):
        return
    clear_entire_temp()
    files_count, size_mb = get_folder_stats()
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Файлов: {files_count}\nВес: {size_mb:.2f} mb",
            reply_markup=types.InlineKeyboardMarkup()
        )
    except Exception:
        pass

if __name__ == '__main__':
    logging.info("Бот запущен.")
    bot.infinity_polling()
