from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import os
import requests
import polyline
import urllib.parse
from pymongo import MongoClient
from dotenv import load_dotenv
from requests.exceptions import RequestException
from datetime import datetime

# Constants for cost calculations
CUSTO_AGUA_POR_PARADA = 4.0  # Cost of water per stop
CUSTO_COMIDA_POR_PARADA = 20.0  # Cost of food per stop
TEMPERATURA_ALTA = 30  # Temperature threshold for AC use
AC_AUMENTO_PORC = 0.10  # Extra fuel cost when AC is used

# Fuel efficiency for different vehicles (liters per km)
VEHICLE_EFFICIENCY = {
    "carro": 0.083,  # 12 km per liter
    "moto": 0.033,   # 30 km per liter
    "caminhao": 0.2, # 5 km per liter
    "motocicleta": 0.033,
}

# Load environment variables from .env file
load_dotenv(dotenv_path=".env", override=True)
mongo_url = os.getenv("MONGO_URL")
GASOLINE_PRICE = float(os.getenv("GASOLINE_PRICE", 6.0))  # Default R$6 per liter

# Connect to MongoDB
try:
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)
    client.server_info()
    db = client["cidades"]
    historico_collection = db["historico"]
except Exception:
    historico_collection = None  # Set to None if connection fails

# Set up Flask app
app = Flask(__name__)
CORS(app, resources={r"/plan_viagem": {"origins": "*"}})

# API keys from environment
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Calculate trip costs (fuel, water, food)
def calcular_gastos(route_info, weather_reports, veiculo):
    if not route_info.get('legs'):
        return {"erro": "Dados da rota incompletos."}

    # Get distance in km
    distancia_km = float(route_info['legs'][0]['distance']['text'].replace(' km', '').replace(',', '.'))
    clima_quente = any(w['temperature'] >= TEMPERATURA_ALTA for w in weather_reports)

    # Calculate fuel cost based on vehicle type
    veiculo_key = veiculo.lower()
    if veiculo_key not in VEHICLE_EFFICIENCY:
        veiculo_key = "carro"  # Default to car if vehicle not recognized
    litros_por_km = VEHICLE_EFFICIENCY[veiculo_key]
    litros_totais = distancia_km * litros_por_km
    custo_gasolina = litros_totais * GASOLINE_PRICE

    if clima_quente:
        custo_gasolina *= (1 + AC_AUMENTO_PORC)  # Increase fuel cost if hot

    # Estimate number of stops (1 per 100 km, at least 1)
    qtd_paradas = max(1, int(distancia_km // 100))
    qtd_paradas = min(qtd_paradas, len(weather_reports))
    custo_agua = qtd_paradas * CUSTO_AGUA_POR_PARADA
    custo_comida = qtd_paradas * CUSTO_COMIDA_POR_PARADA

    return {
        "gasolina": round(custo_gasolina, 2),
        "agua": round(custo_agua, 2),
        "comida": round(custo_comida, 2),
        "total": round(custo_gasolina + custo_agua + custo_comida, 2)
    }

# Get route from Google Maps API
def get_route(origin, destination):
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        'origin': origin,
        'destination': destination,
        'key': GOOGLE_MAPS_API_KEY,
        'language': 'pt-BR',
        'region': 'br'
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('status') != 'OK':
            return None
        return data['routes'][0]
    except RequestException:
        return None

# Extract coordinates from route for weather checks
def extract_route_coordinates(route):
    coordinates = []
    for leg in route.get('legs', []):
        for step in leg.get('steps', []):
            polyline_str = step['polyline']['points']
            coordinates.extend(polyline.decode(polyline_str))
    return coordinates

# Select key points along the route
def select_waypoints(coordinates, max_points=15):
    step = max(1, len(coordinates) // max_points)
    return coordinates[::step]

# Get weather for a specific location
def get_weather(lat, lon):
    url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        'lat': lat,
        'lon': lon,
        'appid': OPENWEATHER_API_KEY,
        'units': 'metric',
        'lang': 'pt'
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("cod") != 200 or not data.get("weather"):
            return None
        return {
            "city": data.get("name", "Local desconhecido"),
            "description": data['weather'][0]['description'].capitalize(),
            "temperature": data['main']['temp']
        }
    except RequestException:
        return None

# Create a detailed travel summary
def generate_travel_summary(route_info, weather_reports, veiculo, destination, gastos=None):
    if not route_info.get('legs'):
        return "Não foi possível gerar o resumo: dados da rota incompletos."

    leg = route_info['legs'][0]
    base_summary = (
        f"## Resumo da Viagem ##\n"
        f"**Origem:** {leg['start_address']}\n"
        f"**Destino:** {leg['end_address']}\n"
        f"**Distância:** {leg['distance']['text']}\n"
        f"**Duraçāo estimada:** {leg['duration']['text']}\n"
        f"**Veículo:** {veiculo}\n\n"
    )

    if weather_reports:
        base_summary += "## Previsão do Tempo nas Principais Paradas ##\n"
        for weather in weather_reports:
            base_summary += f"- {weather['city']}: {weather['description']}, {weather['temperature']}°C\n"
    else:
        base_summary += "\n⚠️ Não foi possível obter dados meteorológicos para esta rota."

    if gastos and veiculo.lower() in ["carro", "moto", "caminhão", "caminhao", "motocicleta"]:
        base_summary += (
            "\n\n## Estimativa de Gastos ##\n"
            f"- Gasolina: R$ {gastos['gasolina']:.2f}\n"
            f"- Água: R$ {gastos['agua']:.2f}\n"
            f"- Comida: R$ {gastos['comida']:.2f}\n"
            f"**Total estimado:** R$ {gastos['total']:.2f}\n"
        )

    # Ask Groq API for a personalized guide
    prompt = (
        f"Você é um assistente de viagem especializado em criar guias detalhados, personalizados e acolhedores em português. "
        f"Transforme os dados técnicos abaixo em um guia de viagem completo para o destino '{destination}'. "
        f"Use formatação Markdown para destacar seções e pontos importantes (ex.: **Título**, *itálico*). "
        f"Inclua:\n"
        f"- Uma introdução amigável sobre a viagem.\n"
        f"- Pontos turísticos e atrações imperdíveis no destino.\n"
        f"- Dicas de segurança (ex.: áreas ou horários a evitar).\n"
        f"- Informações sobre custos (ex.: se a cidade é cara por ser turística).\n"
        f"- Sugestões de restaurantes ou atividades locais.\n"
        f"- Dicas específicas para quem viaja de {veiculo} (ex.: estacionamento, manutenção).\n\n"
        f"Dados técnicos:\n{base_summary}"
    )

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-70b-8192",
        "messages": [{
            "role": "system",
            "content": "Você é um assistente de viagem especializado em criar relatórios detalhados e acolhedores."
        }, {
            "role": "user",
            "content": prompt
        }],
        "temperature": 0.5
    }

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=15
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        # Fallback if Groq API fails
        fallback_summary = (
            f"{base_summary}\n\n"
            f"## Dicas para sua Viagem ##\n"
            f"Não conseguimos gerar um guia completo, mas aqui vão algumas dicas gerais:\n"
            f"- Pesquise pontos turísticos em {destination} para aproveitar ao máximo.\n"
            f"- Evite áreas desconhecidas à noite e mantenha seus pertences seguros.\n"
            f"- Verifique os preços locais, pois algumas cidades turísticas podem ser mais caras.\n"
        )
        return fallback_summary

# Serve the main page
@app.route('/')
def index():
    return render_template('index.html', google_maps_key=os.getenv("GOOGLE_MAPS_API_KEY"))

# equestes
@app.route('/plan_viagem', methods=['POST'])
def plan_viagem():
    data = request.get_json()
    origin = data.get('origem')
    destination = data.get('destino')
    veiculo = data.get('veiculo', 'carro')
    
    if not origin or not destination:
        return jsonify({"error": "Parâmetros 'origem' e 'destino' são obrigatórios"}), 400
    
    route = get_route(origin, destination)
    if not route:
        return jsonify({"error": "Não foi possível calcular a rota"}), 400
    
    coordinates = extract_route_coordinates(route)
    waypoints = select_waypoints(coordinates)
    
    weather_reports = [report for report in (get_weather(lat, lon) for lat, lon in waypoints) if report]
    gastos = calcular_gastos(route, weather_reports, veiculo)
    summary = generate_travel_summary(route, weather_reports, veiculo, destination, gastos)

    # Save trip to MongoDB
    if historico_collection is not None:
        try:
            historico_collection.insert_one({
                "origem": origin,
                "destino": destination,
                "veiculo": veiculo,
                "data": datetime.now()
            })
        except Exception as e:
            return jsonify({"error": f"Erro ao salvar no banco de dados: {str(e)}"}), 500
    
    response = {
        "polyline": route.get('overview_polyline', {}).get('points', ''),
        "summary": summary,
        "origin": origin,
        "destination": destination,
        "veiculo": veiculo
    }
    return jsonify(response)

# Show trip history
@app.route('/historico', methods=['GET'])
def mostrar_historico():
    if historico_collection is None:
        return jsonify({"error": "Não foi possível conectar ao banco de dados MongoDB"}), 500
    try:
        registros = list(
            historico_collection.find({}, {"_id": 0, "origem": 1, "destino": 1, "data": 1}).sort("data", -1)
        )
        return jsonify(registros)
    except Exception as e:
        return jsonify({"error": f"Erro ao acessar o histórico: {str(e)}"}), 500

# favicon
@app.route('/favicon.ico')
def favicon():
    return "", 204

# erros handling
@app.errorhandler(Exception)
def handle_error(error):
    return jsonify({"error": f"Erro interno do servidor: {str(error)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)