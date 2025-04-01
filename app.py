import os
import requests
import polyline
from requests.exceptions import RequestException

from dotenv import load_dotenv

load_dotenv()  
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def get_route(origin, destination):
    """Obtém a rota da API do Google Maps Directions com tratamento robusto de erros."""
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        'origin': origin,
        'destination': destination,
        'key': GOOGLE_MAPS_API_KEY
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('status') != 'OK':
            print(f"Erro na API Google Maps: {data.get('error_message', data.get('status'))}")
            return None
        return data['routes'][0]
    except RequestException as e:
        print(f"Erro de rede ao obter rota: {str(e)}")
        return None

def extract_route_coordinates(route):
    """Extrai coordenadas de todos os passos da rota para máxima precisão."""
    coordinates = []
    for leg in route.get('legs', []):
        for step in leg.get('steps', []):
            polyline_str = step['polyline']['points']
            coordinates.extend(polyline.decode(polyline_str))
    return coordinates

def select_waypoints(coordinates, max_points=15):
    """Seleciona waypoints garantindo um número máximo para evitar excesso de chamadas."""
    step = max(1, len(coordinates) // max_points)
    return coordinates[::step]

def get_weather(lat, lon):
    """Obtém dados climáticos com tratamento avançado de erros."""
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

def generate_travel_summary(route_info, weather_reports):
    """Gera um resumo narrativo da viagem usando IA com fallback para dados brutos."""
    if not route_info.get('legs'):
        return "Não foi possível gerar o resumo: dados da rota incompletos."
    
    leg = route_info['legs'][0]
    base_summary = (
        f"## Resumo da Viagem ##\n"
        f"**Origem:** {leg['start_address']}\n"
        f"**Destino:** {leg['end_address']}\n"
        f"**Distância:** {leg['distance']['text']}\n"
        f"**Duraçāo estimada:** {leg['duration']['text']}\n\n"
    )
    
    if weather_reports:
        base_summary += "## Previsão do Tempo nas Principais Paradas ##\n"
        for weather in weather_reports:
            base_summary += f"- {weather['city']}: {weather['description']}, {weather['temperature']}°C\n"
    else:
        base_summary += "\n⚠️ Nāo foi possível obter dados meteorológicos para esta rota."

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-70b-8192",
        "messages": [{
            "role": "system",
            "content": "Você é um assistente de viagem especializado em criar relatórios detalhados e acolhedores."
        }, {
            "role": "user",
            "content": f"Transforme estes dados técnicos em um guia de viagem completo:\n\n{base_summary}"
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
        return f"{base_summary}\n\n[Erro na geração do relatório: {str(e)}]"

def main():
    """Fluxo principal do programa com interface amigável."""
    print("\n" + "="*40)
    print(" Planejador de Viagem Inteligente ")
    print("="*40 + "\n")
    
    origin = input("📍 Cidade de origem: ").strip()
    destination = input("🎯 Cidade de destino: ").strip()
    
    if not (route := get_route(origin, destination)):
        print("\n🚨 Erro: Não foi possível calcular a rota. Verifique os locais informados.")
        return

    coordinates = extract_route_coordinates(route)
    waypoints = select_waypoints(coordinates)
    
    print(f"\n⏳ Coletando dados meteorológicos para {len(waypoints)} paradas...")
    weather_reports = [report for report in (get_weather(lat, lon) for lat, lon in waypoints) if report]
    
    print("\n✨ Gerando relatório final...")
    summary = generate_travel_summary(route, weather_reports)
    
    print("\n" + "="*40)
    print(" Relatório de Viagem ")
    print("="*40)
    print(summary)

if __name__ == "__main__":
    main()