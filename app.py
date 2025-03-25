import requests
import polyline

###
### APIS 
###
def get_route(origin, destination):
    """
    Consulta a API do Google Maps Directions e retorna a rota.
    """
    url = (
        f"https://maps.googleapis.com/maps/api/directions/json?"
        f"origin={origin}&destination={destination}&key={GOOGLE_MAPS_API_KEY}"
    )
    response = requests.get(url)
    data = response.json()
    if data.get('status') != 'OK':
        print("Erro ao obter rota:", data.get('error_message', data.get('status')))
        return None
    return data['routes'][0]

def decode_route_polyline(polyline_str):
    """
    Decodifica a polyline da rota para uma lista de coordenadas (latitude, longitude).
    """
    return polyline.decode(polyline_str)

def select_waypoints(coordinates, step=50):  
    return coordinates[::step] if len(coordinates) > step else coordinates

def get_weather(lat, lon):
    """
    Consulta a API do OpenWeather para obter informações do tempo para uma dada coordenada.
    """
    url = (
        f"http://api.openweathermap.org/data/2.5/weather?"
            f"lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric&lang=pt"
    )
    response = requests.get(url)
    data = response.json()
    if data.get("cod") != 200:
        return None
    return {
        "city": data.get("name", "Local desconhecido"),
        "description": data["weather"][0]["description"],
        "temperature": data["main"]["temp"]
    }

def generate_friendly_text(route_info, weather_reports):
    """
    Compila informações da rota e dos climas e envia para a API da Groq
    """
    leg = route_info['legs'][0]
    summary = (
        f"Resumo da Rota:\n"
        f"De: {leg['start_address']} para {leg['end_address']}\n"
        f"Distância: {leg['distance']['text']}\n"
        f"Duração: {leg['duration']['text']}\n\n"
        "Condições do tempo nas paradas selecionadas:\n"
    )
    for w in weather_reports:
        if w:
            summary += f"{w['city']}: {w['description']}, {w['temperature']}°C\n"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.3-70b-versatile",  # 
        "messages": [
            {
                "role": "user",
                "content": f"Por favor, gere um resumo amigável para uma viagem com base nestes dados. Inclua detalhes do clima e formate de maneira convidativa:\n\n{summary}"
            }
        ],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        ds_data = response.json()
        return ds_data['choices'][0]['message']['content']
        
    except requests.exceptions.HTTPError as err:
        print(f"\nERRO HTTP: {err.response.status_code}")
        print(f"Resposta da API: {err.response.text}\n")
        return f"Erro na API: {err.response.reason}\nResumo original:\n{summary}"
        
    except Exception as e:
        print(f"\nERRO INESPERADO: {str(e)}\n")
        return f"Erro ao gerar texto: {str(e)}\nResumo original:\n{summary}"

def main():
    origin = input("Digite a cidade de origem: ")
    destination = input("Digite a cidade de destino: ")
    
    route = get_route(origin, destination)
    if not route:
        print("Não foi possível obter a rota.")
        return

    polyline_str = route['overview_polyline']['points']
    coordinates = decode_route_polyline(polyline_str)
    
    waypoints = select_waypoints(coordinates, step=50)
    
    weather_reports = []
    for lat, lon in waypoints:
        weather = get_weather(lat, lon)
        if weather:
            weather_reports.append(weather)
    
    friendly_text = generate_friendly_text(route, weather_reports)
    print("\nTexto Final:")
    print(friendly_text)

if __name__ == "__main__":
    main()
