import requests
from datetime import datetime, timedelta

from telegram import ReplyKeyboardMarkup, Update, ReplyKeyboardRemove
from telegram.ext import CommandHandler, ApplicationBuilder, ContextTypes, MessageHandler, filters, ConversationHandler
from pymongo import MongoClient
import matplotlib.pyplot as plt
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')

SET_CITY = 1


async def set_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Inviami il nome della città da salvare.")
    return SET_CITY


async def save_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text
    context.user_data["city"] = city

    keyboard = [
        ["📊 Mostra grafico", "📍 Imposta città"],
        ["ℹ️ Info", "Forcast", "Grafico PGD", "❌ Chiudi"]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        f"✅ Città impostata: *{city.title()}*",
        parse_mode="Markdown",
        reply_markup=markup
    )


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operazione annullata.")
    return ConversationHandler.END


def get_coordinates(city_name):
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={city_name}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)

    try:
        data = response.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
        else:
            return None, None
    except Exception as e:
        print(f"Errore nella decodifica JSON: {e}")
        return None, None


def get_weather(city_name):
    lat, lon = get_coordinates(city_name)
    if lat is None:
        return f"❌ Città non trovata: {city_name}"

    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
    data = requests.get(url).json()
    current = data.get("current_weather", {})
    time = datetime.now().strftime('%H:%M')

    return (f"📍 Meteo per *{city_name.title()}*\n"
            f"🌡 Temperatura: {current.get('temperature')}°C\n"
            f"💨 Vento: {current.get('windspeed')} km/h\n"
            f"🕒 Orario: {time}")


def save_to_mongo(city, weather):
    client = MongoClient('localhost', 27017)
    db = client["weather_db"]
    collection = db["daily_weather"]
    weather['city'] = city
    collection.insert_one(weather)


#Create Graph looking day params
def create_grafico(city, day):
    lat, lon = get_coordinates(city)
    if lat is None or lon is None:
        return f"❌ Città non trovata: {city}"

    end = datetime.now()
    start = end - timedelta(hours=24)
    start_str = start.strftime('%Y-%m-%dT%H:%M')
    end_str = end.strftime('%Y-%m-%dT%H:%M')

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m&start={start_str}&end={end_str}&timezone=auto"
    )

    response = requests.get(url).json()

    filtered_times = []
    filtered_temps = []

    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    if day == 'today':
        for t, temp in zip(response["hourly"]["time"], response["hourly"]["temperature_2m"]):
            if t.startswith(today.isoformat()):
                filtered_times.append(datetime.fromisoformat(t))
                filtered_temps.append(temp)
    elif day == 'tomorrow':
        for t, temp in zip(response["hourly"]["time"], response["hourly"]["temperature_2m"]):
            if t.startswith(tomorrow.isoformat()):
                filtered_times.append(datetime.fromisoformat(t))
                filtered_temps.append(temp)

    df = pd.DataFrame({
        "time": filtered_times,
        "temperature": filtered_temps
    })

    df["hour"] = df["time"].dt.strftime("%H:%M")

    if day == 'tomorrow':
        today = tomorrow
    plt.figure(figsize=(10, 5))
    plt.plot(df["hour"], df["temperature"], marker="o", linestyle="-", color="blue")
    plt.xticks(rotation=45)
    plt.title(f"Temperatura oraria ({today})")
    plt.xlabel("Orario")
    plt.ylabel("Temperatura (°C)")
    plt.grid(True)
    plt.tight_layout()

    filename = f"{city.title()}_{today}_Grafico.png"
    plt.savefig(filename)
    plt.close()

    print(f"✅ Grafico salvato come: {filename}")
    return filename


#Temp handler
async def temp(update, context):
    if context.args:
        city = " ".join(context.args)
    else:
        city = context.user_data.get("city")

    if not city:
        await update.message.reply_text(
            "❗ Usa il comando così: /temp NomeCittà oppure imposta una città con 📍 Imposta città.")
        return

    message = get_weather(city)
    await update.message.reply_text(message, parse_mode="Markdown")


#Make Graph for today temp
async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        city = " ".join(context.args)
    else:
        city = context.user_data.get("city")

    if not city:
        await update.message.reply_text("❗ Prima imposta una città cliccando su 📍 Imposta città.")
        return

    img_grafico = create_grafico(city, "today")
    if img_grafico:
        with open(img_grafico, "rb") as f:
            await update.message.reply_photo(f, caption=f"📊 Temperatura a {city.title()} (ultime 24h)")
    else:
        await update.message.reply_text("⚠️ Errore nella creazione del grafico.")


# Send an API calls to get the weather data
def get_forcast(city):
    lat, lon = get_coordinates(city)
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max"
        f"&timezone=auto"
    )
    if lat is None:
        return f"❌ Città non trovata: {city}"

    response = requests.get(url)
    data = response.json().get("daily", {})
    if not data:
        return "⚠️ Nessun dato meteo disponibile."

    today_index = 0
    date = data['time'][today_index]
    t_max = data['temperature_2m_max'][today_index]
    t_min = data['temperature_2m_min'][today_index]
    rain = data['precipitation_sum'][today_index]
    wind = data['windspeed_10m_max'][today_index]

    data_g = date.format('%d-%m-%Y')

    return (f"📅 Meteo per *{city.title()}* il {data_g}:\n"
            f"🔺 Max: {t_max}°C\n"
            f"🔻 Min: {t_min}°C\n"
            f"🌧 Pioggia: {rain} mm\n"
            f"💨 Vento max: {wind} km/h")


#Set and return the forcast
async def forcast(update, context):
    if context.args:
        city = " ".join(context.args)
    else:
        city = context.user_data.get("city")

    if not city:
        await update.message.reply_text("❗ Usa il comando così: /forcast NomeCittà")
    msg = get_forcast(city)
    await update.message.reply_text(msg, parse_mode="Markdown")


#Function to handle the /start message
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📊 Mostra grafico", "📍 Imposta città"],
        ["ℹ️ Info", "Forcast", "Grafico PGD", "❌ Chiudi"]
    ]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Ciao! Sono il bot meteo. Scegli un'opzione:",
        reply_markup=markup
    )


#Closing the keyboard
async def close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Tastiera rimossa. Scrivi /start per riattivarla.",
        reply_markup=ReplyKeyboardRemove()
    )


#Function for create a graph for tomorrow temp
async def grafico_after(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        city = " ".join(context.args)
    else:
        city = context.user_data.get("city")

    if not city:
        await update.message.reply_text("❗ Prima imposta una città cliccando su 📍 Imposta città.")
        return

    img_grafico = create_grafico(city, "tomorrow")
    if img_grafico:
        with open(img_grafico, "rb") as f:
            await update.message.reply_photo(f, caption=f"📊 Temperatura a {city.title()} (prossime 24h)")
    else:
        await update.message.reply_text("⚠️ Errore nella creazione del grafico.")


#Main function-I use it to set the message handler
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📊 Mostra grafico$"), grafico))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^ℹ️ Info$"), temp))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^❌ Chiudi$"), close))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Forcast$"), forcast))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^Grafico PGD$"), grafico_after))

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & filters.Regex("^📍 Imposta città$"), set_city)],
        states={SET_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_city)]},
        fallbacks=[CommandHandler("annulla", back)]
    )

    app.add_handler(conv_handler)
    app.run_polling()


if __name__ == '__main__':
    main()
